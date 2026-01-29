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

# Список дополнительных админов (можно добавлять ID через запятую в .env или здесь напрямую)
ADDITIONAL_ADMINS = [5748499226, 7995846384]  # @sterline_cryptos

# Список получателей уведомлений о промоакциях (кроме основного ADMIN_CHAT_ID)
# Эти пользователи будут получать ВСЕ уведомления: автопроверка, принудительная проверка и т.д.
NOTIFICATION_RECIPIENTS = [7995846384]  # ID друзей, которые тоже получают уведомления

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

# Список всех админов (основной + дополнительные)
ADMIN_IDS = [ADMIN_CHAT_ID] + ADDITIONAL_ADMINS

# Все получатели уведомлений (админ + дополнительные)
ALL_NOTIFICATION_RECIPIENTS = [ADMIN_CHAT_ID] + NOTIFICATION_RECIPIENTS

print(f"🚀 Бот инициализирован: {BOT_TOKEN[:15]}...")
print(f"👤 Admin Chat ID: {ADMIN_CHAT_ID}")
print(f"👥 Всего админов: {len(ADMIN_IDS)} - {ADMIN_IDS}")
print(f"📬 Получатели уведомлений: {len(ALL_NOTIFICATION_RECIPIENTS)} - {ALL_NOTIFICATION_RECIPIENTS}")

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
# STAKING CONFIGURATION
# =============================================================================
# Максимальная заполненность пула (%) для отображения стейкингов
# Стейкинги с заполненностью выше этого порога не будут показываться
MAX_POOL_FILL_PERCENTAGE = float(os.getenv('MAX_POOL_FILL_PERCENTAGE', '90.0'))

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'
LOG_FILE_PATH = os.getenv('LOG_FILE_PATH', 'logs/bot.log')
LOG_MAX_SIZE_MB = int(os.getenv('LOG_MAX_SIZE_MB', '10'))  # Ротация при 10MB
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '5'))  # Хранить 5 старых файлов

# =============================================================================
# EXECUTOR CONFIGURATION (для параллельного парсинга)
# =============================================================================
EXECUTOR_MAX_WORKERS = int(os.getenv('EXECUTOR_MAX_WORKERS', '12'))  # Потоков для парсинга (12 для 4GB RAM)

# =============================================================================
# BROWSER POOL CONFIGURATION (пул переиспользуемых браузеров)
# =============================================================================
BROWSER_POOL_SIZE = int(os.getenv('BROWSER_POOL_SIZE', '2'))  # Количество браузеров в пуле (2 оптимально для 4GB + Playwright)
BROWSER_MAX_AGE_SECONDS = int(os.getenv('BROWSER_MAX_AGE_SECONDS', '1200'))  # Пересоздавать через 20 мин
BROWSER_MAX_REQUESTS = int(os.getenv('BROWSER_MAX_REQUESTS', '75'))  # Пересоздавать после 75 запросов
BROWSER_HEALTH_CHECK_INTERVAL = int(os.getenv('BROWSER_HEALTH_CHECK_INTERVAL', '60'))  # Проверка каждые 60 сек
BROWSER_POOL_ENABLED = os.getenv('BROWSER_POOL_ENABLED', 'true').lower() == 'true'  # Использовать пул

# =============================================================================
# DEBOUNCE CONFIGURATION (защита от спама кнопок)
# =============================================================================
DEBOUNCE_SECONDS = float(os.getenv('DEBOUNCE_SECONDS', '0.5'))  # Игнорировать повторы 0.5с

# =============================================================================
# CACHE CONFIGURATION (кэширование для отзывчивого UI)
# =============================================================================
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() == 'true'  # Включить кэширование
CACHE_MAX_SIZE = int(os.getenv('CACHE_MAX_SIZE', '1000'))  # Максимум записей в кэше
CACHE_DEFAULT_TTL = float(os.getenv('CACHE_DEFAULT_TTL', '30.0'))  # TTL по умолчанию (секунды)
CACHE_LINKS_TTL = float(os.getenv('CACHE_LINKS_TTL', '30.0'))  # TTL для списка ссылок
CACHE_PROMOS_TTL = float(os.getenv('CACHE_PROMOS_TTL', '60.0'))  # TTL для промоакций
CACHE_STAKINGS_TTL = float(os.getenv('CACHE_STAKINGS_TTL', '60.0'))  # TTL для стейкингов

# =============================================================================
# PARALLEL PARSING CONFIGURATION (параллельный парсинг)
# =============================================================================
PARALLEL_PARSING_ENABLED = os.getenv('PARALLEL_PARSING_ENABLED', 'true').lower() == 'true'
PARALLEL_PARSING_WORKERS = int(os.getenv('PARALLEL_PARSING_WORKERS', '2'))  # Кол-во воркеров (2 оптимально для 4GB RAM + Playwright)
PARALLEL_PARSING_QUEUE_SIZE = int(os.getenv('PARALLEL_PARSING_QUEUE_SIZE', '150'))  # Размер очереди
PARALLEL_PARSING_TASK_TIMEOUT = int(os.getenv('PARALLEL_PARSING_TASK_TIMEOUT', '120'))  # Таймаут задачи (120сек для NVMe SSD)
PARALLEL_PARSING_MAX_RETRIES = int(os.getenv('PARALLEL_PARSING_MAX_RETRIES', '3'))  # Макс. повторов

