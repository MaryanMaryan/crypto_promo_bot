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
        if 'binance' in url:
            return 'binance'
        elif 'bybit' in url:
            return 'bybit'
        elif 'kucoin' in url:
            return 'kucoin'
        elif 'okx' in url:
            return 'okx'
        elif 'huobi' in url:
            return 'huobi'
        else:
            return 'unknown'

    def make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[requests.Response]:
        """Обновленный метод запроса с интеграцией системы менеджеров"""
        # Соблюдаем интервал между запросами
        self._respect_request_interval()

        # Получаем целевую биржу из URL
        exchange = self._extract_exchange_from_url(url)
        self.logger.info(f"🌐 BaseParser: Выполнение {method} запроса к {exchange}")
        self.logger.debug(f"   URL: {url}")

        # Получаем оптимальную комбинацию прокси + User-Agent
        self.logger.debug(f"🔄 Получение оптимальной комбинации прокси + User-Agent для {exchange}")
        proxy, user_agent = self.rotation_manager.get_optimal_combination(exchange)

        if not proxy or not user_agent:
            self.logger.error(f"❌ Не удалось получить комбинацию прокси/User-Agent для {exchange}")
            return None

        self.logger.info(f"🔧 Используем прокси: {proxy.address} (протокол: {proxy.protocol})")
        self.logger.info(f"🔧 Используем User-Agent: {user_agent.browser_type} {user_agent.browser_version} на {user_agent.platform}")

        # Подготавливаем параметры запроса
        proxies = {
            'http': f"{proxy.protocol}://{proxy.address}",
            'https': f"{proxy.protocol}://{proxy.address}"
        }

        headers = kwargs.get('headers', {})
        headers['User-Agent'] = user_agent.user_agent_string
        kwargs['headers'] = headers
        kwargs['proxies'] = proxies
        kwargs['timeout'] = kwargs.get('timeout', 30)

        start_time = time.time()
        response = None
        success = False
        response_code = None
        response_time_ms = 0

        try:
            self.logger.debug(f"📡 Отправка запроса...")
            response = requests.request(method, url, **kwargs)
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
                self.logger.warning(f"   Прокси: {proxy.address}, User-Agent: {user_agent.browser_type}")

        except requests.exceptions.Timeout:
            response_time_ms = (time.time() - start_time) * 1000
            self.logger.error(f"⏰ ТАЙМАУТ запроса для {exchange} ({response_time_ms:.0f}мс)")
        except requests.exceptions.ProxyError as e:
            self.logger.error(f"🔌 ОШИБКА ПРОКСИ для {exchange}: {e}")
            self.logger.error(f"   Прокси: {proxy.address}")
        except Exception as e:
            self.logger.error(f"❌ ОШИБКА запроса для {exchange}: {e}", exc_info=True)
        finally:
            # Всегда логируем результат запроса
            self.logger.debug(f"📊 Логирование результата запроса в систему статистики")
            self.rotation_manager.handle_request_result(
                exchange=exchange,
                proxy_id=proxy.id,
                user_agent_id=user_agent.id,
                success=success,
                response_time_ms=response_time_ms,
                response_code=response_code
            )

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