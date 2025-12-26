"""
Тестирование исправленного парсера стейкинга
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.staking_parser import StakingParser

print("=" * 80)
print("ТЕСТ: Проверка правильного определения монет в Bybit стейкинге")
print("=" * 80)

# Создаем парсер
parser = StakingParser(
    api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
    exchange_name="Bybit"
)

# Парсим
stakings = parser.parse()

print(f"\nВсего найдено стейкингов: {len(stakings)}\n")

# Проверяем продукты с высоким APR
high_apr_stakings = [s for s in stakings if s.get('apr', 0) >= 100]

print(f"Стейкинги с APR >= 100%: {len(high_apr_stakings)}\n")
print("=" * 80)

# Группируем по монетам
coins_count = {}
for s in high_apr_stakings:
    coin = s.get('coin')
    if coin not in coins_count:
        coins_count[coin] = 0
    coins_count[coin] += 1

print("\nРаспределение по монетам:")
for coin, count in sorted(coins_count.items(), key=lambda x: x[1], reverse=True):
    print(f"  {coin}: {count} продуктов")

# Проверяем USDT продукты
print("\n" + "=" * 80)
print("USDT продукты (должны быть 555%, 600% и т.д.):")
print("=" * 80)

usdt_stakings = [s for s in stakings if s.get('coin') == 'USDT']
for s in usdt_stakings:
    apr = s.get('apr', 0)
    term = s.get('term_days', 0)
    product_id = s.get('product_id')
    status = s.get('status')
    print(f"\nProduct {product_id}:")
    print(f"  Монета: {s.get('coin')}")
    print(f"  APR: {apr}%")
    print(f"  Срок: {term} дней")
    print(f"  Статус: {status}")
    if apr >= 100:
        print(f"  ✅ ПРАВИЛЬНО! USDT с высоким APR")

# Проверяем BNB продукты
print("\n" + "=" * 80)
print("BNB продукты (не должно быть 555%, 600%):")
print("=" * 80)

bnb_stakings = [s for s in stakings if s.get('coin') == 'BNB']
for s in bnb_stakings:
    apr = s.get('apr', 0)
    term = s.get('term_days', 0)
    product_id = s.get('product_id')
    print(f"\nProduct {product_id}:")
    print(f"  APR: {apr}%, Срок: {term} дней")
    if apr >= 500:
        print(f"  ❌ ОШИБКА! BNB не должен иметь такой высокий APR!")

print("\n" + "=" * 80)
print("Тест завершён!")
print("=" * 80)
