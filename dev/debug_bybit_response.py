"""
Отладочный скрипт для изучения структуры ответа Bybit API
"""
import sys
import io
import requests
import json

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def debug_bybit_api():
    """Получаем и изучаем полную структуру ответа Bybit"""

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
        "limit": 100,
        "fixed_saving_version": 1,
        "fuzzy_coin_name": "",
        "sort_type": 0,
        "match_user_asset": False,
        "eligible_only": False
    }

    print("📡 Отправка запроса к Bybit API...\n")

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print(f"❌ Ошибка: {response.status_code}")
        return

    data = response.json()

    print("✅ Ответ получен!\n")
    print("=" * 80)

    # Проверяем структуру первого coin_product
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])

    if not coin_products:
        print("❌ Нет coin_products в ответе")
        return

    print(f"📊 Всего монет: {len(coin_products)}\n")

    # Показываем первые 3 coin_product полностью
    for i, coin_product in enumerate(coin_products[:3], 1):
        print(f"\n{'='*80}")
        print(f"МОНЕТА #{i}")
        print('='*80)
        print(json.dumps(coin_product, indent=2, ensure_ascii=False))

        # Ищем все возможные поля с названием монеты
        print(f"\n🔍 Поиск полей с названием монеты:")
        for key, value in coin_product.items():
            if isinstance(value, str) and len(value) < 20:
                print(f"  {key}: {value}")

    # Выводим все ID монет и попытки найти названия
    print(f"\n\n{'='*80}")
    print("📋 СПИСОК ВСЕХ МОНЕТ В ОТВЕТЕ:")
    print('='*80)

    for coin_product in coin_products:
        coin_id = coin_product.get('coin')
        coin_name = coin_product.get('coin_name', 'N/A')
        coin_symbol = coin_product.get('symbol', 'N/A')
        coin_code = coin_product.get('coin_code', 'N/A')

        print(f"ID: {coin_id:3d} | coin_name: {coin_name:10s} | symbol: {coin_symbol:10s} | coin_code: {coin_code}")

if __name__ == "__main__":
    debug_bybit_api()
