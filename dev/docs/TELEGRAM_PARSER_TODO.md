# TODO: Интеграция универсального Telegram-парсера

> **Цель:** Полная интеграция парсера Telegram-каналов в бота для мониторинга промоакций через анонсы в каналах.
>
> **Дата создания:** 2025-12-26
>
> **Статус:** 0/20 задач выполнено

---

## Архитектура решения

Telegram-парсер будет **ПОЛНОСТЬЮ интегрирован** в существующего бота:

- ✅ Пользователь добавляет каналы через интерфейс бота
- ✅ Пользователь настраивает ключевые слова для каждого канала
- ✅ Автоматический мониторинг каналов 24/7
- ✅ Уведомления о найденных промоакциях
- ✅ Фильтрация дубликатов

---

## 📊 БЛОК 1: Зависимости и конфигурация

### ☐ Задача 1: Добавить зависимость Telethon в requirements.txt

**Описание:**
- Добавить библиотеку `telethon==1.34.0` в requirements.txt
- Telethon - это MTProto клиент для работы с Telegram API
- Позволяет мониторить каналы и получать сообщения в реальном времени

**Файл:** `requirements.txt`

**Действие:**
```txt
telethon==1.34.0
```

---

### ☐ Задача 2: Добавить настройки Telegram API в config.py

**Описание:**
- Добавить переменные окружения `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`
- Эти credentials необходимы для подключения к Telegram
- Получаются на https://my.telegram.org/apps
- Добавить валидацию: если парсер включен, то credentials обязательны

**Файл:** `config.py`

**Действие:**
```python
# =============================================================================
# TELEGRAM PARSER CONFIGURATION
# =============================================================================
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
TELEGRAM_PARSER_ENABLED = os.getenv('TELEGRAM_PARSER_ENABLED', 'false').lower() == 'true'

# Валидация (только если парсер включен)
if TELEGRAM_PARSER_ENABLED:
    if not TELEGRAM_API_ID:
        raise ValueError(
            "❌ TELEGRAM_API_ID не установлен!\n"
            "Получите на https://my.telegram.org/apps\n"
            "Добавьте в .env: TELEGRAM_API_ID=your_api_id"
        )

    if not TELEGRAM_API_HASH:
        raise ValueError(
            "❌ TELEGRAM_API_HASH не установлен!\n"
            "Получите на https://my.telegram.org/apps\n"
            "Добавьте в .env: TELEGRAM_API_HASH=your_api_hash"
        )

    try:
        TELEGRAM_API_ID = int(TELEGRAM_API_ID)
    except ValueError:
        raise ValueError(f"❌ TELEGRAM_API_ID должен быть числом, получено: {TELEGRAM_API_ID}")
```

---

### ☐ Задача 3: Обновить .env.example с полями Telegram API

**Описание:**
- Добавить примеры переменных для Telegram API
- Добавить инструкцию где получить credentials
- Добавить флаг включения/выключения парсера

**Файл:** `.env.example`

**Действие:**
```env
# =============================================================================
# TELEGRAM PARSER CONFIGURATION
# =============================================================================
# Включить/выключить Telegram-парсер (true/false)
TELEGRAM_PARSER_ENABLED=false

# Telegram API Credentials
# Получите бесплатно на: https://my.telegram.org/apps
# 1. Войдите с номером телефона
# 2. Создайте новое приложение
# 3. Скопируйте API_ID и API_HASH
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

---

## 💾 БЛОК 2: База данных

### ☐ Задача 4: Создать модель TelegramChannel в data/models.py

**Описание:**
- Модель для хранения отслеживаемых Telegram-каналов
- Каждый канал имеет свой набор ключевых слов
- Поддержка активации/деактивации мониторинга

**Файл:** `data/models.py`

**Действие:**
```python
class TelegramChannel(Base):
    __tablename__ = 'telegram_channels'

    id = Column(Integer, primary_key=True)

    # Информация о канале
    channel_username = Column(String, unique=True)  # @channel_name или ссылка
    channel_title = Column(String, nullable=True)  # Название канала
    channel_id = Column(Integer, nullable=True)  # Telegram ID канала

    # Ключевые слова для поиска (JSON массив)
    keywords = Column(Text, default='[]')  # ["airdrop", "промо", "campaign"]

    # Настройки мониторинга
    is_active = Column(Boolean, default=True)
    check_interval = Column(Integer, default=60)  # Проверка каждые 60 сек

    # Статистика
    total_messages_found = Column(Integer, default=0)
    last_message_date = Column(DateTime, nullable=True)
    last_checked = Column(DateTime, nullable=True)

    # Мета-информация
    added_by = Column(Integer)  # User ID кто добавил
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_keywords(self):
        """Получить список ключевых слов"""
        try:
            return json.loads(self.keywords) if self.keywords else []
        except:
            return []

    def set_keywords(self, keywords_list):
        """Установить список ключевых слов"""
        self.keywords = json.dumps(keywords_list) if keywords_list else '[]'

    def add_keyword(self, keyword):
        """Добавить ключевое слово"""
        keywords = self.get_keywords()
        if keyword.lower() not in [k.lower() for k in keywords]:
            keywords.append(keyword)
            self.set_keywords(keywords)
            return True
        return False

    def remove_keyword(self, keyword):
        """Удалить ключевое слово"""
        keywords = self.get_keywords()
        keywords = [k for k in keywords if k.lower() != keyword.lower()]
        self.set_keywords(keywords)
```

---

### ☐ Задача 5: Создать модель TelegramMessage в data/models.py

**Описание:**
- Модель для хранения найденных сообщений из Telegram-каналов
- Хранит текст, найденные ключевые слова, извлеченные ссылки
- Предотвращает дубликаты уведомлений

**Файл:** `data/models.py`

**Действие:**
```python
class TelegramMessage(Base):
    __tablename__ = 'telegram_messages'

    id = Column(Integer, primary_key=True)

    # Связь с каналом
    channel_id = Column(Integer, ForeignKey('telegram_channels.id'))

    # Информация о сообщении
    message_id = Column(Integer)  # ID сообщения в Telegram
    message_text = Column(Text)  # Полный текст сообщения
    message_date = Column(DateTime)  # Дата публикации

    # Найденные данные
    matched_keywords = Column(Text, default='[]')  # Какие ключевые слова совпали
    extracted_links = Column(Text, default='[]')  # Извлеченные ссылки из текста
    extracted_dates = Column(Text, nullable=True)  # Найденные даты (период акции)

    # Обработка
    notification_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)

    # Мета-информация
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связь
    channel = relationship("TelegramChannel", backref="messages")

    # Уникальность: один message_id на канал
    __table_args__ = (
        UniqueConstraint('channel_id', 'message_id', name='_channel_message_uc'),
    )

    def get_matched_keywords(self):
        """Получить список совпавших ключевых слов"""
        try:
            return json.loads(self.matched_keywords) if self.matched_keywords else []
        except:
            return []

    def set_matched_keywords(self, keywords_list):
        """Установить список совпавших ключевых слов"""
        self.matched_keywords = json.dumps(keywords_list) if keywords_list else '[]'

    def get_extracted_links(self):
        """Получить список извлеченных ссылок"""
        try:
            return json.loads(self.extracted_links) if self.extracted_links else []
        except:
            return []

    def set_extracted_links(self, links_list):
        """Установить список извлеченных ссылок"""
        self.extracted_links = json.dumps(links_list) if links_list else '[]'
```

---

### ☐ Задача 6: Добавить миграцию БД для новых таблиц Telegram

**Описание:**
- Создать миграцию для автоматического создания таблиц
- Добавить индексы для оптимизации поиска
- Интегрировать в существующую систему миграций

**Файл:** `data/database.py`

**Действие:**
```python
# В функции create_indexes() добавить:
def create_indexes():
    """Создание индексов для оптимизации"""
    indexes = [
        # ... существующие индексы ...

        # Индексы для Telegram
        Index('idx_tg_channel_username', TelegramChannel.channel_username),
        Index('idx_tg_channel_active', TelegramChannel.is_active),
        Index('idx_tg_message_channel_date', TelegramMessage.channel_id, TelegramMessage.message_date),
        Index('idx_tg_message_notification', TelegramMessage.notification_sent),
    ]
    return indexes

