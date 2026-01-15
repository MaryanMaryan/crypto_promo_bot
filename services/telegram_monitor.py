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

            # Если message - это объект Telethon Message, пересылаем его
            if hasattr(message, 'id') and hasattr(message, 'chat'):
                # Сначала отправляем заголовок с информацией
                header = f"🎉 <b>НОВАЯ ПРОМОАКЦИЯ!</b>\n\n"
                header += f"<b>🏢 Биржа:</b> @{channel_username}\n"

                if result.get('matched_keywords'):
                    keywords_str = ", ".join([f"<code>{kw}</code>" for kw in result['matched_keywords']])
                    header += f"<b>🔑 Найденные ключевые слова:</b> {keywords_str}\n"

                header += f"━━━━━━━━━━━━━━━━\n"

                await self.bot.send_message(
                    config.ADMIN_CHAT_ID,
                    header,
                    parse_mode="HTML"
                )

                # Затем копируем оригинальное сообщение (без пометки "Forwarded")
                # Используем copy_message вместо forward_message для публичных каналов
                try:
                    await self.bot.copy_message(
                        chat_id=config.ADMIN_CHAT_ID,
                        from_chat_id=message.chat.id,
                        message_id=message.id
                    )
                    logger.info(f"✅ Оригинальное сообщение скопировано админу")
                except Exception as copy_error:
                    # Если копирование не удалось, отправляем текст
                    logger.warning(f"⚠️ Не удалось скопировать сообщение: {copy_error}")
                    await self.bot.send_message(
                        config.ADMIN_CHAT_ID,
                        message.text,
                        parse_mode=None
                    )
                    logger.info(f"✅ Текст сообщения отправлен админу")

            else:
                # Если message - это просто текст (из ручной проверки), используем старый формат
                message_text = message if isinstance(message, str) else str(message)
                notification = self._format_basic_notification(
                    channel_username,
                    message_text,
                    result['matched_keywords'],
                    result['links'],
                    result['dates']
                )

                await self.bot.send_message(
                    config.ADMIN_CHAT_ID,
                    notification,
                    parse_mode="HTML"
                )

                logger.info(f"✅ Уведомление отправлено админу")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")

    def _format_basic_notification(self, channel_username: str, message_text: str,
                                   matched_keywords: List[str], links: List[str],
                                   dates: Optional[str]) -> str:
        """Базовое форматирование уведомления"""
        # Создаем краткую версию текста (максимум 300 символов)
        summary = message_text[:300] + "..." if len(message_text) > 300 else message_text

        message = "🎉 <b>НОВАЯ ПРОМОАКЦИЯ!</b>\n\n"
        message += f"<b>🏢 Биржа:</b> @{channel_username}\n"

        keywords_str = ", ".join([f"<code>{kw}</code>" for kw in matched_keywords])
        message += f"<b>🔑 Найденные ключевые слова:</b> {keywords_str}\n\n"

        if dates:
            message += f"📅 Период: {dates}\n\n"

        message += f"📝 <b>Описание:</b>\n<i>{summary}</i>\n\n"

        if links:
            message += "🔗 <b>Ссылки:</b>\n"
            for i, link in enumerate(links[:3], 1):
                message += f"  {i}. {link}\n"
            message += "\n"

        message += "━━━━━━━━━━━━━━━━\n"
        message += f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        return message

    async def reload_channels(self):
        """Перезагрузка списка отслеживаемых каналов"""
        logger.info("🔄 Перезагрузка списка каналов...")
        await self.load_active_channels()
