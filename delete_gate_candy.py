"""
Удаляет существующие Gate Candy промоакции из БД,
чтобы при следующем парсинге они сохранились с правильными периодами
"""
import sys
import os

sys.path.insert(0, os.path.abspath('.'))

from data.database import init_database, get_db_session
from data.models import PromoHistory

init_database()

print("=" * 80)
print("УДАЛЕНИЕ GATE CANDY ПРОМОАКЦИЙ ИЗ БД")
print("=" * 80)

with get_db_session() as db:
    # Находим все Gate Candy промоакции
    gate_promos = db.query(PromoHistory).filter(
        PromoHistory.exchange == 'GateCandy'
    ).all()
    
    print(f"\nНайдено промоакций GateCandy: {len(gate_promos)}")
    
    if gate_promos:
        print("\nУдаляемые промоакции:")
        for promo in gate_promos:
            print(f"  - {promo.promo_id}: {promo.title}")
        
        # Удаляем
        for promo in gate_promos:
            db.delete(promo)
        
        db.commit()
        print(f"\n✅ Удалено {len(gate_promos)} промоакций")
        print("\n⚠️ ВАЖНО: Теперь выполните принудительную проверку GateCandy в боте,")
        print("   чтобы промоакции сохранились заново с правильными датами!")
    else:
        print("\n✅ Промоакции GateCandy не найдены в БД")

print("\n" + "=" * 80)
