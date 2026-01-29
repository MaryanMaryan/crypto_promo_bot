#!/usr/bin/env python3
"""
Обновление данных Bybit в БД с правильными decimals
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
print(f"Получено {len(stakings)} стейкингов")

# Обновляем БД
with get_db_session() as session:
    for s in stakings:
        product_id = s.get('product_id')
        if not product_id:
            continue
        
        # Ищем запись в БД
        existing = session.query(StakingHistory).filter_by(
            exchange='Bybit',
            product_id=str(product_id)
        ).first()
        
        if existing:
            old_max = existing.max_capacity or 0
            new_max = s.get('max_capacity') or 0
            old_current = existing.current_deposit or 0
            new_current = s.get('current_deposit') or 0
            
            if old_max != new_max or old_current != new_current:
                print(f"Обновляем {existing.coin}:")
                print(f"  max_capacity: {old_max:,.0f} -> {new_max:,.0f}")
                print(f"  current_deposit: {old_current:,.0f} -> {new_current:,.0f}")
                
                existing.max_capacity = new_max
                existing.current_deposit = new_current
                existing.fill_percentage = s.get('fill_percentage')

    session.commit()
print("\nГотово!")
