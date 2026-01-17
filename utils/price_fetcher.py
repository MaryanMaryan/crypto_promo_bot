"""
utils/price_fetcher.py
Утилита для получения актуальных цен криптовалют с бирж (Bybit, KuCoin, Gate.io)
с fallback на CoinGecko и CoinMarketCap.

Приоритет источников:
1. Bybit API (бесплатно, без лимитов)
2. KuCoin API (бесплатно, много альткоинов)
3. Gate.io API (бесплатно, ещё больше альткоинов)
4. CoinGecko API (лимиты ~30 req/min)
5. CoinMarketCap API (требует API ключ)
"""

import requests
import logging
from typing import Optional, Dict, List, Tuple
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Получение цен токенов с бирж и агрегаторов"""

    # API endpoints
    BYBIT_API = "https://api.bybit.com/v5/market/tickers"
    KUCOIN_API = "https://api.kucoin.com/api/v1/market/orderbook/level1"
    GATEIO_API = "https://api.gateio.ws/api/v4/spot/tickers"
    COINGECKO_API = "https://api.coingecko.com/api/v3"
    COINMARKETCAP_API = "https://pro-api.coinmarketcap.com/v1"
    
    # Настройки
    CACHE_DURATION = 300  # 5 минут кэш
    FAST_TIMEOUT = 3  # Быстрый таймаут для бирж
    SLOW_TIMEOUT = 10  # Таймаут для агрегаторов
    
    # Стейблкоины (цена = 1 USD)
    STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX', 'LUSD', 'SUSD'}

    def __init__(self, cmc_api_key: Optional[str] = None):
        self._cache: Dict[str, Tuple[float, float]] = {}  # {symbol: (price, timestamp)}
        self.cmc_api_key = cmc_api_key or os.getenv('COINMARKETCAP_API_KEY')
        self.use_cmc = bool(self.cmc_api_key)
        
        # Статистика для логирования
        self._stats = {
            'bybit_hits': 0,
            'kucoin_hits': 0,
            'gateio_hits': 0,
            'coingecko_hits': 0,
            'cmc_hits': 0,
            'cache_hits': 0,
            'not_found': 0
        }
        
        # Circuit breaker для CoinGecko/CMC (они имеют лимиты)
        self._rate_limit_hits = 0
        self._circuit_open = False
        self.rate_limit_threshold = 5

    def get_token_price(self, symbol: str, preferred_exchange: Optional[str] = None) -> Optional[float]:
        """
        Получить цену токена в USD.
        
        Args:
            symbol: Символ токена (BTC, ETH, SCOR)
            preferred_exchange: Предпочтительная биржа ('bybit', 'kucoin', 'gateio', 'mexc')
                              Используется для оптимизации - сначала пробуем эту биржу
        
        Returns:
            Цена в USD или None если не найдена
        """
        symbol = symbol.upper().strip()
        
        # Стейблкоины = 1 USD
        if symbol in self.STABLECOINS:
            return 1.0
        
        # Проверяем кэш
        cached = self._get_from_cache(symbol)
        if cached is not None:
            self._stats['cache_hits'] += 1
            return cached
        
        # Определяем порядок бирж
        exchanges = self._get_exchange_order(preferred_exchange)
        
        # Пробуем биржи по порядку
        for exchange in exchanges:
            price = self._try_exchange(symbol, exchange)
            if price is not None:
                self._save_to_cache(symbol, price)
                return price
        
        # Fallback на агрегаторы (только если circuit breaker не активен)
        if not self._circuit_open:
            price = self._try_aggregators(symbol)
            if price is not None:
                self._save_to_cache(symbol, price)
                return price
        
        self._stats['not_found'] += 1
        logger.warning(f"⚠️ Цена для {symbol} не найдена ни на одном источнике")
        return None

    def _get_exchange_order(self, preferred: Optional[str]) -> List[str]:
        """Определяет порядок опроса бирж"""
        default_order = ['bybit', 'kucoin', 'gateio']
        
        if preferred and preferred.lower() in default_order:
            # Ставим предпочтительную биржу первой
            order = [preferred.lower()]
            order.extend([e for e in default_order if e != preferred.lower()])
            return order
        
        return default_order

    def _try_exchange(self, symbol: str, exchange: str) -> Optional[float]:
        """Пробует получить цену с указанной биржи"""
        try:
            if exchange == 'bybit':
                return self._get_price_from_bybit(symbol)
            elif exchange == 'kucoin':
                return self._get_price_from_kucoin(symbol)
            elif exchange == 'gateio':
                return self._get_price_from_gateio(symbol)
        except Exception as e:
            logger.debug(f"⚠️ Ошибка {exchange} для {symbol}: {e}")
        return None

    def _try_aggregators(self, symbol: str) -> Optional[float]:
        """Пробует агрегаторы (CoinGecko, CMC)"""
        # Сначала CoinGecko (не требует ключа)
        price = self._get_price_from_coingecko(symbol)
        if price:
            return price
        
        # Потом CMC (если есть ключ)
        if self.use_cmc:
            price = self._get_price_from_cmc(symbol)
            if price:
                return price
        
        return None

    def _get_from_cache(self, symbol: str) -> Optional[float]:
        """Получить цену из кэша"""
        if symbol in self._cache:
            price, timestamp = self._cache[symbol]
            if time.time() - timestamp < self.CACHE_DURATION:
                logger.debug(f"💰 {symbol}: ${price:.6f} (кэш)")
                return price
        return None

    def _save_to_cache(self, symbol: str, price: float):
        """Сохранить цену в кэш"""
        self._cache[symbol] = (price, time.time())

    # ==================== БИРЖЕВЫЕ API ====================

    def _get_price_from_bybit(self, symbol: str) -> Optional[float]:
        """Получить цену с Bybit API"""
        try:
            # Bybit использует формат SCORUSDT
            pair = f"{symbol}USDT"
            url = f"{self.BYBIT_API}?category=spot&symbol={pair}"
            
            response = requests.get(url, timeout=self.FAST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('retCode') == 0:
                    result_list = data.get('result', {}).get('list', [])
                    if result_list:
                        price = float(result_list[0].get('lastPrice', 0))
                        if price > 0:
                            self._stats['bybit_hits'] += 1
                            logger.debug(f"✅ {symbol}: ${price:.6f} (Bybit)")
                            return price
            
            return None
            
        except requests.exceptions.Timeout:
            logger.debug(f"⏱️ Bybit timeout для {symbol}")
            return None
        except Exception as e:
            logger.debug(f"⚠️ Bybit ошибка для {symbol}: {e}")
            return None

    def _get_price_from_kucoin(self, symbol: str) -> Optional[float]:
        """Получить цену с KuCoin API"""
        try:
            # KuCoin использует формат SCOR-USDT
            pair = f"{symbol}-USDT"
            url = f"{self.KUCOIN_API}?symbol={pair}"
            
            response = requests.get(url, timeout=self.FAST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '200000':
                    price_str = data.get('data', {}).get('price')
                    if price_str:
                        price = float(price_str)
                        if price > 0:
                            self._stats['kucoin_hits'] += 1
                            logger.debug(f"✅ {symbol}: ${price:.6f} (KuCoin)")
                            return price
            
            return None
            
        except requests.exceptions.Timeout:
            logger.debug(f"⏱️ KuCoin timeout для {symbol}")
            return None
        except Exception as e:
            logger.debug(f"⚠️ KuCoin ошибка для {symbol}: {e}")
            return None

    def _get_price_from_gateio(self, symbol: str) -> Optional[float]:
        """Получить цену с Gate.io API"""
        try:
            # Gate.io использует формат SCOR_USDT
            pair = f"{symbol}_USDT"
            url = f"{self.GATEIO_API}?currency_pair={pair}"
            
            response = requests.get(url, timeout=self.FAST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    price_str = data[0].get('last')
                    if price_str:
                        price = float(price_str)
                        if price > 0:
                            self._stats['gateio_hits'] += 1
                            logger.debug(f"✅ {symbol}: ${price:.6f} (Gate.io)")
                            return price
            
            return None
            
        except requests.exceptions.Timeout:
            logger.debug(f"⏱️ Gate.io timeout для {symbol}")
            return None
        except Exception as e:
            logger.debug(f"⚠️ Gate.io ошибка для {symbol}: {e}")
            return None

    # ==================== АГРЕГАТОРЫ (FALLBACK) ====================

    def _get_price_from_coingecko(self, symbol: str) -> Optional[float]:
        """Получить цену с CoinGecko (fallback)"""
        try:
            logger.debug(f"📡 Запрос CoinGecko для {symbol}...")
            
            # Сначала ищем ID монеты
            search_url = f"{self.COINGECKO_API}/search"
            response = requests.get(
                search_url, 
                params={"query": symbol}, 
                timeout=self.SLOW_TIMEOUT
            )
            
            if response.status_code == 429:
                self._handle_rate_limit("CoinGecko")
                return None
                
            response.raise_for_status()
            search_data = response.json()
            
            # Ищем точное совпадение
            coin_id = None
            for coin in search_data.get('coins', []):
                if coin['symbol'].upper() == symbol:
                    coin_id = coin['id']
                    break
            
            if not coin_id:
                return None
            
            # Получаем цену
            price_url = f"{self.COINGECKO_API}/simple/price"
            response = requests.get(
                price_url,
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=self.SLOW_TIMEOUT
            )
            
            if response.status_code == 429:
                self._handle_rate_limit("CoinGecko")
                return None
                
            response.raise_for_status()
            price_data = response.json()
            
            price = price_data.get(coin_id, {}).get('usd')
            if price:
                self._stats['coingecko_hits'] += 1
                logger.debug(f"✅ {symbol}: ${price:.6f} (CoinGecko)")
                return float(price)
            
            return None
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                self._handle_rate_limit("CoinGecko")
            return None
        except Exception as e:
            logger.debug(f"⚠️ CoinGecko ошибка для {symbol}: {e}")
            return None

    def _get_price_from_cmc(self, symbol: str) -> Optional[float]:
        """Получить цену с CoinMarketCap (fallback, требует API ключ)"""
        if not self.cmc_api_key:
            return None
            
        try:
            logger.debug(f"📡 Запрос CMC для {symbol}...")
            
            url = f"{self.COINMARKETCAP_API}/cryptocurrency/quotes/latest"
            headers = {
                'X-CMC_PRO_API_KEY': self.cmc_api_key,
                'Accept': 'application/json'
            }
            params = {'symbol': symbol, 'convert': 'USD'}
            
            response = requests.get(url, headers=headers, params=params, timeout=self.SLOW_TIMEOUT)
            
            if response.status_code == 429:
                self._handle_rate_limit("CMC")
                return None
                
            response.raise_for_status()
            data = response.json()
            
            if data.get('status', {}).get('error_code') == 0:
                token_data = data.get('data', {}).get(symbol)
                if token_data:
                    if isinstance(token_data, list) and len(token_data) > 0:
                        price = token_data[0]['quote']['USD']['price']
                    elif isinstance(token_data, dict):
                        price = token_data['quote']['USD']['price']
                    else:
                        return None
                    
                    self._stats['cmc_hits'] += 1
                    logger.debug(f"✅ {symbol}: ${price:.6f} (CMC)")
                    return float(price)
            
            return None
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                self._handle_rate_limit("CMC")
            return None
        except Exception as e:
            logger.debug(f"⚠️ CMC ошибка для {symbol}: {e}")
            return None

    # ==================== BATCH ОПЕРАЦИИ ====================

    def get_multiple_prices(self, symbols: List[str], preferred_exchange: Optional[str] = None) -> Dict[str, Optional[float]]:
        """
        Получить цены нескольких токенов эффективно.
        Использует кэш и параллельные запросы.
        
        Args:
            symbols: Список символов ['BTC', 'ETH', 'SCOR']
            preferred_exchange: Предпочтительная биржа
        
        Returns:
            Словарь {symbol: price}
        """
        prices = {}
        symbols_to_fetch = []
        
        # Проверяем кэш
        for symbol in symbols:
            symbol = symbol.upper().strip()
            
            # Стейблкоины
            if symbol in self.STABLECOINS:
                prices[symbol] = 1.0
                continue
            
            # Кэш
            cached = self._get_from_cache(symbol)
            if cached is not None:
                prices[symbol] = cached
                self._stats['cache_hits'] += 1
            else:
                symbols_to_fetch.append(symbol)
        
        # Получаем недостающие цены параллельно
        if symbols_to_fetch:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self.get_token_price, symbol, preferred_exchange): symbol
                    for symbol in symbols_to_fetch
                }
                
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        price = future.result()
                        prices[symbol] = price
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка получения цены {symbol}: {e}")
                        prices[symbol] = None
        
        return prices

    # ==================== УТИЛИТЫ ====================

    def _handle_rate_limit(self, source: str):
        """Обработка rate limit"""
        self._rate_limit_hits += 1
        logger.warning(f"⚠️ Rate limit #{self._rate_limit_hits} от {source}")
        
        if self._rate_limit_hits >= self.rate_limit_threshold:
            self._circuit_open = True
            logger.warning(
                f"🚨 Circuit breaker активирован! "
                f"Агрегаторы временно отключены (получено {self._rate_limit_hits} ошибок 429)"
            )

    def reset_circuit_breaker(self):
        """Сбросить circuit breaker"""
        if self._circuit_open:
            logger.info("🔄 Circuit breaker сброшен")
        self._rate_limit_hits = 0
        self._circuit_open = False

    def clear_cache(self):
        """Очистить кэш цен"""
        self._cache.clear()
        logger.info("🗑️ Кэш цен очищен")

    def get_stats(self) -> Dict[str, int]:
        """Получить статистику запросов"""
        return self._stats.copy()

    def log_stats(self):
        """Вывести статистику в лог"""
        stats = self._stats
        total = sum(stats.values())
        if total > 0:
            logger.info(
                f"📊 Статистика цен: "
                f"Bybit={stats['bybit_hits']}, "
                f"KuCoin={stats['kucoin_hits']}, "
                f"Gate.io={stats['gateio_hits']}, "
                f"CoinGecko={stats['coingecko_hits']}, "
                f"CMC={stats['cmc_hits']}, "
                f"Кэш={stats['cache_hits']}, "
                f"Не найдено={stats['not_found']}"
            )


# Singleton instance
_price_fetcher: Optional[PriceFetcher] = None


def get_price_fetcher() -> PriceFetcher:
    """Получить singleton instance PriceFetcher"""
    global _price_fetcher
    if _price_fetcher is None:
        _price_fetcher = PriceFetcher()
    return _price_fetcher
