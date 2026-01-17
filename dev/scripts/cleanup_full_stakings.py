"""
Очистка 100% заполненных стейкингов из базы данных
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from data.database import get_db_session
from data.models import StakingHistory
from sqlalchemy import and_, or_

def cleanup_full_stakings():
    """Удаляет или деактивирует стейкинги с заполненностью >= 95%"""
    
    print("=" * 80)
    print("CLEANUP 95%+ FILLED STAKINGS")
    print("=" * 80)
    
    with get_db_session() as session:
        # Находим все стейкинги с заполненностью >= 95%
        full_stakings = session.query(StakingHistory).filter(
            and_(
                StakingHistory.fill_percentage != None,
                StakingHistory.fill_percentage >= 95.0
            )
        ).all()
        
        print(f"\nFound {len(full_stakings)} stakings with 95%+ fill")
        
        if not full_stakings:
            print("Nothing to cleanup!")
            return
        
        # Показываем что будет удалено
        print("\nStakings to update:")
        for s in full_stakings[:10]:  # Показываем первые 10
            print(f"  - {s.exchange} | {s.coin} | {s.apr}% APR | Fill: {s.fill_percentage}%")
        
        if len(full_stakings) > 10:
            print(f"  ... and {len(full_stakings) - 10} more")
        
        # Обновляем статус на "Sold Out" вместо удаления
        # Это безопаснее и сохраняет историю
        for staking in full_stakings:
            staking.status = 'Sold Out'
        
        session.commit()
        
        print(f"\n✅ Updated {len(full_stakings)} stakings to 'Sold Out' status")
        print("These stakings will now be filtered out from display")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    cleanup_full_stakings()
