# В config.py ЗАМЕНИТЕ весь код на:
import os

# ПРИНУДИТЕЛЬНО НОВЫЙ ТОКЕН
BOT_TOKEN = "8256535319:AAE5YfagYcC1RF7M77UaJf7wyReiAniRli8"
ADMIN_CHAT_ID = 7193869664

print(f"🚀 ЗАПУСК С НОВЫМ БОТОМ: {BOT_TOKEN[:15]}...")

# Остальные настройки
DATABASE_URL = "sqlite:///data/database.db"
DEFAULT_CHECK_INTERVAL = 300
MAX_CHECK_INTERVAL = 86400
MIN_CHECK_INTERVAL = 60
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"