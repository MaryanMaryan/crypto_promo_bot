"""
Тест: Проверка работы CoinMarketCap API
"""
import sys
import io
import os
from dotenv import load_dotenv

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Загружаем переменные окружения
load_dotenv()

print("=" * 80)
print("🧪 ТЕСТ: CoinMarketCap API интеграция")
print("=" * 80)
print()

# Проверяем загрузку API ключа
api_key = os.getenv('COINMARKETCAP_API_KEY')
if api_key:
    print(f"✅ API ключ загружен: {api_key[:10]}... ({len(api_key)} символов)")
else:
    print("❌ API ключ НЕ найден в .env")
    sys.exit(1)

print()

# Тестируем PriceFetcher
from utils.price_fetcher import PriceFetcher

# Создаём fetcher с явным указанием ключа
fetcher = PriceFetcher(cmc_api_key=api_key)

print(f"📊 PriceFetcher настройки:")
print(f"   - Использует CMC: {fetcher.use_cmc}")
print(f"   - CMC API Key: {fetcher.cmc_api_key[:10]}..." if fetcher.cmc_api_key else "   - Нет ключа")
print()

# Тест получения цен
print("=" * 80)
print("💰 ТЕСТ: Получение цен популярных монет")
print("=" * 80)
print()

test_coins = ['BTC', 'ETH', 'BNB', 'USDT', 'SOL', 'ADA', 'DOGE']

successful = 0
failed = 0

for coin in test_coins:
    price = fetcher.get_token_price(coin)
    if price:
        print(f"✅ {coin:8s} = ${price:,.2f}")
        successful += 1
    else:
        print(f"❌ {coin:8s} = Не получена")
        failed += 1

print()
print("=" * 80)
print("📈 РЕЗУЛЬТАТЫ")
print("=" * 80)
print(f"✅ Успешно: {successful}/{len(test_coins)}")
print(f"❌ Не удалось: {failed}/{len(test_coins)}")
print(f"📦 В кэше: {len(fetcher._cache)} монет")
print()

if successful == len(test_coins):
    print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
else:
    print(f"⚠️ {failed} монет не получены")
