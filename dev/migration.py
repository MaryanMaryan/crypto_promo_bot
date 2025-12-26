"""
migration.py
Скрипт для применения миграций базы данных
"""

import logging
import sys
import io

# Исправление кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    print("Применение миграции БД...")
    print("=" * 50)

    # Импортируем database - это автоматически запустит миграции
    from data.database import init_database, migration_runner

    # Инициализация БД (если еще не инициализирована)
    init_database()

    # Запуск миграций
    migration_runner.run_migrations()

    print("=" * 50)
    print("Миграция завершена!")
    print("\nПроверьте логи выше для деталей.")
