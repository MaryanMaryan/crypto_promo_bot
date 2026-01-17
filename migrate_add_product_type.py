"""
Миграция: Добавление поля product_type в таблицу staking_history
"""

import sqlite3
import os
from pathlib import Path

# Путь к базе данных
DB_PATH = Path(__file__).parent / 'data' / 'database.db'

def add_product_type_column():
    """Добавить поле product_type в staking_history"""
    
    if not DB_PATH.exists():
        print(f"❌ База данных не найдена: {DB_PATH}")
        return
    
    print(f"📁 Работаем с базой: {DB_PATH}")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Проверяем, существует ли поле
        cursor.execute("PRAGMA table_info(staking_history)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'product_type' in columns:
            print("✅ Поле product_type уже существует")
            conn.close()
            return
        
        # Добавляем поле
        print("➕ Добавляем поле product_type...")
        cursor.execute("""
            ALTER TABLE staking_history 
            ADD COLUMN product_type TEXT
        """)
        
        conn.commit()
        print("✅ Поле product_type успешно добавлено!")
        
        # Проверяем
        cursor.execute("PRAGMA table_info(staking_history)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"\n📋 Текущие поля в staking_history ({len(columns)}):")
        for col in columns:
            print(f"   - {col}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print('='*70)
    print('МИГРАЦИЯ: Добавление product_type')
    print('='*70)
    print()
    
    add_product_type_column()
    
    print()
    print('='*70)
    print('ГОТОВО!')
    print('='*70)
