import sys
sys.path.insert(0, '.')

from data.database import get_db_session
from data.models import StakingHistory
from sqlalchemy import and_

with get_db_session() as session:
    full_stakings = session.query(StakingHistory).filter(
        and_(
            StakingHistory.fill_percentage != None,
            StakingHistory.fill_percentage >= 95.0
        )
    ).all()
    
    print(f'Found {len(full_stakings)} stakings with 95+ percent fill')
    
    for staking in full_stakings:
        staking.status = 'Sold Out'
        print(f'  Updated: {staking.exchange} | {staking.coin} | {staking.apr} percent APR')
    
    session.commit()
    
    print(f'\nOK: Updated {len(full_stakings)} stakings to Sold Out status')
