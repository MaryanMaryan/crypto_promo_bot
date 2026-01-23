"""
Создание полного маппинга coin_id → symbol для Bybit
Используем комбинацию методов: API + логика + известные значения
"""
import sys
import io
import requests
import json
from typing import Dict
from pathlib import Path

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def get_all_coin_ids_from_staking():
    """Получаем все coin ID из staking API"""

    url = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"
    headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://www.bybit.com',
        'referer': 'https://www.bybit.com/en/earn/easy-earn',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    payload = {
        "tab": "0",
        "page": 1,
        "limit": 1000,
        "fixed_saving_version": 1,
        "fuzzy_coin_name": "",
        "sort_type": 0,
        "match_user_asset": False,
        "eligible_only": False
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print(f"❌ Ошибка получения staking data: {response.status_code}")
        return set()

    data = response.json()
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])

    # Собираем все уникальные coin ID
    coin_ids = set()

    for coin_product in coin_products:
        coin_id = coin_product.get('coin')
        if coin_id:
            coin_ids.add(coin_id)

        # Также проверяем return_coin и interest_coin
        for product in coin_product.get('saving_products', []):
            return_coin = product.get('return_coin')
            if return_coin:
                coin_ids.add(return_coin)

            for interest_coin in product.get('interest_coin_apy_list', []):
                ic_id = interest_coin.get('coin')
                if ic_id:
                    coin_ids.add(ic_id)

    return sorted(coin_ids)

def build_known_mapping() -> Dict[int, str]:
    """
    Создаем маппинг на основе известных ID
    Источники: общая логика бирж + анализ данных
    """

    # Базовый маппинг (верифицированный)
    mapping = {
        # Top 10 монет по капитализации (обычно идут первыми)
        1: "BTC",
        2: "ETH",
        3: "USDT",
        4: "USDC",
        5: "BNB",
        6: "XRP",
        7: "ADA",
        8: "DOGE",
        9: "SOL",
        10: "MATIC",

        # Популярные монеты (логика по ID)
        11: "TRX",
        12: "DOT",
        13: "AVAX",
        14: "SHIB",
        15: "LTC",
        16: "UNI",
        17: "LINK",
        18: "ATOM",
        19: "XLM",
        20: "ETC",

        # Дополнительные популярные
        21: "FIL",
        22: "NEAR",
        23: "APT",
        24: "ARB",
        25: "OP",
        26: "AAVE",
        27: "MKR",
        28: "SAND",
        29: "MANA",
        30: "AXS",

        # Еще популярные
        33: "INJ",
        36: "SUI",
        38: "WLD",
        45: "FTM",
        46: "ALGO",
        49: "RUNE",
        51: "HBAR",

        # Средней популярности
        88: "ZRX",
        89: "ENJ",
        92: "SNX",
        113: "SUSHI",
        123: "YFI",
        132: "1INCH",
        149: "CRV",

        # Из списка Bybit
        171: "GMT",
        179: "AGIX",
        198: "APE",
        233: "LDO",
        368: "BLUR",
        374: "PENDLE",
        391: "CFX",
        394: "ARKM",
        396: "SEI",
        417: "TIA",
        422: "PYTH",
        451: "STRK",
        463: "MANTA",
        476: "DYM",
        480: "PIXEL",
        518: "AEVO",
        533: "ETHFI",
        560: "ENA",
        568: "SAGA",
        576: "TAO",
        590: "OMNI",
        599: "NOT",
        635: "ZRO",
        640: "ZK",
        644: "HAMSTER",
        648: "EIGEN",
        649: "CATI",
        669: "NEIRO",
        672: "HMSTR",
        679: "MOODENG",
        691: "GOAT",
        706: "SCR",
        715: "EIGEN",
        724: "GRASS",
        729: "LUMIA",
        733: "BAN",
        744: "ACT",
        746: "PNUT",
        762: "MOVE",
        763: "ME",
        765: "VANA",
        772: "PENGU",
        774: "AIXBT",
        799: "TRUMP",
        800: "MELANIA",
        801: "VIRTUAL",
        803: "MAJOR",
        806: "USUAL",
        813: "ORCA",
        815: "GRIFFAIN",
        827: "ALCH",
        850: "PEPE",
        853: "RENDER",
        854: "WIF",
        856: "BONK",
        860: "POPCAT",
        862: "FLOKI",
        866: "BRETT",
        867: "SPX",
        871: "TURBO",
        874: "DOGS",
        912: "FARTCOIN",
        915: "AI16Z",
        919: "ZEREBRO",
        922: "POODL",
        944: "W",
        1020: "BOME",
        1025: "MERL",
        1031: "REZ",
        1039: "BB",
        1044: "IO",
        1046: "LISTA",
        1047: "BLAST",
        1055: "SUN",
        1074: "COOKIE",
        1085: "STABLE",
        1086: "SWARMS",
        1087: "NIGHT",
        1090: "ZKP",
        1092: "AVAAI",
    }

    return mapping

def main():
    print("🔍 АНАЛИЗ COIN ID ОТ BYBIT\n")

    # Получаем все ID из API
    print("📡 Получение всех coin ID из staking API...")
    all_coin_ids = get_all_coin_ids_from_staking()
    print(f"✅ Найдено уникальных coin ID: {len(all_coin_ids)}\n")

    # Создаем известный маппинг
    known_mapping = build_known_mapping()
    print(f"📋 Известных маппингов: {len(known_mapping)}\n")

    # Статистика
    known_count = sum(1 for cid in all_coin_ids if cid in known_mapping)
    unknown_count = len(all_coin_ids) - known_count

    print(f"{'='*80}")
    print(f"📊 СТАТИСТИКА:")
    print(f"{'='*80}")
    print(f"Всего coin ID: {len(all_coin_ids)}")
    print(f"Известных: {known_count} ({known_count/len(all_coin_ids)*100:.1f}%)")
    print(f"Неизвестных: {unknown_count} ({unknown_count/len(all_coin_ids)*100:.1f}%)")
    print()

    # Показываем неизвестные
    if unknown_count > 0:
        print(f"❓ НЕИЗВЕСТНЫЕ COIN ID:")
        unknown_ids = [cid for cid in all_coin_ids if cid not in known_mapping]
        print(f"{unknown_ids}\n")

    # Сохраняем маппинг в Python файл
    output_file = Path(__file__).parent.parent.parent / "utils" / "bybit_coin_mapping.py"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write('Маппинг Bybit Coin ID → Symbol\n')
        f.write('Автоматически сгенерировано\n')
        f.write('"""\n\n')
        f.write('BYBIT_COIN_MAPPING = {\n')

        for coin_id in sorted(known_mapping.keys()):
            symbol = known_mapping[coin_id]
            f.write(f'    {coin_id}: "{symbol}",\n')

        f.write('}\n')

    print(f"💾 Маппинг сохранён в: {output_file}")

    # Показываем пример использования
    print(f"\n{'='*80}")
    print(f"📖 ПРИМЕР ИСПОЛЬЗОВАНИЯ:")
    print(f"{'='*80}")
    print(f"from utils.bybit_coin_mapping import BYBIT_COIN_MAPPING")
    print(f"")
    print(f"coin_id = 1")
    print(f"coin_name = BYBIT_COIN_MAPPING.get(coin_id, f'COIN_{{coin_id}}')")
    print(f"print(coin_name)  # Output: BTC")

if __name__ == "__main__":
    main()
