import sqlite3

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# Смотрим таблицы
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print(f"Таблицы: {tables}")

# Ищем промо
for table in tables:
    try:
        cursor.execute(f"SELECT * FROM {table} WHERE promo_id = ?", ('mexc_airdrop_3183',))
        rows = cursor.fetchall()
        if rows:
            print(f"\nНайдено в таблице {table}: {len(rows)} записей")
            cursor.execute(f"DELETE FROM {table} WHERE promo_id = ?", ('mexc_airdrop_3183',))
            print(f"Удалено: {cursor.rowcount}")
    except Exception as e:
        pass

conn.commit()
conn.close()
print("\nГотово!")
