"""
Миграция БД: Добавление полей для раздельных пулов MEXC Airdrop

Добавляет в таблицу promo_history три новых колонки:
- token_pool (Float) - пул токенов проекта
- token_pool_currency (String) - валюта токен-пула
- bonus_usdt (Float) - бонусный пул в USDT

Дата: 2026-01-20
"""

import sys
import os

# Добавляем путь к корневой директории проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from data.database import get_db_session, init_database
import data.database
import logging

# Настраиваем базовый логгер
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализируем БД и получаем engine
init_database()
engine = data.database._engine

def migrate():
    """Выполняет миграцию БД"""
    try:
        logger.info("🚀 Начало миграции: добавление полей для MEXC Airdrop пулов")

        with engine.connect() as connection:
            # Проверяем, существуют ли уже колонки
            result = connection.execute(text("PRAGMA table_info(promo_history)"))
            columns = [row[1] for row in result]

            columns_to_add = []

            if 'token_pool' not in columns:
                columns_to_add.append(('token_pool', 'REAL'))
                logger.info("   ➕ Добавляем колонку: token_pool")
            else:
                logger.info("   ✅ Колонка token_pool уже существует")

            if 'token_pool_currency' not in columns:
                columns_to_add.append(('token_pool_currency', 'VARCHAR'))
                logger.info("   ➕ Добавляем колонку: token_pool_currency")
            else:
                logger.info("   ✅ Колонка token_pool_currency уже существует")

            if 'bonus_usdt' not in columns:
                columns_to_add.append(('bonus_usdt', 'REAL'))
                logger.info("   ➕ Добавляем колонку: bonus_usdt")
            else:
                logger.info("   ✅ Колонка bonus_usdt уже существует")

            # Добавляем недостающие колонки
            if columns_to_add:
                for col_name, col_type in columns_to_add:
                    connection.execute(text(f"ALTER TABLE promo_history ADD COLUMN {col_name} {col_type}"))
                    connection.commit()
                    logger.info(f"   ✅ Колонка {col_name} добавлена успешно")

                logger.info(f"✅ Миграция завершена успешно! Добавлено колонок: {len(columns_to_add)}")
            else:
                logger.info("✅ Все колонки уже существуют, миграция не требуется")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}", exc_info=True)
        return False

def rollback():
    """Откат миграции (удаление добавленных колонок)"""
    try:
        logger.info("🔄 Начало отката миграции")

        with engine.connect() as connection:
            # SQLite не поддерживает DROP COLUMN напрямую
            # Нужно создать новую таблицу без этих колонок и скопировать данные
            logger.warning("⚠️ SQLite не поддерживает удаление колонок напрямую")
            logger.warning("⚠️ Для полного отката требуется создание резервной копии и восстановление")
            logger.info("💡 Рекомендуется использовать резервную копию БД из папки backups/")

        return False

    except Exception as e:
        logger.error(f"❌ Ошибка отката: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Миграция БД для MEXC Airdrop пулов')
    parser.add_argument('--rollback', action='store_true', help='Откатить миграцию')
    args = parser.parse_args()

    if args.rollback:
        success = rollback()
    else:
        success = migrate()

    sys.exit(0 if success else 1)
