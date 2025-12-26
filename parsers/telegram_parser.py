import re
import logging
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
    """Парсер для мониторинга Telegram-каналов"""

    def __init__(self, api_id: Optional[str] = None, api_hash: Optional[str] = None, session_file: Optional[str] = None):
        """
        Инициализация парсера

        Args:
            api_id: Telegram API ID (если None - загружается из БД)
            api_hash: Telegram API Hash (если None - загружается из БД)
            session_file: Имя файла сессии (если None - загружается из БД)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_file = session_file or 'telegram_parser_session'
        self.client = None
        self.is_connected = False

        # Если credentials не переданы - загружаем из БД
        if not self.api_id or not self.api_hash:
            self._load_settings_from_db()

        # Паттерны для извлечения данных
        self.url_pattern = re.compile(r'https?://[^\s]+')
        self.date_pattern = re.compile(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}')

    def _load_settings_from_db(self):
        """Загрузка настроек Telegram из базы данных"""
        try:
            from data.database import get_db_session
            from data.models import TelegramSettings

            with get_db_session() as db:
                settings = db.query(TelegramSettings).first()

                if settings and settings.is_configured:
                    self.api_id = settings.api_id
                    self.api_hash = settings.api_hash
                    self.session_file = settings.session_file or 'telegram_parser_session'
                    logger.info("✅ Настройки Telegram загружены из БД")
                else:
                    logger.warning("⚠️ Telegram API не настроен в БД")
                    self.api_id = None
                    self.api_hash = None

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки настроек Telegram из БД: {e}")
            self.api_id = None
            self.api_hash = None

    def is_configured(self) -> bool:
        """Проверка наличия API credentials"""
        return bool(self.api_id and self.api_hash)

    async def connect(self):
        """Подключение к Telegram"""
        try:
            if not self.is_configured():
                logger.error("❌ Telegram API не настроен. Настройте API_ID и API_HASH в разделе 'Обход блокировок'")
                return False

            logger.info("🔌 Подключение к Telegram...")

            self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
            await self.client.start()

            self.is_connected = True
            logger.info("✅ Успешно подключено к Telegram")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Telegram: {e}")
            self.is_connected = False

            # Закрываем клиент при ошибке
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass

            return False

    async def connect_with_retry(self, max_retries: int = 3, retry_delay: int = 5) -> bool:
        """Подключение к Telegram с повторными попытками"""
        if not self.is_configured():
            logger.error("❌ Telegram API не настроен. Настройте API_ID и API_HASH в разделе 'Обход блокировок'")
            return False

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"🔌 Попытка подключения {attempt}/{max_retries}...")

                self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
                await self.client.start()

                self.is_connected = True
                logger.info("✅ Успешно подключено к Telegram")
                return True

            except PhoneNumberBannedError:
                logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Номер телефона заблокирован Telegram")
                # Закрываем клиент
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                return False

            except AuthKeyUnregisteredError:
                logger.error("❌ Сессия недействительна. Необходима повторная авторизация")

                # Закрываем клиент
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass

                # Удаляем старую сессию
                import os
                session_path = f'{self.session_file}.session'
                if os.path.exists(session_path):
                    os.remove(session_path)
                    logger.info(f"🗑️ Удалена старая сессия: {session_path}")

                if attempt < max_retries:
                    logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                    await asyncio.sleep(retry_delay)
                continue

            except ConnectionError as e:
                logger.error(f"❌ Ошибка соединения: {e}")
                # Закрываем клиент
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass

                if attempt < max_retries:
                    logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                    await asyncio.sleep(retry_delay)
                continue

            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка подключения: {e}")
                # Закрываем клиент
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass

                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                continue

        logger.error("❌ Не удалось подключиться после всех попыток")
        self.is_connected = False

        # Финальная очистка клиента
        if self.client:
            try:
                await self.client.disconnect()
            except:
                pass

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
        """Отключение от Telegram"""
        if self.client:
            try:
                await self.client.disconnect()
                self.is_connected = False
                logger.info("👋 Отключено от Telegram")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при отключении от Telegram: {e}")
                self.is_connected = False

    def __del__(self):
        """Деструктор для гарантированного закрытия клиента"""
        if self.client and self.is_connected:
            try:
                # Получаем event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если loop уже запущен, создаем задачу на отключение
                    asyncio.create_task(self.client.disconnect())
                else:
                    # Если loop не запущен, запускаем синхронно
                    loop.run_until_complete(self.client.disconnect())
            except:
                pass  # Игнорируем ошибки в деструкторе

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

    async def join_channel(self, channel_username: str) -> bool:
        """
        Подписаться на канал

        Returns:
            bool: True если подписка успешна или уже подписан, False если ошибка
        """
        try:
            if not self.is_connected:
                logger.error("❌ Не подключено к Telegram")
                return False

            entity = await self.client.get_entity(channel_username)

            # Проверяем, подписаны ли уже
            try:
                participant = await self.client.get_permissions(entity)
                if participant.is_admin or participant.is_creator or hasattr(participant, 'until_date'):
                    logger.info(f"✅ Уже подписан на канал {channel_username}")
                    return True
            except:
                pass  # Если не подписаны - продолжаем

            # Подписываемся на канал
            await self.client(
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
