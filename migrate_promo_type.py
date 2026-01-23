"""
Міграція: Заповнення promo_type на основі ApiLink.category

Заповнює поле promo_type в PromoHistory на основі категорії пов'язаного ApiLink.
Це потрібно для швидкої фільтрації промо по категоріях без JOIN.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'database.db')


def migrate_promo_type():
    """Заповнити promo_type на основі ApiLink.category"""
    
    print("=" * 60)
    print("МІГРАЦІЯ: Заповнення promo_type")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Маппінг категорій ApiLink -> promo_type
        category_mapping = {
            'airdrop': 'airdrop',
            'candybomb': 'candybomb',
            'launchpad': 'launchpad',
            'launchpool': 'launchpool',
            # Інші залишаємо як є або 'other'
        }
        
        # Статистика до міграції
        cursor.execute("""
            SELECT promo_type, COUNT(*) 
            FROM promo_history 
            GROUP BY promo_type
        """)
        print("\n📊 Статистика ДО міграції:")
        for row in cursor.fetchall():
            print(f"   {row[0] or 'NULL'}: {row[1]}")
        
        # Отримуємо промо з NULL promo_type та відповідні категорії ApiLink
        cursor.execute("""
            SELECT ph.id, al.category, al.name
            FROM promo_history ph
            LEFT JOIN api_links al ON ph.api_link_id = al.id
            WHERE ph.promo_type IS NULL
        """)
        
        rows = cursor.fetchall()
        print(f"\n🔍 Знайдено {len(rows)} промо без promo_type")
        
        # Оновлюємо promo_type
        updated_counts = {}
        for promo_id, category, api_name in rows:
            if category in category_mapping:
                new_type = category_mapping[category]
                cursor.execute(
                    "UPDATE promo_history SET promo_type = ? WHERE id = ?",
                    (new_type, promo_id)
                )
                updated_counts[new_type] = updated_counts.get(new_type, 0) + 1
            else:
                # Для невідомих категорій ставимо 'other'
                cursor.execute(
                    "UPDATE promo_history SET promo_type = 'other' WHERE id = ?",
                    (promo_id,)
                )
                updated_counts['other'] = updated_counts.get('other', 0) + 1
        
        conn.commit()
        
        print("\n✅ Оновлено promo_type:")
        for ptype, count in sorted(updated_counts.items()):
            print(f"   {ptype}: {count}")
        
        # Статистика після міграції
        cursor.execute("""
            SELECT promo_type, COUNT(*) 
            FROM promo_history 
            GROUP BY promo_type
        """)
        print("\n📊 Статистика ПІСЛЯ міграції:")
        for row in cursor.fetchall():
            print(f"   {row[0] or 'NULL'}: {row[1]}")
        
        print("\n✅ Міграція завершена успішно!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Помилка міграції: {e}")
        raise
    finally:
        conn.close()


def show_category_distribution():
    """Показати розподіл промо по категоріях з ApiLink"""
    
    print("\n" + "=" * 60)
    print("РОЗПОДІЛ ПРОМО ПО КАТЕГОРІЯХ")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                al.category,
                ph.promo_type,
                COUNT(*) as cnt
            FROM promo_history ph
            LEFT JOIN api_links al ON ph.api_link_id = al.id
            GROUP BY al.category, ph.promo_type
            ORDER BY al.category, cnt DESC
        """)
        
        results = cursor.fetchall()
        print("\n📊 ApiLink.category → promo_type:")
        for category, promo_type, count in results:
            print(f"   {category or 'NULL'} → {promo_type or 'NULL'}: {count}")
            
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"\n🕐 Запуск міграції: {datetime.now()}")
    
    # Показуємо поточний стан
    show_category_distribution()
    
    # Запускаємо міграцію
    migrate_promo_type()
    
    # Показуємо результат
    show_category_distribution()
