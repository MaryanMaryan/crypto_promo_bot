"""
Утилита для автоматического определения биржи по URL
"""
import logging

logger = logging.getLogger(__name__)

def detect_exchange_from_url(url: str) -> str:
    """
    Определяет название биржи по URL

    Args:
        url: URL API или страницы биржи

    Returns:
        Название биржи (Bybit, Kucoin, OKX, и т.д.)
    """
    if not url:
        return 'Unknown'

    url_lower = url.lower()

    if 'bybit.com' in url_lower:
        return 'Bybit'
    elif 'kucoin.com' in url_lower:
        return 'Kucoin'
    elif 'okx.com' in url_lower:
        return 'OKX'
    elif 'binance.com' in url_lower:
        return 'Binance'
    elif 'gate.io' in url_lower or 'gate.com' in url_lower:
        return 'Gate.io'
    elif 'mexc.com' in url_lower:
        return 'MEXC'
    elif 'weex.com' in url_lower:
        return 'WEEX'
    elif 'bitget.com' in url_lower:
        return 'Bitget'
    elif 'htx.com' in url_lower or 'huobi.com' in url_lower:
        return 'HTX'
    else:
        logger.debug(f"Не удалось определить биржу по URL: {url}")
        return 'Unknown'
