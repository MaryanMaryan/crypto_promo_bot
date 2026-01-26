# utils/browser_pool.py
"""
BROWSER POOL - Пул переиспользуемых браузеров Playwright

Проблема: Каждый запрос = новый браузер (2-5 сек startup)
Решение: Пул из N браузеров, переиспользуемых между запросами

Особенности:
- Асинхронный пул с asyncio
- Health-check перед использованием
- Автоперезапуск при крашах
- Graceful shutdown
- Статистика использования
"""

import asyncio
import logging
import time
import sys
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from playwright.async_api import Error as PlaywrightError
from playwright_stealth import Stealth

import config

logger = logging.getLogger(__name__)


@dataclass
class BrowserInstance:
    """Экземпляр браузера в пуле"""
    id: int
    playwright: Playwright
    browser: Browser
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    request_count: int = 0
    is_healthy: bool = True
    is_busy: bool = False
    
    def mark_used(self):
        """Отмечает использование браузера"""
        self.last_used_at = time.time()
        self.request_count += 1
    
    @property
    def age_seconds(self) -> float:
        """Возраст браузера в секундах"""
        return time.time() - self.created_at
    
    @property
    def idle_seconds(self) -> float:
        """Время простоя в секундах"""
        return time.time() - self.last_used_at


class BrowserPool:
    """
    Пул переиспользуемых браузеров Playwright
    
    Использование:
        pool = BrowserPool(size=3)
        await pool.start()
        
        async with pool.acquire() as browser:
            context = await browser.new_context(...)
            page = await context.new_page()
            # работаем с page
            await context.close()
        
        await pool.shutdown()
    """
    
    def __init__(
        self,
        size: int = None,
        max_age_seconds: int = None,
        max_requests_per_browser: int = None,
        health_check_interval: int = None
    ):
        """
        Args:
            size: Размер пула (по умолчанию из config)
            max_age_seconds: Максимальный возраст браузера перед пересозданием
            max_requests_per_browser: Максимум запросов на браузер перед пересозданием
            health_check_interval: Интервал проверки здоровья в секундах
        """
        self.size = size or getattr(config, 'BROWSER_POOL_SIZE', 3)
        self.max_age_seconds = max_age_seconds or getattr(config, 'BROWSER_MAX_AGE_SECONDS', 1800)  # 30 минут
        self.max_requests = max_requests_per_browser or getattr(config, 'BROWSER_MAX_REQUESTS', 50)
        self.health_check_interval = health_check_interval or getattr(config, 'BROWSER_HEALTH_CHECK_INTERVAL', 60)
        
        self._pool: Dict[int, BrowserInstance] = {}
        # Ленивая инициализация lock/condition для корректной работы с разными event loops
        self._lock: Optional[asyncio.Lock] = None
        self._condition: Optional[asyncio.Condition] = None
        self._loop_id: Optional[int] = None  # ID event loop для которого созданы примитивы
        self._started = False
        self._shutting_down = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._next_id = 0
        
        # Статистика
        self._stats = {
            'total_acquires': 0,
            'total_releases': 0,
            'total_recreates': 0,
            'wait_times': [],
            'errors': 0
        }
        
        # Настройки браузера
        self._browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-web-security',
            '--disable-gpu',
            '--disable-software-rasterizer',
        ]
        
        logger.info(f"🌐 BrowserPool инициализирован: size={self.size}, max_age={self.max_age_seconds}s, max_requests={self.max_requests}")
    
    def _ensure_primitives(self):
        """
        Создаёт asyncio примитивы для текущего event loop если нужно.
        Это решает проблему 'is bound to a different event loop'.
        """
        try:
            current_loop = asyncio.get_running_loop()
            current_loop_id = id(current_loop)
        except RuntimeError:
            # Нет running loop - создадим примитивы при первом вызове
            current_loop_id = None
        
        # Если примитивы уже созданы для этого loop - ничего не делаем
        if self._loop_id == current_loop_id and self._lock is not None:
            return
        
        # Создаём новые примитивы для текущего loop
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._loop_id = current_loop_id
        logger.debug(f"🔧 Созданы asyncio примитивы для event loop #{current_loop_id}")
    
    async def start(self):
        """Запускает пул браузеров"""
        # Инициализируем примитивы для текущего event loop
        self._ensure_primitives()
        
        if self._started:
            logger.warning("⚠️ BrowserPool уже запущен")
            return
        
        logger.info(f"🚀 Запуск BrowserPool (размер: {self.size})...")
        
        # Создаём браузеры параллельно
        tasks = [self._create_browser() for _ in range(self.size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        error_count = sum(1 for r in results if isinstance(r, Exception))
        
        if success_count == 0:
            logger.error("❌ Не удалось создать ни одного браузера!")
            raise RuntimeError("BrowserPool: не удалось запустить браузеры")
        
        if error_count > 0:
            logger.warning(f"⚠️ Создано {success_count}/{self.size} браузеров (ошибок: {error_count})")
        else:
            logger.info(f"✅ BrowserPool запущен: {success_count} браузеров готовы")
        
        self._started = True
        
        # Запускаем фоновую проверку здоровья
        self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def shutdown(self):
        """Останавливает пул и закрывает все браузеры"""
        if not self._started:
            return
        
        # Инициализируем примитивы для текущего event loop если нужно
        self._ensure_primitives()
        
        logger.info("🛑 Остановка BrowserPool...")
        self._shutting_down = True
        
        # Останавливаем health check
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Закрываем все браузеры
        async with self._lock:
            for instance in list(self._pool.values()):
                await self._close_browser(instance)
            self._pool.clear()
        
        self._started = False
        self._shutting_down = False
        
        # Логируем статистику
        avg_wait = sum(self._stats['wait_times']) / len(self._stats['wait_times']) if self._stats['wait_times'] else 0
        logger.info(
            f"✅ BrowserPool остановлен. Статистика: "
            f"acquires={self._stats['total_acquires']}, "
            f"recreates={self._stats['total_recreates']}, "
            f"errors={self._stats['errors']}, "
            f"avg_wait={avg_wait:.2f}ms"
        )
    
    async def _create_browser(self) -> bool:
        """Создаёт новый экземпляр браузера"""
        try:
            playwright = await async_playwright().start()
            
            browser = await playwright.chromium.launch(
                headless=True,
                args=self._browser_args
            )
            
            browser_id = self._next_id
            self._next_id += 1
            
            instance = BrowserInstance(
                id=browser_id,
                playwright=playwright,
                browser=browser
            )
            
            self._pool[browser_id] = instance
            logger.debug(f"🌐 Браузер #{browser_id} создан")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания браузера: {e}")
            self._stats['errors'] += 1
            return False
    
    async def _close_browser(self, instance: BrowserInstance):
        """Закрывает экземпляр браузера"""
        try:
            logger.debug(f"🔄 Закрытие браузера #{instance.id} (requests: {instance.request_count}, age: {instance.age_seconds:.0f}s)")
            
            # Закрываем браузер
            if instance.browser.is_connected():
                await instance.browser.close()
            
            # Останавливаем Playwright
            await instance.playwright.stop()
            
            # Даём время на cleanup subprocess на Windows
            if sys.platform == 'win32':
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка закрытия браузера #{instance.id}: {e}")
    
    async def _recreate_browser(self, instance: BrowserInstance) -> Optional[BrowserInstance]:
        """Пересоздаёт браузер (закрывает старый, создаёт новый)"""
        old_id = instance.id
        
        # Закрываем старый
        await self._close_browser(instance)
        del self._pool[old_id]
        
        # Создаём новый
        if await self._create_browser():
            self._stats['total_recreates'] += 1
            # Возвращаем последний созданный
            new_id = self._next_id - 1
            return self._pool.get(new_id)
        
        return None
    
    async def _check_browser_health(self, instance: BrowserInstance) -> bool:
        """Проверяет здоровье браузера"""
        try:
            # Проверяем, что браузер ещё жив
            if not instance.browser.is_connected():
                logger.warning(f"⚠️ Браузер #{instance.id} отключен")
                return False
            
            # Проверяем возраст
            if instance.age_seconds > self.max_age_seconds:
                logger.info(f"🔄 Браузер #{instance.id} устарел ({instance.age_seconds:.0f}s)")
                return False
            
            # Проверяем количество запросов
            if instance.request_count >= self.max_requests:
                logger.info(f"🔄 Браузер #{instance.id} достиг лимита запросов ({instance.request_count})")
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки здоровья браузера #{instance.id}: {e}")
            return False
    
    async def _health_check_loop(self):
        """Фоновая проверка здоровья браузеров"""
        # Инициализируем примитивы для текущего event loop
        self._ensure_primitives()
        
        while not self._shutting_down:
            try:
                await asyncio.sleep(self.health_check_interval)
                
                async with self._lock:
                    for instance in list(self._pool.values()):
                        if instance.is_busy:
                            continue
                        
                        is_healthy = await self._check_browser_health(instance)
                        instance.is_healthy = is_healthy
                        
                        if not is_healthy:
                            logger.info(f"🔄 Пересоздание нездорового браузера #{instance.id}")
                            await self._recreate_browser(instance)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка health check: {e}")
    
    @asynccontextmanager
    async def acquire(self, timeout: float = 30.0):
        """
        Получает браузер из пула (context manager)
        
        Args:
            timeout: Максимальное время ожидания свободного браузера
            
        Yields:
            Browser: Экземпляр браузера Playwright
            
        Usage:
            async with pool.acquire() as browser:
                context = await browser.new_context()
                page = await context.new_page()
                # ...
                await context.close()
        """
        # Инициализируем примитивы для текущего event loop
        self._ensure_primitives()
        
        if not self._started:
            raise RuntimeError("BrowserPool не запущен! Вызовите await pool.start()")
        
        if self._shutting_down:
            raise RuntimeError("BrowserPool останавливается")
        
        start_time = time.time()
        instance = None
        
        async with self._condition:
            while True:
                # Ищем свободный здоровый браузер
                for inst in self._pool.values():
                    if not inst.is_busy and inst.is_healthy:
                        instance = inst
                        break
                
                if instance:
                    break
                
                # Проверяем timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    logger.error(f"❌ Timeout ожидания браузера ({timeout}s)")
                    raise TimeoutError(f"Не удалось получить браузер за {timeout}s")
                
                # Ждём освобождения браузера
                remaining = timeout - elapsed
                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=remaining
                    )
                except asyncio.TimeoutError:
                    continue
            
            # Помечаем браузер как занятый
            instance.is_busy = True
            instance.mark_used()
            self._stats['total_acquires'] += 1
        
        wait_time = (time.time() - start_time) * 1000
        self._stats['wait_times'].append(wait_time)
        
        if wait_time > 100:
            logger.debug(f"🌐 Браузер #{instance.id} получен (ожидание: {wait_time:.0f}ms)")
        
        try:
            # Проверяем здоровье перед использованием
            if not await self._check_browser_health(instance):
                logger.info(f"🔄 Браузер #{instance.id} нездоров, пересоздаём...")
                new_instance = await self._recreate_browser(instance)
                if new_instance:
                    instance = new_instance
                    instance.is_busy = True
                else:
                    raise RuntimeError("Не удалось пересоздать браузер")
            
            yield instance.browser
            
        except Exception as e:
            # Помечаем браузер как нездоровый при ошибке
            instance.is_healthy = False
            self._stats['errors'] += 1
            logger.warning(f"⚠️ Ошибка при работе с браузером #{instance.id}: {e}")
            raise
            
        finally:
            # Освобождаем браузер
            async with self._condition:
                instance.is_busy = False
                self._stats['total_releases'] += 1
                self._condition.notify()
    
    async def acquire_with_context(
        self,
        proxy: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None,
        viewport: Tuple[int, int] = (1920, 1080),
        locale: str = 'de-DE',
        timezone_id: str = 'Europe/Berlin',
        apply_stealth: bool = True
    ):
        """
        Получает браузер с настроенным контекстом
        
        Args:
            proxy: Настройки прокси {'server': ..., 'username': ..., 'password': ...}
            user_agent: User-Agent строка
            viewport: Размер viewport
            locale: Локаль
            timezone_id: Часовой пояс
            apply_stealth: Применить playwright-stealth
            
        Returns:
            Tuple[BrowserContext, Page]: Контекст и страница
            
        Note: Вызывающий код должен закрыть контекст после использования!
        """
        async with self.acquire() as browser:
            # Настройки контекста
            context_options = {
                'viewport': {'width': viewport[0], 'height': viewport[1]},
                'locale': locale,
                'timezone_id': timezone_id,
            }
            
            if user_agent:
                context_options['user_agent'] = user_agent
            else:
                context_options['user_agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            
            if proxy:
                context_options['proxy'] = proxy
            
            # Создаём контекст
            context = await browser.new_context(**context_options)
            
            # Добавляем headers
            await context.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': f'{locale},{locale.split("-")[0]};q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
            })
            
            # Маскируем автоматизацию
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            
            # Создаём страницу
            page = await context.new_page()
            
            # Применяем stealth
            if apply_stealth:
                stealth = Stealth()
                await stealth.apply_stealth_async(page)
            
            return context, page
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику пула"""
        active_count = sum(1 for i in self._pool.values() if i.is_busy)
        healthy_count = sum(1 for i in self._pool.values() if i.is_healthy)
        avg_wait = sum(self._stats['wait_times']) / len(self._stats['wait_times']) if self._stats['wait_times'] else 0
        
        return {
            'pool_size': self.size,
            'active_browsers': len(self._pool),
            'busy_count': active_count,
            'healthy_count': healthy_count,
            'total_acquires': self._stats['total_acquires'],
            'total_recreates': self._stats['total_recreates'],
            'total_errors': self._stats['errors'],
            'avg_wait_ms': round(avg_wait, 2),
        }
    
    @property
    def is_running(self) -> bool:
        """Проверяет, запущен ли пул"""
        if not self._started or self._shutting_down:
            return False
        
        # Проверяем, не закрыт ли event loop в котором были созданы браузеры
        if self._loop_id is not None:
            try:
                current_loop = asyncio.get_running_loop()
                if id(current_loop) != self._loop_id:
                    # Пул был создан в другом event loop - считаем его не запущенным
                    logger.warning(f"⚠️ BrowserPool был создан в другом event loop (old: {self._loop_id}, current: {id(current_loop)})")
                    self._started = False
                    self._pool.clear()  # Очищаем старые браузеры
                    return False
            except RuntimeError:
                # Нет running loop - пока не можем проверить
                pass
        
        return True


# Глобальный экземпляр пула (singleton)
_browser_pool: Optional[BrowserPool] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def reset_browser_pool():
    """Сбрасывает глобальный пул браузеров (для пересоздания в новом event loop)"""
    global _browser_pool
    if _browser_pool is not None:
        logger.info("🔄 Сброс глобального BrowserPool для пересоздания")
        _browser_pool._started = False
        _browser_pool._pool.clear()
        _browser_pool = None


def set_main_loop(loop: asyncio.AbstractEventLoop = None):
    """Устанавливает главный event loop для использования парсерами из ThreadPool"""
    global _main_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
    _main_loop = loop
    logger.debug(f"🔧 Главный event loop установлен: #{id(loop)}")


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Возвращает главный event loop"""
    return _main_loop


