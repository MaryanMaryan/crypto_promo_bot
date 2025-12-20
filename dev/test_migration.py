#!/usr/bin/env python3
"""Тестовый скрипт для проверки миграции parsing_type"""

import sys
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_migration():
    """Проверяет наличие поля parsing_type в таблице api_links"""
    try:
        conn = sqlite3.connect('data/database.db')
        cursor = conn.cursor()

        # Проверяем текущую структуру таблицы
        cursor.execute('PRAGMA table_info(api_links)')
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]

        logger.info("✅ Текущие столбцы в таблице api_links:")
        for i, col in enumerate(columns):
            logger.info(f"   {i+1}. {col[1]} ({col[2]})")

        # Проверяем наличие parsing_type
        if 'parsing_type' not in column_names:
            logger.warning("⚠️ Поле parsing_type не найдено!")
            logger.info("🔄 Добавляем поле parsing_type...")

            cursor.execute("ALTER TABLE api_links ADD COLUMN parsing_type TEXT DEFAULT 'combined'")
            conn.commit()
            logger.info("✅ Поле parsing_type успешно добавлено!")

            # Проверяем снова
            cursor.execute('PRAGMA table_info(api_links)')
            columns = cursor.fetchall()
            for col in columns:
                if col[1] == 'parsing_type':
                    logger.info(f"✅ Подтверждено: {col[1]} ({col[2]}) успешно добавлено")
        else:
            logger.info("✅ Поле parsing_type уже существует в таблице")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка проверки миграции: {e}")
        return False

if __name__ == "__main__":
    logger.info("🔍 Запуск проверки миграции parsing_type...")
    success = check_migration()

    if success:
        logger.info("✅ Проверка миграции завершена успешно!")
        sys.exit(0)
    else:
        logger.error("❌ Проверка миграции провалилась!")
        sys.exit(1)
