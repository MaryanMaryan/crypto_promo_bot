"""
utils/futures_fetcher.py
Получение информации о фьючерсах с криптобирж.

Поддерживаемые биржи:
- Binance, Bybit, OKX, Gate.io, Bitget
- KuCoin, MEXC, BingX, Phemex, WEEX

Основное применение: поиск фьючерсов для хеджирования стейкинга.
"""

import aiohttp
import asyncio
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import time

logger = logging.getLogger(__name__)


@dataclass
class FuturesInfo:
    """Информация о фьючерсе на бирже"""
    exchange: str
    symbol: str
    available: bool = False
    
    # Основные данные
    price: Optional[float] = None
    price_change_24h: Optional[float] = None  # в процентах
    volume_24h: Optional[float] = None  # в USD
    
    # Расширенные данные
    funding_rate: Optional[float] = None  # текущий FR
    next_funding_time: Optional[datetime] = None
    open_interest: Optional[float] = None  # в USD
    max_leverage: Optional[int] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    
    # Мета
    error: Optional[str] = None
    trade_url: Optional[str] = None
    
    def __post_init__(self):
        """Генерация trade URL"""
        if self.available and not self.trade_url:
            self.trade_url = self._generate_trade_url()
    
    def _generate_trade_url(self) -> str:
        """Генерирует ссылку на торговлю"""
        symbol = self.symbol.upper()
        urls = {
            'binance': f'https://www.binance.com/en/futures/{symbol}USDT',
            'bybit': f'https://www.bybit.com/trade/usdt/{symbol}USDT',
            'okx': f'https://www.okx.com/trade-swap/{symbol.lower()}-usdt-swap',
            'gateio': f'https://www.gate.io/futures_trade/USDT/{symbol}_USDT',
            'bitget': f'https://www.bitget.com/futures/usdt/{symbol}USDT',
            'kucoin': f'https://www.kucoin.com/futures/trade/{symbol}USDTM',
            'mexc': f'https://futures.mexc.com/exchange/{symbol}_USDT',
            'bingx': f'https://bingx.com/en-us/perpetual/{symbol}-USDT/',
            'phemex': f'https://phemex.com/trade/{symbol}USDT',
            'weex': f'https://www.weex.com/futures/{symbol}USDT',
        }
        return urls.get(self.exchange, '')


@dataclass 
class FuturesSearchResult:
    """Результат поиска фьючерсов по токену"""
    symbol: str
    timestamp: datetime = field(default_factory=datetime.now)
    results: List[FuturesInfo] = field(default_factory=list)
    
    @property
    def available_count(self) -> int:
        """Количество бирж с фьючерсом"""
        return sum(1 for r in self.results if r.available)
    
    @property
    def total_count(self) -> int:
        """Общее количество проверенных бирж"""
        return len(self.results)
    
    @property
    def best_long_fr(self) -> Optional[FuturesInfo]:
        """Лучший FR для лонга (самый низкий положительный или отрицательный)"""
        available = [r for r in self.results if r.available and r.funding_rate is not None]
        if not available:
            return None
        return min(available, key=lambda x: x.funding_rate)
    
    @property
    def best_short_fr(self) -> Optional[FuturesInfo]:
        """Лучший FR для шорта (самый высокий)"""
        available = [r for r in self.results if r.available and r.funding_rate is not None]
        if not available:
            return None
        return max(available, key=lambda x: x.funding_rate)
    
    @property
    def avg_price(self) -> Optional[float]:
        """Средняя цена по всем биржам"""
        prices = [r.price for r in self.results if r.available and r.price]
        if not prices:
            return None
        return sum(prices) / len(prices)


