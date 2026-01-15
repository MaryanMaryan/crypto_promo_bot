"""
Скрипт для исправления старых стейкингов: устанавливает notification_sent=True

Проблема: Старые стейкинги в БД имеют notification_sent=False и отправляются повторно
Решение: Установить notification_sent=True для всех старых стейкингов
"""

import sys
import os

# Добавляем корневую директорию проекта в PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from data.database import get_db_session
from data.models import StakingHistory
from datetime import datetime, timedelta

def fix_old_stakings():
    """
    Устанавливает notification_sent=True для всех старых стейкингов
    """
    with get_db_session() as db:
        # Получаем все стейкинги с notification_sent=False или NULL
        old_stakings = db.query(StakingHistory).filter(
            (StakingHistory.notification_sent == False) |
            (StakingHistory.notification_sent == None)
        ).all()

        print(f"\n🔍 Найдено {len(old_stakings)} старых стейкингов с notification_sent=False/NULL")

        if not old_stakings:
            print("✅ Нет стейкингов для обновления")
            return

        # Группируем по биржам для статистики
        by_exchange = {}
        for staking in old_stakings:
            exchange = staking.exchange or 'Unknown'
            by_exchange[exchange] = by_exchange.get(exchange, 0) + 1

        print(f"\n📊 Распределение по биржам:")
        for exchange, count in sorted(by_exchange.items(), key=lambda x: x[1], reverse=True):
            print(f"   • {exchange}: {count} стейкингов")

        # Спрашиваем подтверждение
        print(f"\n⚠️  Это установит notification_sent=True для ВСЕХ {len(old_stakings)} стейкингов!")
        confirmation = input("Продолжить? (yes/no): ")

        if confirmation.lower() != 'yes':
            print("❌ Отменено пользователем")
            return

        # Устанавливаем notification_sent=True для всех
        updated_count = 0
        for staking in old_stakings:
            staking.notification_sent = True
            updated_count += 1

        # Коммитим изменения
        db.commit()

        print(f"\n✅ Обновлено {updated_count} стейкингов")
        print(f"✅ Все старые стейкинги отмечены как уведомленные")
        print(f"\n💡 Теперь бот не будет отправлять их повторно")

if __name__ == "__main__":
    print("=" * 60)
    print("ИСПРАВЛЕНИЕ СТАРЫХ СТЕЙКИНГОВ")
    print("=" * 60)

    try:
        fix_old_stakings()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