# В класс DatabaseMigration добавить миграцию:
def _migration_005_telegram_tables(self, db):
    """Миграция 005: Добавление таблиц для Telegram-парсера"""
    logger.info("🔄 Миграция 005: Создание таблиц Telegram-парсера...")

    # Таблицы создаются автоматически через Base.metadata.create_all()
    # Просто проверяем их наличие

    from sqlalchemy import inspect
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()

    if 'telegram_channels' in tables:
        logger.info("✅ Таблица telegram_channels существует")
    else:
        logger.warning("⚠️ Таблица telegram_channels не создана")

    if 'telegram_messages' in tables:
        logger.info("✅ Таблица telegram_messages существует")
    else:
        logger.warning("⚠️ Таблица telegram_messages не создана")

    logger.info("✅ Миграция 005 завершена")
```

---

## 🎯 БЛОК 3: Парсер и мониторинг

### ☐ Задача 7: Создать parsers/telegram_parser.py с классом TelegramParser

**Описание:**
- Основной класс для работы с Telegram API
- Подключение к Telegram через Telethon
- Поиск ключевых слов в сообщениях
- Извлечение ссылок и дат из текста

**Файл:** `parsers/telegram_parser.py` (НОВЫЙ)

**Действие:**
```python
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import Channel, User
import config

logger = logging.getLogger(__name__)

class TelegramParser:
    """Парсер для мониторинга Telegram-каналов"""

    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.client = None
        self.is_connected = False

        # Паттерны для извлечения данных
        self.url_pattern = re.compile(r'https?://[^\s]+')
        self.date_pattern = re.compile(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}')

    async def connect(self):
        """Подключение к Telegram"""
        try:
            logger.info("🔌 Подключение к Telegram...")

            self.client = TelegramClient('telegram_parser_session', self.api_id, self.api_hash)
            await self.client.start()

            self.is_connected = True
            logger.info("✅ Успешно подключено к Telegram")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Telegram: {e}")
            self.is_connected = False
            return False

    async def disconnect(self):
        """Отключение от Telegram"""
        if self.client:
            await self.client.disconnect()
            self.is_connected = False
            logger.info("👋 Отключено от Telegram")

    async def get_channel_info(self, channel_username: str) -> Optional[Dict]:
        """Получить информацию о канале"""
        try:
            entity = await self.client.get_entity(channel_username)

            if isinstance(entity, Channel):
                return {
                    'id': entity.id,
                    'title': entity.title,
                    'username': entity.username,
                    'participants_count': entity.participants_count
                }

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о канале {channel_username}: {e}")
            return None

    def search_keywords_in_message(self, text: str, keywords: List[str]) -> List[str]:
        """Поиск ключевых слов в тексте сообщения"""
        if not text or not keywords:
            return []

        text_lower = text.lower()
        matched = []

        for keyword in keywords:
            if keyword.lower() in text_lower:
                matched.append(keyword)

        return matched

    def extract_links(self, text: str) -> List[str]:
        """Извлечение ссылок из текста"""
        if not text:
            return []

        links = self.url_pattern.findall(text)
        return list(set(links))  # Убираем дубликаты

    def extract_dates(self, text: str) -> Optional[str]:
        """Извлечение дат из текста"""
        if not text:
            return None

        dates = self.date_pattern.findall(text)
        return ', '.join(dates) if dates else None

    async def get_recent_messages(self, channel_username: str, limit: int = 10) -> List[Dict]:
        """Получить последние сообщения из канала"""
        try:
            messages = []

            async for message in self.client.iter_messages(channel_username, limit=limit):
                if message.text:
                    messages.append({
                        'id': message.id,
                        'text': message.text,
                        'date': message.date
                    })

            return messages

        except FloodWaitError as e:
            logger.warning(f"⏰ Flood Wait: нужно подождать {e.seconds} секунд")
            return []
        except Exception as e:
            logger.error(f"❌ Ошибка получения сообщений из {channel_username}: {e}")
            return []

    async def process_message(self, message_text: str, keywords: List[str]) -> Optional[Dict]:
        """Обработка сообщения: поиск ключевых слов и извлечение данных"""
        matched_keywords = self.search_keywords_in_message(message_text, keywords)

        if not matched_keywords:
            return None

        return {
            'matched_keywords': matched_keywords,
            'links': self.extract_links(message_text),
            'dates': self.extract_dates(message_text)
        }
```

---

### ☐ Задача 8: Создать services/telegram_monitor.py для мониторинга каналов

**Описание:**
- Сервис для непрерывного мониторинга Telegram-каналов
- Обработка новых сообщений в реальном времени
- Отправка уведомлений при совпадении ключевых слов
- Автоматическое переподключение при сбоях

**Файл:** `services/telegram_monitor.py` (НОВЫЙ)

**Действие:**
```python
import asyncio
import logging
from datetime import datetime
from typing import List, Dict
from telethon import events
from parsers.telegram_parser import TelegramParser
from data.database import get_db_session
from data.models import TelegramChannel, TelegramMessage
from bot.notification_service import NotificationService
import config

logger = logging.getLogger(__name__)

