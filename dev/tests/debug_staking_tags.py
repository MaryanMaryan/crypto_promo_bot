"""
Отладка: проверка тегов VIP и New User в стейкингах
"""
import sys
import io
import requests
import json
from parsers.staking_parser import StakingParser

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("ОТЛАДКА: Проверка тегов в стейкингах Bybit")
print("=" * 80)

# Запрос к Bybit API
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
    "tab": "2",  # Fixed Term
    "page": 1,
    "limit": 100,
    "fixed_saving_version": 1,
    "fuzzy_coin_name": "",
    "sort_type": 0,
    "match_user_asset": False,
    "eligible_only": False
}

response = requests.post(url, headers=headers, json=payload, timeout=30)
data = response.json()

# Находим стейкинг с APR 600% на 3 дня
result = data.get('result', {})
coin_products = result.get('coin_products', [])

print("\nПоиск стейкинга: USDT, APR 600%, 3 дня")
print("-" * 80)

found = False
for coin_product in coin_products:
    saving_products = coin_product.get('saving_products', [])

    for product in saving_products:
        apy = float(product.get('apy', '0%').replace('%', ''))
        term = int(product.get('staking_term', '0'))

        if apy == 600.0 and term == 3:
            found = True
            print(f"\nНАЙДЕН!\n")

            # Основная информация
            print(f"APY: {product.get('apy')}")
            print(f"Term: {product.get('staking_term')} дней")
            print(f"Product ID: {product.get('product_id')}")
            print(f"Display Status: {product.get('display_status')}")

            # ТЕГИ
            print(f"\nТЕГИ И ФЛАГИ:")
            print(f"is_vip: {product.get('is_vip')}")

            tag_info = product.get('product_tag_info', {})
            print(f"\nproduct_tag_info:")
            print(json.dumps(tag_info, indent=2, ensure_ascii=False))

            display_tag_key = tag_info.get('display_tag_key', '')
            print(f"\ndisplay_tag_key: '{display_tag_key}'")

            # Проверка на New User
            is_new_user = 'newuser' in display_tag_key.lower() or 'new user' in display_tag_key.lower()
            print(f"Определяется как New User: {is_new_user}")

            # Проверка на VIP
            is_vip = product.get('is_vip', False) or 'VIP' in display_tag_key or 'vip' in display_tag_key
            print(f"Определяется как VIP: {is_vip}")

            # Полные данные продукта
            print(f"\nПОЛНЫЕ ДАННЫЕ ПРОДУКТА:")
            print(json.dumps(product, indent=2, ensure_ascii=False))

            break

    if found:
        break

if not found:
    print("\n❌ Стейкинг не найден!")
    print("\nПоказываю первые 5 продуктов:")

    count = 0
    for coin_product in coin_products:
        if count >= 5:
            break

        saving_products = coin_product.get('saving_products', [])
        for product in saving_products:
            if count >= 5:
                break

            apy = product.get('apy', '0%')
            term = product.get('staking_term', '0')
            tag_info = product.get('product_tag_info', {})
            display_tag = tag_info.get('display_tag_key', '')

            print(f"\n{count+1}. APY: {apy}, Term: {term} дней")
            print(f"   Tag: '{display_tag}'")
            print(f"   is_vip: {product.get('is_vip')}")

            count += 1

print("\n" + "=" * 80)
