"""
Миграция: Переименование категории 'general' в 'launches'

Эта миграция обновляет все существующие записи в БД,
где category = 'general', заменяя на 'launches'.

Запуск: python migrate_general_to_launches.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.database import get_db_session
from data.models import ApiLink
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_general_to_launches():
    """Мигрирует категорию 'general' в 'launches'"""
    print("🚀 Миграция категорий: general → launches")
    print("=" * 50)
    
    with get_db_session() as db:
        # Находим все записи с category = 'general' или NULL
        general_links = db.query(ApiLink).filter(
            (ApiLink.category == 'general') | (ApiLink.category == None)
        ).all()
        
        if not general_links:
            print("✅ Записей для миграции не найдено")
            return
        
        print(f"📝 Найдено {len(general_links)} записей для миграции:\n")
        
        for link in general_links:
            old_category = link.category or 'NULL'
            print(f"  • [{link.id}] {link.name}: '{old_category}' → 'launches'")
            link.category = 'launches'
        
        db.commit()
        print(f"\n✅ Успешно мигрировано {len(general_links)} записей!")


def rollback_launches_to_general():
    """Откатывает миграцию (если нужно)"""
    print("⏪ Откат миграции: launches → general")
    print("=" * 50)
    
    with get_db_session() as db:
        launches_links = db.query(ApiLink).filter(
            ApiLink.category == 'launches'
        ).all()
        
        if not launches_links:
            print("✅ Записей для отката не найдено")
            return
        
        print(f"📝 Найдено {len(launches_links)} записей для отката:\n")
        
        for link in launches_links:
            print(f"  • [{link.id}] {link.name}: 'launches' → 'general'")
            link.category = 'general'
        
        db.commit()
        print(f"\n✅ Успешно откачено {len(launches_links)} записей!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Миграция категорий general → launches')
    parser.add_argument('--rollback', action='store_true', 
                        help='Откатить миграцию (launches → general)')
    args = parser.parse_args()
    
    if args.rollback:
        rollback_launches_to_general()
    else:
        migrate_general_to_launches()