class TelegramMonitor:
    """Сервис мониторинга Telegram-каналов"""

    def __init__(self, bot):
        self.bot = bot
        self.parser = TelegramParser()
        self.notification_service = NotificationService(bot)
        self.is_running = False
        self.monitored_channels = {}
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Запуск мониторинга"""
        try:
            if not config.TELEGRAM_PARSER_ENABLED:
                logger.info("ℹ️ Telegram-парсер отключен в конфигурации")
                return

            logger.info("🚀 Запуск Telegram Monitor...")

            # Подключаемся к Telegram
            connected = await self.parser.connect()
            if not connected:
                logger.error("❌ Не удалось подключиться к Telegram")
                return

            # Загружаем активные каналы
            await self.load_active_channels()

            # Подписываемся на новые сообщения
            self.parser.client.add_event_handler(
                self.handle_new_message,
                events.NewMessage()
            )

            self.is_running = True
            logger.info(f"✅ Telegram Monitor запущен. Отслеживается {len(self.monitored_channels)} каналов")

            # Ожидаем сигнала завершения
            await self._shutdown_event.wait()

        except Exception as e:
            logger.error(f"❌ Ошибка запуска Telegram Monitor: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Остановка мониторинга"""
        logger.info("🛑 Остановка Telegram Monitor...")
        self.is_running = False

        if self.parser:
            await self.parser.disconnect()

        logger.info("✅ Telegram Monitor остановлен")

    async def shutdown(self):
        """Сигнал завершения работы"""
        self._shutdown_event.set()

    async def load_active_channels(self):
        """Загрузка активных каналов из БД"""
        try:
            with get_db_session() as db:
                channels = db.query(TelegramChannel).filter(
                    TelegramChannel.is_active == True
                ).all()

                for channel in channels:
                    self.monitored_channels[channel.channel_username] = {
                        'id': channel.id,
                        'keywords': channel.get_keywords(),
                        'channel_id': channel.channel_id
                    }

                logger.info(f"📋 Загружено {len(self.monitored_channels)} активных каналов")

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки каналов: {e}")

    async def handle_new_message(self, event):
        """Обработка нового сообщения из канала"""
        try:
            message = event.message

            # Проверяем, отслеживается ли этот канал
            chat = await event.get_chat()
            channel_username = getattr(chat, 'username', None)

            if not channel_username or channel_username not in self.monitored_channels:
                return

            channel_data = self.monitored_channels[channel_username]
            keywords = channel_data['keywords']

            if not message.text or not keywords:
                return

            # Обрабатываем сообщение
            result = await self.parser.process_message(message.text, keywords)

            if result:
                logger.info(f"🔔 Найдено совпадение в канале @{channel_username}")
                logger.info(f"   Ключевые слова: {', '.join(result['matched_keywords'])}")

                # Сохраняем в БД
                await self.save_message(
                    channel_data['id'],
                    message.id,
                    message.text,
                    message.date,
                    result
                )

                # Отправляем уведомление
                await self.send_notification(
                    channel_username,
                    message.text,
                    result
                )

        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")

    async def save_message(self, channel_id: int, message_id: int, text: str,
                          date: datetime, result: Dict):
        """Сохранение найденного сообщения в БД"""
        try:
            with get_db_session() as db:
                # Проверяем, не сохранено ли уже
                existing = db.query(TelegramMessage).filter(
                    TelegramMessage.channel_id == channel_id,
                    TelegramMessage.message_id == message_id
                ).first()

                if existing:
                    logger.debug(f"ℹ️ Сообщение {message_id} уже сохранено")
                    return

                # Создаем новую запись
                tg_message = TelegramMessage(
                    channel_id=channel_id,
                    message_id=message_id,
                    message_text=text,
                    message_date=date
                )

                tg_message.set_matched_keywords(result['matched_keywords'])
                tg_message.set_extracted_links(result['links'])
                tg_message.extracted_dates = result['dates']

                db.add(tg_message)
                db.commit()

                # Обновляем статистику канала
                channel = db.query(TelegramChannel).filter(
                    TelegramChannel.id == channel_id
                ).first()

                if channel:
                    channel.total_messages_found += 1
                    channel.last_message_date = date
                    channel.last_checked = datetime.utcnow()
                    db.commit()

                logger.info(f"💾 Сообщение сохранено в БД")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения сообщения: {e}")

    async def send_notification(self, channel_username: str, message_text: str, result: Dict):
        """Отправка уведомления о найденном сообщении"""
        try:
            # Формируем уведомление
            notification = self.notification_service.format_telegram_promo(
                channel_username,
                message_text,
                result['matched_keywords'],
                result['links'],
                result['dates']
            )

            # Отправляем админу
            await self.notification_service.send_message(
                config.ADMIN_CHAT_ID,
                notification
            )

            # Отмечаем как отправленное
            with get_db_session() as db:
                tg_message = db.query(TelegramMessage).filter(
                    TelegramMessage.channel_id == self.monitored_channels[channel_username]['id'],
                    TelegramMessage.notification_sent == False
                ).order_by(TelegramMessage.created_at.desc()).first()

                if tg_message:
                    tg_message.notification_sent = True
                    tg_message.sent_at = datetime.utcnow()
                    db.commit()

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")

    async def reload_channels(self):
        """Перезагрузка списка отслеживаемых каналов"""
        logger.info("🔄 Перезагрузка списка каналов...")
        await self.load_active_channels()
```

---

### ☐ Задача 9: Создать utils/telegram_message_processor.py для обработки сообщений

**Описание:**
- Утилиты для обработки и анализа текста сообщений
- Извлечение структурированных данных из текста
- Определение типа промоакции (airdrop, staking, campaign и т.д.)

**Файл:** `utils/telegram_message_processor.py` (НОВЫЙ)

**Действие:**
```python
import re
from typing import Dict, List, Optional
from datetime import datetime

class TelegramMessageProcessor:
    """Процессор для анализа и обработки сообщений из Telegram"""

    # Паттерны для различных типов данных
    PRIZE_PATTERNS = [
        r'\$[\d,]+',  # $10,000
        r'[\d,]+\s*USD[T]?',  # 10000 USDT
        r'[\d,]+\s*[A-Z]{3,4}',  # 1000 BTC
    ]

    DATE_PATTERNS = [
        r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}',  # 01.01.2025
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}',  # Jan 15
        r'\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)',  # 15 января
    ]

    PROMO_TYPES = {
        'airdrop': ['airdrop', 'air drop', 'раздача', 'бесплатно'],
        'staking': ['staking', 'stake', 'стейкинг', 'locked', 'earn'],
        'trading': ['trading', 'trade', 'трейдинг', 'volume', 'объем'],
        'campaign': ['campaign', 'competition', 'contest', 'кампания', 'конкурс'],
        'launchpool': ['launchpool', 'launch pool', 'лаунчпул', 'farming'],
    }

    @staticmethod
    def extract_prize_pool(text: str) -> Optional[str]:
        """Извлечение призового фонда"""
        for pattern in TelegramMessageProcessor.PRIZE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def extract_period(text: str) -> Optional[str]:
        """Извлечение периода проведения акции"""
        dates = []
        for pattern in TelegramMessageProcessor.DATE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)

        if dates:
            return ' - '.join(dates[:2]) if len(dates) >= 2 else dates[0]
        return None

    @staticmethod
    def detect_promo_type(text: str, keywords: List[str]) -> str:
        """Определение типа промоакции"""
        text_lower = text.lower()

        # Проверяем каждый тип
        for promo_type, terms in TelegramMessageProcessor.PROMO_TYPES.items():
            for term in terms:
                if term in text_lower:
                    return promo_type

        # Если не определено, возвращаем тип по ключевому слову
        if keywords:
            keyword_lower = keywords[0].lower()
            for promo_type, terms in TelegramMessageProcessor.PROMO_TYPES.items():
                if keyword_lower in terms:
                    return promo_type

        return 'general'

    @staticmethod
    def extract_requirements(text: str) -> List[str]:
        """Извлечение требований для участия"""
        requirements = []

        # Ищем списки с маркерами
        list_pattern = r'[•\-\*]\s*(.+)'
        matches = re.findall(list_pattern, text)

        if matches:
            requirements = [m.strip() for m in matches[:5]]  # Максимум 5 пунктов

        return requirements

    @staticmethod
    def create_summary(text: str, max_length: int = 300) -> str:
        """Создание краткого содержания сообщения"""
        # Убираем лишние пробелы и переносы
        clean_text = ' '.join(text.split())

        if len(clean_text) <= max_length:
            return clean_text

        # Обрезаем по словам
        summary = clean_text[:max_length]
        last_space = summary.rfind(' ')

        if last_space > 0:
            summary = summary[:last_space]

        return summary + '...'

    @staticmethod
    def analyze_message(text: str, matched_keywords: List[str]) -> Dict:
        """Полный анализ сообщения"""
        return {
            'prize_pool': TelegramMessageProcessor.extract_prize_pool(text),
            'period': TelegramMessageProcessor.extract_period(text),
            'promo_type': TelegramMessageProcessor.detect_promo_type(text, matched_keywords),
            'requirements': TelegramMessageProcessor.extract_requirements(text),
            'summary': TelegramMessageProcessor.create_summary(text)
        }
```

---

## 🎮 БЛОК 4: Интерфейс бота

### ☐ Задача 10: Добавить FSM состояния AddTelegramChannelStates в bot/handlers.py

**Описание:**
- Добавить новый класс состояний для процесса добавления Telegram-канала
- Три этапа: ввод канала, ввод ключевых слов, подтверждение

**Файл:** `bot/handlers.py`

**Действие:**
```python
# Добавить после существующих StatesGroup:

class AddTelegramChannelStates(StatesGroup):
    """Состояния для добавления Telegram-канала"""
    waiting_for_channel = State()      # Ожидание ввода @канала или ссылки
    waiting_for_keywords = State()     # Ожидание ввода ключевых слов
    confirmation = State()              # Подтверждение добавления

class ManageTelegramChannelStates(StatesGroup):
    """Состояния для управления Telegram-каналом"""
    waiting_for_keyword_action = State()  # Выбор действия с ключевыми словами
    waiting_for_new_keyword = State()      # Ввод нового ключевого слова
    waiting_for_delete_keyword = State()   # Выбор ключевого слова для удаления
