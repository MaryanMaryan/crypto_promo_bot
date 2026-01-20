# utils/promo_formatter.py
"""
Универсальный форматтер заголовков уведомлений.
Определяет биржу и категорию, формирует единый стиль заголовков.
"""

import re
from typing import Dict, Tuple, Optional

# ============================================
# КОНФИГУРАЦИЯ БИРЖ
# ============================================

EXCHANGE_CONFIG = {
    'bybit': {
        'icon': '🟡',
        'name': 'BYBIT',
        'patterns': ['bybit', 'bybit.com'],
    },
    'mexc': {
        'icon': '🔵',
        'name': 'MEXC',
        'patterns': ['mexc', 'mexc.com'],
    },
    'weex': {
        'icon': '🟣',
        'name': 'WEEX',
        'patterns': ['weex', 'weex.com'],
    },
    'okx': {
        'icon': '🟠',
        'name': 'OKX',
        'patterns': ['okx', 'okx.com', 'okex'],
    },
    'binance': {
        'icon': '🟢',
        'name': 'BINANCE',
        'patterns': ['binance', 'binance.com'],
    },
    'gate': {
        'icon': '⚪',
        'name': 'GATE.IO',
        'patterns': ['gate.io', 'gate', 'gateio'],
    },
    'bitget': {
        'icon': '🔴',
        'name': 'BITGET',
        'patterns': ['bitget', 'bitget.com'],
    },
    'kucoin': {
        'icon': '🟤',
        'name': 'KUCOIN',
        'patterns': ['kucoin', 'kucoin.com'],
    },
    'htx': {
        'icon': '🔷',
        'name': 'HTX',
        'patterns': ['htx', 'huobi', 'htx.com'],
    },
}

# ============================================
# КОНФИГУРАЦИЯ КАТЕГОРИЙ
# ============================================

CATEGORY_CONFIG = {
    'launchpad': {
        'icon': '🚀',
        'name': 'LAUNCHPAD',
        'patterns': ['launchpad', 'launch_pad', 'token_sale', 'ieo', 'ido'],
    },
    'launchpool': {
        'icon': '🚀',
        'name': 'LAUNCHPOOL',
        'patterns': ['launchpool', 'launch_pool', 'farming'],
    },
    'airdrop': {
        'icon': '🪂',
        'name': 'AIRDROP',
        'patterns': ['airdrop', 'air_drop', 'eftd', 'free_token'],
    },
    'staking': {
        'icon': '💎',
        'name': 'STAKING',
        'patterns': ['staking', 'stake', 'earn', 'savings', 'locked'],
    },
    'flash_earn': {
        'icon': '⚡',
        'name': 'FLASH EARN',
        'patterns': ['flash_earn', 'flash-earn', 'flashearn'],
    },
    'rewards': {
        'icon': '🎁',
        'name': 'REWARDS',
        'patterns': ['rewards', 'reward', 'bonus', 'cashback', 'rebate'],
    },
    'candy': {
        'icon': '🍬',
        'name': 'CANDY',
        'patterns': ['candy', 'candybox'],
    },
    'competition': {
        'icon': '🏆',
        'name': 'COMPETITION',
        'patterns': ['competition', 'contest', 'challenge', 'trading_comp'],
    },
    'boost': {
        'icon': '📈',
        'name': 'BOOST',
        'patterns': ['boost', 'jumstart', 'jumpstart'],
    },
    'telegram': {
        'icon': '📢',
        'name': 'TELEGRAM',
        'patterns': ['telegram', 'tg_'],
    },
    'announcement': {
        'icon': '📣',
        'name': 'ANNOUNCEMENT',
        'patterns': ['announcement', 'news', 'notice'],
    },
}


def detect_exchange(
    exchange: str = None,
    url: str = None,
    promo_id: str = None,
    name: str = None
) -> Tuple[str, str]:
    """
    Определяет биржу из доступных данных.
    
    Args:
        exchange: Название биржи (если уже известно)
        url: URL ссылки
        promo_id: ID промоакции
        name: Название ссылки/канала
        
    Returns:
        Tuple[icon, name]: Иконка и название биржи
    """
    # Собираем все данные в одну строку для поиска
    search_text = ' '.join(filter(None, [
        str(exchange or '').lower(),
        str(url or '').lower(),
        str(promo_id or '').lower(),
        str(name or '').lower(),
    ]))
    
    # Ищем совпадение с паттернами бирж
    for ex_key, config in EXCHANGE_CONFIG.items():
        for pattern in config['patterns']:
            if pattern in search_text:
                return config['icon'], config['name']
    
    # По умолчанию
    return '🎉', 'CRYPTO'


