"""
Исправление поля exchange для OKX EARN
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from data.database import get_db_session, ApiLink

def fix_okx_earn():
    """Исправить поле exchange для OKX EARN"""
    with get_db_session() as db:
        link = db.query(ApiLink).filter(ApiLink.id == 11).first()

        if not link:
            print("OKX EARN (ID 11) не найдена")
            return

        print("=" * 80)
        print("ИСПРАВЛЕНИЕ OKX EARN")
        print("=" * 80)
        print(f"\nID: {link.id}")
        print(f"Название: {link.name}")
        print(f"Категория: {link.category}")
        print(f"\nСТАРОЕ значение exchange: '{link.exchange}'")

        # Устанавливаем правильное значение
        link.exchange = 'OKX'

        print(f"НОВОЕ значение exchange: '{link.exchange}'")

        db.commit()

        print("\n" + "=" * 80)
        print("[OK] Поле 'exchange' успешно обновлено на 'OKX'!")
        print("=" * 80)
        print("\nТеперь перезапустите бота и попробуйте снова проверить OKX EARN")

if __name__ == "__main__":
    fix_okx_earn()
