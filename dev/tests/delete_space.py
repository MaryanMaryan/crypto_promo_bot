import sqlite3

conn = sqlite3.connect('data/database.db')
cur = conn.cursor()

# Удаляем SPACE промоакции
cur.execute("DELETE FROM promo_history WHERE promo_id IN ('bitget_candybomb_233015', 'bitget_candybomb_233016')")
deleted = cur.rowcount
conn.commit()

print(f"Удалено промоакций SPACE: {deleted}")

conn.close()