# Таймауты для тяжёлых парсеров (Bitget требует браузер + медленный API)
# Формат: exchange_name -> timeout в секундах
PARSER_TIMEOUT_OVERRIDES = {
    'bitget': 180,   # Bitget медленный из-за Cloudflare
    'gate': 150,     # Gate тоже иногда медленный
    'weex': 150,     # WEEX через браузер
}
# Также можно задать по категории
PARSER_TIMEOUT_BY_CATEGORY = {
    'candybomb': 180,   # CandyBomb требует много API запросов
    'launchpad': 150,   # Launchpad страницы тяжёлые
    'launchpool': 180,  # Launchpool тоже тяжёлые (Bitget и др.)
}

# =============================================================================
# CIRCUIT BREAKER CONFIGURATION (защита от недоступных бирж)
# =============================================================================
CIRCUIT_BREAKER_ENABLED = os.getenv('CIRCUIT_BREAKER_ENABLED', 'true').lower() == 'true'
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv('CIRCUIT_BREAKER_FAILURE_THRESHOLD', '3'))  # Неудач для блокировки
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = int(os.getenv('CIRCUIT_BREAKER_RECOVERY_TIMEOUT', '120'))  # 2 минуты блокировки (быстрее на мощном сервере)
CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS = int(os.getenv('CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS', '2'))  # Пробных запросов
CIRCUIT_BREAKER_SUCCESS_THRESHOLD = int(os.getenv('CIRCUIT_BREAKER_SUCCESS_THRESHOLD', '2'))  # Успехов для разблокировки

# =============================================================================
# RESOURCE MONITOR CONFIGURATION (мониторинг ресурсов)
# =============================================================================
RESOURCE_MONITOR_ENABLED = os.getenv('RESOURCE_MONITOR_ENABLED', 'true').lower() == 'true'
RESOURCE_MONITOR_INTERVAL = int(os.getenv('RESOURCE_MONITOR_INTERVAL', '300'))  # Проверка каждые 5 мин
RESOURCE_RAM_WARNING_PERCENT = float(os.getenv('RESOURCE_RAM_WARNING_PERCENT', '75.0'))  # Предупреждение RAM (75% от 4GB = 3GB)
RESOURCE_RAM_CRITICAL_PERCENT = float(os.getenv('RESOURCE_RAM_CRITICAL_PERCENT', '90.0'))  # Критический RAM (90% от 4GB = 3.6GB)
RESOURCE_CPU_WARNING_PERCENT = float(os.getenv('RESOURCE_CPU_WARNING_PERCENT', '70.0'))  # Предупреждение CPU
RESOURCE_CPU_CRITICAL_PERCENT = float(os.getenv('RESOURCE_CPU_CRITICAL_PERCENT', '90.0'))  # Критический CPU

# =============================================================================
# GRACEFUL DEGRADATION CONFIGURATION (адаптивное снижение нагрузки)
# =============================================================================
GRACEFUL_DEGRADATION_ENABLED = os.getenv('GRACEFUL_DEGRADATION_ENABLED', 'true').lower() == 'true'
GRACEFUL_DEGRADATION_CHECK_INTERVAL = int(os.getenv('GRACEFUL_DEGRADATION_CHECK_INTERVAL', '60'))  # сек

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

# =============================================================================
# EXCHANGE API CREDENTIALS (для получения полных данных о стейкингах)
# =============================================================================
# Bybit API
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')

# Kucoin API
KUCOIN_API_KEY = os.getenv('KUCOIN_API_KEY', '')
KUCOIN_API_SECRET = os.getenv('KUCOIN_API_SECRET', '')
KUCOIN_PASSPHRASE = os.getenv('KUCOIN_PASSPHRASE', '')

# OKX API
OKX_API_KEY = os.getenv('OKX_API_KEY', '')
OKX_API_SECRET = os.getenv('OKX_API_SECRET', '')
OKX_PASSPHRASE = os.getenv('OKX_PASSPHRASE', '')

# Логирование настроек API ключей
def _log_exchange_api_status():
    """Логирует статус настройки API ключей бирж"""
    exchanges = [
        ('Bybit', BYBIT_API_KEY, BYBIT_API_SECRET),
        ('Kucoin', KUCOIN_API_KEY, KUCOIN_API_SECRET),
        ('OKX', OKX_API_KEY, OKX_API_SECRET),
    ]
    
    configured = []
    for name, api_key, api_secret in exchanges:
        if api_key and api_secret:
            configured.append(name)
    
    if configured:
        print(f"🔑 API ключи настроены: {', '.join(configured)}")
    else:
        print(f"ℹ️  API ключи бирж не настроены (расширенные данные недоступны)")

_log_exchange_api_status()
