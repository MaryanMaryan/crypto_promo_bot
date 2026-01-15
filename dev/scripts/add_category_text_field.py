"""
Миграция: Добавление поля category_text в таблицу staking_history

Назначение:
- Добавить поле category_text для сохранения текстового описания категории из KuCoin API

Использование:
    python dev/scripts/add_category_text_field.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data.database import init_database, get_db_session
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def add_category_text_field():
    """Добавляет поле category_text в таблицу staking_history"""

    logger.info("🚀 Начинаем миграцию: добавление поля category_text")

    init_database()

    with get_db_session() as session:
        try:
            # Проверяем, существует ли уже поле
            result = session.execute(text("PRAGMA table_info(staking_history)")).fetchall()
            columns = [col[1] for col in result]

            if 'category_text' in columns:
                logger.info("✅ Поле category_text уже существует")
                return

            # Добавляем поле
            logger.info("📝 Добавляем поле category_text в таблицу staking_history...")
            session.execute(text(
                "ALTER TABLE staking_history ADD COLUMN category_text TEXT"
            ))
            session.commit()

            logger.info("✅ Поле category_text успешно добавлено!")

            # Проверяем результат
            result = session.execute(text("PRAGMA table_info(staking_history)")).fetchall()
            columns = [col[1] for col in result]

            if 'category_text' in columns:
                logger.info("✅ Миграция завершена успешно!")
            else:
                logger.error("❌ Не удалось добавить поле category_text")

        except Exception as e:
            logger.error(f"❌ Ошибка миграции: {e}")
            session.rollback()
            raise

if __name__ == "__main__":
    add_category_text_field()
