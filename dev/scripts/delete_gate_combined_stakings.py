"""
Удаляет Combined стейкинги Gate.io из БД для повторного теста
"""

import sys
import os

# Добавляем корневую директорию проекта в PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from data.database import get_db_session
from data.models import StakingHistory

def delete_gate_combined():
    """
    Удаляет Combined стейкинги Gate.io из БД
    """
    with get_db_session() as db:
        # Получаем все Combined стейкинги Gate.io
        combined_stakings = db.query(StakingHistory).filter(
            StakingHistory.exchange == 'Gate.io',
            StakingHistory.type == 'Fixed/Flexible'
        ).all()

        print(f"\n🔍 Найдено {len(combined_stakings)} Combined стейкингов Gate.io:")

        for staking in combined_stakings:
            print(f"   • {staking.coin}: {staking.apr}% APR (notification_sent={staking.notification_sent})")

        if not combined_stakings:
            print("✅ Нет Combined стейкингов для удаления")
            return

        # Спрашиваем подтверждение
        print(f"\n⚠️  Это удалит все {len(combined_stakings)} Combined стейкингов из БД!")
        confirmation = input("Продолжить? (yes/no): ")

        if confirmation.lower() != 'yes':
            print("❌ Отменено пользователем")
            return

        # Удаляем сначала связанные снимки, потом стейкинги
        from data.models import StakingSnapshot

        total_snapshots = 0
        for staking in combined_stakings:
            # Удаляем все снимки для этого стейкинга
            snapshots = db.query(StakingSnapshot).filter(
                StakingSnapshot.staking_history_id == staking.id
            ).all()

            for snapshot in snapshots:
                db.delete(snapshot)
                total_snapshots += 1

            # Удаляем сам стейкинг
            db.delete(staking)

        db.commit()

        print(f"\n✅ Удалено {total_snapshots} снимков")
        print(f"✅ Удалено {len(combined_stakings)} Combined стейкингов")
        print(f"✅ Теперь они будут считаться НОВЫМИ при следующей проверке")

if __name__ == "__main__":
    print("=" * 60)
    print("УДАЛЕНИЕ COMBINED СТЕЙКИНГОВ GATE.IO")
    print("=" * 60)

    try:
        delete_gate_combined()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
