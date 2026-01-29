#!/usr/bin/env python3
"""Проверка и исправление USDT 600% стейкинга"""
import sys
sys.path.insert(0, '/opt/crypto_promo_bot')

from data.database import get_db_session
from data.models import StakingHistory

with get_db_session() as session:
    # Ищем USDT с высоким APR
    results = session.query(StakingHistory).filter(
        StakingHistory.exchange == 'Bybit',
        StakingHistory.coin == 'USDT',
        StakingHistory.apr >= 400
    ).all()
    
    print(f"Найдено {len(results)} записей USDT с APR >= 400%\n")
    
    for r in results:
        print(f"ID: {r.id}, product_id: {r.product_id}")
        print(f"  APR: {r.apr}%")
        print(f"  max_capacity: {r.max_capacity:,.0f}")
        print(f"  current_deposit: {r.current_deposit:,.0f}")
        
        # Если max_capacity > 100M - это старые данные, нужно делить на 1000
        if r.max_capacity and r.max_capacity > 100_000_000:
            new_max = r.max_capacity / 1000
            new_current = r.current_deposit / 1000 if r.current_deposit else 0
            print(f"  -> ИСПРАВЛЯЕМ!")
            print(f"     new_max: {new_max:,.0f}")
            print(f"     new_current: {new_current:,.0f}")
            r.max_capacity = new_max
            r.current_deposit = new_current
            if r.max_capacity > 0:
                r.fill_percentage = round((new_current / new_max) * 100, 2)
        print()
    
    session.commit()
    print("Готово!")
