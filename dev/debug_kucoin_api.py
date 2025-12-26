"""
Отладка: проверка данных от KuCoin API
"""
import sys
import io
import requests
import json

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("ОТЛАДКА: Проверка данных KuCoin API")
print("=" * 80)

# Запрос к KuCoin API
url = "https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1&lang=ru_RU"

response = requests.get(url, timeout=30)
data = response.json()

products = data.get('data', [])

if not products:
    print("\nНет данных!")
else:
    print(f"\nНайдено продуктов: {len(products)}")

    # Ищем продукт MIN с APR 220%
    print("\nПоиск: MIN с APR 220%")
    print("-" * 80)

    found = False
    for product in products:
        coin = product.get('currency')
        apr = float(product.get('total_apr', product.get('apr', '0')))

        if coin == 'MIN' and apr == 220.0:
            found = True
            print("\nНАЙДЕН!\n")

            # Основная информация
            print(f"Currency: {product.get('currency')}")
            print(f"Total APR: {product.get('total_apr')}")
            print(f"Type: {product.get('type')}")
            print(f"Status: {product.get('status')}")
            print(f"Category: {product.get('category')}")
            print(f"Duration: {product.get('duration')} дней")

            # ЛИМИТЫ И МЕСТА
            print(f"\nЛИМИТЫ И МЕСТА:")
            print(f"user_limit: {product.get('user_limit')}")
            print(f"user_max_limit: {product.get('user_max_limit')}")
            print(f"min_amount: {product.get('min_amount')}")
            print(f"max_amount: {product.get('max_amount')}")
            print(f"total_amount: {product.get('total_amount')}")
            print(f"available_amount: {product.get('available_amount')}")
            print(f"total_places: {product.get('total_places')}")
            print(f"available_places: {product.get('available_places')}")

            # ВРЕМЕННЫЕ МЕТКИ
            print(f"\nВРЕМЕННЫЕ МЕТКИ:")
            print(f"start_time: {product.get('start_time')}")
            print(f"end_time: {product.get('end_time')}")
            print(f"subscribe_start_time: {product.get('subscribe_start_time')}")
            print(f"subscribe_end_time: {product.get('subscribe_end_time')}")

            # ВСЕ КЛЮЧИ
            print(f"\nВСЕ ДОСТУПНЫЕ КЛЮЧИ:")
            print(json.dumps(list(product.keys()), indent=2, ensure_ascii=False))

            # ПОЛНЫЕ ДАННЫЕ
            print(f"\nПОЛНЫЕ ДАННЫЕ ПРОДУКТА:")
            print(json.dumps(product, indent=2, ensure_ascii=False))

            break

    if not found:
        print("\nПродукт не найден!")
        print("\nПоказываю первые 3 продукта:")

        for i, product in enumerate(products[:3], 1):
            coin = product.get('currency')
            apr = float(product.get('total_apr', product.get('apr', '0')))
            duration = product.get('duration', 0)

            print(f"\n{i}. {coin} - {apr}% APR - {duration} дней")
            print(f"   Ключи: {list(product.keys())}")

print("\n" + "=" * 80)