class FuturesFetcher:
    """
    Получение информации о фьючерсах с криптобирж.
    
    Использование:
        fetcher = FuturesFetcher()
        result = await fetcher.search("BTC")
        print(result.available_count)  # Количество бирж с BTC фьючерсом
    """
    
    # Список поддерживаемых бирж
    EXCHANGES = [
        'binance', 'bybit', 'okx', 'gateio', 'bitget',
        'kucoin', 'mexc', 'bingx', 'phemex', 'weex'
    ]
    
    # Настройки
    TIMEOUT = 5  # секунд на запрос
    CACHE_DURATION = 60  # секунд кэширования
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # {symbol: (result, timestamp)}
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить или создать aiohttp сессию"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        """Закрыть сессию"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    # ==================== ОСНОВНОЙ МЕТОД ====================
    
    async def search(self, symbol: str, use_cache: bool = True) -> FuturesSearchResult:
        """
        Поиск фьючерсов по символу токена.
        
        Args:
            symbol: Символ токена (BTC, ETH, SOL)
            use_cache: Использовать кэш
            
        Returns:
            FuturesSearchResult с данными со всех бирж
        """
        symbol = symbol.upper().strip()
        
        # Проверяем кэш
        if use_cache and symbol in self._cache:
            result, ts = self._cache[symbol]
            if time.time() - ts < self.CACHE_DURATION:
                logger.debug(f"📦 {symbol} из кэша")
                return result
        
        logger.info(f"🔍 Поиск фьючерсов: {symbol}")
        
        # Параллельный запрос ко всем биржам
        tasks = [
            self._fetch_exchange(symbol, exchange) 
            for exchange in self.EXCHANGES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Собираем результаты
        futures_list = []
        for exchange, result in zip(self.EXCHANGES, results):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ {exchange} ошибка: {result}")
                futures_list.append(FuturesInfo(
                    exchange=exchange,
                    symbol=symbol,
                    available=False,
                    error=str(result)
                ))
            else:
                futures_list.append(result)
        
        # Создаём результат
        search_result = FuturesSearchResult(
            symbol=symbol,
            results=futures_list
        )
        
        # Сохраняем в кэш
        self._cache[symbol] = (search_result, time.time())
        
        logger.info(f"✅ {symbol}: найдено на {search_result.available_count}/{search_result.total_count} биржах")
        
        return search_result
    
    async def _fetch_exchange(self, symbol: str, exchange: str) -> FuturesInfo:
        """Получить данные с конкретной биржи"""
        try:
            method = getattr(self, f'_fetch_{exchange}', None)
            if method:
                return await method(symbol)
            else:
                return FuturesInfo(exchange=exchange, symbol=symbol, error="Not implemented")
        except asyncio.TimeoutError:
            return FuturesInfo(exchange=exchange, symbol=symbol, error="Timeout")
        except Exception as e:
            logger.debug(f"⚠️ {exchange} {symbol}: {e}")
            return FuturesInfo(exchange=exchange, symbol=symbol, error=str(e))
    
    # ==================== BINANCE ====================
    
    async def _fetch_binance(self, symbol: str) -> FuturesInfo:
        """Получить данные с Binance Futures"""
        session = await self._get_session()
        pair = f"{symbol}USDT"
        
        # Запрашиваем ticker и funding rate параллельно
        ticker_url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={pair}"
        funding_url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={pair}"
        
        try:
            async with session.get(ticker_url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='binance', symbol=symbol, available=False)
                ticker = await resp.json()
            
            async with session.get(funding_url) as resp:
                funding = await resp.json() if resp.status == 200 else {}
            
            return FuturesInfo(
                exchange='binance',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPrice', 0)),
                price_change_24h=float(ticker.get('priceChangePercent', 0)),
                volume_24h=float(ticker.get('quoteVolume', 0)),
                funding_rate=float(funding.get('lastFundingRate', 0)) * 100 if funding.get('lastFundingRate') else None,
                mark_price=float(funding.get('markPrice', 0)) if funding.get('markPrice') else None,
                index_price=float(funding.get('indexPrice', 0)) if funding.get('indexPrice') else None,
                max_leverage=125,  # Binance default for BTC
                next_funding_time=datetime.fromtimestamp(funding.get('nextFundingTime', 0) / 1000) if funding.get('nextFundingTime') else None,
            )
        except Exception as e:
            logger.debug(f"Binance {symbol}: {e}")
            return FuturesInfo(exchange='binance', symbol=symbol, available=False, error=str(e))
    
    # ==================== BYBIT ====================
    
    async def _fetch_bybit(self, symbol: str) -> FuturesInfo:
        """Получить данные с Bybit"""
        session = await self._get_session()
        pair = f"{symbol}USDT"
        
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={pair}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='bybit', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('retCode') != 0:
                return FuturesInfo(exchange='bybit', symbol=symbol, available=False)
            
            result_list = data.get('result', {}).get('list', [])
            if not result_list:
                return FuturesInfo(exchange='bybit', symbol=symbol, available=False)
            
            ticker = result_list[0]
            
            return FuturesInfo(
                exchange='bybit',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPrice', 0)),
                price_change_24h=float(ticker.get('price24hPcnt', 0)) * 100,
                volume_24h=float(ticker.get('turnover24h', 0)),
                funding_rate=float(ticker.get('fundingRate', 0)) * 100 if ticker.get('fundingRate') else None,
                open_interest=float(ticker.get('openInterestValue', 0)) if ticker.get('openInterestValue') else None,
                mark_price=float(ticker.get('markPrice', 0)) if ticker.get('markPrice') else None,
                index_price=float(ticker.get('indexPrice', 0)) if ticker.get('indexPrice') else None,
                max_leverage=100,
            )
        except Exception as e:
            logger.debug(f"Bybit {symbol}: {e}")
            return FuturesInfo(exchange='bybit', symbol=symbol, available=False, error=str(e))
    
    # ==================== OKX ====================
    
    async def _fetch_okx(self, symbol: str) -> FuturesInfo:
        """Получить данные с OKX"""
        session = await self._get_session()
        # OKX использует формат BTC-USDT-SWAP
        inst_id = f"{symbol}-USDT-SWAP"
        
        ticker_url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
        funding_url = f"https://www.okx.com/api/v5/public/funding-rate?instId={inst_id}"
        
        try:
            async with session.get(ticker_url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='okx', symbol=symbol, available=False)
                ticker_data = await resp.json()
            
            if ticker_data.get('code') != '0' or not ticker_data.get('data'):
                return FuturesInfo(exchange='okx', symbol=symbol, available=False)
            
            ticker = ticker_data['data'][0]
            
            # Funding rate
            funding_rate = None
            next_funding = None
            try:
                async with session.get(funding_url) as resp:
                    if resp.status == 200:
                        funding_data = await resp.json()
                        if funding_data.get('data'):
                            fr_data = funding_data['data'][0]
                            funding_rate = float(fr_data.get('fundingRate', 0)) * 100
                            if fr_data.get('nextFundingTime'):
                                next_funding = datetime.fromtimestamp(int(fr_data['nextFundingTime']) / 1000)
            except:
                pass
            
            # Расчёт 24h change
            last = float(ticker.get('last', 0))
            open_24h = float(ticker.get('open24h', 0))
            change_24h = ((last - open_24h) / open_24h * 100) if open_24h > 0 else 0
            
            return FuturesInfo(
                exchange='okx',
                symbol=symbol,
                available=True,
                price=last,
                price_change_24h=change_24h,
                volume_24h=float(ticker.get('volCcy24h', 0)),
                funding_rate=funding_rate,
                next_funding_time=next_funding,
                max_leverage=125,
            )
        except Exception as e:
            logger.debug(f"OKX {symbol}: {e}")
            return FuturesInfo(exchange='okx', symbol=symbol, available=False, error=str(e))
    
    # ==================== GATE.IO ====================
    
    async def _fetch_gateio(self, symbol: str) -> FuturesInfo:
        """Получить данные с Gate.io Futures"""
        session = await self._get_session()
        contract = f"{symbol}_USDT"
        
        url = f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={contract}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='gateio', symbol=symbol, available=False)
                data = await resp.json()
            
            if not data or not isinstance(data, list) or len(data) == 0:
                return FuturesInfo(exchange='gateio', symbol=symbol, available=False)
            
            ticker = data[0]
            
            return FuturesInfo(
                exchange='gateio',
                symbol=symbol,
                available=True,
                price=float(ticker.get('last', 0)),
                price_change_24h=float(ticker.get('change_percentage', 0)),
                volume_24h=float(ticker.get('quote_volume_24h', 0)),
                funding_rate=float(ticker.get('funding_rate', 0)) * 100 if ticker.get('funding_rate') else None,
                mark_price=float(ticker.get('mark_price', 0)) if ticker.get('mark_price') else None,
                index_price=float(ticker.get('index_price', 0)) if ticker.get('index_price') else None,
                max_leverage=100,
            )
        except Exception as e:
            logger.debug(f"Gate.io {symbol}: {e}")
            return FuturesInfo(exchange='gateio', symbol=symbol, available=False, error=str(e))
    
    # ==================== BITGET ====================
    
    async def _fetch_bitget(self, symbol: str) -> FuturesInfo:
        """Получить данные с Bitget"""
        session = await self._get_session()
        pair = f"{symbol}USDT"
        
        ticker_url = f"https://api.bitget.com/api/v2/mix/market/ticker?productType=USDT-FUTURES&symbol={pair}"
        
        try:
            async with session.get(ticker_url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='bitget', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('code') != '00000' or not data.get('data'):
                return FuturesInfo(exchange='bitget', symbol=symbol, available=False)
            
            ticker = data['data'][0] if isinstance(data['data'], list) else data['data']
            
            return FuturesInfo(
                exchange='bitget',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPr', 0)),
                price_change_24h=float(ticker.get('change24h', 0)) * 100 if ticker.get('change24h') else 0,
                volume_24h=float(ticker.get('quoteVolume', 0)),
                funding_rate=float(ticker.get('fundingRate', 0)) * 100 if ticker.get('fundingRate') else None,
                open_interest=float(ticker.get('openInterest', 0)) if ticker.get('openInterest') else None,
                max_leverage=125,
            )
        except Exception as e:
            logger.debug(f"Bitget {symbol}: {e}")
            return FuturesInfo(exchange='bitget', symbol=symbol, available=False, error=str(e))
    
    # ==================== KUCOIN ====================
    
    async def _fetch_kucoin(self, symbol: str) -> FuturesInfo:
        """Получить данные с KuCoin Futures"""
        session = await self._get_session()
        # KuCoin: BTC -> XBTUSDTM
        kucoin_symbol = symbol
        if symbol == 'BTC':
            kucoin_symbol = 'XBT'
        pair = f"{kucoin_symbol}USDTM"
        
        url = f"https://api-futures.kucoin.com/api/v1/ticker?symbol={pair}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='kucoin', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('code') != '200000' or not data.get('data'):
                return FuturesInfo(exchange='kucoin', symbol=symbol, available=False)
            
            ticker = data['data']
            
            # Расчёт 24h change
            price = float(ticker.get('price', 0))
            price_change = float(ticker.get('priceChgPct', 0)) * 100
            
            return FuturesInfo(
                exchange='kucoin',
                symbol=symbol,
                available=True,
                price=price,
                price_change_24h=price_change,
                volume_24h=float(ticker.get('turnoverOf24h', 0)),
                mark_price=float(ticker.get('markPrice', 0)) if ticker.get('markPrice') else None,
                index_price=float(ticker.get('indexPrice', 0)) if ticker.get('indexPrice') else None,
                max_leverage=100,
            )
        except Exception as e:
            logger.debug(f"KuCoin {symbol}: {e}")
            return FuturesInfo(exchange='kucoin', symbol=symbol, available=False, error=str(e))
    
    # ==================== MEXC ====================
    
    async def _fetch_mexc(self, symbol: str) -> FuturesInfo:
        """Получить данные с MEXC Futures"""
        session = await self._get_session()
        contract = f"{symbol}_USDT"
        
        url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={contract}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='mexc', symbol=symbol, available=False)
                data = await resp.json()
            
            if not data.get('success') or not data.get('data'):
                return FuturesInfo(exchange='mexc', symbol=symbol, available=False)
            
            ticker = data['data']
            
            return FuturesInfo(
                exchange='mexc',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPrice', 0)),
                price_change_24h=float(ticker.get('riseFallRate', 0)) * 100 if ticker.get('riseFallRate') else 0,
                volume_24h=float(ticker.get('amount24', 0)),
                funding_rate=float(ticker.get('fundingRate', 0)) * 100 if ticker.get('fundingRate') else None,
                open_interest=float(ticker.get('holdVol', 0)) if ticker.get('holdVol') else None,
                max_leverage=200,
            )
        except Exception as e:
            logger.debug(f"MEXC {symbol}: {e}")
            return FuturesInfo(exchange='mexc', symbol=symbol, available=False, error=str(e))
    
    # ==================== BINGX ====================
    
    async def _fetch_bingx(self, symbol: str) -> FuturesInfo:
        """Получить данные с BingX"""
        session = await self._get_session()
        pair = f"{symbol}-USDT"
        
        url = f"https://open-api.bingx.com/openApi/swap/v2/quote/ticker?symbol={pair}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='bingx', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('code') != 0 or not data.get('data'):
                return FuturesInfo(exchange='bingx', symbol=symbol, available=False)
            
            ticker = data['data']
            
            return FuturesInfo(
                exchange='bingx',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPrice', 0)),
                price_change_24h=float(ticker.get('priceChangePercent', 0)),
                volume_24h=float(ticker.get('quoteVolume', 0)),
                open_interest=float(ticker.get('openInterest', 0)) if ticker.get('openInterest') else None,
                max_leverage=150,
            )
        except Exception as e:
            logger.debug(f"BingX {symbol}: {e}")
            return FuturesInfo(exchange='bingx', symbol=symbol, available=False, error=str(e))
    
    # ==================== PHEMEX ====================
    
    async def _fetch_phemex(self, symbol: str) -> FuturesInfo:
        """Получить данные с Phemex"""
        session = await self._get_session()
        pair = f"{symbol}USDT"
        
        # Phemex products endpoint
        url = f"https://api.phemex.com/md/v2/ticker/24hr?symbol={pair}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='phemex', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('code') != 0 or not data.get('result'):
                return FuturesInfo(exchange='phemex', symbol=symbol, available=False)
            
            ticker = data['result']
            
            # Phemex использует scale для цен (обычно / 10000)
            scale = 10000
            price = float(ticker.get('lastPrice', 0)) / scale if ticker.get('lastPrice') else 0
            
            return FuturesInfo(
                exchange='phemex',
                symbol=symbol,
                available=True,
                price=price,
                price_change_24h=float(ticker.get('priceChangePercent24h', 0)) if ticker.get('priceChangePercent24h') else 0,
                volume_24h=float(ticker.get('quoteVolume', 0)) / scale if ticker.get('quoteVolume') else 0,
                max_leverage=100,
            )
        except Exception as e:
            logger.debug(f"Phemex {symbol}: {e}")
            return FuturesInfo(exchange='phemex', symbol=symbol, available=False, error=str(e))
    
    # ==================== WEEX ====================
    
    async def _fetch_weex(self, symbol: str) -> FuturesInfo:
        """Получить данные с WEEX"""
        session = await self._get_session()
        pair = f"{symbol}USDT"
        
        # WEEX API похож на Bitget
        url = f"https://api.weex.com/api/v2/mix/market/ticker?productType=usdt-futures&symbol={pair}"
        
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FuturesInfo(exchange='weex', symbol=symbol, available=False)
                data = await resp.json()
            
            if data.get('code') != '00000' or not data.get('data'):
                return FuturesInfo(exchange='weex', symbol=symbol, available=False)
            
            ticker = data['data'][0] if isinstance(data['data'], list) else data['data']
            
            return FuturesInfo(
                exchange='weex',
                symbol=symbol,
                available=True,
                price=float(ticker.get('lastPr', ticker.get('last', 0))),
                price_change_24h=float(ticker.get('change24h', 0)) * 100 if ticker.get('change24h') else 0,
                volume_24h=float(ticker.get('quoteVolume', ticker.get('baseVolume', 0))),
                funding_rate=float(ticker.get('fundingRate', 0)) * 100 if ticker.get('fundingRate') else None,
                max_leverage=100,
            )
        except Exception as e:
            logger.debug(f"WEEX {symbol}: {e}")
            return FuturesInfo(exchange='weex', symbol=symbol, available=False, error=str(e))
    
    # ==================== ИСТОРИЯ FUNDING RATE ====================
    
    async def get_funding_history(self, symbol: str, exchange: str = 'binance', limit: int = 21) -> List[dict]:
        """
        Получить историю funding rate.
        
        Args:
            symbol: Символ токена
            exchange: Биржа (по умолчанию binance)
            limit: Количество записей (21 = 7 дней по 3 фандинга)
            
        Returns:
            Список словарей с историей FR
        """
        session = await self._get_session()
        
        if exchange == 'binance':
            pair = f"{symbol}USDT"
            url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={pair}&limit={limit}"
            
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                
                history = []
                for item in data:
                    history.append({
                        'timestamp': datetime.fromtimestamp(item['fundingTime'] / 1000),
                        'funding_rate': float(item['fundingRate']) * 100,
                        'mark_price': float(item.get('markPrice', 0)) if item.get('markPrice') else None,
                    })
                
                return history
            except Exception as e:
                logger.error(f"Ошибка получения FR history: {e}")
                return []
        
        return []


