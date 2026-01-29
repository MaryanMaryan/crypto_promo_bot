#!/usr/bin/env python3
"""
Полное обновление всех Bybit стейкингов с правильными decimals
"""
import sys
sys.path.insert(0, '/opt/crypto_promo_bot')

from data.database import get_db_session
from data.models import StakingHistory
from parsers.staking_parser import StakingParser

# Парсим свежие данные
print("Парсим свежие данные Bybit...")
parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)
stakings = parser.parse()
print(f"Получено {len(stakings)} стейкингов из API\n")

# Создаём словарь для быстрого поиска
api_data = {str(s.get('product_id')): s for s in stakings if s.get('product_id')}

with get_db_session() as session:
    # Получаем все Bybit записи
    db_records = session.query(StakingHistory).filter(
        StakingHistory.exchange == 'Bybit'
    ).all()
    
    print(f"Найдено {len(db_records)} записей Bybit в БД\n")
    
    updated = 0
    for r in db_records:
        product_id = str(r.product_id)
        
        if product_id in api_data:
            new_data = api_data[product_id]
            new_max = new_data.get('max_capacity')
            new_current = new_data.get('current_deposit')
            new_fill = new_data.get('fill_percentage')
            
            old_max = r.max_capacity or 0
            old_current = r.current_deposit or 0
            
            # Проверяем нужно ли обновлять
            if abs(old_max - new_max) > 1 or abs(old_current - new_current) > 1:
                print(f"Обновляем {r.coin} (product_id={product_id}):")
                print(f"  max: {old_max:,.0f} -> {new_max:,.0f}")
                print(f"  current: {old_current:,.0f} -> {new_current:,.0f}")
                
                r.max_capacity = new_max
                r.current_deposit = new_current
                r.fill_percentage = new_fill
                updated += 1
    
    session.commit()
    print(f"\nОбновлено {updated} записей")
    print("Готово!")
