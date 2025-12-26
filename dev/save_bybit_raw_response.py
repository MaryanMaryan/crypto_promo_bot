"""
Сохранение сырого ответа Bybit API в JSON файл для анализа
"""
import requests
import json

API_URL = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"

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

print("Requesting Bybit API...")
try:
    response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    print(f"Status code: {response.status_code}")
    print(f"Response length: {len(response.text)} bytes")

    # Сохраняем сырой текст
    with open('bybit_raw_response.txt', 'w', encoding='utf-8') as f:
        f.write(response.text)
    print("Saved raw response to bybit_raw_response.txt")

    # Пытаемся распарсить JSON
    try:
        data = response.json()

        # Сохраняем JSON с отступами
        with open('bybit_api_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Saved JSON to bybit_api_response.json")

        # Проверяем статус
        if data.get('ret_code') == 0:
            result = data.get('result', {})
            coin_products = result.get('coin_products', [])
            print(f"\nSuccess! Found {len(coin_products)} coins")

            # Показываем первые 5 монет
            print("\nFirst 5 coins:")
            for cp in coin_products[:5]:
                coin_id = cp.get('coin')
                products_count = len(cp.get('saving_products', []))
                print(f"  Coin ID: {coin_id}, Products: {products_count}")
        else:
            print(f"\nAPI Error: {data.get('ret_msg')}")

    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON: {e}")
        print("Check bybit_raw_response.txt for raw content")

except requests.RequestException as e:
    print(f"Request failed: {e}")
