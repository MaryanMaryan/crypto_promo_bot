#!/usr/bin/env python3
"""
Скрипт для настройки Telegram API credentials
"""

import sys
from datetime import datetime
from data.database import get_db_session
from data.models import TelegramSettings

def setup_telegram_credentials(api_id: str, api_hash: str, phone_number: str = None):
    """Сохранение Telegram API credentials в базу данных"""

    try:
        with get_db_session() as db:
            # Ищем существующие настройки
            settings = db.query(TelegramSettings).first()

            if settings:
                # Обновляем существующие
                settings.api_id = api_id
                settings.api_hash = api_hash
                if phone_number:
                    settings.phone_number = phone_number
                settings.is_configured = True
                settings.updated_at = datetime.utcnow()
                print(f"OK Obnovleny sushchestvuyushchie nastroyki Telegram API")
            else:
                # Создаем новые
                settings = TelegramSettings(
                    api_id=api_id,
                    api_hash=api_hash,
                    phone_number=phone_number,
                    session_file='telegram_parser_session',
                    is_configured=True
                )
                db.add(settings)
                print(f"OK Sozdany novye nastroyki Telegram API")

            db.commit()

            print(f"\nSohranennye dannye:")
            print(f"   API ID: {api_id}")
            print(f"   API Hash: {api_hash[:8]}...")
            if phone_number:
                print(f"   Telefon: {phone_number}")
            print(f"   Fayl sessii: telegram_parser_session")

            return True

    except Exception as e:
        print(f"ERROR Oshibka sohraneniya nastroyek: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Nastroyka Telegram API credentials")
    print("=" * 60)

    # Ваши данные из my.telegram.org
    API_ID = "26450551"
    API_HASH = "04afe3a811681b473ef58c1e5a52d9e8"
    PHONE = "+380 63 242 88 61"

    print(f"\nDannye dlya sohraneniya:")
    print(f"   API ID: {API_ID}")
    print(f"   API Hash: {API_HASH[:8]}...")
    print(f"   Telefon: {PHONE}")

    response = input("\nSohranit eti dannye? (y/n): ")

    if response.lower() in ['y', 'yes', 'д', 'да']:
        if setup_telegram_credentials(API_ID, API_HASH, PHONE):
            print("\nNastroyka zavershena uspeshno!")
            print("\nChto dalshe:")
            print("   1. Podozhdite 1-2 chasa (Telegram vremenno blokiruet posle neudachnyh popytok)")
            print("   2. Zapustite bota: python main.py")
            print("   3. Teper pri zaprose koda on dolzhen priyti ot Telegram")
            print("\nVazhno: vvodite kod TOCHNO kak poluchili (obychno 5 tsifr)")
        else:
            print("\nNe udalos sohranit nastroyki")
            sys.exit(1)
    else:
        print("\nOtmeneno polzovatelem")
        sys.exit(0)
