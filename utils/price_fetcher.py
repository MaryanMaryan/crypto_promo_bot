"""
utils/price_fetcher.py
Утилита для получения актуальных цен криптовалют с бирж (Bybit, KuCoin, Gate.io)
с fallback на Pre-market данные.

Приоритет источников:
1. Bybit API (бесплатно, без лимитов)
2. KuCoin API (бесплатно, много альткоинов)
3. Gate.io API (бесплатно, ещё больше альткоинов)
4. Pre-market данные (MEXC, Gate.io pre-market) - для токенов до листинга
"""

import requests
import logging
from typing import Optional, Dict, List, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Lazy import для premarket fetcher (избегаем циклических импортов)
_premarket_fetcher = None

def _get_premarket_fetcher():
    """Ленивая загрузка premarket fetcher"""
    global _premarket_fetcher
    if _premarket_fetcher is None:
        try:
            from utils.premarket_price_fetcher import get_premarket_fetcher
            _premarket_fetcher = get_premarket_fetcher()
        except ImportError as e:
            logger.debug(f"⚠️ PremarketFetcher недоступен: {e}")
            _premarket_fetcher = False  # Помечаем как недоступный
    return _premarket_fetcher if _premarket_fetcher else None


class PriceFetcher:
    """Получение цен токенов с бирж"""

    # API endpoints
    BYBIT_API = "https://api.bybit.com/v5/market/tickers"
    KUCOIN_API = "https://api.kucoin.com/api/v1/market/orderbook/level1"
    GATEIO_API = "https://api.gateio.ws/api/v4/spot/tickers"
    
    # Настройки
    CACHE_DURATION = 300  # 5 минут кэш
    FAST_TIMEOUT = 3  # Быстрый таймаут для бирж
    
    # Стейблкоины (цена = 1 USD)
    STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX', 'LUSD', 'SUSD'}

    def __init__(self):
        self._cache: Dict[str, Tuple[float, float]] = {}  # {symbol: (price, timestamp)}
        
        # Статистика для логирования
        self._stats = {
            'bybit_hits': 0,
            'kucoin_hits': 0,
            'gateio_hits': 0,
            'premarket_hits': 0,
            'cache_hits': 0,
            'not_found': 0
        }

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
        
        # Fallback: Pre-market данные (для токенов до листинга)
        price = self._try_premarket(symbol)
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

    def _try_premarket(self, symbol: str) -> Optional[float]:
        """
        Пробует получить цену из Pre-market данных.
        Используется как финальный fallback для токенов, которые ещё не листинге.
        """
        fetcher = _get_premarket_fetcher()
        if fetcher is None:
            return None
        
        try:
            price = fetcher.get_premarket_price(symbol)
            if price is not None:
                self._stats['premarket_hits'] += 1
                logger.debug(f"📈 {symbol}: ${price:.6f} (Pre-market)")
                return price
        except Exception as e:
            logger.debug(f"⚠️ Pre-market ошибка для {symbol}: {e}")
        
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
                f"Pre-market={stats['premarket_hits']}, "
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
