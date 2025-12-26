"""
Тестирование отображения ВСЕХ незаполненных пулов
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.staking_parser import StakingParser
from bot.notification_service import NotificationService
from unittest.mock import MagicMock

print("=" * 80)
print("ТЕСТ: Отображение ВСЕХ незаполненных пулов")
print("=" * 80)

# Создаем парсер
parser = StakingParser(
    api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
    exchange_name="Bybit"
)

# Получаем все стейкинги
stakings = parser.parse()
print(f"\nВсего стейкингов: {len(stakings)}")

# Фильтруем по критериям как в handlers.py
pools_with_fill = [
    s for s in stakings
    if s.get('fill_percentage') is not None
    and s.get('status') == 'Active'
    and s.get('apr', 0) >= 100
    and s.get('fill_percentage', 100) < 100
]

# Сортируем по APR
pools_with_fill.sort(key=lambda x: x.get('apr', 0), reverse=True)

print(f"Незаполненных пулов с APR >= 100%: {len(pools_with_fill)}")
print("\nСписок всех пулов:")
print("-" * 80)

for i, pool in enumerate(pools_with_fill, 1):
    coin = pool.get('coin')
    apr = pool.get('apr')
    term = pool.get('term_days')
    fill = pool.get('fill_percentage', 0)
    is_vip = pool.get('is_vip', False)
    is_new_user = pool.get('is_new_user', False)

    tags = []
    if is_vip:
        tags.append("VIP")
    if is_new_user:
        tags.append("NEW USER")

    tags_str = f" [{', '.join(tags)}]" if tags else ""

    print(f"{i:2d}. {coin:10s} | {apr:6.1f}% APR | {term:3d} дней | {fill:5.2f}% заполнено{tags_str}")

# Создаем отчёт
print("\n" + "=" * 80)
print("ОТЧЁТ С ВСЕМИ ПУЛАМИ:")
print("=" * 80)

notification_service = NotificationService(MagicMock())
message = notification_service.format_pools_report(
    pools_with_fill,
    exchange_name="Bybit",
    page_url="https://www.bybit.com/en/earn/easy-earn"
)

print(message)

# Проверяем длину
print("\n" + "=" * 80)
print("СТАТИСТИКА:")
print("=" * 80)
print(f"Длина сообщения: {len(message)} символов")
print(f"Telegram лимит: 4096 символов")

if len(message) > 4096:
    print(f"⚠️ ВНИМАНИЕ: Сообщение превышает лимит на {len(message) - 4096} символов")
    print("   (будет автоматически обрезано)")
else:
    print(f"✅ Сообщение в пределах лимита (запас: {4096 - len(message)} символов)")

# Подсчитываем пулы в сообщении
pool_count_in_message = message.count('💰')
print(f"\nПулов в сообщении: {pool_count_in_message}")
print(f"Всего незаполненных: {len(pools_with_fill)}")

if pool_count_in_message == len(pools_with_fill):
    print("✅ Все незаполненные пулы включены в сообщение!")
else:
    print(f"⚠️ В сообщении {pool_count_in_message} пулов из {len(pools_with_fill)}")

print("=" * 80)
