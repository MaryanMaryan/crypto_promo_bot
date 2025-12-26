"""
Конфигурация приложения
Загружается из .env файла через python-dotenv
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')

# Определяем корневую директорию проекта
BASE_DIR = Path(__file__).resolve().parent

# Загружаем переменные окружения из .env
env_path = BASE_DIR / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ Конфигурация загружена из: {env_path}")
else:
    print(f"⚠️ ВНИМАНИЕ: .env файл не найден по пути {env_path}")
    print(f"⚠️ Создайте .env файл на основе .env.example")

# =============================================================================
# TELEGRAM BOT CONFIGURATION
# =============================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# Валидация критичных переменных
if not BOT_TOKEN:
    raise ValueError(
        "❌ BOT_TOKEN не установлен!\n"
        "Создайте .env файл и добавьте: BOT_TOKEN=your_token_here"
    )

if not ADMIN_CHAT_ID:
    raise ValueError(
        "❌ ADMIN_CHAT_ID не установлен!\n"
        "Создайте .env файл и добавьте: ADMIN_CHAT_ID=your_chat_id"
    )

# Конвертируем ADMIN_CHAT_ID в int
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    raise ValueError(f"❌ ADMIN_CHAT_ID должен быть числом, получено: {ADMIN_CHAT_ID}")

print(f"🚀 Бот инициализирован: {BOT_TOKEN[:15]}...")
print(f"👤 Admin Chat ID: {ADMIN_CHAT_ID}")

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/database.db')

# =============================================================================
# PARSING CONFIGURATION
# =============================================================================
DEFAULT_CHECK_INTERVAL = int(os.getenv('DEFAULT_CHECK_INTERVAL', '300'))
MAX_CHECK_INTERVAL = int(os.getenv('MAX_CHECK_INTERVAL', '86400'))
MIN_CHECK_INTERVAL = int(os.getenv('MIN_CHECK_INTERVAL', '60'))

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# =============================================================================
# TELEGRAM PARSER CONFIGURATION
# =============================================================================
# ВАЖНО: Telegram API настройки теперь хранятся в БД (TelegramSettings)
# Настройте через бота: Меню → Обход блокировок → Telegram API
TELEGRAM_PARSER_ENABLED = os.getenv('TELEGRAM_PARSER_ENABLED', 'false').lower() == 'true'

# Legacy support (для обратной совместимости, если кто-то использует старый способ)
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

if TELEGRAM_PARSER_ENABLED:
    print(f"📡 Telegram Parser включен")
    if TELEGRAM_API_ID and TELEGRAM_API_HASH:
        print(f"⚠️  ВНИМАНИЕ: Используются устаревшие настройки из .env")
        print(f"⚠️  Рекомендуется настроить через бота: Обход блокировок → Telegram API")
    else:
        print(f"ℹ️  Настройте Telegram API через бота: Обход блокировок → Telegram API")
else:
    print(f"ℹ️ Telegram Parser отключен (TELEGRAM_PARSER_ENABLED=false)")
