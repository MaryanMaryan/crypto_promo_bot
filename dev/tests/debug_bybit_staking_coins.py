"""
Отладочный скрипт для проверки coin_id в Bybit API
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
import json
from utils.bybit_coin_mapping import BYBIT_COIN_MAPPING

API_URL = "https://api2.bybit.com/fapi/beehive/public/v1/common/product/list"

headers = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://www.bybit.com',
    'referer': 'https://www.bybit.com/en/earn/easy-earn',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

payload = {
    "tab": "2",  # Fixed Term
    "page": 1,
    "limit": 100,
    "fixed_saving_version": 1,
    "fuzzy_coin_name": "",
    "sort_type": 0,
    "match_user_asset": False,
    "eligible_only": False
}

print("🔍 Запрос к Bybit API...")
response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
data = response.json()

if data.get('ret_code') != 0:
    print(f"❌ Ошибка API: {data.get('ret_msg')}")
    exit(1)

result = data.get('result', {})
coin_products = result.get('coin_products', [])

print(f"\n📊 Найдено монет: {len(coin_products)}\n")
print("=" * 80)

# Проверяем продукты с высоким APR
for coin_product in coin_products:
    coin_id = coin_product.get('coin')
    coin_name = BYBIT_COIN_MAPPING.get(coin_id, f"UNKNOWN_{coin_id}")

    saving_products = coin_product.get('saving_products', [])

    # Ищем продукты с APR > 100%
    high_apr_products = []
    for product in saving_products:
        apy_str = product.get('apy', '0%')
        apy = float(apy_str.replace('%', '').strip())

        if apy >= 100:
            term = product.get('staking_term', '0')
            high_apr_products.append({
                'apy': apy,
                'term': term,
                'product_id': product.get('product_id'),
                'display_status': product.get('display_status')
            })

    if high_apr_products:
        print(f"\n💰 Coin ID: {coin_id} → {coin_name}")
        print(f"   Продуктов с APR ≥ 100%: {len(high_apr_products)}")

        for p in high_apr_products[:5]:  # Показываем первые 5
            status = {1: "Active", 2: "Sold Out", 3: "Coming Soon"}.get(p['display_status'], "Unknown")
            print(f"   - APR: {p['apy']}% | Срок: {p['term']} дней | Статус: {status}")

print("\n" + "=" * 80)
print("\n🔍 Проверка USDT продуктов (coin_id должен быть 3):")

# Специально ищем USDT продукты
for coin_product in coin_products:
    coin_id = coin_product.get('coin')
    coin_name = BYBIT_COIN_MAPPING.get(coin_id, f"UNKNOWN_{coin_id}")

    # Ищем продукты с конкретными APR из примера пользователя
    saving_products = coin_product.get('saving_products', [])
    for product in saving_products:
        apy_str = product.get('apy', '0%')
        apy = float(apy_str.replace('%', '').strip())
        term = product.get('staking_term', '0')

        # 555% на 2 дня или 600% на 3 дня
        if (apy == 555 and term == '2') or (apy == 600 and term == '3'):
            print(f"\n🎯 НАЙДЕН: APR {apy}% на {term} дней")
            print(f"   Coin ID из API: {coin_id}")
            print(f"   Маппинг говорит: {coin_name}")
            print(f"   Product ID: {product.get('product_id')}")
            print(f"   Полные данные продукта:")
            print(f"   {json.dumps(product, indent=2, ensure_ascii=False)}")
