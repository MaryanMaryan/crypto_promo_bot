#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт миграции для интеграции Telegram парсинга в ApiLink

Что делает скрипт:
1. Добавляет новые колонки telegram_channel и telegram_keywords в таблицу api_links
2. Удаляет старые таблицы telegram_channels и telegram_messages
3. Обновляет структуру базы данных для новой интеграции Telegram

Использование:
    python migrate_telegram.py
"""

import sqlite3
import logging
import os
import sys
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Путь к базе данных
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'database.db'


def check_database_exists():
    """Проверяет существование базы данных"""
    if not DB_PATH.exists():
        logger.error(f"❌ База данных не найдена: {DB_PATH}")
        logger.error("Сначала запустите бота для создания БД")
        return False
    logger.info(f"✅ База данных найдена: {DB_PATH}")
    return True


def backup_database():
    """Создает резервную копию базы данных"""
    backup_path = DB_PATH.parent / f"{DB_PATH.stem}_backup.db"
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"✅ Создана резервная копия: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка создания резервной копии: {e}")
        return False


def migrate_database():
    """Выполняет миграцию базы данных"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        logger.info("🔄 Начало миграции базы данных...")

        # Шаг 1: Проверяем, существуют ли колонки telegram_channel и telegram_keywords
        cursor.execute("PRAGMA table_info(api_links)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'telegram_channel' not in columns:
            logger.info("➕ Добавление колонки telegram_channel...")
            cursor.execute("""
                ALTER TABLE api_links
                ADD COLUMN telegram_channel TEXT
            """)
            logger.info("✅ Колонка telegram_channel добавлена")
        else:
            logger.info("ℹ️ Колонка telegram_channel уже существует")

        if 'telegram_keywords' not in columns:
            logger.info("➕ Добавление колонки telegram_keywords...")
            cursor.execute("""
                ALTER TABLE api_links
                ADD COLUMN telegram_keywords TEXT DEFAULT '[]'
            """)
            logger.info("✅ Колонка telegram_keywords добавлена")
        else:
            logger.info("ℹ️ Колонка telegram_keywords уже существует")

        # Шаг 2: Проверяем существование старых таблиц
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND (name='telegram_channels' OR name='telegram_messages')
        """)
        old_tables = [table[0] for table in cursor.fetchall()]

        if old_tables:
            logger.info(f"🗑️ Найдены старые таблицы Telegram: {', '.join(old_tables)}")

            # Спрашиваем подтверждение
            print("\n⚠️ ВНИМАНИЕ: Найдены старые таблицы Telegram:")
            for table in old_tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"   - {table}: {count} записей")

            print("\nУдалить эти таблицы? Все данные будут потеряны.")
            print("(Резервная копия БД уже создана)")

            response = input("Введите 'yes' для подтверждения: ").strip().lower()

            if response == 'yes':
                for table in old_tables:
                    logger.info(f"🗑️ Удаление таблицы {table}...")
                    cursor.execute(f"DROP TABLE {table}")
                    logger.info(f"✅ Таблица {table} удалена")
            else:
                logger.info("ℹ️ Старые таблицы НЕ удалены (оставлены для совместимости)")
        else:
            logger.info("ℹ️ Старые таблицы Telegram не найдены")

        # Коммитим изменения
        conn.commit()
        logger.info("✅ Миграция завершена успешно!")

        # Показываем статистику
        logger.info("\n📊 Статистика базы данных:")

        cursor.execute("SELECT COUNT(*) FROM api_links")
        total_links = cursor.fetchone()[0]
        logger.info(f"   Всего ссылок: {total_links}")

        cursor.execute("SELECT COUNT(*) FROM api_links WHERE parsing_type='telegram'")
        telegram_links = cursor.fetchone()[0]
        logger.info(f"   Telegram ссылок: {telegram_links}")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")
        logger.error("Восстановите БД из резервной копии в случае проблем")
        return False


def main():
    """Главная функция"""
    print("=" * 60)
    print("📱 Миграция Telegram парсинга")
    print("=" * 60)
    print()

    # Проверяем существование БД
    if not check_database_exists():
        return 1

    # Создаем резервную копию
    print("\n🔒 Создание резервной копии БД...")
    if not backup_database():
        print("\n⚠️ Не удалось создать резервную копию.")
        response = input("Продолжить без резервной копии? (yes/no): ").strip().lower()
        if response != 'yes':
            logger.info("❌ Миграция отменена пользователем")
            return 1

    # Выполняем миграцию
    print("\n🔄 Выполнение миграции...")
    if migrate_database():
        print("\n" + "=" * 60)
        print("✅ Миграция завершена успешно!")
        print("=" * 60)
        print("\nТеперь вы можете:")
        print("1. Запустить бота: python main.py")
        print("2. Добавить Telegram-ссылки через бота")
        print("3. Настроить Telegram API в разделе 'Обход блокировок'")
        return 0
    else:
        print("\n" + "=" * 60)
        print("❌ Миграция завершилась с ошибками")
        print("=" * 60)
        print("\nВосстановите БД из резервной копии:")
        print(f"   cp {DB_PATH.parent / f'{DB_PATH.stem}_backup.db'} {DB_PATH}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
