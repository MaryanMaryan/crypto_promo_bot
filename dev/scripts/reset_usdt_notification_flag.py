"""
Скрипт для сброса флага notification_sent у USDT Combined стейкинга
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
from data.models import StakingHistory


def reset_usdt_notification():
    """Сбросить notification_sent для USDT Combined"""
    print("=" * 70)
    print("🔄 СБРОС ФЛАГА notification_sent ДЛЯ USDT COMBINED")
    print("=" * 70)

    with get_db_session() as db:
        # Находим USDT Combined
        usdt_staking = db.query(StakingHistory).filter(
            StakingHistory.exchange == 'Gate.io',
            StakingHistory.product_id == 'gate_combined_USDT'
        ).first()

        if not usdt_staking:
            print("❌ USDT Combined стейкинг не найден")
            return

        print(f"\n📌 Найден стейкинг:")
        print(f"   Coin: {usdt_staking.coin}")
        print(f"   APR: {usdt_staking.apr}%")
        print(f"   Lock Type: {usdt_staking.lock_type}")
        print(f"   notification_sent (до): {usdt_staking.notification_sent}")
        print(f"   notification_sent_at (до): {usdt_staking.notification_sent_at}")

        # Сбрасываем флаг
        usdt_staking.notification_sent = False
        usdt_staking.notification_sent_at = None

        db.commit()

        print(f"\n✅ ФЛАГ СБРОШЕН:")
        print(f"   notification_sent (после): {usdt_staking.notification_sent}")
        print(f"   notification_sent_at (после): {usdt_staking.notification_sent_at}")

        print("\n" + "=" * 70)
        print("✅ ГОТОВО!")
        print("=" * 70)


if __name__ == "__main__":
    try:
        reset_usdt_notification()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
