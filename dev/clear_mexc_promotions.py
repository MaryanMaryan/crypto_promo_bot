"""
Скрипт для очистки промоакций MEXC из базы данных
"""
import sys
import os
import io

# Фиксим кодировку для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import get_db_session
from data.models import ApiLink, PromoHistory

def clear_mexc_promotions():
    """Удаляет все промоакции MEXC из базы данных"""

    mexc_url = "https://www.mexc.com/api/operateactivity/eftd/list"

    print("=" * 80)
    print("ОЧИСТКА ПРОМОАКЦИЙ MEXC")
    print("=" * 80)
    print(f"\nURL для очистки: {mexc_url}\n")

    with get_db_session() as db:
        # Находим ссылку MEXC
        link = db.query(ApiLink).filter(ApiLink.url == mexc_url).first()

        if not link:
            print("❌ Ссылка MEXC не найдена в базе данных!")
            print("\nДоступные ссылки:")
            all_links = db.query(ApiLink).all()
            for l in all_links:
                print(f"  - {l.name}: {l.url}")
            return

        print(f"✅ Найдена ссылка: {link.name} (ID: {link.id})")

        # Подсчитываем промоакции
        mexc_promotions = db.query(PromoHistory).filter(PromoHistory.api_link_id == link.id).all()
        count = len(mexc_promotions)

        print(f"\nНайдено промоакций для удаления: {count}")

        if count == 0:
            print("\n✅ База данных уже чистая!")
            return

        # Показываем первые 10 для подтверждения
        print("\nПримеры промоакций для удаления:")
        for i, promo in enumerate(mexc_promotions[:10], 1):
            print(f"  {i}. {promo.title} (ID: {promo.promo_id})")

        if count > 10:
            print(f"  ... и ещё {count - 10} промоакций")

        # Запрашиваем подтверждение
        print(f"\n⚠️  ВНИМАНИЕ: Будет удалено {count} промоакций!")

        # Проверяем аргументы командной строки
        import sys
        auto_confirm = '--yes' in sys.argv or '-y' in sys.argv

        if not auto_confirm:
            confirm = input("Продолжить? (да/нет): ").strip().lower()
            if confirm not in ['да', 'yes', 'y', 'д']:
                print("\n❌ Отменено пользователем")
                return
        else:
            print("Автоматическое подтверждение (--yes)")

        # Удаляем промоакции
        print("\n🗑️  Удаление промоакций...")
        for promo in mexc_promotions:
            db.delete(promo)

        db.commit()

        print(f"\n✅ Успешно удалено {count} промоакций MEXC!")
        print("\nТеперь можете запустить принудительную проверку в боте")
        print("=" * 80)

if __name__ == "__main__":
    clear_mexc_promotions()
