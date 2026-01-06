"""
Скрипт для исправления путей к сессиям в БД
Добавляет префикс sessions/ к путям, которые его не имеют
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import get_db_session
from data.models import TelegramAccount

def fix_session_paths():
    """Обновить пути к сессиям, добавив префикс sessions/"""

    with get_db_session() as db:
        accounts = db.query(TelegramAccount).all()

        print(f"\n[INFO] Найдено аккаунтов: {len(accounts)}")
        print("="*70)

        updated_count = 0
        for account in accounts:
            old_path = account.session_file

            # Проверяем, нужно ли обновление
            if not old_path.startswith('sessions/'):
                # Убираем расширение .session если есть
                path_without_ext = old_path.replace('.session', '')

                # Добавляем префикс sessions/
                new_path = f'sessions/{path_without_ext}'

                print(f"\n[UPDATE] Аккаунт #{account.id}: {account.name or account.phone_number}")
                print(f"   Старый путь: {old_path}")
                print(f"   Новый путь:  {new_path}")

                account.session_file = new_path
                updated_count += 1
            else:
                print(f"\n[OK] Аккаунт #{account.id}: {account.name or account.phone_number}")
                print(f"   Путь уже правильный: {old_path}")

        if updated_count > 0:
            db.commit()
            print(f"\n[SUCCESS] Обновлено путей: {updated_count}")
        else:
            print(f"\n[SUCCESS] Все пути уже корректны!")

        print("="*70)

if __name__ == "__main__":
    try:
        fix_session_paths()
    except Exception as e:
        print(f"[ERROR] Ошибка: {e}")
        import traceback
        traceback.print_exc()