def get_browser_pool() -> BrowserPool:
    """Получает глобальный экземпляр пула браузеров"""
    global _browser_pool
    
    # Если пул существует, проверяем что он не привязан к мёртвому event loop
    if _browser_pool is not None:
        try:
            current_loop = asyncio.get_running_loop()
            if _browser_pool._loop_id is not None and id(current_loop) != _browser_pool._loop_id:
                # Пул создан в другом loop - пересоздаём
                logger.warning(f"🔄 BrowserPool привязан к другому event loop, пересоздаём...")
                _browser_pool._started = False
                _browser_pool._pool.clear()
                _browser_pool = None
        except RuntimeError:
            # Нет running loop - проверка невозможна
            pass
    
    if _browser_pool is None:
        _browser_pool = BrowserPool()
    return _browser_pool


async def init_browser_pool():
    """Инициализирует глобальный пул браузеров"""
    # Сохраняем главный event loop для использования парсерами из ThreadPool
    set_main_loop()
    
    pool = get_browser_pool()
    if not pool.is_running:
        await pool.start()
    return pool


async def shutdown_browser_pool():
    """Останавливает глобальный пул браузеров"""
    global _browser_pool
    if _browser_pool and _browser_pool.is_running:
        await _browser_pool.shutdown()
        _browser_pool = None