```

---

### ☐ Задача 11: Создать handler для добавления Telegram канала с ключевыми словами

**Описание:**
- Handler для добавления нового Telegram-канала через бота
- Проверка доступности канала
- Валидация ввода пользователя
- Сохранение в БД

**Файл:** `bot/handlers.py`

**Действие:**
```python
# ============================================================================
# TELEGRAM CHANNELS - Управление Telegram-каналами
# ============================================================================

@router.message(F.text == "📡 Telegram каналы")
async def telegram_channels_menu(message: Message):
    """Главное меню управления Telegram-каналами"""
    try:
        if not config.TELEGRAM_PARSER_ENABLED:
            await message.answer(
                "⚠️ Telegram-парсер отключен в конфигурации.\n"
                "Установите TELEGRAM_PARSER_ENABLED=true в .env файле."
            )
            return

        with get_db_session() as db:
            total_channels = db.query(TelegramChannel).count()
            active_channels = db.query(TelegramChannel).filter(
                TelegramChannel.is_active == True
            ).count()
            total_messages = db.query(TelegramMessage).count()

        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="➕ Добавить канал",
            callback_data="telegram_add_channel"
        ))
        builder.add(InlineKeyboardButton(
            text="📋 Список каналов",
            callback_data="telegram_list_channels"
        ))
        builder.add(InlineKeyboardButton(
            text="📊 Статистика",
            callback_data="telegram_stats"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="back_to_main"
        ))
        builder.adjust(2, 1, 1)

        await message.answer(
            f"📡 <b>Управление Telegram-каналами</b>\n\n"
            f"📊 Всего каналов: {total_channels}\n"
            f"✅ Активных: {active_channels}\n"
            f"💬 Найдено сообщений: {total_messages}\n\n"
            f"Выберите действие:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка меню Telegram-каналов: {e}")
        await message.answer("❌ Ошибка при загрузке меню")

@router.callback_query(F.data == "telegram_add_channel")
async def start_add_telegram_channel(callback: CallbackQuery, state: FSMContext):
    """Начало процесса добавления Telegram-канала"""
    await callback.message.edit_text(
        "📡 <b>Добавление Telegram-канала</b>\n\n"
        "Введите username канала (с @ или без) или ссылку:\n"
        "Примеры:\n"
        "• @binance_announcements\n"
        "• binance_announcements\n"
        "• https://t.me/binance_announcements\n\n"
        "Или отправьте /cancel для отмены",
        parse_mode="HTML"
    )
    await state.set_state(AddTelegramChannelStates.waiting_for_channel)

@router.message(AddTelegramChannelStates.waiting_for_channel)
async def process_channel_input(message: Message, state: FSMContext):
    """Обработка ввода канала"""
    try:
        channel_input = message.text.strip()

        # Извлекаем username из разных форматов
        if 't.me/' in channel_input:
            channel_username = channel_input.split('t.me/')[-1].split('?')[0]
        elif channel_input.startswith('@'):
            channel_username = channel_input[1:]
        else:
            channel_username = channel_input

        # Проверяем, не добавлен ли уже
        with get_db_session() as db:
            existing = db.query(TelegramChannel).filter(
                TelegramChannel.channel_username == channel_username
            ).first()

            if existing:
                await message.answer(
                    f"⚠️ Канал @{channel_username} уже добавлен!\n"
                    f"Используйте управление каналами для редактирования."
                )
                await state.clear()
                return

        # Проверяем доступность канала (если парсер запущен)
        # TODO: добавить проверку через TelegramParser

        # Сохраняем данные для следующего шага
        await state.update_data(channel_username=channel_username)

        await message.answer(
            f"✅ Канал: @{channel_username}\n\n"
            f"📝 Теперь введите ключевые слова для поиска.\n"
            f"Несколько слов вводите через запятую:\n\n"
            f"Примеры:\n"
            f"• airdrop\n"
            f"• промо, акция, campaign\n"
            f"• staking, earn, APR\n\n"
            f"Или отправьте /cancel для отмены"
        )
        await state.set_state(AddTelegramChannelStates.waiting_for_keywords)

    except Exception as e:
        logger.error(f"Ошибка обработки канала: {e}")
        await message.answer("❌ Ошибка обработки. Попробуйте снова.")

@router.message(AddTelegramChannelStates.waiting_for_keywords)
async def process_keywords_input(message: Message, state: FSMContext):
    """Обработка ввода ключевых слов"""
    try:
        keywords_input = message.text.strip()

        # Парсим ключевые слова
        keywords = [k.strip() for k in keywords_input.split(',') if k.strip()]

        if not keywords:
            await message.answer(
                "⚠️ Вы не ввели ни одного ключевого слова.\n"
                "Попробуйте снова:"
            )
            return

        # Получаем данные из state
        data = await state.get_data()
        channel_username = data.get('channel_username')

        # Сохраняем в БД
        with get_db_session() as db:
            new_channel = TelegramChannel(
                channel_username=channel_username,
                added_by=message.from_user.id,
                is_active=True
            )
            new_channel.set_keywords(keywords)

            db.add(new_channel)
            db.commit()

            channel_id = new_channel.id

        # Уведомляем об успехе
        keywords_list = '\n'.join([f"  • {k}" for k in keywords])

        await message.answer(
            f"✅ <b>Канал успешно добавлен!</b>\n\n"
            f"📡 Канал: @{channel_username}\n"
            f"🔑 Ключевые слова:\n{keywords_list}\n\n"
            f"🔄 Мониторинг активирован.\n"
            f"Вы будете получать уведомления о новых сообщениях с этими словами.",
            parse_mode="HTML"
        )

        # Перезагружаем каналы в мониторе (если он запущен)
        # TODO: добавить вызов telegram_monitor.reload_channels()

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка сохранения канала: {e}")
        await message.answer("❌ Ошибка при сохранении. Попробуйте снова.")
```

---

### ☐ Задача 12: Создать handler для управления Telegram каналами (список, удаление)

**Описание:**
- Показать список всех добавленных каналов
- Статистика по каждому каналу
- Возможность включить/выключить мониторинг
- Удаление канала

**Файл:** `bot/handlers.py`

**Действие:**
```python
@router.callback_query(F.data == "telegram_list_channels")
async def list_telegram_channels(callback: CallbackQuery):
    """Список всех Telegram-каналов"""
    try:
        with get_db_session() as db:
            channels = db.query(TelegramChannel).order_by(
                TelegramChannel.created_at.desc()
            ).all()

            if not channels:
                await callback.message.edit_text(
                    "📭 У вас пока нет добавленных Telegram-каналов.\n"
                    "Добавьте первый канал через кнопку '➕ Добавить канал'",
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_telegram_menu")
                    ).as_markup()
                )
                return

            builder = InlineKeyboardBuilder()

            for channel in channels:
                status_icon = "✅" if channel.is_active else "⏸️"
                keywords_count = len(channel.get_keywords())

                builder.add(InlineKeyboardButton(
                    text=f"{status_icon} @{channel.channel_username} ({keywords_count} слов)",
                    callback_data=f"tg_channel_{channel.id}"
                ))

            builder.add(InlineKeyboardButton(
                text="🔙 Назад",
                callback_data="back_to_telegram_menu"
            ))
            builder.adjust(1)

            await callback.message.edit_text(
                f"📋 <b>Ваши Telegram-каналы ({len(channels)})</b>\n\n"
                f"Выберите канал для управления:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка списка каналов: {e}")
        await callback.answer("❌ Ошибка при загрузке списка")

