"""
Воркеры параллельного парсинга.
Запускают несколько воркеров, каждый берёт задачи из очереди.

Фаза 5 добавления:
- Graceful degradation при нехватке ресурсов
- Автовосстановление воркеров при крашах
- Интеграция с Circuit Breaker
- Интеграция с Resource Monitor
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime

from utils.parsing_queue import (
    ParsingQueue, ParsingTask, TaskPriority, TaskStatus, 
    get_parsing_queue, shutdown_parsing_queue
)
from utils.executor import get_executor
from utils.circuit_breaker import get_circuit_breaker, CircuitOpenError
from utils.resource_monitor import get_resource_monitor, ResourceLevel
from bot.parser_service import ParserService
import config

logger = logging.getLogger(__name__)


class ParsingWorker:
    """
    Воркер парсинга - берёт задачи из очереди и выполняет их.
    
    Каждый воркер:
    - Работает в отдельной async-корутине
    - Берёт задачу из очереди
    - Выполняет парсинг в executor (чтобы не блокировать event loop)
    - Сообщает результат обратно
    - Автоматически перезапускается при краше
    - Учитывает Circuit Breaker для бирж
    """
    
    def __init__(
        self,
        worker_id: int,
        queue: ParsingQueue,
        parser_service: ParserService,
        on_result: Optional[Callable[[ParsingTask], Awaitable[None]]] = None
    ):
        self.worker_id = worker_id
        self.queue = queue
        self.parser_service = parser_service
        self.on_result = on_result  # Callback при получении результата
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_task: Optional[ParsingTask] = None
        
        # Статистика
        self._stats = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'tasks_skipped_circuit': 0,  # Пропущено из-за Circuit Breaker
            'total_time': 0.0,
            'restarts': 0,  # Количество перезапусков
        }
        
        # Автовосстановление
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5  # После 5 ошибок — пауза
        self._error_pause_seconds = 30  # Пауза после серии ошибок
        self._default_timeout = config.PARALLEL_PARSING_TASK_TIMEOUT  # Базовый таймаут
    
    def _get_task_timeout(self, task: ParsingTask) -> int:
        """
        Определяет таймаут для конкретной задачи.
        Приоритет: exchange override > name-based exchange > category override > default
        """
        # Проверяем override по бирже
        exchange = (task.exchange or self._extract_exchange(task.url) or '').lower()
        
        # Если exchange пустой, пробуем извлечь из имени ссылки
        if not exchange and task.link_name:
            exchange = self._extract_exchange_from_name(task.link_name)
        
        if exchange and hasattr(config, 'PARSER_TIMEOUT_OVERRIDES'):
            exchange_timeout = config.PARSER_TIMEOUT_OVERRIDES.get(exchange)
            if exchange_timeout:
                return exchange_timeout
        
        # Проверяем override по категории
        category = (task.category or '').lower()
        if category and hasattr(config, 'PARSER_TIMEOUT_BY_CATEGORY'):
            category_timeout = config.PARSER_TIMEOUT_BY_CATEGORY.get(category)
            if category_timeout:
                return category_timeout
        
        # Дефолтный таймаут
        return self._default_timeout
    
    def _extract_exchange_from_name(self, name: str) -> Optional[str]:
        """Извлекает название биржи из имени ссылки"""
        if not name:
            return None
        name_lower = name.lower()
        # Проверяем известные биржи
        exchanges = ['bitget', 'bybit', 'mexc', 'gate', 'okx', 'binance', 'kucoin', 'weex', 'bingx', 'phemex']
        for ex in exchanges:
            if ex in name_lower:
                return ex
        return None
    
    async def start(self):
        """Запускает воркера"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"👷 Воркер {self.worker_id} запущен")
    
    async def stop(self):
        """Останавливает воркера"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"👷 Воркер {self.worker_id} остановлен")
    
    async def _run_loop(self):
        """Основной цикл воркера с автовосстановлением"""
        while self._running:
            try:
                # Получаем задачу из очереди
                task = await self.queue.get_task()
                
                if task is None:
                    # Нет задач или shutdown
                    if self.queue.is_shutdown:
                        break
                    continue
                
                self._current_task = task
                start_time = time.time()
                
                # Проверяем Circuit Breaker
                exchange = task.exchange or self._extract_exchange(task.url)
                circuit_breaker = get_circuit_breaker()
                
                if exchange and not circuit_breaker.can_execute(exchange):
                    # Биржа заблокирована — пропускаем
                    logger.info(f"⏸️ Воркер {self.worker_id}: {task.link_name} пропущен (Circuit OPEN для {exchange})")
                    self._stats['tasks_skipped_circuit'] += 1
                    await self.queue.complete_task(task, error=f"Circuit OPEN for {exchange}")
                    self._current_task = None
                    continue
                
                # Определяем таймаут для этой задачи (до логирования!)
                task_timeout = self._get_task_timeout(task)
                
                logger.info(f"👷 Воркер {self.worker_id}: начал {task.link_name} (категория: {task.category}, таймаут: {task_timeout}с)")
                
                try:
                    # Выполняем парсинг с таймаутом
                    try:
                        result = await asyncio.wait_for(
                            self._execute_task(task),
                            timeout=task_timeout
                        )
                    except asyncio.TimeoutError:
                        raise TimeoutError(f"Таймаут {task_timeout}с для {task.link_name}")
                    
                    # Отмечаем успех в Circuit Breaker
                    if exchange:
                        circuit_breaker.record_success(exchange)
                    
                    # Отмечаем успех
                    await self.queue.complete_task(task, result=result)
                    self._stats['tasks_completed'] += 1
                    self._consecutive_errors = 0  # Сбрасываем счётчик ошибок
                    
                    elapsed = time.time() - start_time
                    self._stats['total_time'] += elapsed
                    
                    # Логируем результат
                    if result:
                        new_count = result.get('new_count', 0)
                        if new_count > 0:
                            logger.info(f"🎉 Воркер {self.worker_id}: {task.link_name} — найдено {new_count} новых")
                        else:
                            logger.info(f"✅ Воркер {self.worker_id}: {task.link_name} — без изменений ({elapsed:.1f}с)")
                    
                    # Callback с результатом
                    if self.on_result:
                        await self.on_result(task)
                    
                except Exception as e:
                    # Записываем неудачу в Circuit Breaker
                    if exchange:
                        circuit_breaker.record_failure(exchange, str(e))
                    
                    logger.error(f"❌ Воркер {self.worker_id}: ошибка {task.link_name}: {e}", exc_info=True)
                    await self.queue.complete_task(task, error=str(e))
                    self._stats['tasks_failed'] += 1
                    self._consecutive_errors += 1
                    
                    # Callback даже при ошибке - чтобы обновить last_checked
                    if self.on_result:
                        await self.on_result(task)
                    
                    # Проверяем, нужна ли пауза после серии ошибок
                    if self._consecutive_errors >= self._max_consecutive_errors:
                        logger.warning(
                            f"⚠️ Воркер {self.worker_id}: {self._consecutive_errors} ошибок подряд, "
                            f"пауза {self._error_pause_seconds}с"
                        )
                        await asyncio.sleep(self._error_pause_seconds)
                        self._consecutive_errors = 0
                
                finally:
                    self._current_task = None
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Критическая ошибка воркера — автовосстановление
                self._stats['restarts'] += 1
                logger.error(
                    f"❌ Критическая ошибка воркера {self.worker_id}: {e}. "
                    f"Перезапуск #{self._stats['restarts']}", 
                    exc_info=True
                )
                await asyncio.sleep(5)  # Пауза перед продолжением
    
    def _extract_exchange(self, url: str) -> Optional[str]:
        """Извлекает название биржи из URL"""
        if not url:
            return None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            parts = domain.replace('www.', '').split('.')
            if len(parts) >= 2:
                return parts[0]
            return domain
        except:
            return None
    
    async def _execute_task(self, task: ParsingTask) -> Dict[str, Any]:
        """
        Выполняет задачу парсинга.
        
        Возвращает результат в формате:
        {
            'new_count': int,        # Количество новых элементов
            'items': List[Dict],     # Список новых элементов
            'changed': bool,         # Были ли изменения (для announcements)
            'message': str,          # Сообщение для уведомления
            ...
        }
        """
        loop = asyncio.get_event_loop()
        
        if task.category == 'staking':
            # СТЕЙКИНГ
            from utils.exchange_detector import detect_exchange_from_url
            
            api_url = task.api_url or task.url
            exchange = task.exchange
            if not exchange or exchange in ['Unknown', 'None', '']:
                exchange = detect_exchange_from_url(api_url)
            
            new_stakings = await loop.run_in_executor(
                get_executor(),
                self.parser_service.parse_staking_link,
                task.link_id,
                api_url,
                exchange,
                task.page_url,
                task.min_apr
            )
            
            # Фильтруем маркеры _no_new - они не являются реальными стейкингами
            real_stakings = [s for s in (new_stakings or []) if not s.get('_no_new')]
            
            return {
                'new_count': len(real_stakings),
                'items': real_stakings,
                'category': 'staking',
                'exchange': exchange,
            }
        
        elif task.category == 'announcement':
            # АНОНСЫ
            result = await loop.run_in_executor(
                get_executor(),
                self.parser_service.check_announcement_link,
                task.link_id,
                task.url
            )
            
            if result and result.get('changed'):
                return {
                    'new_count': 1,
                    'changed': True,
                    'items': [result],
                    'category': 'announcement',
                    **result
                }
            else:
                return {
                    'new_count': 0,
                    'changed': False,
                    'items': [],
                    'category': 'announcement',
                }
        
        else:
            # ОБЫЧНЫЕ ПРОМОАКЦИИ
            new_promos = await loop.run_in_executor(
                get_executor(),
                self.parser_service.check_for_new_promos,
                task.link_id,
                task.url
            )
            
            return {
                'new_count': len(new_promos) if new_promos else 0,
                'items': new_promos or [],
                'category': 'promo',
            }
    
    @property
    def is_busy(self) -> bool:
        return self._current_task is not None
    
    @property
    def current_task_name(self) -> Optional[str]:
        return self._current_task.link_name if self._current_task else None
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            'worker_id': self.worker_id,
            'is_busy': self.is_busy,
            'current_task': self.current_task_name,
            **self._stats
        }


class ParsingWorkerPool:
    """
    Пул воркеров парсинга.
    
    Управляет несколькими воркерами для параллельного парсинга.
    Поддерживает Graceful degradation при нехватке ресурсов.
    """
    
    def __init__(
        self,
        num_workers: int = None,
        parser_service: ParserService = None,
        on_result: Optional[Callable[[ParsingTask], Awaitable[None]]] = None,
        enable_graceful_degradation: bool = None
    ):
        self.num_workers = num_workers or config.PARALLEL_PARSING_WORKERS
        self._initial_workers = self.num_workers
        self.parser_service = parser_service
        self.on_result = on_result
        self.enable_graceful_degradation = (
            enable_graceful_degradation 
            if enable_graceful_degradation is not None 
            else getattr(config, 'GRACEFUL_DEGRADATION_ENABLED', True)
        )
        
        self._queue: Optional[ParsingQueue] = None
        self._workers: List[ParsingWorker] = []
        self._running = False
        
        # Callback для уведомлений
        self._notification_callback: Optional[Callable] = None
        
        # Graceful degradation
        self._min_workers = 1
        self._degradation_task: Optional[asyncio.Task] = None
        
        logger.info(
            f"📦 ParsingWorkerPool создан (воркеров: {self.num_workers}, "
            f"graceful_degradation: {self.enable_graceful_degradation})"
        )
    
    def set_notification_callback(self, callback: Callable[[ParsingTask, Any], Awaitable[None]]):
        """Устанавливает callback для отправки уведомлений"""
        self._notification_callback = callback
    
    async def start(self, parser_service: ParserService = None):
        """Запускает пул воркеров"""
        if self._running:
            return
        
        if parser_service:
            self.parser_service = parser_service
        
        if not self.parser_service:
            raise ValueError("ParserService не установлен")
        
        self._queue = get_parsing_queue()
        self._running = True
        
        # Создаём и запускаем воркеры
        for i in range(self.num_workers):
            worker = ParsingWorker(
                worker_id=i + 1,
                queue=self._queue,
                parser_service=self.parser_service,
                on_result=self._on_worker_result
            )
            self._workers.append(worker)
            await worker.start()
        
        # Запускаем Graceful degradation мониторинг
        if self.enable_graceful_degradation:
            self._degradation_task = asyncio.create_task(self._graceful_degradation_loop())
        
        logger.info(f"🚀 ParsingWorkerPool запущен ({self.num_workers} воркеров)")
    
    async def stop(self):
        """Останавливает пул воркеров"""
        if not self._running:
            return
        
        self._running = False
        
        # Останавливаем graceful degradation
        if self._degradation_task:
            self._degradation_task.cancel()
            try:
                await self._degradation_task
            except asyncio.CancelledError:
                pass
        
        # Останавливаем всех воркеров
        for worker in self._workers:
            await worker.stop()
        
        self._workers.clear()
        
        # Завершаем очередь
        await shutdown_parsing_queue()
        
        logger.info("🛑 ParsingWorkerPool остановлен")
    
    async def _on_worker_result(self, task: ParsingTask):
        """Обработка результата воркера"""
        if not self._notification_callback:
            return
        
        try:
            # Вызываем callback для отправки уведомлений
            # Передаём result даже если он пустой — callback обновит last_checked
            await self._notification_callback(task, task.result or {})
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")
    
    async def add_task(
        self,
        link_id: int,
        link_name: str,
        url: str,
        category: str = "launches",
        priority: TaskPriority = TaskPriority.NORMAL,
        **kwargs
    ) -> str:
        """Добавляет задачу в очередь"""
        if not self._queue:
            raise RuntimeError("WorkerPool не запущен")
        
        return await self._queue.add_task(
            link_id=link_id,
            link_name=link_name,
            url=url,
            category=category,
            priority=priority,
            **kwargs
        )
    
    async def add_links(
        self,
        links_data: List[Dict[str, Any]],
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> List[str]:
        """Добавляет несколько ссылок в очередь"""
        task_ids = []
        
        for link_data in links_data:
            # Пропускаем Telegram ссылки (они обрабатываются отдельно)
            if link_data.get('parsing_type') == 'telegram':
                continue
            
            task_id = await self.add_task(
                link_id=link_data['id'],
                link_name=link_data['name'],
                url=link_data['url'],
                category=link_data.get('category', 'launches'),
                parsing_type=link_data.get('parsing_type', 'combined'),
                exchange=link_data.get('exchange', ''),
                api_url=link_data.get('api_url'),
                page_url=link_data.get('page_url'),
                min_apr=link_data.get('min_apr'),
                priority=priority
            )
            task_ids.append(task_id)
        
        logger.info(f"📥 Добавлено {len(task_ids)} задач в очередь (приоритет: {priority.name})")
        return task_ids
    
    async def wait_for_completion(self, timeout: float = 300.0, task_ids: List[str] = None) -> List[ParsingTask]:
        """
        Ждёт завершения задач в очереди.
        
        Args:
            timeout: Максимальное время ожидания в секундах
            task_ids: Список ID задач для ожидания (если None - все задачи)
        
        Returns:
            Список завершённых задач
        """
        if not self._queue:
            return []
        
        results = []
        pending_task_ids = set(task_ids) if task_ids else None
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Проверяем, все ли нужные задачи завершены
            if pending_task_ids is not None:
                if not pending_task_ids:
                    # Все нужные задачи завершены
                    break
            else:
                # Проверяем, есть ли ещё задачи (старое поведение)
                if self._queue.is_empty and not any(w.is_busy for w in self._workers):
                    # Собираем оставшиеся результаты
                    remaining = await self._queue.get_all_results(timeout=1.0)
                    results.extend(remaining)
                    break
            
            # Собираем результаты
            result = await self._queue.get_result(timeout=1.0)
            if result:
                if pending_task_ids is not None:
                    # Проверяем, что это нужная задача
                    if result.task_id in pending_task_ids:
                        results.append(result)
                        pending_task_ids.discard(result.task_id)
                    # Чужие результаты просто игнорируем - они уже обработаны через callback
                else:
                    results.append(result)
        
        return results
    
    @property
    def pending_count(self) -> int:
        """Количество ожидающих задач"""
        return self._queue.pending_count if self._queue else 0
    
    @property
    def busy_workers(self) -> int:
        """Количество занятых воркеров"""
        return sum(1 for w in self._workers if w.is_busy)
    
    def get_stats(self) -> Dict[str, Any]:
        """Статистика пула"""
        workers_stats = [w.get_stats() for w in self._workers]
        queue_stats = self._queue.get_stats() if self._queue else {}
        
        # Получаем статистику Circuit Breaker
        circuit_breaker = get_circuit_breaker()
        circuit_stats = circuit_breaker.get_stats() if circuit_breaker else {}
        
        return {
            'num_workers': len(self._workers),
            'initial_workers': self._initial_workers,
            'busy_workers': self.busy_workers,
            'pending_tasks': self.pending_count,
            'graceful_degradation': self.enable_graceful_degradation,
            'queue': queue_stats,
            'workers': workers_stats,
            'circuit_breaker': circuit_stats,
        }
    
    async def _graceful_degradation_loop(self):
        """
        Фоновый цикл для Graceful degradation.
        
        При нехватке ресурсов:
        - WARNING: уменьшаем воркеры до половины
        - CRITICAL: уменьшаем до минимума (1 воркер)
        - NORMAL: восстанавливаем до начального количества
        """
        check_interval = getattr(config, 'GRACEFUL_DEGRADATION_CHECK_INTERVAL', 60)  # секунд
        
        while self._running:
            try:
                await asyncio.sleep(check_interval)
                
                if not self._running:
                    break
                
                monitor = get_resource_monitor()
                if not monitor:
                    continue
                
                snapshot = monitor.get_current_snapshot()
                if not snapshot:
                    continue
                
                # Определяем рекомендуемое количество воркеров
                recommended = monitor.get_recommended_workers(self._initial_workers)
                current = len(self._workers)
                
                if recommended < current:
                    # Нужно уменьшить количество воркеров
                    await self._scale_down(current - recommended)
                    logger.warning(
                        f"📉 Graceful degradation: уменьшено до {len(self._workers)} воркеров "
                        f"(RAM: {snapshot.ram_percent:.1f}%, CPU: {snapshot.cpu_percent:.1f}%)"
                    )
                
                elif recommended > current and current < self._initial_workers:
                    # Можно восстановить воркеры
                    await self._scale_up(min(recommended - current, self._initial_workers - current))
                    logger.info(
                        f"📈 Восстановление: увеличено до {len(self._workers)} воркеров "
                        f"(RAM: {snapshot.ram_percent:.1f}%, CPU: {snapshot.cpu_percent:.1f}%)"
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка graceful degradation: {e}")
    
    async def _scale_down(self, count: int):
        """Уменьшает количество воркеров"""
        if len(self._workers) <= self._min_workers:
            return
        
        to_stop = min(count, len(self._workers) - self._min_workers)
        
        for _ in range(to_stop):
            if len(self._workers) <= self._min_workers:
                break
            
            # Останавливаем последний незанятый воркер
            for worker in reversed(self._workers):
                if not worker.is_busy:
                    await worker.stop()
                    self._workers.remove(worker)
                    break
    
    async def _scale_up(self, count: int):
        """Увеличивает количество воркеров"""
        current = len(self._workers)
        target = min(current + count, self._initial_workers)
        
        for i in range(current, target):
            worker = ParsingWorker(
                worker_id=i + 1,
                queue=self._queue,
                parser_service=self.parser_service,
                on_result=self._on_worker_result
            )
            self._workers.append(worker)
            await worker.start()


# Глобальный экземпляр пула
_worker_pool: Optional[ParsingWorkerPool] = None


def get_worker_pool() -> Optional[ParsingWorkerPool]:
    """Возвращает глобальный пул воркеров"""
    return _worker_pool


async def init_worker_pool(
    parser_service: ParserService,
    num_workers: int = None,
    notification_callback: Callable = None,
    enable_graceful_degradation: bool = None
) -> ParsingWorkerPool:
    """Инициализирует глобальный пул воркеров"""
    global _worker_pool
    
    _worker_pool = ParsingWorkerPool(
        num_workers=num_workers,
        enable_graceful_degradation=enable_graceful_degradation
    )
    
    if notification_callback:
        _worker_pool.set_notification_callback(notification_callback)
    
    await _worker_pool.start(parser_service)
    return _worker_pool


async def shutdown_worker_pool():
    """Останавливает глобальный пул воркеров"""
    global _worker_pool
    
    if _worker_pool:
        await _worker_pool.stop()
        _worker_pool = None
