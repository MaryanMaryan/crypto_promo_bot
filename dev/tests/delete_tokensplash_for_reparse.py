"""
Скрипт для удаления токенсплешей из базы данных, чтобы бот заново их спарсил с новым форматированием
"""

import sqlite3
from pathlib import Path

# Путь к базе данных
DB_PATH = Path(__file__).parent / "data" / "database.db"

def get_tokensplash_samples():
    """Получает примеры токенсплешей из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("=" * 70)
    print("🔍 ПОИСК ТОКЕНСПЛЕШЕЙ В БАЗЕ ДАННЫХ")
    print("=" * 70)
    
    # Ищем токенсплеши Bybit
    cursor.execute("""
        SELECT promo_id, title, award_token, total_prize_pool, 
               participants_count, winners_count, 
               start_time, end_time, link
        FROM promo_history 
        WHERE exchange = 'Bybit' 
        AND promo_id LIKE 'bybit_%'
        AND (promo_id NOT LIKE '%launchpool%')
        ORDER BY created_at DESC
        LIMIT 20
    """)
    
    rows = cursor.fetchall()
    
    if not rows:
        print("❌ Токенсплеши не найдены в базе данных")
        conn.close()
        return []
    
    print(f"✅ Найдено {len(rows)} токенсплешей\n")
    
    samples = []
    for i, row in enumerate(rows, 1):
        promo_id, title, token, prize_pool, participants, winners, start_time, end_time, link = row
        print(f"{i}. {promo_id}")
        print(f"   Название: {title}")
        print(f"   Токен: {token}")
        print(f"   Призовой фонд: {prize_pool}")
        print(f"   Участники: {participants}")
        print(f"   Призовые места: {winners}")
        print()
        
        samples.append(promo_id)
    
    conn.close()
    return samples

def delete_tokensplash(promo_id):
    """Удаляет токенсплеш из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем существование
    cursor.execute("SELECT title FROM promo_history WHERE promo_id = ?", (promo_id,))
    row = cursor.fetchone()
    
    if not row:
        print(f"❌ Токенсплеш {promo_id} не найден в базе данных")
        conn.close()
        return False
    
    title = row[0]
    
    # Удаляем
    cursor.execute("DELETE FROM promo_history WHERE promo_id = ?", (promo_id,))
    conn.commit()
    
    print(f"✅ Удалён токенсплеш: {title} ({promo_id})")
    
    conn.close()
    return True

def main():
    print("\n" + "=" * 70)
    print("🗑️  УДАЛЕНИЕ ТОКЕНСПЛЕШЕЙ ДЛЯ ПОВТОРНОГО ПАРСИНГА")
    print("=" * 70 + "\n")
    
    # Получаем список токенсплешей
    samples = get_tokensplash_samples()
    
    if not samples:
        return
    
    print("=" * 70)
    print("📌 ВЫБОР ТОКЕНСПЛЕШЕЙ ДЛЯ УДАЛЕНИЯ")
    print("=" * 70)
    
    # Пытаемся найти разные типы токенсплешей
    # Для упрощения просто удалим первые 3
    to_delete = samples[:min(3, len(samples))]
    
    print(f"\n🎯 Будут удалены следующие токенсплеши:")
    for promo_id in to_delete:
        print(f"   • {promo_id}")
    
    # Запрашиваем подтверждение
    print(f"\n⚠️  Это действие нельзя отменить!")
    confirmation = input("Продолжить? (yes/no): ").strip().lower()
    
    if confirmation not in ['yes', 'y', 'да', 'д']:
        print("❌ Операция отменена")
        return
    
    # Удаляем
    print("\n" + "=" * 70)
    print("🗑️  УДАЛЕНИЕ...")
    print("=" * 70 + "\n")
    
    deleted = 0
    for promo_id in to_delete:
        if delete_tokensplash(promo_id):
            deleted += 1
    
    print("\n" + "=" * 70)
    print(f"✅ УСПЕШНО УДАЛЕНО: {deleted} из {len(to_delete)} токенсплешей")
    print("=" * 70)
    
    print("\n💡 Теперь запустите бота, и он заново спарсит эти промоакции с новым форматированием!")
    print("   Команда: python main.py")

if __name__ == "__main__":
    main()
