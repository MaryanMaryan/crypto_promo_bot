#!/usr/bin/env python3
"""
Простой скрипт для удаления всех ссылок из базы данных
"""
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.database import get_db_session
from data.models import ApiLink

def main():
    print("=" * 50)
    print("УДАЛЕНИЕ ВСЕХ ССЫЛОК ИЗ БАЗЫ ДАННЫХ")
    print("=" * 50)

    try:
        with get_db_session() as session:
            # Получаем количество ссылок
            count = session.query(ApiLink).count()

            print(f"\nВ базе данных найдено ссылок: {count}")

            if count == 0:
                print("База данных уже пустая!")
                return

            # Удаляем все ссылки
            deleted = session.query(ApiLink).delete()
            session.commit()

            print(f"✅ Успешно удалено: {deleted} ссылок")
            print("Теперь вы можете добавить ссылки заново через бота")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
