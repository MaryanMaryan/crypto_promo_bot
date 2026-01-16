"""
Скрипт для проверки синхронизации Bybit с БД
Сравнивает текущие промоакции с API с данными в БД
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import sqlite3
from parsers.universal_parser import UniversalParser

def verify_bybit_sync():
    """Проверка синхронизации Bybit"""
    print("\n" + "="*80)
    print("ПРОВЕРКА СИНХРОНИЗАЦИИ BYBIT")
    print("="*80 + "\n")

    # 1. Получаем текущие промоакции из API
    url = "https://www.bybit.com/x-api/spot/api/deposit-activity/v2/project/ongoing/projectList"
    parser = UniversalParser(url)

    print("Шаг 1: Получение текущих промоакций из API Bybit...")
    api_promos = parser.get_promotions()
    api_ids = {promo['promo_id'] for promo in api_promos}

    print(f"Найдено промоакций в API: {len(api_promos)}")
    for promo in api_promos:
        print(f"  - {promo['title']} ({promo['promo_id']})")

    # 2. Получаем промоакции из БД
    print(f"\nШаг 2: Проверка БД...")
    conn = sqlite3.connect('data/database.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT promo_id, title
        FROM promo_history
        WHERE api_link_id = 3
        AND promo_id LIKE 'bybit_202601%'
        ORDER BY created_at DESC
    ''')

    db_promos = cursor.fetchall()
    db_ids = {promo[0] for promo in db_promos}

    print(f"Найдено промоакций в БД (январь 2026): {len(db_promos)}")
    for promo in db_promos[:10]:
        print(f"  - {promo[1]} ({promo[0]})")

    # 3. Сравнение
    print(f"\nШаг 3: Сравнение...")
    print("-"*80)

    missing_in_db = api_ids - db_ids
    extra_in_db = db_ids - api_ids
    synced = api_ids & db_ids

    print(f"✅ Синхронизированных: {len(synced)}")
    print(f"❌ Отсутствуют в БД: {len(missing_in_db)}")
    print(f"⚠️ Устарели в БД: {len(extra_in_db)}")

    if missing_in_db:
        print("\nПромоакции, которых НЕТ в БД:")
        for promo_id in missing_in_db:
            promo = next(p for p in api_promos if p['promo_id'] == promo_id)
            print(f"  - {promo['title']} ({promo_id})")

    if extra_in_db:
        print("\nУстаревшие промоакции в БД (их нет в API):")
        for promo_id in extra_in_db:
            promo = next(p for p in db_promos if p[0] == promo_id)
            print(f"  - {promo[1]} ({promo_id})")

    # 4. Заключение
    print("\n" + "="*80)
    if len(missing_in_db) == 0:
        print("✅ СТАТУС: ВСЕ ПРОМОАКЦИИ СИНХРОНИЗИРОВАНЫ")
        print("Парсинг Bybit работает корректно!")
        print("Новых промоакций нет, поэтому бот не отправил уведомления.")
    else:
        print("⚠️ СТАТУС: ТРЕБУЕТСЯ СИНХРОНИЗАЦИЯ")
        print(f"Найдено {len(missing_in_db)} новых промоакций")
    print("="*80 + "\n")

    conn.close()
    return len(missing_in_db)

if __name__ == "__main__":
    missing = verify_bybit_sync()
    sys.exit(0 if missing == 0 else 1)
