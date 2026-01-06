#!/usr/bin/env python3
"""
Скрипт для обновления номера телефона в Telegram настройках
"""

from datetime import datetime
from data.database import get_db_session
from data.models import TelegramSettings

def update_phone_number(new_phone: str):
    """Обновление номера телефона в базе данных"""
    try:
        with get_db_session() as db:
            settings = db.query(TelegramSettings).first()

            if settings:
                old_phone = settings.phone_number
                settings.phone_number = new_phone
                settings.last_auth = datetime.utcnow()
                settings.updated_at = datetime.utcnow()
                db.commit()

                print(f"OK Nomer telefona obnoven:")
                print(f"   Staryy: {old_phone}")
                print(f"   Novyy: {new_phone}")
                print(f"   API ID: {settings.api_id}")
                print(f"   Sessiya: {settings.session_file}")
                return True
            else:
                print("ERROR Nastroyki Telegram ne naydeny v BD")
                return False

    except Exception as e:
        print(f"ERROR Oshibka obnovleniya: {e}")
        return False

if __name__ == "__main__":
    NEW_PHONE = "+27 65 736 1808"

    print("=" * 60)
    print("Obnovlenie nomera telefona")
    print("=" * 60)
    print(f"\nNovyy nomer: {NEW_PHONE}")

    if update_phone_number(NEW_PHONE):
        print("\nOK Nomer uspeshno obnoven!")
        print("\nBot teper budet ispolzovat novyy nomer")
    else:
        print("\nERROR Ne udalos obnovit nomer")
