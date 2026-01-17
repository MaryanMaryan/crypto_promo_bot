"""Скрипт для диагностики дублирования уведомлений Binance"""
from data.database import get_db_session, init_database
from data.models import StakingHistory
from datetime import datetime, timedelta

init_database()

with get_db_session() as session:
    print("=== Последние 30 Binance стейкингов в БД ===\n")
    binance_stakings = session.query(StakingHistory).filter(
        StakingHistory.exchange == 'Binance'
    ).order_by(StakingHistory.first_seen.desc()).limit(30).all()
    
    for s in binance_stakings:
        print(f"ID: {s.id}")
        print(f"  Coin: {s.coin} -> Reward: {s.reward_coin or 'same'}")
        print(f"  APR: {s.apr}%")
        print(f"  Type: {s.type}")
        print(f"  product_id: {s.product_id}")
        print(f"  First seen: {s.first_seen}")
        print(f"  Last updated: {s.last_updated}")
        print(f"  Notification sent: {s.notification_sent}")
        print(f"  lock_type: {s.lock_type}, is_pending: {s.is_notification_pending}")
        print("-" * 60)
    
    print(f"\n=== Статистика ===")
    total_binance = session.query(StakingHistory).filter(StakingHistory.exchange == 'Binance').count()
    print(f"Всего Binance записей: {total_binance}")
    
    # Проверяем на дубликаты product_id
    from sqlalchemy import func
    dups = session.query(
        StakingHistory.product_id,
        func.count(StakingHistory.id).label('count')
    ).filter(
        StakingHistory.exchange == 'Binance'
    ).group_by(
        StakingHistory.product_id
    ).having(
        func.count(StakingHistory.id) > 1
    ).all()
    
    if dups:
        print(f"\n⚠️ НАЙДЕНЫ ДУБЛИКАТЫ product_id:")
        for dup in dups:
            print(f"  {dup[0]}: {dup[1]} записей")
    else:
        print("\n✅ Дубликаты product_id не найдены")
    
    # Проверяем записи за последние 24 часа
    since = datetime.utcnow() - timedelta(hours=24)
    recent = session.query(StakingHistory).filter(
        StakingHistory.exchange == 'Binance',
        StakingHistory.first_seen >= since
    ).all()
    
    print(f"\n=== Новые записи за последние 24 часа: {len(recent)} ===")
    for s in recent:
        print(f"  {s.coin} | APR: {s.apr}% | {s.type} | {s.product_id} | notified: {s.notification_sent}")
    
    # Проверяем USDC -> SUI стейкинг
    print("\n=== Поиск USDC -> SUI стейкинга ===")
    usdc_sui = session.query(StakingHistory).filter(
        StakingHistory.exchange == 'Binance',
        StakingHistory.coin == 'USDC'
    ).all()
    
    for s in usdc_sui:
        print(f"  {s.coin} -> {s.reward_coin} | APR: {s.apr}% | {s.type} | product_id: {s.product_id}")
        print(f"  Created: {s.created_at} | notified: {s.notification_sent}")
