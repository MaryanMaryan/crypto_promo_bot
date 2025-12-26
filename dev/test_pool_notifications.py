"""
Тестирование уведомлений о заполненности пулов
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.staking_parser import StakingParser
from bot.notification_service import NotificationService
from unittest.mock import MagicMock

print("=" * 80)
print("ТЕСТ: Уведомления о заполненности пулов Bybit")
print("=" * 80)

# Создаем парсер
parser = StakingParser(
    api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
    exchange_name="Bybit"
)

# Получаем данные о пулах
print("\n1. Получение данных о пулах...")
pools = parser.get_pool_fills()
print(f"   Найдено пулов с данными о заполненности: {len(pools)}")

# Фильтруем активные пулы с APR >= 100%
high_apr_pools = [p for p in pools if p.get('apr', 0) >= 100 and p.get('status') == 'Active']
print(f"   Активных пулов с APR >= 100%: {len(high_apr_pools)}")

# Сортируем по APR
high_apr_pools.sort(key=lambda x: x.get('apr', 0), reverse=True)

# Показываем топ-5
print("\n2. Топ-5 пулов с высоким APR:")
print("-" * 80)
for i, pool in enumerate(high_apr_pools[:5], 1):
    coin = pool.get('coin')
    apr = pool.get('apr')
    term = pool.get('term_days')
    fill = pool.get('fill_percentage', 0)
    status = pool.get('status')

    print(f"{i}. {coin} | {apr}% APR | {term} дней | Заполнено: {fill:.2f}% | {status}")

# Создаем NotificationService (мокаем бота)
print("\n3. Форматирование уведомления...")
mock_bot = MagicMock()
notification_service = NotificationService(mock_bot)

# Форматируем сообщение с топ-5 пулами
message = notification_service.format_pools_report(
    pools=high_apr_pools[:5],
    exchange_name="Bybit",
    page_url="https://www.bybit.com/en/earn/easy-earn"
)

print("\n4. РЕЗУЛЬТАТ - Уведомление для пользователя:")
print("=" * 80)
print(message)
print("=" * 80)

# Проверяем что нет BNB с высоким APR в сообщении
print("\n5. Проверка корректности:")
lines = message.split('\n')
errors = []

for i, line in enumerate(lines, 1):
    # Ищем строки с монетами и APR
    if '💰' in line and '%' in line:
        # Извлекаем монету (после 💰 и до |)
        if '💰' in line and '|' in line:
            coin_part = line.split('💰')[1].split('|')[0].strip()
            # Извлекаем APR
            if '%' in line:
                apr_part = line.split('|')[1].split('%')[0].strip()
                try:
                    apr = float(apr_part.replace(',', '.'))

                    # Проверяем: если APR >= 500, монета должна быть USDT
                    if apr >= 500:
                        if 'BNB' in coin_part and 'USDT' not in coin_part:
                            errors.append(f"Строка {i}: BNB с APR {apr}% (должен быть USDT)")
                        elif 'USDT' in coin_part:
                            print(f"   ✅ Строка {i}: Правильно - USDT с {apr}% APR")
                except:
                    pass

if errors:
    print("\n❌ НАЙДЕНЫ ОШИБКИ:")
    for error in errors:
        print(f"   {error}")
else:
    print("\n✅ Все проверки пройдены! Монеты отображаются правильно.")

print("\n" + "=" * 80)
print("Тест завершён!")
print("=" * 80)
