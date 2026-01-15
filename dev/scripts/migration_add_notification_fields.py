#!/usr/bin/env python3
"""
Миграция 010: Добавление полей для системы умных уведомлений

Добавляет:
1. 6 полей в StakingHistory (lock_type, stable_since, last_apr_change, previous_apr, notification_sent_at, is_notification_pending)
2. 9 полей в ApiLink (настройки уведомлений)
3. Таблицу UserLinkSubscription

Использование:
    python dev/scripts/migration_add_notification_fields.py
"""

import sys
import os

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DATABASE_URL = 'sqlite:///data/database.db'

def get_engine():
    """Создание подключения к БД"""
    return create_engine(DATABASE_URL, connect_args={'check_same_thread': False})

def check_column_exists(session, table_name, column_name):
    """Проверка существования столбца в таблице"""
    result = session.execute(text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns

def check_table_exists(session, table_name):
    """Проверка существования таблицы"""
    inspector = inspect(session.bind)
    tables = inspector.get_table_names()
    return table_name in tables

def migration_add_staking_history_fields(session):
    """Добавление полей в StakingHistory"""
    logging.info("🔄 Миграция: Обновление StakingHistory...")

    fields_to_add = {
        'lock_type': "TEXT",
        'stable_since': "DATETIME",
        'last_apr_change': "DATETIME",
        'previous_apr': "REAL",
        'notification_sent_at': "DATETIME",
        'is_notification_pending': "INTEGER DEFAULT 0"
    }

    added_count = 0
    for field_name, field_type in fields_to_add.items():
        if not check_column_exists(session, 'staking_history', field_name):
            query = f"ALTER TABLE staking_history ADD COLUMN {field_name} {field_type}"
            session.execute(text(query))
            logging.info(f"  ✅ Добавлено поле: {field_name}")
            added_count += 1
        else:
            logging.info(f"  ℹ️ Поле {field_name} уже существует")

    if added_count > 0:
        session.commit()
        logging.info(f"✅ StakingHistory: добавлено {added_count} полей")
    else:
        logging.info("✅ StakingHistory: все поля уже существуют")

    return added_count

def migration_add_api_link_fields(session):
    """Добавление полей настроек уведомлений в ApiLink"""
    logging.info("🔄 Миграция: Обновление ApiLink...")

    fields_to_add = {
        'notify_new_stakings': "INTEGER DEFAULT 1",
        'notify_apr_changes': "INTEGER DEFAULT 1",
        'notify_fill_changes': "INTEGER DEFAULT 0",
        'notify_min_apr_change': "REAL DEFAULT 5.0",
        'flexible_stability_hours': "INTEGER DEFAULT 6",
        'fixed_notify_immediately': "INTEGER DEFAULT 1",
        'notify_only_stable_flexible': "INTEGER DEFAULT 1",
        'notify_combined_as_fixed': "INTEGER DEFAULT 1",
        'last_notification_sent': "DATETIME"
    }

    added_count = 0
    for field_name, field_type in fields_to_add.items():
        if not check_column_exists(session, 'api_links', field_name):
            query = f"ALTER TABLE api_links ADD COLUMN {field_name} {field_type}"
            session.execute(text(query))
            logging.info(f"  ✅ Добавлено поле: {field_name}")
            added_count += 1
        else:
            logging.info(f"  ℹ️ Поле {field_name} уже существует")

    if added_count > 0:
        session.commit()
        logging.info(f"✅ ApiLink: добавлено {added_count} полей")
    else:
        logging.info("✅ ApiLink: все поля уже существуют")

    return added_count

def migration_create_user_link_subscription_table(session):
    """Создание таблицы UserLinkSubscription"""
    logging.info("🔄 Миграция: Создание таблицы user_link_subscriptions...")

    if check_table_exists(session, 'user_link_subscriptions'):
        logging.info("✅ Таблица user_link_subscriptions уже существует")
        return False

    create_table_query = """
    CREATE TABLE user_link_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        api_link_id INTEGER NOT NULL,
        notify_new INTEGER DEFAULT 1,
        notify_apr_changes INTEGER DEFAULT 1,
        notify_fill_changes INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (api_link_id) REFERENCES api_links(id),
        UNIQUE (user_id, api_link_id)
    )
    """

    session.execute(text(create_table_query))
    session.commit()
    logging.info("✅ Таблица user_link_subscriptions создана")
    return True

def run_migration():
    """Запуск всех миграций"""
    logging.info("=" * 60)
    logging.info("🚀 МИГРАЦИЯ 010: Система умных уведомлений")
    logging.info("=" * 60)

    engine = get_engine()
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Миграция 1: StakingHistory
        staking_added = migration_add_staking_history_fields(session)

        # Миграция 2: ApiLink
        api_link_added = migration_add_api_link_fields(session)

        # Миграция 3: UserLinkSubscription
        table_created = migration_create_user_link_subscription_table(session)

        logging.info("=" * 60)
        logging.info("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
        logging.info(f"   - StakingHistory: {staking_added} новых полей")
        logging.info(f"   - ApiLink: {api_link_added} новых полей")
        logging.info(f"   - UserLinkSubscription: {'создана' if table_created else 'уже существует'}")
        logging.info("=" * 60)

        return True

    except Exception as e:
        logging.error(f"❌ Ошибка миграции: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    try:
        run_migration()
        logging.info("🎉 Миграция выполнена без ошибок")
        sys.exit(0)
    except Exception as e:
        logging.error(f"💥 Критическая ошибка: {e}")
        sys.exit(1)
