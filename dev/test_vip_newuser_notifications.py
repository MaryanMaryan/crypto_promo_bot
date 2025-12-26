"""
Тестирование уведомлений с пометками VIP и New User
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.staking_parser import StakingParser
from bot.notification_service import NotificationService
from unittest.mock import MagicMock

print("=" * 80)
print("ТЕСТ: Уведомления с пометками VIP и New User")
print("=" * 80)

# Создаем парсер
parser = StakingParser(
    api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
    exchange_name="Bybit"
)

# Получаем все стейкинги
stakings = parser.parse()

# Фильтруем VIP и New User продукты
vip_stakings = [s for s in stakings if s.get('is_vip')]
new_user_stakings = [s for s in stakings if s.get('is_new_user')]

print(f"\nНайдено VIP продуктов: {len(vip_stakings)}")
print(f"Найдено New User продуктов: {len(new_user_stakings)}")

# Создаем NotificationService
mock_bot = MagicMock()
notification_service = NotificationService(mock_bot)

# Тестируем уведомление для VIP продукта
if vip_stakings:
    print("\n" + "=" * 80)
    print("ПРИМЕР 1: VIP продукт")
    print("=" * 80)
    vip_product = vip_stakings[0]
    print(f"Продукт: {vip_product.get('coin')} | {vip_product.get('apr')}% APR")
    print(f"is_vip: {vip_product.get('is_vip')}")

    message = notification_service.format_new_staking(
        vip_product,
        page_url="https://www.bybit.com/en/earn/easy-earn"
    )
    print("\nУведомление:")
    print("-" * 80)
    print(message)

# Тестируем уведомление для New User продукта
if new_user_stakings:
    print("\n" + "=" * 80)
    print("ПРИМЕР 2: New User продукт")
    print("=" * 80)
    new_user_product = new_user_stakings[0]
    print(f"Продукт: {new_user_product.get('coin')} | {new_user_product.get('apr')}% APR")
    print(f"is_new_user: {new_user_product.get('is_new_user')}")

    message = notification_service.format_new_staking(
        new_user_product,
        page_url="https://www.bybit.com/en/earn/easy-earn"
    )
    print("\nУведомление:")
    print("-" * 80)
    print(message)

# Тестируем отчёт о пулах с VIP и New User
print("\n" + "=" * 80)
print("ПРИМЕР 3: Отчёт о заполненности пулов")
print("=" * 80)

# Получаем пулы с данными о заполненности
pools = parser.get_pool_fills()

# Фильтруем VIP и New User активные пулы с высоким APR
filtered_pools = [
    p for p in pools
    if (p.get('is_vip') or p.get('is_new_user'))
    and p.get('status') == 'Active'
    and p.get('apr', 0) >= 25
]

print(f"Найдено активных VIP/New User пулов с APR >= 25%: {len(filtered_pools)}")

if filtered_pools:
    # Берём топ-3
    top_pools = sorted(filtered_pools, key=lambda x: x.get('apr', 0), reverse=True)[:3]

    message = notification_service.format_pools_report(
        pools=top_pools,
        exchange_name="Bybit",
        page_url="https://www.bybit.com/en/earn/easy-earn"
    )

    print("\nОтчёт:")
    print("-" * 80)
    print(message)

# Проверка: есть ли пометки в сообщениях
print("\n" + "=" * 80)
print("ПРОВЕРКА: Наличие пометок")
print("=" * 80)

checks = []

if vip_stakings:
    vip_msg = notification_service.format_new_staking(vip_stakings[0])
    if '👑 VIP' in vip_msg:
        print("✅ VIP пометка присутствует в уведомлении о новом стейкинге")
        checks.append(True)
    else:
        print("❌ VIP пометка отсутствует в уведомлении о новом стейкинге")
        checks.append(False)

if new_user_stakings:
    new_user_msg = notification_service.format_new_staking(new_user_stakings[0])
    if '🎁 NEW USER' in new_user_msg:
        print("✅ NEW USER пометка присутствует в уведомлении о новом стейкинге")
        checks.append(True)
    else:
        print("❌ NEW USER пометка отсутствует в уведомлении о новом стейкинге")
        checks.append(False)

if all(checks):
    print("\n🎉 Все проверки пройдены!")
else:
    print("\n⚠️ Некоторые проверки не пройдены")

print("=" * 80)
