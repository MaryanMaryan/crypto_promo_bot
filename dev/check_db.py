"""Проверка данных в БД"""
import sys
import json
from data.database import init_database, get_db_session, ApiLink, PromoHistory

def check_okx_links():
    """Проверяет все ссылки OKX в БД"""
    init_database()

    with get_db_session() as db:
        # Ищем все ссылки, связанные с OKX
        links = db.query(ApiLink).filter(
            (ApiLink.name.like('%OKX%')) |
            (ApiLink.name.like('%okx%')) |
            (ApiLink.url.like('%okx%'))
        ).all()

        print(f"\n{'='*80}")
        print(f"Найдено {len(links)} ссылок для OKX:")
        print(f"{'='*80}\n")

        for link in links:
            print(f"ID: {link.id}")
            print(f"Название: {link.name}")
            print(f"URL (основной): {link.url}")
            print(f"API URL (новое поле): {link.api_url}")
            print(f"HTML URL (новое поле): {link.html_url}")
            print(f"API URLs (legacy): {link.api_urls}")
            print(f"HTML URLs (legacy): {link.html_urls}")
            print(f"Активна: {link.is_active}")
            print(f"Интервал проверки: {link.check_interval} сек")
            print(f"Последняя проверка: {link.last_checked}")
            print(f"\nРаспарсенные URL:")
            print(f"  - Основной API URL: {link.get_primary_api_url()}")
            print(f"  - Основной HTML URL: {link.get_primary_html_url()}")
            print(f"  - Все API URLs: {link.get_api_urls()}")
            print(f"  - Все HTML URLs: {link.get_html_urls()}")
            print(f"  - Legacy данные: {link.has_legacy_data()}")

            # Проверяем промоакции для этой ссылки
            promos = db.query(PromoHistory).filter(PromoHistory.api_link_id == link.id).all()
            print(f"\nПромоакций в истории: {len(promos)}")
            if promos:
                print("Последние 3 промоакции:")
                for promo in promos[-3:]:
                    print(f"  - {promo.title} (promo_id: {promo.promo_id})")
                    print(f"    total_prize_pool: {promo.total_prize_pool}")
                    print(f"    award_token: {promo.award_token}")
                    print(f"    link: {promo.link}")

            print(f"\n{'='*80}\n")

if __name__ == '__main__':
    check_okx_links()