def detect_category(
    category: str = None,
    promo_type: str = None,
    promo_id: str = None,
    url: str = None
) -> Tuple[str, str]:
    """
    Определяет категорию промоакции.
    
    Args:
        category: Категория (если уже известна)
        promo_type: Тип промоакции
        promo_id: ID промоакции
        url: URL ссылки
        
    Returns:
        Tuple[icon, name]: Иконка и название категории
    """
    # Собираем все данные в одну строку для поиска
    search_text = ' '.join(filter(None, [
        str(category or '').lower(),
        str(promo_type or '').lower(),
        str(promo_id or '').lower(),
        str(url or '').lower(),
    ]))
    
    # Ищем совпадение с паттернами категорий
    for cat_key, config in CATEGORY_CONFIG.items():
        for pattern in config['patterns']:
            if pattern in search_text:
                return config['icon'], config['name']
    
    # По умолчанию
    return '📌', 'PROMO'


def format_promo_header(
    exchange: str = None,
    category: str = None,
    promo_type: str = None,
    promo_id: str = None,
    url: str = None,
    name: str = None,
    is_new: bool = True
) -> str:
    """
    Формирует универсальный заголовок уведомления.
    
    Args:
        exchange: Название биржи
        category: Категория
        promo_type: Тип промоакции
        promo_id: ID промоакции
        url: URL ссылки
        name: Название ссылки/канала
        is_new: Показывать метку NEW
        
    Returns:
        Отформатированный HTML заголовок
        
    Examples:
        "🟡 BYBIT | 🚀 LAUNCHPAD | 🆕 NEW"
        "🔵 MEXC | 🪂 AIRDROP"
        "⚪ GATE.IO | 💎 STAKING | 🆕 NEW"
    """
    # Определяем биржу
    ex_icon, ex_name = detect_exchange(
        exchange=exchange,
        url=url,
        promo_id=promo_id,
        name=name
    )
    
    # Определяем категорию
    cat_icon, cat_name = detect_category(
        category=category,
        promo_type=promo_type,
        promo_id=promo_id,
        url=url
    )
    
    # Формируем заголовок
    header = f"{ex_icon} <b>{ex_name}</b> | {cat_icon} <b>{cat_name}</b>"
    
    # Добавляем метку NEW если нужно
    if is_new:
        header += " | 🆕 <b>NEW</b>"
    
    return header


def format_promo_header_simple(
    exchange: str = None,
    category: str = None,
    promo_type: str = None,
    promo_id: str = None,
    url: str = None,
    name: str = None,
) -> str:
    """
    Формирует заголовок БЕЗ метки NEW (для списков текущих промо).
    """
    return format_promo_header(
        exchange=exchange,
        category=category,
        promo_type=promo_type,
        promo_id=promo_id,
        url=url,
        name=name,
        is_new=False
    )


def get_exchange_icon(exchange: str) -> str:
    """Получить только иконку биржи"""
    icon, _ = detect_exchange(exchange=exchange)
    return icon


def get_category_icon(category: str = None, promo_type: str = None) -> str:
    """Получить только иконку категории"""
    icon, _ = detect_category(category=category, promo_type=promo_type)
    return icon


# ============================================
# ТЕСТЫ
# ============================================

if __name__ == '__main__':
    # Тестовые примеры
    test_cases = [
        {'exchange': 'Bybit', 'promo_id': 'bybit_20260119070928', 'promo_type': 'launchpad'},
        {'exchange': 'MEXC', 'promo_id': 'mexc_launchpad_44', 'promo_type': 'launchpad'},
        {'exchange': 'MEXC', 'promo_id': 'mexc_airdrop_123', 'promo_type': 'airdrop'},
        {'exchange': 'weex', 'promo_id': 'weex_airdrop_289', 'promo_type': 'airdrop'},
        {'exchange': 'weex', 'promo_id': 'weex_rewards_8941', 'promo_type': 'rewards'},
        {'exchange': 'OKX', 'url': 'https://okx.com/earn/flash-earn', 'promo_type': 'flash_earn'},
        {'exchange': 'Gate.io', 'category': 'staking', 'promo_type': 'staking'},
        {'exchange': 'Gate.io', 'promo_type': 'candy'},
        {'name': 'Binance News', 'promo_id': 'telegram_binance_123'},
        {'url': 'https://www.bybit.com/en/trade/spot/token-splash'},
    ]
    
    print("=" * 60)
    print("ТЕСТ УНИВЕРСАЛЬНОГО ФОРМАТИРОВАНИЯ")
    print("=" * 60)
    
    for case in test_cases:
        header = format_promo_header(**case)
        # Убираем HTML теги для консоли
        clean = header.replace('<b>', '').replace('</b>', '')
        print(f"\n{clean}")
        print(f"  Данные: {case}")