# ==================== ФОРМАТИРОВАНИЕ ====================

def format_futures_compact(result: FuturesSearchResult) -> str:
    """Форматирует результат в компактном виде"""
    lines = [
        f"🔍 <b>ФЬЮЧЕРСЫ: {result.symbol}</b>",
        "",
        f"📊 Найдено на <b>{result.available_count}/{result.total_count}</b> биржах:",
        ""
    ]
    
    # Сортируем: сначала доступные, потом недоступные
    sorted_results = sorted(result.results, key=lambda x: (not x.available, x.exchange))
    
    for info in sorted_results:
        if info.available:
            # Форматируем цену
            price_str = f"${info.price:,.2f}" if info.price and info.price >= 1 else f"${info.price:.6f}" if info.price else "—"
            
            # Форматируем изменение
            if info.price_change_24h is not None:
                change_emoji = "📈" if info.price_change_24h >= 0 else "📉"
                change_str = f"{info.price_change_24h:+.2f}%"
            else:
                change_emoji = ""
                change_str = ""
            
            # Форматируем FR
            if info.funding_rate is not None:
                fr_str = f"FR: {info.funding_rate:.4f}%"
            else:
                fr_str = ""
            
            line = f"✅ <b>{info.exchange.capitalize()}</b>  {price_str}  {change_str}  {fr_str}"
        else:
            error_hint = f" ({info.error[:20]}...)" if info.error and len(info.error) > 5 else ""
            line = f"❌ <b>{info.exchange.capitalize()}</b> — нет фьючерса{error_hint}"
        
        lines.append(line)
    
    # Рекомендации по FR
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    best_long = result.best_long_fr
    best_short = result.best_short_fr
    
    if best_long and best_long.funding_rate is not None:
        lines.append(f"💚 Лучший FR для LONG: <b>{best_long.exchange.capitalize()}</b> ({best_long.funding_rate:.4f}%)")
    
    if best_short and best_short.funding_rate is not None:
        lines.append(f"💰 Лучший FR для SHORT: <b>{best_short.exchange.capitalize()}</b> ({best_short.funding_rate:.4f}%)")
    
    return "\n".join(lines)


