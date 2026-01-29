#!/usr/bin/env python3
"""Миграция БД: добавление колонок для настроек Launchpool"""

import sqlite3

conn = sqlite3.connect("data/database.db")
cursor = conn.cursor()

columns_to_add = [
    ("lp_min_pool_usd", "REAL DEFAULT 0"),
    ("lp_min_apr", "REAL DEFAULT 0"),
    ("lp_notify_hours_before_end", "INTEGER DEFAULT 0"),
    ("lp_stake_coins_filter", "TEXT DEFAULT '[]'"),
    ("lp_min_user_limit_usd", "REAL DEFAULT 0")
]

for col_name, col_type in columns_to_add:
    try:
        cursor.execute(f"ALTER TABLE api_links ADD COLUMN {col_name} {col_type}")
        print(f"✅ Добавлена колонка: {col_name}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"⏭️ Колонка {col_name} уже существует")
        else:
            print(f"❌ Ошибка {col_name}: {e}")

conn.commit()
conn.close()
print("✅ Миграция завершена")
