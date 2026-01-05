import re
import logging
import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    AuthKeyUnregisteredError,
    PhoneNumberBannedError
)
from telethon.tl.types import Channel, User
import asyncio

logger = logging.getLogger(__name__)

class TelegramParser:
    """Парсер для мониторинга Telegram-каналов с поддержкой нескольких аккаунтов"""

    def __init__(self, api_id: Optional[str] = None, api_hash: Optional[str] = None):
        """
        Инициализация парсера

        Args:
            api_id: Telegram API ID (если None - загружается из БД)
            api_hash: Telegram API Hash (если None - загружается из БД)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.clients = {}  # account_id -> {'client': TelegramClient, 'account': dict, 'is_connected': bool}
        self.is_connected = False

        # Если credentials не переданы - загружаем из БД
        if not self.api_id or not self.api_hash:
            self._load_settings_from_db()

        # Паттерны для извлечения данных
        self.url_pattern = re.compile(r'https?://[^\s]+')
        self.date_pattern = re.compile(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}')

    def _load_settings_from_db(self):
        """Загрузка настроек Telegram API из базы данных"""
        try:
            from data.database import get_db_session
            from data.models import TelegramSettings

            with get_db_session() as db:
                settings = db.query(TelegramSettings).first()

                if settings and settings.api_id and settings.api_hash:
                    self.api_id = settings.api_id
                    self.api_hash = settings.api_hash
                    logger.info("✅ Telegram API credentials загружены из БД")
                else:
                    logger.warning("⚠️ Telegram API не настроен в БД")
                    self.api_id = None
                    self.api_hash = None

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки настроек Telegram из БД: {e}")
            self.api_id = None
            self.api_hash = None

    def _load_accounts_from_db(self) -> List[Dict]:
        """Загрузка активных и авторизованных аккаунтов из БД"""
        try:
            from data.database import get_db_session
            from data.models import TelegramAccount

            with get_db_session() as db:
                accounts = db.query(TelegramAccount).filter_by(
                    is_active=True,
                    is_authorized=True
                ).all()

                # Конвертируем в словари
                result = []
                for acc in accounts:
                    result.append({
                        'id': acc.id,
                        'name': acc.name,
                        'phone_number': acc.phone_number,
                        'session_file': acc.session_file
                    })

                logger.info(f"📋 Загружено {len(result)} активных аккаунтов из БД")
                return result

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки аккаунтов из БД: {e}")
            return []

    def is_configured(self) -> bool:
        """Проверка наличия API credentials"""
        return bool(self.api_id and self.api_hash)

    def get_connected_clients_count(self) -> int:
        """Получить количество подключенных клиентов"""
        return sum(1 for c in self.clients.values() if c['is_connected'])

    def get_random_client(self) -> Optional[TelegramClient]:
        """Получить случайный подключенный клиент для распределения нагрузки"""
        connected = [c['client'] for c in self.clients.values() if c['is_connected']]
        if connected:
            return random.choice(connected)
        return None

    def get_client_by_id(self, account_id: int) -> Optional[TelegramClient]:
        """Получить клиент конкретного аккаунта"""
        client_data = self.clients.get(account_id)
        if client_data and client_data['is_connected']:
            return client_data['client']
        return None

    async def connect(self):
        """Подключение всех активных аккаунтов к Telegram"""
        try:
            if not self.is_configured():
                logger.error("❌ Telegram API не настроен. Настройте API_ID и API_HASH в разделе 'Обход блокировок'")
                return False

            # Загружаем аккаунты из БД
            accounts = self._load_accounts_from_db()

            if not accounts:
                logger.warning("⚠️ Нет активных аккаунтов в БД. Добавьте аккаунты в разделе 'Обход блокировок → Telegram API'")
                return False

            logger.info(f"🔌 Подключение {len(accounts)} аккаунтов к Telegram...")

            # Подключаем каждый аккаунт
            connected_count = 0
            for account in accounts:
                try:
                    client = TelegramClient(account['session_file'], self.api_id, self.api_hash)
                    await client.connect()

                    # Проверяем авторизацию
                    if not await client.is_user_authorized():
                        logger.warning(f"⚠️ Аккаунт {account['name']} не авторизован, пропускаем")
                        await client.disconnect()
                        continue

                    self.clients[account['id']] = {
                        'client': client,
                        'account': account,
                        'is_connected': True
                    }
                    connected_count += 1
                    logger.info(f"✅ Аккаунт {account['name']} ({account['phone_number']}) подключен")

                except Exception as e:
                    logger.error(f"❌ Ошибка подключения аккаунта {account['name']}: {e}")
                    continue

            if connected_count > 0:
                self.is_connected = True
                logger.info(f"✅ Подключено {connected_count} из {len(accounts)} аккаунтов")
                return True
            else:
                logger.error("❌ Не удалось подключить ни один аккаунт")
                return False

        except Exception as e:
            logger.error(f"❌ Критическая ошибка подключения: {e}")
            self.is_connected = False
            return False

    async def connect_with_retry(self, max_retries: int = 3, retry_delay: int = 5) -> bool:
        """Подключение всех аккаунтов к Telegram с повторными попытками"""
        for attempt in range(1, max_retries + 1):
            logger.info(f"🔌 Попытка подключения {attempt}/{max_retries}...")

            if await self.connect():
                return True

            if attempt < max_retries:
                logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                await asyncio.sleep(retry_delay)

        logger.error("❌ Не удалось подключиться после всех попыток")
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

    async def disconnect(self):
        """Отключение всех аккаунтов от Telegram"""
        disconnected_count = 0
        for account_id, client_data in list(self.clients.items()):
            try:
                if client_data['is_connected']:
                    await client_data['client'].disconnect()
                    client_data['is_connected'] = False
                    disconnected_count += 1
                    logger.info(f"👋 Отключен аккаунт {client_data['account']['name']}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка отключения аккаунта {client_data['account']['name']}: {e}")

        self.is_connected = False
        logger.info(f"👋 Отключено {disconnected_count} аккаунтов от Telegram")

    def __del__(self):
        """Деструктор для гарантированного закрытия всех клиентов"""
        if self.clients:
            try:
                # Получаем event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если loop уже запущен, создаем задачу на отключение
                    for client_data in self.clients.values():
                        if client_data['is_connected']:
                            asyncio.create_task(client_data['client'].disconnect())
                else:
                    # Если loop не запущен, запускаем синхронно
                    loop.run_until_complete(self.disconnect())
            except:
                pass  # Игнорируем ошибки в деструкторе

    async def get_channel_info(self, channel_username: str, account_id: Optional[int] = None) -> Optional[Dict]:
        """
        Получить информацию о канале

        Args:
            channel_username: Username канала
            account_id: ID конкретного аккаунта (если None - используется случайный)
        """
        try:
            client = self.get_client_by_id(account_id) if account_id else self.get_random_client()

            if not client:
                logger.error("❌ Нет подключенных аккаунтов")
                return None

            entity = await client.get_entity(channel_username)

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

    async def join_channel(self, channel_username: str, account_id: Optional[int] = None) -> bool:
        """
        Подписаться на канал

        Args:
            channel_username: Username канала
            account_id: ID конкретного аккаунта (если None - используется случайный)

        Returns:
            bool: True если подписка успешна или уже подписан, False если ошибка
        """
        try:
            if not self.is_connected:
                logger.error("❌ Не подключено к Telegram")
                return False

            client = self.get_client_by_id(account_id) if account_id else self.get_random_client()

            if not client:
                logger.error("❌ Нет подключенных аккаунтов")
                return False

            entity = await client.get_entity(channel_username)

            # Проверяем, подписаны ли уже
            try:
                participant = await client.get_permissions(entity)
                if participant.is_admin or participant.is_creator or hasattr(participant, 'until_date'):
                    logger.info(f"✅ Уже подписан на канал {channel_username}")
                    return True
            except:
                pass  # Если не подписаны - продолжаем

            # Подписываемся на канал
            await client(
                __import__('telethon.tl.functions.channels', fromlist=['JoinChannelRequest']).JoinChannelRequest(entity)
            )

            logger.info(f"✅ Успешно подписан на канал {channel_username}")
            return True

        except FloodWaitError as e:
            logger.error(f"⏰ Flood Wait при подписке на {channel_username}: нужно подождать {e.seconds} сек")
            return False

        except Exception as e:
            logger.error(f"❌ Ошибка подписки на канал {channel_username}: {e}")
            return False

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

    async def get_recent_messages(self, channel_username: str, limit: int = 10, account_id: Optional[int] = None) -> List[Dict]:
        """
        Получить последние сообщения из канала

        Args:
            channel_username: Username канала
            limit: Количество сообщений
            account_id: ID конкретного аккаунта (если None - используется случайный)
        """
        try:
            client = self.get_client_by_id(account_id) if account_id else self.get_random_client()

            if not client:
                logger.error("❌ Нет подключенных аккаунтов")
                return []

            messages = []

            async for message in client.iter_messages(channel_username, limit=limit):
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