@router.callback_query(F.data.startswith("tg_channel_"))
async def show_telegram_channel_details(callback: CallbackQuery):
    """Детали конкретного Telegram-канала"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if not channel:
                await callback.answer("❌ Канал не найден")
                return

            keywords = channel.get_keywords()
            keywords_list = '\n'.join([f"  • {k}" for k in keywords]) if keywords else "  (нет)"

            status = "Активен ✅" if channel.is_active else "Приостановлен ⏸️"
            last_check = channel.last_checked.strftime("%d.%m.%Y %H:%M") if channel.last_checked else "Никогда"

            text = (
                f"📡 <b>Канал: @{channel.channel_username}</b>\n\n"
                f"📊 Статус: {status}\n"
                f"💬 Найдено сообщений: {channel.total_messages_found}\n"
                f"⏰ Последняя проверка: {last_check}\n\n"
                f"🔑 <b>Ключевые слова ({len(keywords)}):</b>\n{keywords_list}\n\n"
                f"Выберите действие:"
            )

            builder = InlineKeyboardBuilder()

            # Кнопка вкл/выкл
            if channel.is_active:
                builder.add(InlineKeyboardButton(
                    text="⏸️ Приостановить",
                    callback_data=f"tg_pause_{channel_id}"
                ))
            else:
                builder.add(InlineKeyboardButton(
                    text="▶️ Возобновить",
                    callback_data=f"tg_resume_{channel_id}"
                ))

            builder.add(InlineKeyboardButton(
                text="🔑 Управление словами",
                callback_data=f"tg_keywords_{channel_id}"
            ))
            builder.add(InlineKeyboardButton(
                text="🗑️ Удалить канал",
                callback_data=f"tg_delete_{channel_id}"
            ))
            builder.add(InlineKeyboardButton(
                text="🔙 К списку",
                callback_data="telegram_list_channels"
            ))
            builder.adjust(2, 1, 1, 1)

            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка отображения канала: {e}")
        await callback.answer("❌ Ошибка при загрузке")

@router.callback_query(F.data.startswith("tg_pause_"))
async def pause_telegram_channel(callback: CallbackQuery):
    """Приостановка мониторинга канала"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if channel:
                channel.is_active = False
                db.commit()

                await callback.answer("⏸️ Мониторинг приостановлен")
                # Перезагружаем детали
                await show_telegram_channel_details(callback)

    except Exception as e:
        logger.error(f"Ошибка приостановки: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("tg_resume_"))
async def resume_telegram_channel(callback: CallbackQuery):
    """Возобновление мониторинга канала"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if channel:
                channel.is_active = True
                db.commit()

                await callback.answer("▶️ Мониторинг возобновлен")
                # Перезагружаем детали
                await show_telegram_channel_details(callback)

    except Exception as e:
        logger.error(f"Ошибка возобновления: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("tg_delete_"))
async def confirm_delete_telegram_channel(callback: CallbackQuery):
    """Подтверждение удаления канала"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"tg_delete_confirm_{channel_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"tg_channel_{channel_id}"
        ))
        builder.adjust(1)

        await callback.message.edit_text(
            "⚠️ <b>Подтверждение удаления</b>\n\n"
            "Вы уверены, что хотите удалить этот канал?\n"
            "Все связанные сообщения также будут удалены.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка подтверждения удаления: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("tg_delete_confirm_"))
async def delete_telegram_channel(callback: CallbackQuery):
    """Удаление канала из БД"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            # Удаляем все сообщения канала
            db.query(TelegramMessage).filter(
                TelegramMessage.channel_id == channel_id
            ).delete()

            # Удаляем канал
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if channel:
                channel_username = channel.channel_username
                db.delete(channel)
                db.commit()

                await callback.answer(f"🗑️ Канал @{channel_username} удален")
                await list_telegram_channels(callback)
            else:
                await callback.answer("❌ Канал не найден")

    except Exception as e:
        logger.error(f"Ошибка удаления канала: {e}")
        await callback.answer("❌ Ошибка при удалении")
```

---

### ☐ Задача 13: Создать handler для управления ключевыми словами канала

**Описание:**
- Просмотр всех ключевых слов канала
- Добавление новых ключевых слов
- Удаление существующих ключевых слов

**Файл:** `bot/handlers.py`

**Действие:**
```python
@router.callback_query(F.data.startswith("tg_keywords_"))
async def manage_telegram_keywords(callback: CallbackQuery):
    """Управление ключевыми словами канала"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if not channel:
                await callback.answer("❌ Канал не найден")
                return

            keywords = channel.get_keywords()
            keywords_list = '\n'.join([f"  {i+1}. {k}" for i, k in enumerate(keywords)]) if keywords else "  (нет)"

            text = (
                f"🔑 <b>Ключевые слова канала @{channel.channel_username}</b>\n\n"
                f"<b>Текущие слова ({len(keywords)}):</b>\n{keywords_list}\n\n"
                f"Выберите действие:"
            )

            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text="➕ Добавить слово",
                callback_data=f"tg_add_keyword_{channel_id}"
            ))

            if keywords:
                builder.add(InlineKeyboardButton(
                    text="➖ Удалить слово",
                    callback_data=f"tg_remove_keyword_{channel_id}"
                ))

            builder.add(InlineKeyboardButton(
                text="🔙 Назад к каналу",
                callback_data=f"tg_channel_{channel_id}"
            ))
            builder.adjust(2, 1)

            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка управления ключевыми словами: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("tg_add_keyword_"))
