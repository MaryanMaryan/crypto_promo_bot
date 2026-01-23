import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
from telethon import events
from telethon.errors import (
    FloodWaitError,
    PhoneNumberBannedError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError
)
from parsers.telegram_parser import TelegramParser
from data.database import get_db_session
from data.models import ApiLink, PromoHistory
from utils.promo_formatter import format_promo_header
import config

logger = logging.getLogger(__name__)

class TelegramMonitor:
    """Сервис мониторинга Telegram-каналов"""

    def __init__(self, bot):
        self.bot = bot
        self.parser = TelegramParser()
        self.is_running = False
        self.monitored_channels = {}
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Запуск мониторинга с автоматическим переподключением"""
        reconnect_delay = 60  # Задержка между попытками переподключения

        while not self._shutdown_event.is_set():
            try:
                if not config.TELEGRAM_PARSER_ENABLED:
                    logger.info("ℹ️ Telegram-парсер отключен в конфигурации")
                    return

                # Проверяем, настроен ли Telegram API
                if not self.parser.is_configured():
                    logger.warning("⚠️ Telegram API не настроен. Настройте API_ID и API_HASH в разделе 'Обход блокировок' → 'Telegram API'")
                    logger.info("ℹ️ Telegram Monitor будет ожидать настройки API...")
                    await asyncio.sleep(reconnect_delay)
                    continue

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

                # Подписываемся на новые сообщения для ВСЕХ подключенных клиентов
                for account_id, client_data in self.parser.clients.items():
                    if client_data['is_connected']:
                        client_data['client'].add_event_handler(
                            self.handle_new_message,
                            events.NewMessage()
                        )
                        logger.info(f"👾 Event handler добавлен для аккаунта {client_data['account']['name']}")

                connected_count = self.parser.get_connected_clients_count()
                self.is_running = True
                logger.info(f"✅ Telegram Monitor запущен. {connected_count} аккаунтов отслеживают {len(self.monitored_channels)} каналов")

                # Ожидаем сигнала завершения
                await self._shutdown_event.wait()

            except (PhoneNumberBannedError, AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
                # НОВОЕ: Обработка блокировки аккаунта с fallback
                logger.error(f"❌ Обнаружена блокировка аккаунта: {type(e).__name__}")
                # Примечание: в этом контексте мы не знаем конкретный account_id
                # Блокировка будет обработана при следующем подключении в parser.connect()
                logger.info(f"🔄 Переподключение через {reconnect_delay} сек...")
                await asyncio.sleep(reconnect_delay)
                continue

            except ConnectionError as e:
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

    async def stop(self):
        """Остановка мониторинга с корректным отключением клиентов"""
        logger.info("🛑 Остановка Telegram Monitor...")
        self.is_running = False

        if self.parser:
            try:
                # Ждём завершения текущих операций (таймаут 10 сек)
                await asyncio.wait_for(self.parser.disconnect(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("⏰ Таймаут остановки парсера, принудительное завершение")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка остановки парсера: {e}")

        logger.info("✅ Telegram Monitor остановлен")

    async def shutdown(self):
        """Сигнал завершения работы"""
        self._shutdown_event.set()

    async def load_active_channels(self):
        """Загрузка активных Telegram-ссылок из БД"""
        try:
            with get_db_session() as db:
                # Загружаем активные ссылки с типом 'telegram'
                telegram_links = db.query(ApiLink).filter(
                    ApiLink.parsing_type == 'telegram',
                    ApiLink.is_active == True,
                    ApiLink.telegram_channel.isnot(None)
                ).all()

                self.monitored_channels.clear()

                for link in telegram_links:
                    # Нормализуем имя канала (убираем @ если есть)
                    channel_username = link.telegram_channel
                    if channel_username.startswith('@'):
                        channel_username = channel_username[1:]

                    self.monitored_channels[channel_username] = {
                        'api_link_id': link.id,
                        'name': link.name,
                        'keywords': link.get_telegram_keywords(),
                        'telegram_channel': link.telegram_channel
                    }

                logger.info(f"📋 Загружено {len(self.monitored_channels)} активных Telegram-каналов")

                # Отображаем список каналов
                if self.monitored_channels:
                    for username, data in self.monitored_channels.items():
                        keywords_count = len(data['keywords'])
                        keywords_preview = ', '.join(data['keywords'][:3])  # Показываем первые 3 ключевых слова
                        if keywords_count > 3:
                            keywords_preview += f" (+{keywords_count - 3} еще)"
                        
                        logger.info(f"   • @{username} ({data['name']}) - {keywords_count} ключевых слов")
                        logger.info(f"     Ключевые слова: {keywords_preview}")
                else:
                    logger.info("   Нет активных каналов для мониторинга")

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Telegram-каналов: {e}")

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

            # Пропускаем сообщения без текста
            if not message.text:
                return

            # ВАЖНО: Если keywords пустой, это ошибка конфигурации - логируем и пропускаем
            if not keywords:
                logger.warning(f"⚠️ Канал @{channel_username} ({channel_data['name']}) не имеет ключевых слов! Пропускаем сообщение.")
                return

            # Обрабатываем сообщение
            logger.debug(f"🔍 Проверка сообщения из @{channel_username} на ключевые слова: {', '.join(keywords)}")
            result = await self.parser.process_message(message.text, keywords)

            if result and result.get('matched_keywords'):
                # СТРОГАЯ ПРОВЕРКА: result существует И matched_keywords не пустой
                logger.info(f"✅ НАЙДЕНО СОВПАДЕНИЕ в канале @{channel_username}!")
                logger.info(f"   🔑 Найденные ключевые слова: {', '.join(result['matched_keywords'])}")
                logger.info(f"   📝 Текст сообщения: {message.text[:100]}...")

                # Сохраняем в БД
                await self.save_message(
                    channel_data['api_link_id'],
                    message.id,
                    message.text,
                    message.date,
                    result,
                    channel_username
                )

                # Отправляем уведомление (пересылаем оригинальное сообщение)
                # ВАЖНО: Уведомление отправляется СРАЗУ, не через send_bulk_notifications из main.py
                await self.send_notification(
                    channel_username,
                    message,  # Передаем весь message объект для пересылки
                    result
                )
            else:
                # Сообщение не содержит ключевые слова - НЕ отправляем уведомление
                logger.debug(f"⏭️ Сообщение из @{channel_username} не содержит ключевые слова - пропускаем")
                return

        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")

    async def save_message(self, api_link_id: int, message_id: int, text: str,
                          date: datetime, result: Dict, channel_username: str):
        """Сохранение найденного сообщения в БД (PromoHistory)"""
        try:
            # КРИТИЧЕСКАЯ ПРОВЕРКА: Ключевые слова должны быть найдены!
            if not result or not result.get('matched_keywords'):
                logger.error(f"❌ ОШИБКА: save_message вызван БЕЗ ключевых слов! Пропускаем.")
                return

            with get_db_session() as db:
                # Генерируем уникальный promo_id на основе канала и message_id
                promo_id = f"telegram_{channel_username}_{message_id}"

                # Проверяем, не сохранено ли уже (фильтрация дубликатов)
                existing = db.query(PromoHistory).filter(
                    PromoHistory.promo_id == promo_id
                ).first()

                if existing:
                    logger.debug(f"ℹ️ Сообщение {message_id} уже сохранено (дубликат)")
                    return

                # Получаем информацию о ссылке
                api_link = db.query(ApiLink).filter(ApiLink.id == api_link_id).first()

                # Формируем описание с ключевыми словами и датами
                description = text[:500]  # Ограничиваем длину описания
                if result['dates']:
                    description = f"📅 {result['dates']}\n\n{description}"

                # Формируем ссылку на сообщение в Telegram
                message_link = None
                if result['links']:
                    message_link = result['links'][0]  # Первая ссылка из сообщения
                else:
                    # Ссылка на сообщение в канале
                    message_link = f"https://t.me/{channel_username}/{message_id}"

                # Создаем новую запись в PromoHistory
                promo = PromoHistory(
                    api_link_id=api_link_id,
                    promo_id=promo_id,
                    exchange=api_link.name if api_link else "Telegram",
                    title=f"📱 Telegram: @{channel_username}",
                    description=description,
                    total_prize_pool=", ".join(result['matched_keywords']),  # Сохраняем ключевые слова
                    award_token=None,
                    start_time=date,
                    end_time=None,
                    link=message_link,
                    icon=None
                )

                db.add(promo)
                db.commit()

                # Обновляем last_checked для ApiLink
                if api_link:
                    api_link.last_checked = datetime.utcnow()
                    db.commit()

                logger.info(f"💾 Сообщение сохранено в PromoHistory")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения сообщения: {e}")

    async def send_notification(self, channel_username: str, message, result: Dict):
        """Отправка уведомления о найденном сообщении

        Args:
            channel_username: Имя канала
            message: Объект сообщения Telethon (для пересылки) или текст (для ручных проверок)
            result: Результат обработки (ключевые слова, ссылки и т.д.)
        """
        try:
            # КРИТИЧЕСКАЯ ПРОВЕРКА: НЕ отправляем уведомление если нет ключевых слов!
            if not result or not result.get('matched_keywords'):
                logger.error(f"❌ ОШИБКА: send_notification вызван БЕЗ ключевых слов! Отмена отправки.")
                return

            # Получаем текст и ID сообщения
            if hasattr(message, 'id') and hasattr(message, 'chat'):
                message_text = message.text or ""
                message_id = message.id
            else:
                message_text = message if isinstance(message, str) else str(message)
                message_id = None

            # Форматируем единое уведомление
            notification = self._format_telegram_notification(
                channel_username=channel_username,
                message_text=message_text,
                message_id=message_id,
                matched_keywords=result.get('matched_keywords', []),
                links=result.get('links', []),
                dates=result.get('dates')
            )

            # Отправляем ВСЕМ получателям уведомлений
            recipients = getattr(config, 'ALL_NOTIFICATION_RECIPIENTS', [config.ADMIN_CHAT_ID])
            sent_count = 0
            
            for chat_id in recipients:
                try:
                    await self.bot.send_message(
                        chat_id,
                        notification,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось отправить уведомление в {chat_id}: {e}")

            logger.info(f"✅ Уведомление отправлено {sent_count}/{len(recipients)} получателям")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")

    def _format_telegram_notification(
        self,
        channel_username: str,
        message_text: str,
        message_id: Optional[int],
        matched_keywords: List[str],
        links: List[str],
        dates: Optional[str]
    ) -> str:
        """
        Универсальный форматер для Telegram уведомлений.
        Создает единое красиво оформленное сообщение с подсветкой ключевых слов.
        
        Args:
            channel_username: Имя канала (без @)
            message_text: Текст оригинального сообщения
            message_id: ID сообщения в Telegram (для ссылки)
            matched_keywords: Список найденных ключевых слов
            links: Список ссылок из сообщения
            dates: Найденные даты
            
        Returns:
            Отформатированное HTML сообщение
        """
        import html
        import re
        
        # === ЗАГОЛОВОК ===
        promo_header = format_promo_header(
            name=channel_username,
            promo_type='telegram',
            is_new=True
        )
        notification = f"{promo_header}\n\n"
        
        # === КАНАЛ ===
        notification += f"📱 <b>Канал:</b> @{channel_username}\n\n"
        
        # === СООБЩЕНИЕ С ПОДСВЕТКОЙ КЛЮЧЕВЫХ СЛОВ ===
        # Ограничиваем длину текста (макс 500 символов)
        truncated = len(message_text) > 500
        display_text = message_text[:500] if truncated else message_text
        
        # Экранируем HTML
        safe_text = html.escape(display_text)
        
        # Подсвечиваем ключевые слова тегом <u> (подчеркивание)
        for keyword in matched_keywords:
            # Создаем паттерн для регистронезависимого поиска
            escaped_keyword = re.escape(html.escape(keyword))
            pattern = re.compile(f'({escaped_keyword})', re.IGNORECASE)
            safe_text = pattern.sub(r'<u>\1</u>', safe_text)
        
        notification += f"📝 <b>Сообщение:</b>\n{safe_text}"
        if truncated:
            notification += "..."
        notification += "\n\n"
        
        # === ТРИГГЕРЫ ===
        if matched_keywords:
            keywords_str = ", ".join([f"<code>{html.escape(kw)}</code>" for kw in matched_keywords])
            notification += f"🔑 <b>Триггеры:</b> {keywords_str}\n"
        
        # === ДАТЫ (если есть) ===
        if dates:
            notification += f"📅 <b>Период:</b> {html.escape(dates)}\n"
        
        # === ССЫЛКА НА СООБЩЕНИЕ ===
        if message_id:
            tg_link = f"https://t.me/{channel_username}/{message_id}"
            notification += f"🔗 <a href=\"{tg_link}\">Открыть в Telegram</a>\n"
        elif links:
            # Показываем первую найденную ссылку
            notification += f"🔗 <a href=\"{links[0]}\">Ссылка из сообщения</a>\n"
            if len(links) > 1:
                notification += f"    <i>(+{len(links)-1} ещё)</i>\n"
        
        # === ВРЕМЯ ===
        notification += f"\n⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        
        return notification

    def _format_basic_notification(self, channel_username: str, message_text: str,
                                   matched_keywords: List[str], links: List[str],
                                   dates: Optional[str]) -> str:
        """Обратная совместимость - вызывает новый форматер"""
        return self._format_telegram_notification(
            channel_username=channel_username,
            message_text=message_text,
            message_id=None,
            matched_keywords=matched_keywords,
            links=links,
            dates=dates
        )

    async def reload_channels(self):
        """Перезагрузка списка отслеживаемых каналов"""
        logger.info("🔄 Перезагрузка списка каналов...")
        await self.load_active_channels()

    async def force_check_channel(self, link_id: int) -> Optional[Dict]:
        """
        Принудительная проверка конкретного Telegram канала.
        Получает последние сообщения и проверяет их на ключевые слова.
        
        Args:
            link_id: ID ссылки в БД
            
        Returns:
            Словарь с результатами проверки или None при ошибке
        """
        try:
            logger.info(f"🔍 Принудительная проверка Telegram канала (link_id={link_id})")
            
            # Получаем данные ссылки
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                
                if not link:
                    logger.error(f"❌ Ссылка {link_id} не найдена")
                    return None
                
                if link.parsing_type != 'telegram':
                    logger.error(f"❌ Ссылка {link_id} не является Telegram ({link.parsing_type})")
                    return None
                
                if not link.telegram_channel:
                    logger.error(f"❌ Telegram канал не указан для ссылки {link_id}")
                    return None
                
                channel_data = {
                    'api_link_id': link.id,
                    'name': link.name,
                    'telegram_channel': link.telegram_channel,
                    'keywords': link.get_telegram_keywords(),
                    'telegram_account_id': link.telegram_account_id
                }
            
            channel_username = channel_data['telegram_channel']
            if channel_username.startswith('@'):
                channel_username = channel_username[1:]
            
            keywords = channel_data['keywords']
            
            logger.info(f"📱 Канал: @{channel_username}")
            logger.info(f"🔑 Ключевые слова: {', '.join(keywords) if keywords else 'НЕ УКАЗАНЫ'}")
            
            # Проверяем, подключен ли парсер
            if not self.parser or not self.parser.is_configured():
                logger.error("❌ Telegram парсер не настроен")
                return {'error': 'Telegram парсер не настроен', 'new_messages': []}
            
            # Подключаемся ТОЛЬКО если ещё не подключены
            if not self.parser.is_connected or self.parser.get_connected_clients_count() == 0:
                logger.info("🔌 Парсер не подключён, выполняем подключение...")
                connected = await self.parser.connect_with_retry()
                if not connected:
                    logger.error("❌ Не удалось подключиться к Telegram")
                    return {'error': 'Не удалось подключиться к Telegram', 'new_messages': []}
            
            # Получаем последние сообщения из канала
            new_messages = []
            
            # Находим клиента для этого канала
            client_data = None
            account_id = channel_data.get('telegram_account_id')
            
            if account_id and account_id in self.parser.clients:
                client_data = self.parser.clients[account_id]
            else:
                # Используем первого подключенного клиента
                for acc_id, data in self.parser.clients.items():
                    if data.get('is_connected'):
                        client_data = data
                        break
            
            if not client_data or not client_data.get('is_connected'):
                logger.error("❌ Нет подключенных Telegram клиентов")
                return {'error': 'Нет подключенных Telegram клиентов', 'new_messages': []}
            
            client = client_data['client']
            
            try:
                # Получаем последние 10 сообщений из канала
                entity = await client.get_entity(channel_username)
                messages = await client.get_messages(entity, limit=10)
                
                logger.info(f"📥 Получено {len(messages)} последних сообщений")
                
                for msg in messages:
                    if not msg.text:
                        continue
                    
                    # Если нет ключевых слов - показываем все сообщения
                    if not keywords:
                        new_messages.append({
                            'id': msg.id,
                            'text': msg.text[:200],
                            'date': msg.date.isoformat() if msg.date else None,
                            'matched_keywords': []
                        })
                        continue
                    
                    # Проверяем на ключевые слова
                    result = await self.parser.process_message(msg.text, keywords)
                    
                    if result and result.get('matched_keywords'):
                        new_messages.append({
                            'id': msg.id,
                            'text': msg.text[:200],
                            'date': msg.date.isoformat() if msg.date else None,
                            'matched_keywords': result['matched_keywords']
                        })
                        
                        # Отправляем уведомление
                        await self.send_notification(channel_username, msg, result)
                        
                        # Сохраняем в БД
                        await self.save_message(
                            channel_data['api_link_id'],
                            msg.id,
                            msg.text,
                            msg.date,
                            result,
                            channel_username
                        )
                
                # Обновляем время проверки
                with get_db_session() as db:
                    link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                    if link:
                        link.last_checked = datetime.utcnow()
                        db.commit()
                
                logger.info(f"✅ Проверка завершена. Найдено совпадений: {len(new_messages)}")
                
                return {
                    'success': True,
                    'channel': f"@{channel_username}",
                    'new_messages': new_messages,
                    'checked_messages': len(messages)
                }
                
            except Exception as e:
                logger.error(f"❌ Ошибка получения сообщений из канала: {e}")
                return {'error': str(e), 'new_messages': []}
            
        except Exception as e:
            logger.error(f"❌ Ошибка принудительной проверки канала: {e}", exc_info=True)
            return {'error': str(e), 'new_messages': []}