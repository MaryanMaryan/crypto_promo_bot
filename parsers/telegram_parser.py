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
        """Загрузка активных и авторизованных аккаунтов из БД с retry логикой"""
        import time
        from sqlite3 import OperationalError
        
        max_retries = 3
        retry_delay = 1  # секунды
        
        for attempt in range(1, max_retries + 1):
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

            except OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < max_retries:
                    logger.warning(f"⚠️ База данных заблокирована, попытка {attempt}/{max_retries}. Повтор через {retry_delay}с...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Экспоненциальная задержка
                    continue
                else:
                    logger.error(f"❌ Ошибка загрузки аккаунтов из БД: {e}")
                    return []
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки аккаунтов из БД: {e}")
                return []
        
        return []

    def is_configured(self) -> bool:
        """Проверка наличия API credentials"""
        return bool(self.api_id and self.api_hash)

    def _enable_wal_for_session(self, session_file: str):
        """Включить WAL режим для сессионного файла Telethon"""
        import sqlite3
        import os
        
        # Проверяем что файл существует
        if not os.path.exists(session_file):
            return
        
        try:
            conn = sqlite3.connect(session_file, timeout=60.0)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=60000')
            conn.commit()
            conn.close()
            logger.debug(f"✅ WAL режим включен для сессии {os.path.basename(session_file)}")
        except Exception as e:
            logger.debug(f"⚠️ Не удалось включить WAL для сессии {os.path.basename(session_file)}: {e}")

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

            # Подключаем каждый аккаунт ПОСЛЕДОВАТЕЛЬНО с задержками
            connected_count = 0
            for idx, account in enumerate(accounts):
                # Добавляем задержку между подключениями для избежания конфликтов БД
                if idx > 0:
                    await asyncio.sleep(1.5)  # 1.5 секунды между подключениями (увеличено)
                
                # Пытаемся подключить аккаунт с retry логикой
                max_retries = 3
                retry_delay = 1.0  # Начальная задержка 1 секунда (увеличено)
                
                for attempt in range(1, max_retries + 1):
                    try:
                        # Включаем WAL режим для session файла
                        session_file = account['session_file']
                        self._enable_wal_for_session(session_file)
                        
                        client = TelegramClient(session_file, self.api_id, self.api_hash)
                        await client.connect()

                        # Проверяем авторизацию
                        if not await client.is_user_authorized():
                            logger.warning(f"⚠️ Аккаунт {account['name']} не авторизован, пропускаем")
                            await client.disconnect()
                            break  # Выходим из retry цикла

                        self.clients[account['id']] = {
                            'client': client,
                            'account': account,
                            'is_connected': True
                        }
                        connected_count += 1
                        logger.info(f"✅ Аккаунт {account['name']} ({account['phone_number']}) подключен")
                        break  # Успешно подключились, выходим из retry цикла

                    except (PhoneNumberBannedError, AuthKeyUnregisteredError) as e:
                        # Блокирующие ошибки - не ретраим
                        logger.error(f"❌ Аккаунт {account['name']} заблокирован: {type(e).__name__}")
                        await self.handle_client_error(account['id'], e)
                        break  # Выходим из retry цикла

                    except Exception as e:
                        error_msg = str(e)
                        if "database is locked" in error_msg.lower() and attempt < max_retries:
                            logger.warning(f"⚠️ БД заблокирована при подключении {account['name']}, попытка {attempt}/{max_retries}")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Экспоненциальная задержка
                            continue
                        else:
                            logger.error(f"❌ Ошибка подключения аккаунта {account['name']}: {e}")
                            break  # Выходим из retry цикла

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
        if hasattr(self, 'clients') and self.clients:
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

    async def handle_client_error(self, account_id: int, error: Exception) -> bool:
        """
        Обработка ошибок клиента с определением блокировки

        Args:
            account_id: ID аккаунта, на котором произошла ошибка
            error: Исключение которое произошло

        Returns:
            bool: True если аккаунт заблокирован и нужен fallback, False иначе
        """
        from datetime import datetime

        # Определяем блокирующие ошибки
        blocking_errors = {
            PhoneNumberBannedError: "PhoneNumberBanned",
            AuthKeyUnregisteredError: "AuthKeyUnregistered",
        }

        # Проверяем, является ли ошибка блокирующей
        error_type = type(error)
        blocked_reason = None

        if error_type in blocking_errors:
            blocked_reason = blocking_errors[error_type]
        elif isinstance(error, FloodWaitError) and error.seconds > 3600:
            # FloodWait больше часа считаем блокировкой
            blocked_reason = f"FloodWait_{error.seconds}s"
        else:
            # Не блокирующая ошибка
            logger.warning(f"Не блокирующая ошибка для аккаунта {account_id}: {error}")
            return False

        # Помечаем аккаунт как заблокированный в БД
        import time
        from sqlite3 import OperationalError
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(1, max_retries + 1):
            try:
                from data.database import get_db_session
                from data.models import TelegramAccount

                with get_db_session() as db:
                    account = db.query(TelegramAccount).filter_by(id=account_id).first()
                    if account:
                        account.is_blocked = True
                        account.blocked_at = datetime.utcnow()
                        account.blocked_reason = blocked_reason
                        account.last_error = str(error)
                        db.commit()

                        logger.error(f"❌ Аккаунт {account.name} (ID: {account_id}) заблокирован. Причина: {blocked_reason}")

                        # Отключаем клиент от парсера
                        if account_id in self.clients:
                            try:
                                await self.clients[account_id]['client'].disconnect()
                            except:
                                pass
                            self.clients[account_id]['is_connected'] = False

                        return True
                    else:
                        logger.error(f"❌ Аккаунт ID {account_id} не найден в БД")
                        return False
                        
            except OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < max_retries:
                    logger.warning(f"⚠️ База данных заблокирована при обновлении аккаунта, попытка {attempt}/{max_retries}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"❌ Ошибка при пометке аккаунта как заблокированного: {e}")
                    return False
            except Exception as e:
                logger.error(f"❌ Ошибка при пометке аккаунта как заблокированного: {e}")
                return False
        
        return False

    async def switch_account_for_link(self, link_id: int, old_account_id: int) -> Optional[int]:
        """
        Переключить аккаунт для парсинга ссылки (fallback)

        Args:
            link_id: ID ссылки для переключения
            old_account_id: ID заблокированного аккаунта

        Returns:
            int: ID нового аккаунта или None если не удалось
        """
        try:
            from data.database import get_db_session
            from data.models import TelegramAccount, ApiLink
            from sqlalchemy import func

            with get_db_session() as db:
                link = db.query(ApiLink).filter_by(id=link_id).first()
                if not link:
                    logger.error(f"❌ Ссылка ID {link_id} не найдена")
                    return None

                # Находим доступные аккаунты (активные, авторизованные, не заблокированные)
                available_accounts = db.query(TelegramAccount).filter(
                    TelegramAccount.is_active == True,
                    TelegramAccount.is_authorized == True,
                    TelegramAccount.is_blocked == False,
                    TelegramAccount.id != old_account_id  # Исключаем старый аккаунт
                ).all()

                if not available_accounts:
                    logger.error(f"❌ Нет доступных аккаунтов для замены аккаунта ID {old_account_id}")
                    return None

                # Load balancing: выбираем аккаунт с наименьшим количеством назначенных ссылок
                account_loads = []
                for acc in available_accounts:
                    # Считаем количество назначенных активных ссылок
                    load_count = db.query(func.count(ApiLink.id)).filter(
                        ApiLink.telegram_account_id == acc.id,
                        ApiLink.is_active == True,
                        ApiLink.parsing_type == 'telegram'
                    ).scalar()
                    account_loads.append((acc, load_count))

                # Сортируем по нагрузке (меньше нагрузка = выше приоритет)
                account_loads.sort(key=lambda x: x[1])
                new_account = account_loads[0][0]

                old_account_name = db.query(TelegramAccount).filter_by(id=old_account_id).first()
                old_name = old_account_name.name if old_account_name else f"ID {old_account_id}"

                logger.info(f"🔄 Fallback: {old_name} → {new_account.name} для ссылки '{link.name}'")

                # Переназначаем ссылку на новый аккаунт
                link.telegram_account_id = new_account.id
                db.commit()

                # Переподключаемся к каналу с новым аккаунтом
                if link.telegram_channel and new_account.id in self.clients:
                    try:
                        await self.join_channel(link.telegram_channel, new_account.id)
                        logger.info(f"✅ Переподключено к каналу {link.telegram_channel} с аккаунтом {new_account.name}")
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось переподключиться к каналу: {e}")

                return new_account.id

        except Exception as e:
            logger.error(f"❌ Ошибка при переключении аккаунта: {e}")
            return None
