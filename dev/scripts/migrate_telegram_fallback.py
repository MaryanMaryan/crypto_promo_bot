"""
Миграция БД для добавления fallback системы Telegram аккаунтов

Добавляет:
1. Поля is_blocked, blocked_at, blocked_reason в telegram_accounts
2. Поле telegram_account_id в api_links
"""
import sqlite3
import os
import sys
from datetime import datetime

# Добавляем корневую директорию в путь для импортов
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Путь к БД
DB_FILE = 'data/database.db'

def migrate():
    """Выполнить миграцию БД"""
    print("=" * 60)
    print("МИГРАЦИЯ: Telegram Fallback система")
    print("=" * 60)
    print()

    if not os.path.exists(DB_FILE):
        print(f"[ERROR] База данных не найдена: {DB_FILE}")
        return False

    # Создаем backup
    backup_file = f"{DB_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"[BACKUP] Создание backup: {backup_file}")

    try:
        import shutil
        shutil.copy2(DB_FILE, backup_file)
        print("[OK] Backup создан успешно")
        print()
    except Exception as e:
        print(f"[ERROR] Ошибка создания backup: {e}")
        return False

    # Подключаемся к БД
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 1. Проверяем, существует ли таблица telegram_accounts
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_accounts'")
        if not cursor.fetchone():
            print("[WARN] Таблица telegram_accounts не найдена. Создаем...")
            # Если таблицы нет, создаем её с нуля с новыми полями
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telegram_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR NOT NULL,
                    phone_number VARCHAR NOT NULL UNIQUE,
                    session_file VARCHAR NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    is_authorized BOOLEAN DEFAULT 0,
                    last_used DATETIME,
                    added_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    messages_parsed INTEGER DEFAULT 0,
                    channels_monitored INTEGER DEFAULT 0,
                    last_error TEXT,
                    is_blocked BOOLEAN DEFAULT 0,
                    blocked_at DATETIME,
                    blocked_reason VARCHAR
                )
            """)
            print("[OK] Таблица telegram_accounts создана")
        else:
            print("[INFO] Таблица telegram_accounts существует")

            # Проверяем и добавляем поля is_blocked, blocked_at, blocked_reason
            cursor.execute("PRAGMA table_info(telegram_accounts)")
            columns = [col[1] for col in cursor.fetchall()]

            fields_to_add = [
                ('is_blocked', 'BOOLEAN DEFAULT 0'),
                ('blocked_at', 'DATETIME'),
                ('blocked_reason', 'VARCHAR')
            ]

            for field_name, field_type in fields_to_add:
                if field_name not in columns:
                    print(f"   [+] Добавление поля {field_name}...")
                    cursor.execute(f"ALTER TABLE telegram_accounts ADD COLUMN {field_name} {field_type}")
                    print(f"   [OK] Поле {field_name} добавлено")
                else:
                    print(f"   [SKIP] Поле {field_name} уже существует")

        print()

        # 2. Проверяем и добавляем поле telegram_account_id в api_links
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_links'")
        if cursor.fetchone():
            print("[INFO] Таблица api_links существует")

            cursor.execute("PRAGMA table_info(api_links)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'telegram_account_id' not in columns:
                print("   [+] Добавление поля telegram_account_id...")
                cursor.execute("ALTER TABLE api_links ADD COLUMN telegram_account_id INTEGER REFERENCES telegram_accounts(id)")
                print("   [OK] Поле telegram_account_id добавлено")
            else:
                print("   [SKIP] Поле telegram_account_id уже существует")
        else:
            print("[WARN] Таблица api_links не найдена")

        print()

        # 3. Применяем изменения
        conn.commit()
        print("[COMMIT] Изменения сохранены в БД")
        print()

        # 4. Показываем статистику
        print("[STATS] Статистика после миграции:")

        cursor.execute("SELECT COUNT(*) FROM telegram_accounts")
        accounts_count = cursor.fetchone()[0]
        print(f"   - Telegram аккаунтов: {accounts_count}")

        cursor.execute("SELECT COUNT(*) FROM api_links WHERE parsing_type='telegram'")
        telegram_links_count = cursor.fetchone()[0]
        print(f"   - Telegram ссылок: {telegram_links_count}")

        cursor.execute("SELECT COUNT(*) FROM api_links WHERE telegram_account_id IS NOT NULL")
        assigned_links_count = cursor.fetchone()[0]
        print(f"   - Ссылок с назначенным аккаунтом: {assigned_links_count}")

        print()
        print("=" * 60)
        print("[SUCCESS] МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 60)
        print()
        print("[INFO] Следующие шаги:")
        print("   1. Запустите бота: python main.py")
        print("   2. Проверьте, что Telegram ссылки работают")
        print("   3. При необходимости назначьте аккаунты вручную через UI")
        print()

        return True

    except Exception as e:
        print()
        print("=" * 60)
        print("[ERROR] ОШИБКА МИГРАЦИИ!")
        print("=" * 60)
        print(f"Ошибка: {e}")
        print()
        print(f"Вы можете восстановить БД из backup:")
        print(f"   copy {backup_file} {DB_FILE}")
        conn.rollback()
        return False

    finally:
        conn.close()

if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
