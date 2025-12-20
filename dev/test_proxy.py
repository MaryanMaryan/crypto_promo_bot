import requests

proxy = {
    'http': 'http://0980b764e6ffcd74:0NLOnydG@res.proxy-seller.io:10001',
    'https': 'http://0980b764e6ffcd74:0NLOnydG@res.proxy-seller.io:10001'
}

print("Тестирование прокси...")
try:
    r = requests.get('https://httpbin.org/ip', proxies=proxy, timeout=10)
    print(f"OK Прокси работает: {r.status_code}")
    print(f"IP: {r.json()}")
except Exception as e:
    print(f"ERROR: {e}")
