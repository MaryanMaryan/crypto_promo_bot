import time
import requests
import logging
from typing import Optional, Dict, Any

from utils.rotation_manager import get_rotation_manager
from utils.statistics_manager import get_statistics_manager

class BaseParser:
    def __init__(self, url: str = None):  # ✅ ДОБАВЛЯЕМ url параметр
        self.url = url
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)
        self.rotation_manager = get_rotation_manager()
        self.stats_manager = get_statistics_manager()
        self._last_request_time = 0
        self._min_request_interval = 1.0

    def _extract_exchange_from_url(self, url: str) -> str:
        """Извлечение названия биржи из URL"""
        url_lower = url.lower()

        if 'binance' in url_lower:
            return 'binance'
        elif 'bybit' in url_lower:
            return 'bybit'
        elif 'mexc' in url_lower:
            return 'mexc'
        elif 'kucoin' in url_lower:
            return 'kucoin'
        elif 'okx' in url_lower or 'okex' in url_lower:
            return 'okx'
        elif 'gate.io' in url_lower or 'gateio' in url_lower:
            return 'gate'
        elif 'huobi' in url_lower:
            return 'huobi'
        elif 'bitget' in url_lower:
            return 'bitget'
        else:
            return 'unknown'

    def make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[requests.Response]:
        """Обновленный метод запроса с интеграцией системы менеджеров и fallback режимом"""
        # Соблюдаем интервал между запросами
        self._respect_request_interval()

        # Получаем целевую биржу из URL
        exchange = self._extract_exchange_from_url(url)
        self.logger.info(f"🌐 BaseParser: Выполнение {method} запроса к {exchange}")
        self.logger.debug(f"   URL: {url}")

        # Получаем оптимальную комбинацию прокси + User-Agent
        self.logger.debug(f"🔄 Получение оптимальной комбинации прокси + User-Agent для {exchange}")
        proxy, user_agent = self.rotation_manager.get_optimal_combination(exchange)

        # FALLBACK РЕЖИМ: Работа без прокси если их нет
        use_fallback = False
        if not proxy or not user_agent:
            self.logger.warning(f"⚠️ Прокси/User-Agent не доступны для {exchange}")
            self.logger.warning(f"🔄 FALLBACK: Работаем БЕЗ прокси с улучшенными headers")
            use_fallback = True
        else:
            self.logger.info(f"🔧 Используем прокси: {proxy.address} (протокол: {proxy.protocol})")
            self.logger.info(f"🔧 Используем User-Agent: {user_agent.browser_type} {user_agent.browser_version} на {user_agent.platform}")

        # Подготавливаем параметры запроса
        headers = kwargs.get('headers', {})

        # Определяем тип запроса (API или HTML)
        is_api_request = any(indicator in url.lower() for indicator in ['/api/', '/x-api/', '/v1/', '/v2/', '/v3/', '/v4/', '/v5/'])

        if is_api_request:
            # Заголовки для API запросов
            api_headers = {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
            }
            headers.update(api_headers)
        else:
            # Заголовки для HTML/браузерных запросов
            browser_headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            }

            # Специальные заголовки для Bybit
            if 'bybit' in exchange.lower():
                browser_headers.update({
                    'Referer': 'https://www.bybit.com/',
                    'Origin': 'https://www.bybit.com',
                    'Sec-Ch-Ua': '"Google Chrome";v="120", "Chromium";v="120", "Not_A Brand";v="99"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                })

            headers.update(browser_headers)

        if use_fallback:
            # Fallback User-Agent - современный Chrome на Windows
            headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            # Не используем прокси в fallback режиме
        else:
            headers['User-Agent'] = user_agent.user_agent_string
            # Используем прокси
            proxies = {
                'http': f"{proxy.protocol}://{proxy.address}",
                'https': f"{proxy.protocol}://{proxy.address}"
            }
            kwargs['proxies'] = proxies

        kwargs['headers'] = headers
        kwargs['timeout'] = kwargs.get('timeout', 30)

        start_time = time.time()
        response = None
        success = False
        response_code = None
        response_time_ms = 0

        try:
            self.logger.debug(f"📡 Отправка запроса...")
            response = self.session.request(method, url, **kwargs)  # ✅ Используем session для сохранения cookies
            response_time_ms = (time.time() - start_time) * 1000
            response_code = response.status_code

            success = response.status_code == 200

            if success:
                self.logger.info(f"✅ Запрос успешен: {response_code} ({response_time_ms:.0f}мс)")
                self.logger.debug(f"   Content-Type: {response.headers.get('Content-Type', 'N/A')}")
                self.logger.debug(f"   Content-Length: {len(response.content)} байт")
            else:
                self.logger.warning(f"⚠️ Запрос вернул код {response_code} ({response_time_ms:.0f}мс)")

            # Обрабатываем блокировки
            if response.status_code in [403, 429]:
                self.logger.warning(f"🚫 Запрос ЗАБЛОКИРОВАН для {exchange}. Код: {response.status_code}")
                if not use_fallback and proxy and user_agent:
                    self.logger.warning(f"   Прокси: {proxy.address}, User-Agent: {user_agent.browser_type}")
                elif use_fallback:
                    self.logger.warning(f"   Режим: FALLBACK (без прокси)")

        except requests.exceptions.Timeout:
            response_time_ms = (time.time() - start_time) * 1000
            self.logger.error(f"⏰ ТАЙМАУТ запроса для {exchange} ({response_time_ms:.0f}мс)")
        except requests.exceptions.ProxyError as e:
            self.logger.error(f"🔌 ОШИБКА ПРОКСИ для {exchange}: {e}")
            if proxy:
                self.logger.error(f"   Прокси: {proxy.address}")
        except Exception as e:
            self.logger.error(f"❌ ОШИБКА запроса для {exchange}: {e}", exc_info=True)
        finally:
            # Логируем результат запроса только если НЕ fallback режим
            if not use_fallback and proxy and user_agent:
                self.logger.debug(f"📊 Логирование результата запроса в систему статистики")
                self.rotation_manager.handle_request_result(
                    exchange=exchange,
                    proxy_id=proxy.id,
                    user_agent_id=user_agent.id,
                    success=success,
                    response_time_ms=response_time_ms,
                    response_code=response_code
                )
            elif use_fallback:
                self.logger.debug(f"⏭️ Пропускаем логирование статистики (fallback режим)")

        return response

    def _respect_request_interval(self):
        """Соблюдение минимального интервала между запросами"""
        current_time = time.time()
        elapsed = current_time - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    # Совместимость со старым кодом
    def get_current_proxy(self) -> Dict:
        """Совместимость со старым кодом - возвращает текущий прокси для биржи по умолчанию"""
        proxy, _ = self.rotation_manager.get_optimal_combination('binance')
        if proxy:
            return {
                'http': f"{proxy.protocol}://{proxy.address}",
                'https': f"{proxy.protocol}://{proxy.address}"
            }
        return {}

    def get_browser_headers(self, url: str) -> Dict:
        """Совместимость со старым кодом - возвращает заголовки с User-Agent"""
        exchange = self._extract_exchange_from_url(url)
        _, user_agent = self.rotation_manager.get_optimal_combination(exchange)
        
        headers = {
            'User-Agent': user_agent.user_agent_string if user_agent else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        return headers