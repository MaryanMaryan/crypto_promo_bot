"""
Ищем рабочий Bybit Earn API endpoint
"""
import requests

# Возможные endpoints для Easy Earn
endpoints = [
    # Новые форматы
    'https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    'https://www.bybit.com/x-api/s1/byfi/list-easy-earn-products',
    'https://www.bybit.com/x-api/s1/byfi/get-product-list',
    'https://www.bybit.com/x-api/s1/byfi/earn-product-list',
    'https://www.bybit.com/x-api/byfi/v1/get-easy-earn-product-list',
    'https://www.bybit.com/x-api/earn/v1/product-list',
    'https://www.bybit.com/x-api/earn/get-product-list',
    # Альтернативы
    'https://api2.bybit.com/spot/api/basic/symbol_list',  # для проверки работоспособности
]

headers = {
    'accept': 'application/json',
    'content-type': 'application/json',
    'origin': 'https://www.bybit.com',
    'referer': 'https://www.bybit.com/en/earn/easy-earn',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

payload = {'tab': '0', 'page': 1, 'limit': 2}

for ep in endpoints:
    try:
        if 'symbol_list' in ep:
            r = requests.get(ep, headers=headers, timeout=10)
        else:
            r = requests.post(ep, headers=headers, json=payload, timeout=10)
        print(ep.split('bybit.com')[1] + ':', r.status_code)
        if r.status_code == 200:
            try:
                data = r.json()
                print('  Keys:', list(data.keys())[:5])
            except:
                pass
    except Exception as e:
        print(ep.split('bybit.com')[1] + ': ERROR -', str(e)[:50])
