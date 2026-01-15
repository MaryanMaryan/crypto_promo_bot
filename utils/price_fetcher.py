"""
utils/price_fetcher.py
Утилита для получения актуальных цен криптовалют с CoinGecko и CoinMarketCap
"""

import requests
import logging
from typing import Optional, Dict
import time
import os

logger = logging.getLogger(__name__)

class PriceFetcher:
    """Получение цен токенов с CoinGecko и CoinMarketCap"""

    COINGECKO_API = "https://api.coingecko.com/api/v3"
    COINMARKETCAP_API = "https://pro-api.coinmarketcap.com/v1"
    CACHE_DURATION = 300  # 5 минут кэш

    def __init__(self, cmc_api_key: Optional[str] = None):
        self._cache: Dict[str, tuple] = {}  # {symbol: (price, timestamp)}
        self.cmc_api_key = cmc_api_key or os.getenv('COINMARKETCAP_API_KEY')
        self.use_cmc = bool(self.cmc_api_key)  # Использовать CMC если есть ключ

        # Circuit breaker для rate limiting
        self._rate_limit_hits = 0  # Счетчик 429 ошибок
        self._circuit_open = False  # Флаг блокировки запросов
        self.rate_limit_threshold = 5  # После 5 ошибок 429 - останавливаем запросы

    def get_token_price(self, symbol: str) -> Optional[float]:
        """
        Получить цену токена в USD
        Пробует CoinMarketCap (если есть ключ), затем CoinGecko

        Args:
            symbol: Символ токена (BTC, ETH, DOGE)

        Returns:
            Цена в USD или None если не найдена
        """
        symbol = symbol.upper()

        # Проверяем circuit breaker
        if self._circuit_open:
            logger.debug(f"⚡ Circuit breaker активен - пропускаем запрос цены для {symbol}")
            return None

        # Проверяем кэш
        if symbol in self._cache:
            price, timestamp = self._cache[symbol]
            if time.time() - timestamp < self.CACHE_DURATION:
                logger.debug(f"💰 Цена {symbol} из кэша: ${price}")
                return price

        # Пробуем CoinMarketCap если есть API ключ
        if self.use_cmc:
            price = self._get_price_from_cmc(symbol)
            if price:
                return price
            # Если CMC не сработал, пробуем CoinGecko
            logger.debug(f"⚠️ CMC не вернул цену для {symbol}, пробуем CoinGecko...")

        # Пробуем CoinGecko
        return self._get_price_from_coingecko(symbol)

    def _handle_rate_limit(self, source: str):
        """
        Обработка rate limit (429 ошибка)
        После 5 ошибок активирует circuit breaker
        """
        self._rate_limit_hits += 1
        logger.warning(f"⚠️ Rate limit hit #{self._rate_limit_hits} from {source}")

        if self._rate_limit_hits >= self.rate_limit_threshold:
            self._circuit_open = True
            logger.error(
                f"🚨 CIRCUIT BREAKER АКТИВИРОВАН! "
                f"Получено {self._rate_limit_hits} ошибок 429. "
                f"Запросы цен остановлены до конца парсинга."
            )

    def reset_circuit_breaker(self):
        """
        Сбросить circuit breaker (для использования при следующем парсинге)
        """
        if self._circuit_open:
            logger.info("🔄 Circuit breaker сброшен")
        self._rate_limit_hits = 0
        self._circuit_open = False

    def _get_price_from_cmc(self, symbol: str) -> Optional[float]:
        """Получить цену с CoinMarketCap"""
        try:
            logger.info(f"📡 Запрос цены {symbol} с CoinMarketCap...")

            url = f"{self.COINMARKETCAP_API}/cryptocurrency/quotes/latest"
            headers = {
                'X-CMC_PRO_API_KEY': self.cmc_api_key,
                'Accept': 'application/json'
            }
            params = {
                'symbol': symbol,
                'convert': 'USD'
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # CMC возвращает данные в двух форматах:
            # 1. List: data[symbol][0].quote.USD.price
            # 2. Dict: data[symbol].quote.USD.price
            if data.get('status', {}).get('error_code') == 0:
                token_data = data.get('data', {}).get(symbol)
                if token_data:
                    # Обработка обоих форматов
                    if isinstance(token_data, list):
                        # List формат
                        if len(token_data) > 0:
                            price = token_data[0]['quote']['USD']['price']
                        else:
                            logger.warning(f"⚠️ Пустой список данных для {symbol}")
                            return None
                    elif isinstance(token_data, dict):
                        # Dict формат
                        price = token_data['quote']['USD']['price']
                    else:
                        logger.warning(f"⚠️ Неизвестный формат данных для {symbol}: {type(token_data)}")
                        return None

                    # Сохраняем в кэш
                    self._cache[symbol] = (price, time.time())
                    logger.info(f"✅ Цена {symbol} (CMC): ${price}")
                    return price

            logger.warning(f"⚠️ Монета {symbol} не найдена на CoinMarketCap")
            return None

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                self._handle_rate_limit("CoinMarketCap")
            else:
                logger.error(f"❌ Ошибка запроса CMC для {symbol}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка запроса CMC для {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка CMC для {symbol}: {e}")
            return None

    def _get_price_from_coingecko(self, symbol: str) -> Optional[float]:
        """Получить цену с CoinGecko"""
        try:
            logger.info(f"📡 Запрос цены {symbol} с CoinGecko...")

            # Сначала находим ID монеты
            search_url = f"{self.COINGECKO_API}/search"
            params = {"query": symbol}
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()

            search_data = response.json()

            # Ищем точное совпадение по symbol
            coin_id = None
            for coin in search_data.get('coins', []):
                if coin['symbol'].upper() == symbol:
                    coin_id = coin['id']
                    break

            if not coin_id:
                logger.warning(f"⚠️ Монета {symbol} не найдена на CoinGecko")
                return None

            # Получаем цену
            price_url = f"{self.COINGECKO_API}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd"
            }
            response = requests.get(price_url, params=params, timeout=10)
            response.raise_for_status()

            price_data = response.json()
            price = price_data.get(coin_id, {}).get('usd')

            if price:
                # Сохраняем в кэш
                self._cache[symbol] = (price, time.time())
                logger.info(f"✅ Цена {symbol} (CoinGecko): ${price}")
                return price
            else:
                logger.warning(f"⚠️ Цена {symbol} не найдена в ответе CoinGecko")
                return None

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                self._handle_rate_limit("CoinGecko")
            else:
                logger.error(f"❌ Ошибка запроса CoinGecko для {symbol}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка запроса CoinGecko для {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка CoinGecko для {symbol}: {e}")
            return None

    def get_multiple_prices(self, symbols: list) -> Dict[str, Optional[float]]:
        """
        Получить цены нескольких токенов одним запросом (более эффективно)

        Args:
            symbols: Список символов ['BTC', 'ETH', 'DOGE']

        Returns:
            Словарь {symbol: price}
        """
        prices = {}
        symbols_to_fetch = []

        # Проверяем кэш для каждого символа
        for symbol in symbols:
            symbol = symbol.upper()
            if symbol in self._cache:
                price, timestamp = self._cache[symbol]
                if time.time() - timestamp < self.CACHE_DURATION:
                    logger.debug(f"💰 Цена {symbol} из кэша: ${price}")
                    prices[symbol] = price
                else:
                    symbols_to_fetch.append(symbol)
            else:
                symbols_to_fetch.append(symbol)

        # Если все цены в кэше, возвращаем результат
        if not symbols_to_fetch:
            return prices

        try:
            logger.info(f"📡 Запрос цен для {len(symbols_to_fetch)} токенов с CoinGecko...")

            # Сначала получаем ID монет для всех символов
            coin_ids_map = {}  # {symbol: coin_id}

            for symbol in symbols_to_fetch:
                search_url = f"{self.COINGECKO_API}/search"
                params = {"query": symbol}
                response = requests.get(search_url, params=params, timeout=10)
                response.raise_for_status()

                search_data = response.json()

                # Ищем точное совпадение
                for coin in search_data.get('coins', []):
                    if coin['symbol'].upper() == symbol:
                        coin_ids_map[symbol] = coin['id']
                        break

                # Задержка между поисками
                time.sleep(0.3)

            # Получаем цены для всех найденных ID одним запросом
            if coin_ids_map:
                coin_ids = ','.join(coin_ids_map.values())
                price_url = f"{self.COINGECKO_API}/simple/price"
                params = {
                    "ids": coin_ids,
                    "vs_currencies": "usd"
                }
                response = requests.get(price_url, params=params, timeout=10)
                response.raise_for_status()

                price_data = response.json()

                # Сопоставляем цены с символами
                for symbol, coin_id in coin_ids_map.items():
                    price = price_data.get(coin_id, {}).get('usd')
                    if price:
                        self._cache[symbol] = (price, time.time())
                        prices[symbol] = price
                        logger.info(f"✅ {symbol}: ${price}")
                    else:
                        prices[symbol] = None
                        logger.warning(f"⚠️ {symbol}: цена не найдена")

            # Для символов, которые не найдены, устанавливаем None
            for symbol in symbols_to_fetch:
                if symbol not in prices:
                    prices[symbol] = None
                    logger.warning(f"⚠️ {symbol}: не найден на CoinGecko")

            return prices

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка запроса цен: {e}")
            # Возвращаем None для всех не закэшированных символов
            for symbol in symbols_to_fetch:
                if symbol not in prices:
                    prices[symbol] = None
            return prices
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при получении цен: {e}")
            for symbol in symbols_to_fetch:
                if symbol not in prices:
                    prices[symbol] = None
            return prices


# Singleton instance
_price_fetcher = None

def get_price_fetcher() -> PriceFetcher:
    """Получить singleton instance PriceFetcher"""
    global _price_fetcher
    if _price_fetcher is None:
        _price_fetcher = PriceFetcher()
    return _price_fetcher