async def start_add_keyword(callback: CallbackQuery, state: FSMContext):
    """Начало добавления ключевого слова"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        await state.update_data(manage_channel_id=channel_id)
        await state.set_state(ManageTelegramChannelStates.waiting_for_new_keyword)

        await callback.message.edit_text(
            "📝 <b>Добавление ключевого слова</b>\n\n"
            "Введите новое ключевое слово для поиска:\n"
            "(или несколько через запятую)\n\n"
            "Или отправьте /cancel для отмены",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка начала добавления слова: {e}")
        await callback.answer("❌ Ошибка")

@router.message(ManageTelegramChannelStates.waiting_for_new_keyword)
async def process_new_keyword(message: Message, state: FSMContext):
    """Обработка нового ключевого слова"""
    try:
        data = await state.get_data()
        channel_id = data.get('manage_channel_id')

        new_keywords_input = message.text.strip()
        new_keywords = [k.strip() for k in new_keywords_input.split(',') if k.strip()]

        if not new_keywords:
            await message.answer("⚠️ Вы не ввели ключевых слов. Попробуйте снова:")
            return

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if not channel:
                await message.answer("❌ Канал не найден")
                await state.clear()
                return

            added_count = 0
            for keyword in new_keywords:
                if channel.add_keyword(keyword):
                    added_count += 1

            db.commit()

            keywords_list = '\n'.join([f"  • {k}" for k in new_keywords])

            await message.answer(
                f"✅ <b>Добавлено слов: {added_count}</b>\n\n"
                f"{keywords_list}\n\n"
                f"Теперь бот будет искать сообщения с этими словами в канале @{channel.channel_username}",
                parse_mode="HTML"
            )

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка добавления ключевого слова: {e}")
        await message.answer("❌ Ошибка при добавлении")
        await state.clear()

@router.callback_query(F.data.startswith("tg_remove_keyword_"))
async def start_remove_keyword(callback: CallbackQuery):
    """Выбор ключевого слова для удаления"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if not channel:
                await callback.answer("❌ Канал не найден")
                return

            keywords = channel.get_keywords()

            if not keywords:
                await callback.answer("⚠️ Нет ключевых слов для удаления")
                return

            builder = InlineKeyboardBuilder()

            for keyword in keywords:
                builder.add(InlineKeyboardButton(
                    text=f"🗑️ {keyword}",
                    callback_data=f"tg_delete_kw_{channel_id}_{keyword}"
                ))

            builder.add(InlineKeyboardButton(
                text="🔙 Отмена",
                callback_data=f"tg_keywords_{channel_id}"
            ))
            builder.adjust(1)

            await callback.message.edit_text(
                f"🗑️ <b>Удаление ключевого слова</b>\n\n"
                f"Выберите слово для удаления:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка начала удаления слова: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("tg_delete_kw_"))
async def delete_keyword(callback: CallbackQuery):
    """Удаление ключевого слова"""
    try:
        parts = callback.data.split("_", 3)
        channel_id = int(parts[2])
        keyword = parts[3]

        with get_db_session() as db:
            channel = db.query(TelegramChannel).filter(
                TelegramChannel.id == channel_id
            ).first()

            if not channel:
                await callback.answer("❌ Канал не найден")
                return

            channel.remove_keyword(keyword)
            db.commit()

            await callback.answer(f"🗑️ Слово '{keyword}' удалено")

            # Возвращаемся к управлению ключевыми словами
            await manage_telegram_keywords(callback)

    except Exception as e:
        logger.error(f"Ошибка удаления ключевого слова: {e}")
        await callback.answer("❌ Ошибка при удалении")

@router.callback_query(F.data == "back_to_telegram_menu")
async def back_to_telegram_menu(callback: CallbackQuery):
    """Возврат в главное меню Telegram-каналов"""
    # Имитируем сообщение для вызова главного меню
    from aiogram.types import Message as TempMessage
    temp_message = callback.message
    await telegram_channels_menu(temp_message)
```

---

### ☐ Задача 14: Добавить кнопки управления Telegram в основное меню бота

**Описание:**
- Добавить кнопку "📡 Telegram каналы" в главное меню
- Интеграция в существующую навигацию

**Файл:** `bot/handlers.py`

**Действие:**
```python
# Найти функцию get_main_menu() и обновить её:

def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Список ссылок"))
    builder.add(KeyboardButton(text="➕ Добавить ссылку"))
    builder.add(KeyboardButton(text="⚙️ Управление ссылками"))
    builder.add(KeyboardButton(text="🔄 Проверить всё"))

    # НОВОЕ: Кнопка Telegram каналов (только если парсер включен)
    if config.TELEGRAM_PARSER_ENABLED:
        builder.add(KeyboardButton(text="📡 Telegram каналы"))

    builder.add(KeyboardButton(text="🛡️ Обход блокировок"))
    builder.add(KeyboardButton(text="📋 История"))
    builder.add(KeyboardButton(text="❓ Помощь"))

    # Регулируем раскладку в зависимости от наличия Telegram
    if config.TELEGRAM_PARSER_ENABLED:
        builder.adjust(2, 2, 1, 2, 1)  # С Telegram кнопкой
    else:
        builder.adjust(2, 2, 2, 1)  # Без Telegram кнопки

    return builder.as_markup(resize_keyboard=True)
```

---

## 🔗 БЛОК 5: Интеграция в систему

### ☐ Задача 15: Интегрировать TelegramMonitor в main.py с автозапуском

**Описание:**
- Добавить инициализацию TelegramMonitor в main.py
- Запуск мониторинга в фоновом режиме параллельно с основным ботом
- Корректное завершение при остановке

**Файл:** `main.py`

**Действие:**
```python
# Добавить импорт:
from services.telegram_monitor import TelegramMonitor
import config

# В классе CryptoPromoBot добавить:
class CryptoPromoBot:
    def __init__(self):
        # ... существующие поля ...
        self.telegram_monitor = None  # НОВОЕ

    async def init_services(self):
        """Инициализация всех сервисов"""
        # ... существующий код ...

        # НОВОЕ: Инициализация Telegram Monitor
        if config.TELEGRAM_PARSER_ENABLED:
            logger.info("📡 Инициализация Telegram Monitor...")
            self.telegram_monitor = TelegramMonitor(self.bot)
            logger.info("✅ Telegram Monitor инициализирован")
        else:
            logger.info("ℹ️ Telegram Monitor отключен (TELEGRAM_PARSER_ENABLED=false)")

    async def start(self):
        """Запуск бота"""
        try:
            await self.init_services()
            self.setup_scheduler()
            self.scheduler.start()

            logger.info("🤖 Crypto Promo Bot запускается...")
            logger.info("⏰ Автоматическая проверка активирована")
            logger.info("🎯 Проверяются ТОЛЬКО активные ссылки")
            logger.info("🚫 Остановленные ссылки игнорируются в автоматическом и ручном режиме")

            # НОВОЕ: Запуск Telegram Monitor в фоне (если включен)
            if self.telegram_monitor:
                logger.info("📡 Запуск Telegram Monitor в фоновом режиме...")
                asyncio.create_task(self.telegram_monitor.start())

            # Запускаем поллинг
            await self.dp.start_polling(self.bot)

        except Exception as e:
            logger.error(f"❌ Фатальная ошибка при запуске: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Корректное завершение работы"""
        if self._shutdown_event.is_set():
            return

        self._shutdown_event.set()
        logger.info("🛑 Завершение работы бота...")

        # НОВОЕ: Остановка Telegram Monitor
        if self.telegram_monitor:
            await self.telegram_monitor.shutdown()

        if self.scheduler:
            self.scheduler.shutdown()
        if self.bot:
            await self.bot.close()
        logger.info("👋 Бот завершил работу")
```

**Важно:** Также нужно обеспечить доступ к `telegram_monitor` из handlers для перезагрузки каналов:

```python
# В bot_manager.py добавить метод:
def get_telegram_monitor(self):
    """Получить экземпляр Telegram Monitor"""
    if self._instance and hasattr(self._instance, 'telegram_monitor'):
        return self._instance.telegram_monitor
    return None
```

---

### ☐ Задача 16: Добавить форматирование уведомлений из Telegram в notification_service.py

**Описание:**
- Создать метод для красивого форматирования уведомлений о найденных сообщениях
- Включить: канал, ключевое слово, текст, ссылки, даты

**Файл:** `bot/notification_service.py`

**Действие:**
```python
# Добавить в класс NotificationService:

def format_telegram_promo(self, channel_username: str, message_text: str,
                          matched_keywords: List[str], links: List[str],
                          dates: Optional[str]) -> str:
    """
    Форматирование уведомления о промоакции из Telegram

    Args:
        channel_username: Username канала
        message_text: Текст сообщения
        matched_keywords: Список совпавших ключевых слов
        links: Список найденных ссылок
        dates: Найденные даты (период акции)

    Returns:
        Отформатированное сообщение для отправки
    """
    from utils.telegram_message_processor import TelegramMessageProcessor

    # Анализируем сообщение
    analysis = TelegramMessageProcessor.analyze_message(message_text, matched_keywords)

    # Заголовок
    message = "📡 <b>Новая промоакция из Telegram</b>\n\n"

    # Канал
    message += f"📢 Канал: @{channel_username}\n"

    # Ключевые слова
    keywords_str = ", ".join([f"<code>{kw}</code>" for kw in matched_keywords])
    message += f"🔑 Ключевые слова: {keywords_str}\n\n"

    # Тип акции (если определен)
    if analysis['promo_type'] != 'general':
        type_icons = {
            'airdrop': '🪂',
            'staking': '💰',
            'trading': '📈',
            'campaign': '🎯',
            'launchpool': '🚀'
        }
        icon = type_icons.get(analysis['promo_type'], '📌')
        message += f"{icon} Тип: {analysis['promo_type'].capitalize()}\n"

    # Призовой фонд (если найден)
    if analysis['prize_pool']:
        message += f"💎 Призовой фонд: <b>{analysis['prize_pool']}</b>\n"

    # Период (если найден)
    if dates or analysis['period']:
        period = dates or analysis['period']
        message += f"📅 Период: {period}\n"

    message += "\n"

    # Краткое содержание
    summary = analysis['summary']
    message += f"📝 <b>Описание:</b>\n<i>{summary}</i>\n\n"

    # Ссылки (если есть)
    if links:
        message += "🔗 <b>Ссылки:</b>\n"
        for i, link in enumerate(links[:3], 1):  # Максимум 3 ссылки
            message += f"  {i}. {link}\n"
        message += "\n"

    # Требования (если найдены)
    if analysis['requirements']:
        message += "📋 <b>Требования:</b>\n"
        for req in analysis['requirements'][:3]:  # Максимум 3 пункта
            message += f"  • {req}\n"
        message += "\n"

    # Футер
    message += "━━━━━━━━━━━━━━━━\n"
    message += f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"

    return message
```

---

### ☐ Задача 17: Создать систему фильтрации дубликатов сообщений

**Описание:**
- Избегать повторных уведомлений об одном и том же сообщении
- Проверка по message_id + channel_id
- Опциональное хранение хешей сообщений

**Файл:** `services/telegram_monitor.py`

**Действие:**
```python
# Уже реализовано в задаче 8 через проверку в save_message():

async def save_message(self, channel_id: int, message_id: int, text: str,
                      date: datetime, result: Dict):
    """Сохранение найденного сообщения в БД"""
    try:
        with get_db_session() as db:
            # ПРОВЕРКА ДУБЛИКАТОВ
            existing = db.query(TelegramMessage).filter(
                TelegramMessage.channel_id == channel_id,
                TelegramMessage.message_id == message_id
            ).first()

            if existing:
                logger.debug(f"ℹ️ Сообщение {message_id} уже сохранено (дубликат)")
                return  # НЕ сохраняем повторно

            # ... остальной код сохранения ...

# Дополнительно можно добавить проверку по хешу текста для похожих сообщений:

import hashlib

def calculate_message_hash(text: str) -> str:
    """Вычисление хеша текста сообщения"""
    # Нормализуем текст: убираем пробелы, переводим в нижний регистр
    normalized = ' '.join(text.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()

async def is_duplicate_message(self, channel_id: int, text: str) -> bool:
    """Проверка, является ли сообщение дубликатом по хешу"""
    text_hash = calculate_message_hash(text)

    with get_db_session() as db:
        # Ищем похожие сообщения за последние 30 дней
        from datetime import timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        similar = db.query(TelegramMessage).filter(
            TelegramMessage.channel_id == channel_id,
            TelegramMessage.created_at >= thirty_days_ago
        ).all()

        for msg in similar:
            if calculate_message_hash(msg.message_text) == text_hash:
                return True

        return False
```

---

### ☐ Задача 18: Добавить обработку ошибок и переподключение для Telethon

**Описание:**
- Автоматическое переподключение при потере соединения
- Обработка Flood Wait (429 ошибки от Telegram)
- Логирование всех проблем
- Retry логика

**Файл:** `parsers/telegram_parser.py` и `services/telegram_monitor.py`

**Действие:**
```python
# В telegram_parser.py добавить:

from telethon.errors import (
    FloodWaitError,
    ConnectionError as TelethonConnectionError,
    AuthKeyUnregisteredError,
    PhoneNumberBannedError
)
import asyncio

async def connect_with_retry(self, max_retries: int = 3, retry_delay: int = 5) -> bool:
    """Подключение к Telegram с повторными попытками"""
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔌 Попытка подключения {attempt}/{max_retries}...")

            self.client = TelegramClient('telegram_parser_session', self.api_id, self.api_hash)
            await self.client.start()

            self.is_connected = True
            logger.info("✅ Успешно подключено к Telegram")
            return True

        except PhoneNumberBannedError:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Номер телефона заблокирован Telegram")
            return False

        except AuthKeyUnregisteredError:
            logger.error("❌ Сессия недействительна. Необходима повторная авторизация")
            # Удаляем старую сессию
            import os
            if os.path.exists('telegram_parser_session.session'):
                os.remove('telegram_parser_session.session')

            if attempt < max_retries:
                logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                await asyncio.sleep(retry_delay)
            continue

        except TelethonConnectionError as e:
            logger.error(f"❌ Ошибка соединения: {e}")
            if attempt < max_retries:
                logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                await asyncio.sleep(retry_delay)
            continue

        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка подключения: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
            continue

    logger.error("❌ Не удалось подключиться после всех попыток")
    self.is_connected = False
    return False

async def handle_flood_wait(self, error: FloodWaitError):
    """Обработка FloodWait ошибки"""
    wait_seconds = error.seconds
    logger.warning(f"⏰ Flood Wait: необходимо подождать {wait_seconds} секунд")

    # Если ожидание меньше 5 минут - ждем
    if wait_seconds <= 300:
        logger.info(f"⏳ Ожидание {wait_seconds} сек...")
        await asyncio.sleep(wait_seconds)
        return True
    else:
        logger.error(f"❌ Слишком долгое ожидание ({wait_seconds} сек). Пропускаем.")
        return False

# В telegram_monitor.py добавить reconnect логику:

async def start(self):
    """Запуск мониторинга с автоматическим переподключением"""
    reconnect_delay = 60  # Задержка между попытками переподключения

    while not self._shutdown_event.is_set():
        try:
            if not config.TELEGRAM_PARSER_ENABLED:
                logger.info("ℹ️ Telegram-парсер отключен в конфигурации")
                return

            logger.info("🚀 Запуск Telegram Monitor...")

            # Подключаемся с retry логикой
            connected = await self.parser.connect_with_retry()
            if not connected:
                logger.error("❌ Не удалось подключиться к Telegram")
                logger.info(f"🔄 Повторная попытка через {reconnect_delay} сек...")
                await asyncio.sleep(reconnect_delay)
                continue

            # Загружаем активные каналы
            await self.load_active_channels()

            # Подписываемся на новые сообщения
            self.parser.client.add_event_handler(
                self.handle_new_message,
                events.NewMessage()
            )

            self.is_running = True
            logger.info(f"✅ Telegram Monitor запущен. Отслеживается {len(self.monitored_channels)} каналов")

            # Ожидаем сигнала завершения
            await self._shutdown_event.wait()

        except TelethonConnectionError as e:
            logger.error(f"❌ Потеряно соединение с Telegram: {e}")
            logger.info(f"🔄 Переподключение через {reconnect_delay} сек...")
            await asyncio.sleep(reconnect_delay)
            continue

        except FloodWaitError as e:
            wait_handled = await self.parser.handle_flood_wait(e)
            if not wait_handled:
                await asyncio.sleep(reconnect_delay)
            continue

        except Exception as e:
            logger.error(f"❌ Критическая ошибка Telegram Monitor: {e}", exc_info=True)
            logger.info(f"🔄 Перезапуск через {reconnect_delay} сек...")
            await asyncio.sleep(reconnect_delay)
            continue

        finally:
            if self.is_running:
                await self.stop()
```

---

## 📚 БЛОК 6: Документация и тестирование

### ☐ Задача 19: Создать инструкцию по получению API_ID и API_HASH в README

**Описание:**
- Подробная инструкция для пользователей
- Скриншоты или шаги
- Решение частых проблем

**Файл:** `README.md` или `TELEGRAM_SETUP.md` (НОВЫЙ)

**Действие:**
```markdown
# Настройка Telegram-парсера

## Получение Telegram API Credentials

Для работы Telegram-парсера необходимо получить `API_ID` и `API_HASH` от Telegram.

### Шаг 1: Регистрация приложения

1. Перейдите на https://my.telegram.org/apps
2. Войдите с вашим номером телефона (тот же, что используется в Telegram)
3. Введите код подтверждения, который придет в Telegram

### Шаг 2: Создание приложения

1. Заполните форму создания приложения:
   - **App title**: Crypto Promo Parser (или любое название)
   - **Short name**: crypto_parser (или любое короткое имя)
   - **Platform**: Other
   - **Description**: Parser for monitoring crypto promotions (опционально)

2. Нажмите "Create application"

### Шаг 3: Получение credentials

После создания приложения вы увидите:
- **App api_id**: числовой ID (например: 12345678)
- **App api_hash**: строка из букв и цифр (например: 0123456789abcdef0123456789abcdef)

⚠️ **ВАЖНО**: Никому не передавайте эти данные!

### Шаг 4: Добавление в .env

Откройте файл `.env` в корне проекта и добавьте:

```env
# Telegram Parser
TELEGRAM_PARSER_ENABLED=true
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

### Шаг 5: Первый запуск

При первом запуске бота с включенным Telegram-парсером:

1. Бот попросит ввести ваш номер телефона
2. Вам придет код подтверждения в Telegram
3. Введите код
4. Если у вас включена двухфакторная аутентификация - введите пароль

После успешной авторизации создастся файл сессии `telegram_parser_session.session`.
При следующих запусках авторизация не потребуется.

## Частые проблемы

### Ошибка "Phone number banned"

**Проблема**: Ваш номер заблокирован Telegram за спам.
**Решение**: Используйте другой номер телефона или обратитесь в поддержку Telegram.

### Ошибка "Invalid API_ID or API_HASH"

**Проблема**: Неверные credentials.
**Решение**:
1. Проверьте правильность API_ID и API_HASH в .env
2. API_ID должен быть числом (без кавычек)
3. API_HASH должен быть строкой из 32 символов

### Ошибка "Flood wait"

**Проблема**: Telegram временно ограничил количество запросов.
**Решение**: Бот автоматически подождет необходимое время. Не перезапускайте его.

### Потеря соединения

**Проблема**: Бот отключается от Telegram.
**Решение**: Бот автоматически переподключится. Проверьте интернет-соединение.

## Безопасность

1. **Не публикуйте** ваши API_ID и API_HASH
2. **Не передавайте** файл сессии другим людям
3. **Используйте** .gitignore для исключения .env и .session файлов
4. **Храните** резервную копию .env в безопасном месте

## Дополнительная информация

- Официальная документация Telegram API: https://core.telegram.org/api
- Документация Telethon: https://docs.telethon.dev/
```

---

### ☐ Задача 20: Протестировать полную интеграцию Telegram-парсера

**Описание:**
- Комплексное тестирование всей функциональности
- Проверка всех пользовательских сценариев
- Исправление найденных багов

**Чек-лист тестирования:**

```markdown
# Чек-лист тестирования Telegram-парсера

## Настройка и запуск

- [ ] Установка зависимости Telethon
- [ ] Настройка .env с API credentials
- [ ] Успешный запуск бота с включенным парсером
- [ ] Первая авторизация в Telegram
- [ ] Создание файла сессии
- [ ] Повторный запуск без повторной авторизации

## Интерфейс бота

- [ ] Отображение кнопки "📡 Telegram каналы" в главном меню
- [ ] Открытие меню управления Telegram-каналами
- [ ] Отображение статистики (0 каналов, 0 сообщений)

## Добавление канала

- [ ] Нажатие кнопки "➕ Добавить канал"
- [ ] Ввод @username канала
- [ ] Ввод ссылки t.me/channel
- [ ] Ввод username без @
- [ ] Валидация уже добавленного канала (ошибка)
- [ ] Ввод ключевых слов (одно слово)
- [ ] Ввод ключевых слов (несколько через запятую)
- [ ] Успешное сохранение канала в БД
- [ ] Отображение подтверждения

## Список каналов

- [ ] Просмотр списка добавленных каналов
- [ ] Отображение статуса (активен/приостановлен)
- [ ] Отображение количества ключевых слов
- [ ] Клик по каналу - открытие деталей

## Детали канала

- [ ] Отображение информации о канале
- [ ] Отображение статистики (найдено сообщений, последняя проверка)
- [ ] Список ключевых слов
- [ ] Кнопка приостановки/возобновления
- [ ] Кнопка управления ключевыми словами
- [ ] Кнопка удаления

## Управление ключевыми словами

- [ ] Просмотр списка ключевых слов
- [ ] Добавление нового ключевого слова
- [ ] Добавление нескольких слов через запятую
- [ ] Проверка дубликатов (регистронезависимо)
- [ ] Удаление ключевого слова
- [ ] Обновление статистики после изменений

## Мониторинг каналов

- [ ] Запуск TelegramMonitor при старте бота
- [ ] Загрузка активных каналов из БД
- [ ] Подписка на события NewMessage
- [ ] Получение нового сообщения из канала
- [ ] Проверка совпадения ключевых слов
- [ ] Сохранение сообщения в БД
- [ ] Отправка уведомления админу

## Уведомления

- [ ] Форматирование уведомления о новой промоакции
- [ ] Отображение канала, ключевых слов, текста
- [ ] Извлечение и отображение ссылок
- [ ] Извлечение и отображение дат
- [ ] Определение типа промоакции
- [ ] Красивое форматирование с HTML-тегами

## Фильтрация дубликатов

- [ ] Проверка дубликата по message_id
- [ ] Не отправлять повторное уведомление
- [ ] Не сохранять дубликат в БД
- [ ] Логирование пропуска дубликата

## Приостановка/Возобновление

- [ ] Приостановка мониторинга канала
- [ ] Проверка, что новые сообщения игнорируются
- [ ] Возобновление мониторинга
- [ ] Проверка, что мониторинг работает снова

## Удаление канала

- [ ] Подтверждение удаления
- [ ] Удаление канала из БД
- [ ] Удаление всех связанных сообщений
- [ ] Обновление списка каналов
- [ ] Остановка мониторинга удаленного канала

## Обработка ошибок

- [ ] Потеря соединения с Telegram - автопереподключение
- [ ] FloodWaitError - автоматическое ожидание
- [ ] Недоступный канал - логирование ошибки
- [ ] Приватный канал без доступа - сообщение пользователю
- [ ] Некорректный API_ID/API_HASH - понятная ошибка

## Производительность

- [ ] Мониторинг 5+ каналов одновременно
- [ ] Обработка сообщений с большим текстом (>1000 символов)
- [ ] Обработка сообщений с множеством ссылок
- [ ] Нет утечек памяти при длительной работе
- [ ] Корректная работа при высокой частоте сообщений

## Завершение работы

- [ ] Корректное завершение TelegramMonitor при остановке бота
- [ ] Отключение от Telegram
- [ ] Сохранение состояния
- [ ] Нет зависших процессов

## Дополнительно

- [ ] Работа с каналами на разных языках (русский, английский)
- [ ] Работа с эмодзи в сообщениях
- [ ] Работа со специальными символами
- [ ] Обработка медиа-сообщений (фото, видео)
- [ ] Обработка форвардов сообщений
```

---

## ✅ Критерии завершения проекта

Telegram-парсер считается полностью интегрированным, когда:

1. ✅ Все 20 задач выполнены
2. ✅ Пройден полный чек-лист тестирования
3. ✅ Нет критических багов
4. ✅ Документация создана и понятна
5. ✅ Бот работает стабильно с Telegram-парсером
6. ✅ Пользователь может самостоятельно:
   - Добавлять/удалять каналы
   - Настраивать ключевые слова
   - Получать уведомления о промоакциях
   - Управлять мониторингом

---

## 🎯 Приоритеты выполнения

### Критическая важность (делать в первую очередь):
- Задачи 1-6: Инфраструктура и база данных
- Задачи 7-9: Парсер и мониторинг
- Задача 15: Интеграция в main.py

### Высокая важность:
- Задачи 10-14: Интерфейс бота
- Задачи 16-18: Уведомления и обработка ошибок

### Средняя важность:
- Задача 19: Документация
- Задача 20: Финальное тестирование

---

**Дата начала:** _____________

**Предполагаемая дата завершения:** _____________

**Статус:** ⏳ Не начато

**Ответственный:** _____________

---

**Примечания:**

_Здесь можно добавлять заметки, идеи, найденные проблемы и решения в процессе разработки._