def format_futures_detailed(result: FuturesSearchResult) -> str:
    """Форматирует результат в детальном виде"""
    lines = [
        f"🔍 <b>ФЬЮЧЕРСЫ: {result.symbol}</b> | <b>ДЕТАЛИ</b>",
        ""
    ]
    
    # Только доступные биржи
    available = [r for r in result.results if r.available]
    
    if not available:
        lines.append("❌ Фьючерс не найден ни на одной бирже")
        return "\n".join(lines)
    
    for info in available:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🟢 <b>{info.exchange.upper()}</b>")
        
        # Цена
        if info.price:
            price_str = f"${info.price:,.2f}" if info.price >= 1 else f"${info.price:.6f}"
            lines.append(f"├ 💵 Цена: <b>{price_str}</b>")
        
        # 24h изменение
        if info.price_change_24h is not None:
            emoji = "📈" if info.price_change_24h >= 0 else "📉"
            lines.append(f"├ {emoji} 24h: <b>{info.price_change_24h:+.2f}%</b>")
        
        # Объём
        if info.volume_24h:
            vol_str = format_volume(info.volume_24h)
            lines.append(f"├ 📊 Объём 24h: {vol_str}")
        
        # Funding Rate
        if info.funding_rate is not None:
            fr_emoji = "🟢" if info.funding_rate >= 0 else "🔴"
            lines.append(f"├ {fr_emoji} Funding Rate: <b>{info.funding_rate:.4f}%</b>")
        
        # Open Interest
        if info.open_interest:
            oi_str = format_volume(info.open_interest)
            lines.append(f"├ 📉 Open Interest: {oi_str}")
        
        # Max Leverage
        if info.max_leverage:
            lines.append(f"├ ⚡ Макс. плечо: {info.max_leverage}x")
        
        # Mark Price
        if info.mark_price:
            mp_str = f"${info.mark_price:,.2f}" if info.mark_price >= 1 else f"${info.mark_price:.6f}"
            lines.append(f"├ 🎯 Mark Price: {mp_str}")
        
        # Ссылка
        if info.trade_url:
            lines.append(f"└ 🔗 <a href=\"{info.trade_url}\">Торговать</a>")
        else:
            lines.append("└")
        
        lines.append("")
    
    # Сводка
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <b>СВОДКА:</b>")
    
    if result.avg_price:
        avg_str = f"${result.avg_price:,.2f}" if result.avg_price >= 1 else f"${result.avg_price:.6f}"
        lines.append(f"• Средняя цена: {avg_str}")
    
    # Разброс цен
    prices = [r.price for r in available if r.price]
    if len(prices) > 1:
        spread = max(prices) - min(prices)
        spread_pct = (spread / min(prices)) * 100 if min(prices) > 0 else 0
        lines.append(f"• Разброс цен: ${spread:.2f} ({spread_pct:.3f}%)")
    
    best_long = result.best_long_fr
    best_short = result.best_short_fr
    
    if best_long and best_long.funding_rate is not None:
        lines.append(f"• Лучший FR LONG: {best_long.exchange.capitalize()}")
    if best_short and best_short.funding_rate is not None:
        lines.append(f"• Лучший FR SHORT: {best_short.exchange.capitalize()}")
    
    return "\n".join(lines)


def format_volume(volume: float) -> str:
    """Форматирует объём в читаемый вид"""
    if volume >= 1_000_000_000:
        return f"${volume/1_000_000_000:.2f}B"
    elif volume >= 1_000_000:
        return f"${volume/1_000_000:.2f}M"
    elif volume >= 1_000:
        return f"${volume/1_000:.2f}K"
    else:
        return f"${volume:.2f}"


# ==================== SINGLETON ====================

_futures_fetcher: Optional[FuturesFetcher] = None


def get_futures_fetcher() -> FuturesFetcher:
    """Получить singleton instance FuturesFetcher"""
    global _futures_fetcher
    if _futures_fetcher is None:
        _futures_fetcher = FuturesFetcher()
    return _futures_fetcher
