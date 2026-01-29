import requests
url = 'https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list'
r = requests.get(url)
data = r.json()
result = data.get('result', {}).get('list', [])
print(f'Всего продуктов: {len(result)}')
print('=== APR > 100% ===')
for p in result:
    apr = float(p.get('apy', 0))
    if apr > 100:
        pid = p.get('id')
        coin = p.get('earningCoin')
        print(f'ID: {pid}, Coin: {coin}, APR: {apr}%')
