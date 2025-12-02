# parsers/browser_parser.py
"""
BROWSER PARSER С PLAYWRIGHT
Парсинг динамических сайтов с JavaScript через реальный браузер
Интегрирован с системой ротации прокси и User-Agent
"""

import logging
import time
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Error as PlaywrightError

from .base_parser import BaseParser
from .html_templates import get_html_selectors

logger = logging.getLogger(__name__)

class BrowserParser(BaseParser):
    """
    Универсальный парсер с использованием Playwright для обхода JavaScript-защиты
    """

    def __init__(self, url: str):
        super().__init__(url)
        self.exchange = self._extract_exchange_from_url(url)
        self._browser = None
        self._context = None
        self._page = None

    def get_promotions(self) -> List[Dict[str, Any]]:
        """Основной метод парсинга через браузер"""
        try:
            logger.info(f"🌐 BrowserParser: Начало парсинга через Playwright")
            logger.info(f"   Биржа: {self.exchange}")
            logger.info(f"   URL: {self.url}")

            # Получаем прокси и User-Agent из системы ротации
            proxy, user_agent = self.rotation_manager.get_optimal_combination(self.exchange)

            if not proxy or not user_agent:
                logger.warning(f"⚠️ Прокси/User-Agent не доступны для {self.exchange}")
                logger.warning(f"🔄 Работаем БЕЗ прокси (может быть заблокировано)")

            # Запускаем браузер
            html_content = self._fetch_with_browser(proxy, user_agent)

            if not html_content:
                logger.error(f"❌ Не удалось получить HTML контент")
                return []

            logger.info(f"✅ HTML контент получен, размер: {len(html_content)} символов")

            # Парсим HTML
            promotions = self._parse_html_content(html_content)

            logger.info(f"✅ BrowserParser: Найдено {len(promotions)} промоакций")
            for i, promo in enumerate(promotions[:5], 1):
                logger.info(f"   {i}. {promo.get('title', 'Без названия')}")

            return promotions

        except Exception as e:
            logger.error(f"❌ Ошибка BrowserParser: {e}", exc_info=True)
            return []

    def _fetch_with_browser(self, proxy, user_agent) -> Optional[str]:
        """Загружает страницу через Playwright с прокси и User-Agent"""
        playwright = None
        try:
            playwright = sync_playwright().start()

            # Настройки браузера
            browser_args = [
                '--disable-blink-features=AutomationControlled',  # Отключаем детекцию автоматизации
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
            ]

            # Настройки прокси если есть
            proxy_config = None
            if proxy:
                # Парсим прокси для Playwright (поддержка username:password@host:port)
                proxy_address = proxy.address
                username = None
                password = None

                # Если прокси содержит авторизацию
                if '@' in proxy_address:
                    auth_part, server_part = proxy_address.split('@', 1)
                    if ':' in auth_part:
                        username, password = auth_part.split(':', 1)
                        proxy_address = server_part

                proxy_config = {
                    'server': f"{proxy.protocol}://{proxy_address}",
                }

                # Добавляем авторизацию если есть
                if username and password:
                    proxy_config['username'] = username
                    proxy_config['password'] = password
                    logger.info(f"🔧 Используем прокси: {proxy_address} (с авторизацией)")
                else:
                    logger.info(f"🔧 Используем прокси: {proxy_address}")

            # Запускаем браузер
            logger.debug(f"🚀 Запуск Chromium браузера...")
            browser = playwright.chromium.launch(
                headless=True,
                args=browser_args,
                proxy=proxy_config
            )

            # Создаём контекст с User-Agent
            context_options = {
                'viewport': {'width': 1920, 'height': 1080},
                'locale': 'en-US',
                'timezone_id': 'America/New_York',
            }

            if user_agent:
                context_options['user_agent'] = user_agent.user_agent_string
                logger.info(f"🔧 Используем User-Agent: {user_agent.browser_type} {user_agent.browser_version}")

            context = browser.new_context(**context_options)

            # Добавляем реалистичные headers
            context.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            })

            # Маскируем автоматизацию
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });

                // Переопределяем chrome.runtime
                window.chrome = {
                    runtime: {}
                };

                // Переопределяем permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)

            # Открываем страницу
            page = context.new_page()
            logger.info(f"📡 Загрузка страницы: {self.url}")

            start_time = time.time()

            # Переходим на страницу с таймаутом
            response = page.goto(self.url, wait_until='networkidle', timeout=30000)

            response_time_ms = (time.time() - start_time) * 1000

            if response and response.ok:
                logger.info(f"✅ Страница загружена успешно: {response.status} ({response_time_ms:.0f}мс)")
            else:
                status = response.status if response else 'N/A'
                logger.warning(f"⚠️ Страница загружена с кодом: {status} ({response_time_ms:.0f}мс)")

            # Ждём полной загрузки JavaScript
            logger.debug(f"⏳ Ожидание загрузки JavaScript контента...")
            page.wait_for_timeout(3000)  # 3 секунды на выполнение JS

            # Скроллим страницу для загрузки lazy-load контента
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Получаем HTML контент
            html_content = page.content()

            # Закрываем браузер
            context.close()
            browser.close()
            playwright.stop()

            logger.info(f"✅ HTML контент успешно получен через браузер")

            # Логируем результат в статистику если есть прокси
            if proxy and user_agent:
                success = response and response.ok
                response_code = response.status if response else None
                self.rotation_manager.handle_request_result(
                    exchange=self.exchange,
                    proxy_id=proxy.id,
                    user_agent_id=user_agent.id,
                    success=success,
                    response_time_ms=response_time_ms,
                    response_code=response_code
                )

            return html_content

        except PlaywrightError as e:
            logger.error(f"❌ Playwright ошибка: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при загрузке через браузер: {e}", exc_info=True)
            return None
        finally:
            # Гарантированная очистка ресурсов
            try:
                if playwright:
                    playwright.stop()
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

            promotions = []

            for i, container in enumerate(containers, 1):
                try:
                    promo = self._extract_promo_from_container(container, selectors)
                    if promo and self._is_valid_promo(promo):
                        promotions.append(promo)
                        logger.debug(f"   ✅ [{i}/{len(containers)}] Промоакция извлечена: {promo.get('title', 'Без названия')}")
                    else:
                        logger.debug(f"   ⏭️ [{i}/{len(containers)}] Контейнер не прошёл валидацию")
                except Exception as e:
                    logger.debug(f"   ⚠️ [{i}/{len(containers)}] Ошибка извлечения: {e}")
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
                'data_source': 'browser',
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
            link_element = container.select_one(selectors.get('link', ''))
            if link_element and link_element.get('href'):
                link = link_element.get('href')
                if link.startswith('/'):
                    base_domain = '/'.join(self.url.split('/')[:3])
                    promo['link'] = base_domain + link
                else:
                    promo['link'] = link

            # Извлекаем остальные поля
            time_element = container.select_one(selectors.get('time', ''))
            if time_element:
                promo['start_time'] = time_element.get_text(strip=True)

            prize_element = container.select_one(selectors.get('prize', ''))
            if prize_element:
                promo['total_prize_pool'] = prize_element.get_text(strip=True)

            token_element = container.select_one(selectors.get('token', ''))
            if token_element:
                promo['award_token'] = token_element.get_text(strip=True)

            participants_element = container.select_one(selectors.get('participants', ''))
            if participants_element:
                promo['participants_count'] = participants_element.get_text(strip=True)

            image_element = container.select_one(selectors.get('image', ''))
            if image_element and image_element.get('src'):
                promo['icon'] = image_element.get('src')

            # Генерируем promo_id
            if promo.get('title') or promo.get('link'):
                import hashlib
                title = promo.get('title', '')
                link = promo.get('link', '')
                stable_key = f"{self.exchange}_{title}_{link}"
                content_hash = hashlib.md5(stable_key.encode('utf-8')).hexdigest()[:12]
                promo['promo_id'] = f"{self.exchange}_browser_{content_hash}"
                return promo

            return None

        except Exception as e:
            logger.debug(f"⚠️ Ошибка извлечения промо из контейнера: {e}")
            return None

    def _is_valid_promo(self, promo: Dict[str, Any]) -> bool:
        """Проверяет валидность промоакции"""
        if not promo.get('title') and not promo.get('description'):
            return False

        if not promo.get('promo_id'):
            return False

        # Минимальная длина заголовка
        title = promo.get('title', '')
        if len(title.strip()) < 2:
            return False

        return True
