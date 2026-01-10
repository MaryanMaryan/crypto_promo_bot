"""
Скрипт для удаления неправильной ссылки OKX boost (ID 4)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from data.database import get_db_session, ApiLink, PromoHistory

def delete_okx_boost_link():
    """Удалить ссылку OKX boost (ID 4) и её промоакции"""

    link_id = 4  # ID неправильной ссылки OKX boost

    with get_db_session() as db:
        # Проверяем, существует ли ссылка
        link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

        if not link:
            print(f"Ссылка с ID {link_id} не найдена")
            return

        print(f"Найдена ссылка:")
        print(f"  ID: {link.id}")
        print(f"  Название: {link.name}")
        print(f"  Категория: {link.category}")
        print(f"  URL: {link.api_url or link.get_primary_api_url()}")

        # Проверяем, это действительно неправильная ссылка
        if link.category == 'staking':
            print(f"\nВНИМАНИЕ! Эта ссылка имеет категорию 'staking' - возможно это правильная ссылка!")
            print("Удаление отменено")
            return

        if 'boost' not in link.name.lower() and 'okx' not in link.name.lower():
            print(f"\nВНИМАНИЕ! Название ссылки не содержит 'boost' или 'okx'")
            print("Удаление отменено из соображений безопасности")
            return

        # Удаляем связанные промоакции
        promo_count = db.query(PromoHistory).filter(PromoHistory.api_link_id == link_id).count()
        if promo_count > 0:
            print(f"\nУдаление {promo_count} связанных промоакций...")
            db.query(PromoHistory).filter(PromoHistory.api_link_id == link_id).delete()

        # Удаляем саму ссылку
        print(f"Удаление ссылки ID {link_id}...")
        db.delete(link)
        db.commit()

        print(f"\n[OK] Ссылка '{link.name}' (ID {link_id}) успешно удалена!")
        print(f"[OK] Удалено промоакций: {promo_count}")

if __name__ == "__main__":
    print("=" * 80)
    print("УДАЛЕНИЕ НЕПРАВИЛЬНОЙ ССЫЛКИ OKX BOOST")
    print("=" * 80)
    print()

    answer = input("Вы уверены, что хотите удалить ссылку 'OKX boost' (ID 4)? (yes/no): ")

    if answer.lower() in ['yes', 'y', 'да']:
        delete_okx_boost_link()
    else:
        print("\nУдаление отменено")
