"""
Поиск API Bybit для маппинга coin_id → symbol
"""
import sys
import io
import requests
import json

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def try_coin_list_api():
    """Пробуем найти endpoint со списком монет"""

    headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://www.bybit.com',
        'referer': 'https://www.bybit.com/en/earn/easy-earn',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    # Возможные endpoints
    endpoints = [
        # x-api endpoints (внутреннее API фронтенда)
        "https://www.bybit.com/x-api/s1/byfi/coin-list",
        "https://www.bybit.com/x-api/s1/byfi/get-coin-list",
        "https://www.bybit.com/x-api/common/coin-info",
        "https://www.bybit.com/x-api/common/coin-list",

        # Публичный spot API v5
        "https://api.bybit.com/v5/market/instruments-info?category=spot",
        "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",

        # Asset API
        "https://api.bybit.com/v5/asset/coin/query-info",
    ]

    for endpoint in endpoints:
        print(f"\n{'='*80}")
        print(f"🔍 Проверяю: {endpoint}")
        print('='*80)

        try:
            if 'api.bybit.com' in endpoint:
                # Публичный API не требует специальных заголовков
                response = requests.get(endpoint, timeout=10)
            else:
                # x-api может требовать больше заголовков
                response = requests.get(endpoint, headers=headers, timeout=10)

            print(f"📊 Статус: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"✅ JSON получен!")

                    # Показываем структуру
                    print(f"\n📋 Ключи верхнего уровня:")
                    if isinstance(data, dict):
                        for key in data.keys():
                            print(f"  - {key}")

                    # Показываем первые элементы
                    print(f"\n📄 Первые 200 символов:")
                    print(json.dumps(data, indent=2, ensure_ascii=False)[:200])

                    # Сохраняем успешный результат
                    if 'result' in data or 'data' in data or isinstance(data, list):
                        filename = endpoint.split('/')[-1].replace('?', '_') + '.json'
                        with open(filename, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        print(f"\n💾 Сохранено в: {filename}")

                except Exception as e:
                    print(f"⚠️ Ошибка парсинга JSON: {e}")
                    print(f"Содержимое: {response.text[:200]}")
            else:
                print(f"❌ Ошибка: {response.status_code}")

        except Exception as e:
            print(f"❌ Исключение: {e}")

def try_spot_api():
    """Попытка получить список монет через Spot API"""
    print(f"\n{'='*80}")
    print(f"🔍 ТЕСТ: Spot API для получения информации о монетах")
    print('='*80)

    # Этот endpoint точно существует
    url = "https://api.bybit.com/v5/market/instruments-info"
    params = {
        "category": "spot",
        "limit": 200
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"📊 Статус: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            if 'result' in data and 'list' in data['result']:
                instruments = data['result']['list']
                print(f"✅ Получено инструментов: {len(instruments)}")

                # Показываем первый инструмент
                if instruments:
                    print(f"\n📋 Пример инструмента:")
                    print(json.dumps(instruments[0], indent=2, ensure_ascii=False))

                # Извлекаем уникальные базовые монеты
                base_coins = set()
                for inst in instruments:
                    base_coin = inst.get('baseCoin', '')
                    if base_coin:
                        base_coins.add(base_coin)

                print(f"\n💎 Уникальных монет: {len(base_coins)}")
                print(f"Примеры: {list(sorted(base_coins))[:20]}")

        else:
            print(f"❌ Ошибка: {response.status_code}")

    except Exception as e:
        print(f"❌ Исключение: {e}")

if __name__ == "__main__":
    print("🚀 ПОИСК API ДЛЯ МАППИНГА COIN ID → SYMBOL\n")

    try_coin_list_api()
    try_spot_api()

    print(f"\n\n{'='*80}")
    print("✅ Поиск завершён!")
    print('='*80)
