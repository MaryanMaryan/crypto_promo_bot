#!/usr/bin/env python3
"""Реактивация существующих User-Agents"""

from data.database import get_db_session
from data.models import UserAgent

def main():
    print('\n' + '='*70)
    print('РЕАКТИВАЦИЯ USER-AGENTS')
    print('='*70 + '\n')

    with get_db_session() as db:
        # Находим все неактивные User-Agents с success_rate >= 10%
        inactive_uas = db.query(UserAgent).filter(
            UserAgent.status == 'inactive',
            UserAgent.success_rate >= 0.10
        ).all()

        print(f'Найдено неактивных User-Agents с success_rate >= 10%: {len(inactive_uas)}\n')

        reactivated = 0
        for ua in inactive_uas:
            ua.status = 'active'
            reactivated += 1
            print(f'[РЕАКТИВИРОВАН] ID={ua.id}, success_rate={ua.success_rate:.2%}, usage_count={ua.usage_count}')

        db.commit()

        # Статистика после реактивации
        total = db.query(UserAgent).count()
        active = db.query(UserAgent).filter_by(status='active').count()
        inactive = total - active

        print(f'\n' + '='*70)
        print(f'Реактивировано: {reactivated}')
        print(f'\nИТОГО User-Agents:')
        print(f'  Всего: {total}')
        print(f'  Активных: {active}')
        print(f'  Неактивных: {inactive}')
        print('='*70 + '\n')

if __name__ == '__main__':
    main()
