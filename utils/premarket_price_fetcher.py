"""
utils/premarket_price_fetcher.py
Fallback Price Fetcher для токенов которые еще не залистены на биржах.

Оптимальный источник: MEXC Pre-Market API
- 12+ активных токенов с актуальными ценами
- Быстрое обновление (~0.8s с параллельными запросами)
- Кэширование для минимизации запросов

Использование:
    from utils.premarket_price_fetcher import get_premarket_price, get_premarket_fetcher
    
    # Получить цену одного токена
    price = get_premarket_price("SENT")
    
    # Получить все премаркет цены
    prices = get_all_premarket_prices()
    
    # Или через singleton
    fetcher = get_premarket_fetcher()
    tokens = fetcher.get_all_premarket_tokens()
"""

import requests
import logging
from typing import Optional, Dict, List, Tuple
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


@dataclass
class PremarketToken:
    """Данные токена с премаркета"""
    symbol: str
    price: float
    source: str = "mexc"
    name: Optional[str] = None
    volume_24h: Optional[float] = None
    change_24h: Optional[float] = None


class PremarketPriceFetcher:
    """
    Получение цен токенов с MEXC Pre-Market.
    Используется как fallback когда токен еще не залистен на обычных биржах.
    
    API Endpoints:
    1. type=1 - возвращает список активных премаркет токенов с названиями
    2. tickers - возвращает цены для всех токенов по ID
    """
    
    # MEXC Pre-Market API (оптимальный источник: 12+ токенов)
    MEXC_TOKENS_API = "https://www.mexc.com/api/gateway/pmt/market/web/all/underlying/type?type=1"
    MEXC_TICKERS_API = "https://www.mexc.com/api/gateway/pmt/market/web/underlying/tickers"
    
    # Gate.io как fallback (всего 2 токена, но может иметь уникальные)
    GATE_PREMARKET_API = "https://www.gate.com/apiw/v2/pre-market/service/currencies?page=1&limit=100&type=1"
    
    # Настройки
    CACHE_DURATION = 120  # 2 минуты кэш
    TOKEN_LIST_CACHE_DURATION = 300  # 5 минут кэш для списка токенов (меняется редко)
    REQUEST_TIMEOUT = 10
    
    # HTTP Headers
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    def __init__(self):
        # Кэш цен: {symbol: (price, timestamp)}
        self._price_cache: Dict[str, Tuple[float, float]] = {}
        
        # Кэш списка токенов: {id: symbol}
        self._token_map: Dict[int, str] = {}
        self._token_map_time: float = 0
        
        # Полный кэш данных токенов
        self._tokens: Dict[str, PremarketToken] = {}
        self._tokens_time: float = 0
        
        # Статистика
        self._stats = {
            'mexc_hits': 0,
            'gate_hits': 0,
            'cache_hits': 0,
            'not_found': 0,
            'requests': 0
        }
    
    def get_premarket_price(self, symbol: str) -> Optional[float]:
        """
        Получить премаркет цену токена.
        
        Args:
            symbol: Символ токена (SENT, WARD, IMU, etc.)
        
        Returns:
            Цена в USD или None если не найдена
        """
        symbol = symbol.upper().strip()
        
        # Проверяем кэш цен
        if symbol in self._price_cache:
            price, timestamp = self._price_cache[symbol]
            if time.time() - timestamp < self.CACHE_DURATION:
                self._stats['cache_hits'] += 1
                return price
        
        # Обновляем данные если кэш устарел
        if time.time() - self._tokens_time > self.CACHE_DURATION:
            self._refresh_premarket_data()
        
        # Ищем токен
        if symbol in self._tokens:
            token = self._tokens[symbol]
            self._price_cache[symbol] = (token.price, time.time())
            self._stats['mexc_hits'] += 1
            logger.debug(f"✅ Pre-market {symbol}: ${token.price:.6f}")
            return token.price
        
        self._stats['not_found'] += 1
        return None
    
    def get_all_premarket_prices(self) -> Dict[str, float]:
        """
        Получить все доступные премаркет цены.
        
        Returns:
            Словарь {symbol: price}
        """
        if time.time() - self._tokens_time > self.CACHE_DURATION:
            self._refresh_premarket_data()
        
        return {symbol: token.price for symbol, token in self._tokens.items()}
    
    def get_all_premarket_tokens(self) -> List[PremarketToken]:
        """Получить все токены с премаркетов"""
        if time.time() - self._tokens_time > self.CACHE_DURATION:
            self._refresh_premarket_data()
        
        return list(self._tokens.values())
    
    def get_premarket_token(self, symbol: str) -> Optional[PremarketToken]:
        """Получить полные данные токена"""
        symbol = symbol.upper().strip()
        
        if time.time() - self._tokens_time > self.CACHE_DURATION:
            self._refresh_premarket_data()
        
        return self._tokens.get(symbol)
    
    # ==================== ЗАГРУЗКА ДАННЫХ ====================
    
    def _refresh_premarket_data(self):
        """Обновить все премаркет данные (MEXC + Gate.io)"""
        logger.debug("🔄 Обновление премаркет данных...")
        
        new_tokens = {}
        
        # 1. Загружаем MEXC (основной источник)
        mexc_tokens = self._fetch_mexc_premarket()
        new_tokens.update(mexc_tokens)
        
        # 2. Загружаем Gate.io (дополнительные токены)
        gate_tokens = self._fetch_gate_premarket()
        for symbol, token in gate_tokens.items():
            if symbol not in new_tokens:  # Не перезаписываем MEXC данные
                new_tokens[symbol] = token
        
        self._tokens = new_tokens
        self._tokens_time = time.time()
        
        logger.debug(f"📊 Загружено {len(new_tokens)} премаркет токенов (MEXC: {len(mexc_tokens)}, Gate: {len(gate_tokens)})")
    
    def _fetch_mexc_premarket(self) -> Dict[str, PremarketToken]:
        """
        Получить данные с MEXC Pre-Market.
        Требует 2 запроса: tokens (названия) + tickers (цены)
        """
        tokens = {}
        
        try:
            self._stats['requests'] += 2
            
            # Параллельные запросы для скорости
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_tokens = executor.submit(
                    requests.get, self.MEXC_TOKENS_API, 
                    headers=self.HEADERS, timeout=self.REQUEST_TIMEOUT
                )
                future_tickers = executor.submit(
                    requests.get, self.MEXC_TICKERS_API,
                    headers=self.HEADERS, timeout=self.REQUEST_TIMEOUT
                )
                
                resp_tokens = future_tokens.result()
                resp_tickers = future_tickers.result()
            
            if resp_tokens.status_code != 200 or resp_tickers.status_code != 200:
                logger.warning(f"⚠️ MEXC API error: tokens={resp_tokens.status_code}, tickers={resp_tickers.status_code}")
                return tokens
            
            data_tokens = resp_tokens.json()
            data_tickers = resp_tickers.json()
            
            if data_tokens.get('code') != 0 or data_tickers.get('code') != 0:
                return tokens
            
            # Создаем карту ID -> symbol
            token_list = data_tokens.get('data', [])
            token_info = {t['id']: t for t in token_list}
            
            # Создаем карту ID -> price
            ticker_list = data_tickers.get('data', [])
            ticker_map = {t['id']: t for t in ticker_list}
            
            # Объединяем данные
            for token_id, info in token_info.items():
                ticker = ticker_map.get(token_id)
                if not ticker:
                    continue
                
                symbol = info.get('vn', '').upper()
                if not symbol:
                    continue
                
                try:
                    price = float(ticker.get('lp', 0))
                except (ValueError, TypeError):
                    continue
                
                if price <= 0:
                    continue
                
                tokens[symbol] = PremarketToken(
                    symbol=symbol,
                    price=price,
                    source='mexc'
                )
            
            logger.debug(f"✅ MEXC Pre-Market: {len(tokens)} токенів")
            
        except requests.exceptions.Timeout:
            logger.warning("⏱️ MEXC Pre-Market timeout")
        except Exception as e:
            logger.warning(f"⚠️ MEXC Pre-Market помилка: {e}")
        
        return tokens
    
    def _fetch_gate_premarket(self) -> Dict[str, PremarketToken]:
        """Получить данные с Gate.io Pre-Market (fallback)"""
        tokens = {}
        
        try:
            self._stats['requests'] += 1
            
            resp = requests.get(
                self.GATE_PREMARKET_API, 
                headers=self.HEADERS, 
                timeout=self.REQUEST_TIMEOUT
            )
            
            if resp.status_code != 200:
                return tokens
            
            data = resp.json()
            if data.get('code') != 0:
                return tokens
            
            items = data.get('data', {}).get('list', [])
            
            for item in items:
                symbol = item.get('currency', '').upper()
                if not symbol:
                    continue
                
                try:
                    price = float(item.get('avg_price', 0))
                except (ValueError, TypeError):
                    continue
                
                if price <= 0:
                    continue
                
                tokens[symbol] = PremarketToken(
                    symbol=symbol,
                    price=price,
                    source='gate',
                    name=item.get('full_name')
                )
            
            if tokens:
                logger.debug(f"✅ Gate.io Pre-Market: {len(tokens)} токенів")
            
        except requests.exceptions.Timeout:
            logger.debug("⏱️ Gate.io Pre-Market timeout")
        except Exception as e:
            logger.debug(f"⚠️ Gate.io Pre-Market помилка: {e}")
        
        return tokens
    
    # ==================== УТИЛИТЫ ====================
    
    def get_stats(self) -> Dict[str, int]:
        """Получить статистику"""
        return self._stats.copy()
    
    def log_stats(self):
        """Вывести статистику"""
        stats = self._stats
        logger.info(
            f"📊 Pre-market: MEXC={stats['mexc_hits']}, Gate={stats['gate_hits']}, "
            f"Кэш={stats['cache_hits']}, Не найдено={stats['not_found']}, "
            f"Запросов={stats['requests']}"
        )
    
    def clear_cache(self):
        """Очистить кэш"""
        self._price_cache.clear()
        self._tokens.clear()
        self._tokens_time = 0
        logger.info("🗑️ Pre-market кэш очищен")


# ==================== SINGLETON & SHORTCUTS ====================

_premarket_fetcher: Optional[PremarketPriceFetcher] = None


def get_premarket_fetcher() -> PremarketPriceFetcher:
    """Получить singleton instance"""
    global _premarket_fetcher
    if _premarket_fetcher is None:
        _premarket_fetcher = PremarketPriceFetcher()
    return _premarket_fetcher


def get_premarket_price(symbol: str) -> Optional[float]:
    """Быстрый доступ к премаркет цене"""
    return get_premarket_fetcher().get_premarket_price(symbol)


def get_all_premarket_prices() -> Dict[str, float]:
    """Быстрый доступ ко всем премаркет ценам"""
    return get_premarket_fetcher().get_all_premarket_prices()
