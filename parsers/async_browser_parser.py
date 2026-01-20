# parsers/async_browser_parser.py
"""
ASYNC BROWSER PARSER С ПОДДЕРЖКОЙ ПУЛА БРАУЗЕРОВ

Асинхронная версия BrowserParser, использующая BrowserPool
для переиспользования браузеров между запросами.

Преимущества:
- Браузеры создаются один раз и переиспользуются
- Экономия 2-5 секунд на каждый запрос
- Параллельный парсинг нескольких бирж
- Health-check и автоперезапуск браузеров
"""

import asyncio
import logging
import time
import hashlib
import json
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page, BrowserContext
from playwright.async_api import Error as PlaywrightError

from .base_parser import BaseParser
from .html_templates import get_html_selectors
from utils.url_template_builder import get_url_builder
from utils.browser_pool import get_browser_pool, BrowserPool

logger = logging.getLogger(__name__)


class AsyncBrowserParser(BaseParser):
    """
    Асинхронный парсер с использованием пула браузеров Playwright
    
    Использование:
        parser = AsyncBrowserParser(url)
        promotions = await parser.get_promotions_async()
    """

    def __init__(self, url: str, browser_pool: Optional[BrowserPool] = None):
        super().__init__(url)
        self.exchange = self._extract_exchange_from_url(url)
        self._pool = browser_pool or get_browser_pool()

    def get_promotions(self) -> List[Dict[str, Any]]:
        """
        Синхронная обёртка для совместимости с существующим кодом.
        Запускает async версию в event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            # Если уже есть running loop, используем run_in_executor
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.get_promotions_async())
                return future.result()
        except RuntimeError:
            # Нет running loop, можно использовать asyncio.run
            return asyncio.run(self.get_promotions_async())

    async def get_promotions_async(self) -> List[Dict[str, Any]]:
        """Основной метод асинхронного парсинга через браузер"""
        try:
            logger.info(f"🌐 AsyncBrowserParser: Начало парсинга")
            logger.info(f"   Биржа: {self.exchange}")
            logger.info(f"   URL: {self.url}")

            # Проверяем, запущен ли пул
            if not self._pool.is_running:
                logger.warning("⚠️ Пул браузеров не запущен, запускаем...")
                await self._pool.start()

            # Проверяем, API это или HTML
            is_api_request = self._is_api_url(self.url)

            # Получаем прокси и User-Agent из системы ротации
            proxy, user_agent = self.rotation_manager.get_optimal_combination(self.exchange)

            if not proxy or not user_agent:
                logger.warning(f"⚠️ Прокси/User-Agent не доступны для {self.exchange}")
                logger.warning(f"🔄 Работаем БЕЗ прокси (может быть заблокировано)")

            if is_api_request:
                # Для API получаем JSON напрямую
                logger.info(f"👾 Обнаружен API endpoint, получаем JSON через браузер")
                json_data = await self._fetch_json_with_browser(proxy, user_agent)

                if not json_data:
                    logger.error(f"❌ Не удалось получить JSON из API")
                    return []

                # Парсим JSON
                from .universal_parser import UniversalParser
                parser = UniversalParser(self.url)
                promotions = parser.parse_json_data(json_data)

                logger.info(f"✅ AsyncBrowserParser (API): Найдено {len(promotions)} промоакций")
                return promotions
            else:
                # Для HTML парсим страницу
                html_content = await self._fetch_with_browser(proxy, user_agent)

                # FALLBACK: Если прокси не работает, пробуем без прокси
                if not html_content and proxy:
                    logger.warning(f"⚠️ Прокси не работает, пробуем БЕЗ прокси")
                    html_content = await self._fetch_with_browser(None, user_agent)

                if not html_content:
                    logger.error(f"❌ Не удалось получить HTML контент")
                    return []

                logger.info(f"✅ HTML контент получен, размер: {len(html_content)} символов")

                # Парсим HTML (синхронная операция, но быстрая)
                promotions = self._parse_html_content(html_content)

                logger.info(f"✅ AsyncBrowserParser: Найдено {len(promotions)} промоакций")
                return promotions

        except Exception as e:
            logger.error(f"❌ Ошибка AsyncBrowserParser: {e}", exc_info=True)
            return []

    def _is_api_url(self, url: str) -> bool:
        """Проверяет, является ли URL API endpoint'ом"""
        api_indicators = ['/api/', '/x-api/', '/v1/', '/v2/', '/v3/', '/v4/', '/v5/']
        return any(indicator in url.lower() for indicator in api_indicators)

    def _build_proxy_config(self, proxy) -> Optional[Dict[str, str]]:
        """Строит конфигурацию прокси для Playwright"""
        if not proxy:
            return None

        proxy_address = proxy.address
        username = None
        password = None

        if '@' in proxy_address:
            auth_part, server_part = proxy_address.split('@', 1)
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
                proxy_address = server_part

        proxy_config = {
            'server': f"{proxy.protocol}://{proxy_address}",
        }

        if username and password:
            proxy_config['username'] = username
            proxy_config['password'] = password
            logger.info(f"🔧 Используем прокси: {proxy_address} (с авторизацией)")
        else:
            logger.info(f"🔧 Используем прокси: {proxy_address}")

        return proxy_config

    async def _fetch_json_with_browser(self, proxy, user_agent) -> Optional[dict]:
        """Загружает JSON из API через браузер из пула"""
        context = None
        try:
            # Получаем браузер из пула и создаём контекст
            async with self._pool.acquire() as browser:
                # Настройки прокси
                proxy_config = self._build_proxy_config(proxy) if proxy else None

                # User-Agent
                user_agent_string = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
                if user_agent and user_agent.user_agent_string:
                    user_agent_string = user_agent.user_agent_string

                # Настройки контекста
                context_options = {
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'de-DE',
                    'timezone_id': 'Europe/Berlin',
                    'user_agent': user_agent_string,
                }

                if proxy_config:
                    context_options['proxy'] = proxy_config

                # Создаём контекст
                context = await browser.new_context(**context_options)

                # API headers
                await context.set_extra_http_headers({
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br, zstd',
                    'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
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
                """)

                # Открываем страницу
                page = await context.new_page()

                # Применяем stealth
                from playwright_stealth import Stealth
                stealth = Stealth()
                await stealth.apply_stealth_async(page)

                logger.info(f"👾 Загрузка API: {self.url}")

                start_time = time.time()
                response = await page.goto(self.url, wait_until='domcontentloaded', timeout=30000)
                response_time_ms = (time.time() - start_time) * 1000

                # Ожидание JavaScript
                await page.wait_for_timeout(5000)

                # Проверяем GeeTest
                geetest_present = await page.evaluate("""
                    () => {
                        return document.querySelector('.geetest_captcha') !== null ||
                               document.querySelector('[class*="geetest"]') !== null;
                    }
                """)

                if geetest_present:
                    logger.warning(f"⚠️ Обнаружена GeeTest капча, ожидаем...")
                    await page.wait_for_timeout(10000)

                if response and response.ok:
                    logger.info(f"✅ API запрос успешен: {response.status} ({response_time_ms:.0f}мс)")

                    content = await page.content()

                    # Извлекаем JSON
                    soup = BeautifulSoup(content, 'html.parser')
                    pre_tag = soup.find('pre')

                    json_text = pre_tag.get_text() if pre_tag else content

                    try:
                        json_data = json.loads(json_text)
                        logger.info(f"✅ JSON успешно распарсен")

                        # Логируем результат
                        if proxy and user_agent:
                            self.rotation_manager.handle_request_result(
                                exchange=self.exchange,
                                proxy_id=proxy.id,
                                user_agent_id=user_agent.id,
                                success=True,
                                response_time_ms=response_time_ms,
                                response_code=response.status
                            )

                        return json_data
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Ошибка парсинга JSON: {e}")
                        return None
                else:
                    status = response.status if response else 'N/A'
                    logger.warning(f"⚠️ API запрос: {status} ({response_time_ms:.0f}мс)")
                    return None

        except PlaywrightError as e:
            logger.error(f"❌ Playwright ошибка при API запросе: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при API запросе через браузер: {e}", exc_info=True)
            return None
        finally:
            if context:
                try:
                    await context.close()
                except:
                    pass

    async def _fetch_with_browser(self, proxy, user_agent) -> Optional[str]:
        """Загружает HTML страницу через браузер из пула"""
        context = None
        try:
            async with self._pool.acquire() as browser:
                # Настройки прокси
                proxy_config = self._build_proxy_config(proxy) if proxy else None

                # User-Agent
                user_agent_string = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
                if user_agent and user_agent.user_agent_string:
                    user_agent_string = user_agent.user_agent_string
                    logger.info(f"🔧 User-Agent: {user_agent.browser_type} {user_agent.browser_version}")

                # Настройки контекста
                context_options = {
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'de-DE',
                    'timezone_id': 'Europe/Berlin',
                    'user_agent': user_agent_string,
                }

                if proxy_config:
                    context_options['proxy'] = proxy_config

                # Создаём контекст
                context = await browser.new_context(**context_options)

                # Headers для обхода Akamai
                await context.set_extra_http_headers({
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
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

                # Открываем страницу
                page = await context.new_page()

                # Применяем stealth
                from playwright_stealth import Stealth
                stealth = Stealth()
                await stealth.apply_stealth_async(page)

                logger.info(f"👾 Загрузка страницы: {self.url}")

                start_time = time.time()
                response = await page.goto(self.url, wait_until='domcontentloaded', timeout=30000)
                response_time_ms = (time.time() - start_time) * 1000

                if response and response.ok:
                    logger.info(f"✅ Страница загружена: {response.status} ({response_time_ms:.0f}мс)")
                else:
                    status = response.status if response else 'N/A'
                    logger.warning(f"⚠️ Страница: {status} ({response_time_ms:.0f}мс)")

                # Ждём JavaScript и Akamai
                await page.wait_for_timeout(8000)

                # Проверяем GeeTest
                geetest_present = await page.evaluate("""
                    () => {
                        return document.querySelector('.geetest_captcha') !== null ||
                               document.querySelector('[class*="geetest"]') !== null;
                    }
                """)

                if geetest_present:
                    logger.warning(f"⚠️ Обнаружена GeeTest капча")
                    await page.wait_for_timeout(10000)

                # Скроллим для lazy-load
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Получаем HTML
                html_content = await page.content()

                # Проверяем блокировку
                if len(html_content) < 5000:
                    logger.warning(f"⚠️ HTML слишком короткий ({len(html_content)} символов)")

                blocking_indicators = ['captcha', 'Access Denied', 'Cloudflare', 'are you a robot']
                for indicator in blocking_indicators:
                    if indicator.lower() in html_content.lower():
                        logger.warning(f"⚠️ Индикатор блокировки: '{indicator}'")

                logger.info(f"✅ HTML получен ({len(html_content)} символов)")

                # Логируем статистику
                if proxy and user_agent:
                    success = response and response.ok
                    self.rotation_manager.handle_request_result(
                        exchange=self.exchange,
                        proxy_id=proxy.id,
                        user_agent_id=user_agent.id,
                        success=success,
                        response_time_ms=response_time_ms,
                        response_code=response.status if response else None
                    )

                return html_content

        except PlaywrightError as e:
            logger.error(f"❌ Playwright ошибка: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки через браузер: {e}", exc_info=True)
            return None
        finally:
            if context:
                try:
                    await context.close()
                except:
                    pass

    def _parse_html_content(self, html_content: str) -> List[Dict[str, Any]]:
        """Парсит HTML контент используя селекторы из html_templates"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            selectors = get_html_selectors(self.exchange)

            if not selectors:
                logger.warning(f"⚠️ Нет селекторов для биржи {self.exchange}")
                return []

            containers = soup.select(selectors['container'])
            logger.info(f"🔍 Найдено {len(containers)} контейнеров для {self.exchange}")

            if len(containers) == 0:
                logger.warning(f"⚠️ Контейнеры не найдены с селектором: {selectors['container']}")

            promotions = []

            for i, container in enumerate(containers, 1):
                try:
                    promo = self._extract_promo_from_container(container, selectors)
                    if promo and self._is_valid_promo(promo):
                        promotions.append(promo)
                except Exception as e:
                    logger.debug(f"   ⚠️ [{i}] Ошибка извлечения: {e}")
                    continue

            return promotions

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга HTML: {e}", exc_info=True)
            return []

    def _extract_promo_from_container(self, container, selectors: dict) -> Optional[Dict[str, Any]]:
        """Извлекает данные промоакции из HTML контейнера"""
        try:
            promo = {
                'exchange': self.exchange,
                'data_source': 'browser_pool',
                'source_url': self.url
            }

            # Извлекаем title
            title_element = container.select_one(selectors['title'])
            if title_element:
                promo['title'] = title_element.get_text(strip=True)

            # Извлекаем description
            desc_element = container.select_one(selectors.get('description', ''))
            if desc_element:
                promo['description'] = desc_element.get_text(strip=True)

            # Извлекаем link
            link_selector = selectors.get('link', '')
            if link_selector == 'self':
                if container.name == 'a' and container.get('href'):
                    link = container.get('href')
                    if link.startswith('/'):
                        base_domain = '/'.join(self.url.split('/')[:3])
                        promo['link'] = base_domain + link
                    else:
                        promo['link'] = link
            else:
                link_element = container.select_one(link_selector)
                if link_element and link_element.get('href'):
                    link = link_element.get('href')
                    if link.startswith('/'):
                        base_domain = '/'.join(self.url.split('/')[:3])
                        promo['link'] = base_domain + link
                    else:
                        promo['link'] = link

            # Остальные поля
            for field, selector_key in [
                ('start_time', 'time'),
                ('total_prize_pool', 'prize'),
                ('award_token', 'token'),
                ('participants_count', 'participants')
            ]:
                selector = selectors.get(selector_key, '')
                if selector:
                    element = container.select_one(selector)
                    if element:
                        promo[field] = element.get_text(strip=True)

            # Image
            image_selector = selectors.get('image', '')
            if image_selector:
                image_element = container.select_one(image_selector)
                if image_element and image_element.get('src'):
                    promo['icon'] = image_element.get('src')

            # Генерация ссылки если не найдена
            if not promo.get('link'):
                try:
                    url_builder = get_url_builder()
                    generated_link = url_builder.build_url(self.exchange, promo)
                    if generated_link:
                        promo['link'] = generated_link
                except Exception:
                    pass

            # Генерируем promo_id
            if promo.get('title') or promo.get('link'):
                title = promo.get('title', '')
                link = promo.get('link', '')
                stable_key = f"{self.exchange}_{title}_{link}"
                content_hash = hashlib.md5(stable_key.encode('utf-8')).hexdigest()[:12]
                promo['promo_id'] = f"{self.exchange}_browser_{content_hash}"
                return promo

            return None

        except Exception as e:
            logger.error(f"⚠️ Ошибка извлечения промо: {e}", exc_info=True)
            return None

    def _is_valid_promo(self, promo: Dict[str, Any]) -> bool:
        """Проверяет валидность промоакции"""
        if not promo.get('title') and not promo.get('description'):
            return False
        if not promo.get('promo_id'):
            return False
        title = promo.get('title', '')
        if len(title.strip()) < 2:
            return False
        return True
