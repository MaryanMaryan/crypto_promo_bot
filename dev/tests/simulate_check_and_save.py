"""
Симуляция check_and_save_new_stakings для отладки
Показывает весь путь фильтрации для ICP и USDT
"""

import sys
import os

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data.database import get_db_session
from data.models import StakingHistory, ApiLink
from services.stability_tracker_service import StabilityTrackerService


def simulate_filtering():
    """Симуляция фильтрации как в check_and_save_new_stakings"""
    print("=" * 90)
    print("🔬 СИМУЛЯЦИЯ check_and_save_new_stakings ДЛЯ ICP И USDT")
    print("=" * 90)

    with get_db_session() as session:
        # Получаем Gate.io ссылку
        api_link = session.query(ApiLink).filter(
            ApiLink.name.like('%Gate%'),
            ApiLink.category == 'staking'
        ).first()

        if not api_link:
            print("❌ Gate.io ссылка не найдена")
            return

        min_apr = api_link.min_apr
        stability_tracker = StabilityTrackerService(session)

        print(f"\n📌 НАСТРОЙКИ ССЫЛКИ:")
        print(f"   min_apr: {min_apr}%")
        print(f"   notify_combined_as_fixed: {api_link.notify_combined_as_fixed}")

        # Тестируем ICP и USDT Combined
        test_coins = ['ICP', 'USDT']

        for coin in test_coins:
            print(f"\n{'=' * 90}")
            print(f"🧪 ТЕСТ ДЛЯ {coin}")
            print(f"{'=' * 90}")

            # Получаем стейкинг из БД
            existing = session.query(StakingHistory).filter(
                StakingHistory.exchange == 'Gate.io',
                StakingHistory.product_id == f'gate_combined_{coin}'
            ).first()

            if not existing:
                print(f"❌ {coin} Combined не найден в БД")
                continue

            print(f"\n📊 ДАННЫЕ ИЗ БД:")
            print(f"   Coin: {existing.coin}")
            print(f"   APR: {existing.apr}%")
            print(f"   Previous APR: {existing.previous_apr}%")
            print(f"   Lock Type: {existing.lock_type}")
            print(f"   notification_sent: {existing.notification_sent}")
            print(f"   notification_sent_at: {existing.notification_sent_at}")

            # ШАГ 1: update_stability_status (строка 565-569)
            print(f"\n🔍 ШАГ 1: update_stability_status()")
            print(f"   (Обновление статуса стабильности при изменении APR)")

            # Предполагаем, что APR не изменился (new_apr = existing.apr)
            new_apr = existing.apr
            print(f"   new_apr: {new_apr}% (не изменился)")

            # ШАГ 2: check_stability (строка 572)
            print(f"\n🔍 ШАГ 2: check_stability()")
            stability_result = stability_tracker.check_stability(existing, api_link)

            print(f"   should_notify: {stability_result['should_notify']}")
            print(f"   notification_type: {stability_result['notification_type']}")
            print(f"   reason: {stability_result['reason']}")

            if not stability_result['should_notify']:
                print(f"\n   ❌ РЕШЕНИЕ: НЕ УВЕДОМЛЯТЬ (check_stability вернул False)")
                continue

            # ШАГ 3: Проверка повтора (строка 574-577)
            print(f"\n🔍 ШАГ 3: Проверка повтора (строка 574-577)")
            print(f"   Условие: (notification_type != 'apr_change' AND notification_sent == True)")
            print(f"   Расчёт: ('{stability_result['notification_type']}' != 'apr_change' AND {existing.notification_sent} == True)")

            skip_duplicate = (
                stability_result['notification_type'] != 'apr_change'
                and existing.notification_sent
            )
            print(f"   Результат: {skip_duplicate}")

            if skip_duplicate:
                print(f"\n   ❌ РЕШЕНИЕ: ПРОПУСТИТЬ (уже отправлено)")
                continue

            # ШАГ 4: Проверка min_apr (строка 579-587)
            print(f"\n🔍 ШАГ 4: Проверка фильтра min_apr (строка 579-587)")
            apr_passes_filter = (min_apr is None or existing.apr >= min_apr)

            print(f"   Формула: (min_apr is None or apr >= min_apr)")
            print(f"   Расчёт: ({min_apr} is None or {existing.apr} >= {min_apr})")
            print(f"   Результат: {apr_passes_filter}")

            # ШАГ 5: Финальное решение (строка 589-605)
            print(f"\n🔍 ШАГ 5: Финальное решение (строка 589-605)")

            if apr_passes_filter:
                print(f"\n   ✅ РЕШЕНИЕ: ДОБАВИТЬ В new_stakings")
                print(f"   ✅ Стейкинг будет отправлен пользователю")
                print(f"   📝 Тип уведомления: {stability_result['notification_type']}")
                print(f"   📝 Причина: {stability_result['reason']}")
            else:
                print(f"\n   ❌ РЕШЕНИЕ: НЕ ДОБАВЛЯТЬ (фильтр min_apr)")
                print(f"   ❌ APR {existing.apr}% < min_apr {min_apr}%")

    print(f"\n{'=' * 90}")
    print("✅ СИМУЛЯЦИЯ ЗАВЕРШЕНА")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    try:
        simulate_filtering()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
