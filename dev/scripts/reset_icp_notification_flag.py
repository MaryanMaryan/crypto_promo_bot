"""
Скрипт для сброса флага notification_sent у ICP Combined стейкинга
Чтобы протестировать фильтр min_apr заново
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


def reset_icp_notification():
    """Сбросить notification_sent для ICP Combined"""
    print("=" * 70)
    print("🔄 СБРОС ФЛАГА notification_sent ДЛЯ ICP COMBINED")
    print("=" * 70)

    with get_db_session() as db:
        # Находим ICP Combined
        icp_staking = db.query(StakingHistory).filter(
            StakingHistory.exchange == 'Gate.io',
            StakingHistory.product_id == 'gate_combined_ICP'
        ).first()

        if not icp_staking:
            print("❌ ICP Combined стейкинг не найден")
            return

        print(f"\n📌 Найден стейкинг:")
        print(f"   Coin: {icp_staking.coin}")
        print(f"   APR: {icp_staking.apr}%")
        print(f"   Lock Type: {icp_staking.lock_type}")
        print(f"   notification_sent (до): {icp_staking.notification_sent}")
        print(f"   notification_sent_at (до): {icp_staking.notification_sent_at}")

        # Сбрасываем флаг
        icp_staking.notification_sent = False
        icp_staking.notification_sent_at = None

        db.commit()

        print(f"\n✅ ФЛАГ СБРОШЕН:")
        print(f"   notification_sent (после): {icp_staking.notification_sent}")
        print(f"   notification_sent_at (после): {icp_staking.notification_sent_at}")

        print("\n" + "=" * 70)
        print("✅ ГОТОВО! Теперь можно запустить принудительную проверку")
        print("=" * 70)


if __name__ == "__main__":
    try:
        reset_icp_notification()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
