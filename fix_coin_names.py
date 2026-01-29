"""
Скрипт для исправления названий монет в БД
"""
import sys
sys.path.insert(0, '.')

from data.database import get_db_session
from data.models import StakingHistory

# Маппинг для исправления
FIX_MAPPING = {
    'COIN_1099': 'IMU',
    'COIN_1098': 'ELSA',
    'COIN_858': 'XAUT',
}

def fix_coin_names():
    with get_db_session() as db:
        # Находим все записи с COIN_X
        stakings = db.query(StakingHistory).filter(StakingHistory.coin.like('COIN_%')).all()
        print(f'Found {len(stakings)} stakings with COIN_X names:')
        
        fixed = 0
        for s in stakings:
            old_name = s.coin
            if old_name in FIX_MAPPING:
                new_name = FIX_MAPPING[old_name]
                print(f'  Fixing: {old_name} -> {new_name} (ID={s.id}, product_id={s.product_id})')
                s.coin = new_name
                fixed += 1
            else:
                print(f'  Unknown: {old_name} (ID={s.id}, product_id={s.product_id})')
        
        if fixed > 0:
            db.commit()
            print(f'\n✅ Fixed {fixed} records')
        else:
            print('\n⚠️ No records to fix')

if __name__ == '__main__':
    fix_coin_names()
