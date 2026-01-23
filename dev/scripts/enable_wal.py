"""
Включение WAL режима для базы данных
"""
import sqlite3

db_path = 'data/database.db'

try:
    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()
    
    print("🔧 Включение WAL режима...")
    
    # Включаем WAL режим
    cursor.execute('PRAGMA journal_mode=WAL')
    result = cursor.fetchone()[0]
    print(f"✅ Journal Mode: {result}")
    
    # Устанавливаем busy_timeout
    cursor.execute('PRAGMA busy_timeout=60000')
    print(f"✅ Busy Timeout: 60000 мс (60 секунд)")
    
    conn.commit()
    conn.close()
    
    print("\n✅ WAL режим успешно включен!")
    print("Теперь база данных будет лучше работать при конкурентном доступе.")
    
except Exception as e:
    print(f"❌ Ошибка: {e}")
