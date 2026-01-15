import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import router
from bot.telegram_account_handlers import router as telegram_account_router
from data.database import init_database, get_db_session, ApiLink
from data.models import StakingHistory, PromoHistory
from services.stability_tracker_service import StabilityTrackerService
from bot.parser_service import ParserService
from bot.notification_service import NotificationService
from bot.bot_manager import bot_manager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os
import signal
import sys

# Импортируем конфигурацию из config.py
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CryptoPromoBot:
    def __init__(self):
        self.bot = None
        self.dp = None
        self.scheduler = None
        self.parser_service = None
        self.notification_service = None
        self.telegram_monitor = None  # Telegram Monitor
        self.telegram_monitor_task = None  # Задача мониторинга Telegram
        self.YOUR_CHAT_ID = config.ADMIN_CHAT_ID
        self._shutdown_event = asyncio.Event()

    async def init_services(self):
        """Инициализация всех сервисов"""
        from data.database import init_database, DatabaseMigration
        from utils.playwright_checker import ensure_playwright_ready

        # Проверка Playwright ПЕРЕД инициализацией (критично для browser_parser)
        logger.info("🔍 Проверка готовности Playwright...")
        if not ensure_playwright_ready():
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Playwright не готов к работе")
            logger.error("🔧 Парсинг через браузер (browser_parser) будет недоступен")
            logger.error("💡 Решение: Запустите 'playwright install chromium'")
            # НЕ прерываем запуск - остальные парсеры могут работать
        else:
            logger.info("✅ Playwright готов к работе")

        init_database()
        
        # Запуск миграций
        migration_runner = DatabaseMigration()
        migration_runner.run_migrations()

        self.bot = Bot(token=config.BOT_TOKEN)
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)
        self.parser_service = ParserService()
        self.notification_service = NotificationService(self.bot)

        # Инициализация Telegram Monitor (если включен)
        if config.TELEGRAM_PARSER_ENABLED:
            from services.telegram_monitor import TelegramMonitor
            self.telegram_monitor = TelegramMonitor(self.bot)
            logger.info("📡 Telegram Monitor инициализирован")
        else:
            logger.info("ℹ️ Telegram Parser отключен (TELEGRAM_PARSER_ENABLED=false)")

        # Регистрируем роутеры (telegram_account_router ПЕРВЫМ для перехвата bypass_telegram)
        self.dp.include_router(telegram_account_router)
        self.dp.include_router(router)

        # Настройка обработчиков завершения
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов для graceful shutdown"""
        try:
            for sig in [signal.SIGINT, signal.SIGTERM]:
                signal.signal(sig, self._signal_handler)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось настроить обработчики сигналов: {e}")

    def _signal_handler(self, signum, frame):
        """Обработчик сигналов завершения"""
        logger.info(f"🛑 Получен сигнал завершения {signum}")
        asyncio.create_task(self.shutdown())

    def _get_promo_count_for_link(self, link_id: int) -> int:
        """Получить количество промоакций для конкретной ссылки"""
        try:
            with get_db_session() as db:
                count = db.query(PromoHistory).filter(PromoHistory.api_link_id == link_id).count()
                return count
        except Exception as e:
            logger.error(f"❌ Ошибка подсчета промоакций: {e}")
            return 0

    async def smart_auto_check(self):
        """Умная автоматическая проверка - ТОЛЬКО АКТИВНЫЕ ссылки (Вариант 1: Компактный)"""
        try:
            logger.info("🤖 Запуск автоматической проверки АКТИВНЫХ ссылок...")

            # Собираем данные ссылок в контексте сессии
            links_data = []
            with get_db_session() as db:
                links = db.query(ApiLink).filter(ApiLink.is_active == True).all()

                if not links:
                    logger.info("ℹ️ Нет активных ссылок для автоматической проверки")
                    return

                # Собираем все данные в словари (детач от сессии)
                for link in links:
                    links_data.append({
                        'id': link.id,
                        'name': link.name,
                        'url': link.url,
                        'check_interval': link.check_interval,
                        'last_checked': link.last_checked,
                        'exchange': link.exchange or 'Unknown',
                        'category': link.category or 'general',
                        'parsing_type': link.parsing_type or '',  # КРИТИЧНО: Для фильтрации Telegram
                        'api_url': link.api_url,
                        'page_url': link.page_url,
                        'min_apr': link.min_apr  # КРИТИЧНО: Добавлен min_apr для фильтрации
                    })

            total_checked = 0
            total_new_promos = 0

            # Обрабатываем ссылки ВНЕ контекста сессии
            for link_data in links_data:
                if self._shutdown_event.is_set():
                    logger.info("⏹️ Проверка прервана из-за завершения работы")
                    return

                # Проверяем, нужно ли проверять эту ссылку
                current_time = datetime.utcnow()
                time_since_last_check = current_time - (link_data['last_checked'] or datetime.min)
                needs_check = time_since_last_check.total_seconds() >= link_data['check_interval']

                if needs_check:
                    # Проверяем категорию и тип парсинга
                    category = link_data.get('category', 'general')
                    parsing_type = link_data.get('parsing_type', '')

                    # ВАЖНО: Пропускаем Telegram ссылки - они обрабатываются в реальном времени через TelegramMonitor
                    if parsing_type == 'telegram':
                        logger.debug(f"⏭️ Пропускаем Telegram ссылку {link_data['name']} - обрабатывается через TelegramMonitor")
                        continue

                    if category == 'staking':
                        # СТЕЙКИНГ: используем parse_staking_link()
                        logger.info(f"💰 Проверка стейкинга: {link_data['name']}")

                        # Автоопределение биржи если exchange не указан
                        from utils.exchange_detector import detect_exchange_from_url
                        api_url = link_data.get('api_url') or link_data['url']
                        exchange = link_data.get('exchange')
                        if not exchange or exchange in ['Unknown', 'None', '']:
                            exchange = detect_exchange_from_url(api_url)
                            logger.info(f"🔍 Автоопределение биржи: {exchange}")

                        # Получаем min_apr из настроек
                        min_apr = link_data.get('min_apr')

                        # Синхронный вызов в отдельном потоке
                        loop = asyncio.get_event_loop()
                        new_stakings = await loop.run_in_executor(
                            None,
                            self.parser_service.parse_staking_link,
                            link_data['id'],
                            api_url,
                            exchange,
                            link_data.get('page_url'),
                            min_apr
                        )

                        new_count = len(new_stakings) if new_stakings else 0

                        if new_count > 0:
                            logger.info(f"🎉 Найдено {new_count} новых стейкингов")

                            # Отправляем уведомления о новых стейкингах
                            # Проверяем, это группа пулов OKX или обычные стейкинги
                            if new_stakings and new_stakings[0].get('_is_okx_group'):
                                # OKX: все пулы в одном сообщении
                                pools = new_stakings[0].get('_group_pools', new_stakings)
                                message = self.notification_service.format_okx_project(
                                    pools,
                                    page_url=link_data.get('page_url')
                                )
                                await self.bot.send_message(
                                    self.YOUR_CHAT_ID,
                                    message,
                                    parse_mode='HTML'
                                )
                            else:
                                # Обычные стейкинги: по одному уведомлению
                                for staking in new_stakings:
                                    message = self.notification_service.format_new_staking(
                                        staking,
                                        page_url=link_data.get('page_url')
                                    )
                                    await self.bot.send_message(
                                        self.YOUR_CHAT_ID,
                                        message,
                                        parse_mode='HTML'
                                    )

                                    # КРИТИЧНО: Отмечаем уведомление как отправленное
                                    staking_db_id = staking.get('_staking_db_id')
                                    if staking_db_id:
                                        try:
                                            with get_db_session() as db:
                                                staking_record = db.query(StakingHistory).filter(
                                                    StakingHistory.id == staking_db_id
                                                ).first()

                                                if staking_record:
                                                    stability_tracker = StabilityTrackerService(db)
                                                    stability_tracker.mark_notification_sent(staking_record)
                                                    db.commit()
                                                    logger.info(f"✅ Отмечено как отправленное: {staking.get('coin')} (ID: {staking_db_id})")
                                        except Exception as e:
                                            logger.error(f"❌ Ошибка mark_notification_sent для {staking.get('coin')}: {e}")
                            total_new_promos += new_count
                        else:
                            logger.info(f"✅ Все стейкинги уже известны")

                    elif category == 'announcement':
                        # АНОНСЫ: используем check_announcement_link()
                        logger.info(f"📢 Проверка анонсов: {link_data['name']}")

                        # Синхронный вызов в отдельном потоке
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None,
                            self.parser_service.check_announcement_link,
                            link_data['id'],
                            link_data['url']
                        )

                        if result and result.get('changed'):
                            logger.info(f"🎉 Обнаружены изменения в анонсах!")

                            # Формируем уведомление
                            message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                            message += f"📝 Ссылка: {link_data['name']}\n"
                            message += f"🔍 Стратегия: {result.get('strategy')}\n"
                            message += f"💬 {result.get('message')}\n\n"
                            if result.get('matched_content'):
                                message += f"📄 Найдено:\n{result.get('matched_content')[:500]}\n\n"
                            
                            # Добавляем найденные ссылки на конкретные анонсы
                            if result.get('announcement_links'):
                                announcement_links = result.get('announcement_links')
                                message += f"🎯 <b>Найдено анонсов: {len(announcement_links)}</b>\n\n"
                                for i, ann in enumerate(announcement_links[:5], 1):  # Показываем топ-5
                                    title = ann.get('title', 'Без названия')
                                    url = ann.get('url', '')
                                    description = ann.get('description', '')
                                    keywords = ', '.join(ann.get('matched_keywords', []))
                                    
                                    message += f"{i}. <a href=\"{url}\">{title}</a>\n"
                                    if description:
                                        # Отображаем первые 150 символов описания
                                        desc_short = description[:150] + '...' if len(description) > 150 else description
                                        message += f"   📝 {desc_short}\n"
                                    if keywords:
                                        message += f"   🔑 {keywords}\n"
                                    message += "\n"
                            else:
                                # Ссылки не найдены - показываем информационное сообщение
                                message += "⚠️ <i>Конкретные ссылки на анонсы не извлечены</i>\n"
                                
                                # Добавляем отладочную информацию, если она есть
                                if result.get('debug_info'):
                                    debug = result['debug_info']
                                    message += f"<i>📊 Всего ссылок на странице: {debug.get('total_links_on_page', 0)}</i>\n"
                                    message += f"<i>🌐 Браузерный парсинг: {'✅ включен' if debug.get('browser_parsing_enabled') else '❌ ВЫКЛЮЧЕН'}</i>\n"
                                    message += f"<i>📄 Размер страницы: {debug.get('page_size', 0):,} байт</i>\n"
                                    
                                    if not debug.get('browser_parsing_enabled'):
                                        message += "\n<b>💡 Рекомендация:</b> <i>Включите браузерный парсинг для этой ссылки</i>\n"
                                
                                message += "<i>Откройте страницу ниже для просмотра</i>\n\n"
                            
                            message += f"🔗 <a href=\"{result.get('url')}\">Открыть страницу со всеми анонсами</a>"

                            # Отправляем уведомление
                            await self.bot.send_message(
                                self.YOUR_CHAT_ID,
                                message,
                                parse_mode='HTML'
                            )
                            total_new_promos += 1
                        else:
                            logger.info(f"✅ Изменений в анонсах не обнаружено")

                    else:
                        # ОБЫЧНЫЕ ПРОМОАКЦИИ: используем check_for_new_promos()
                        # Получаем количество ДО проверки
                        count_before = self._get_promo_count_for_link(link_data['id'])

                        # Синхронный вызов в отдельном потоке
                        loop = asyncio.get_event_loop()
                        new_promos = await loop.run_in_executor(
                            None, self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
                        )

                        # Получаем количество ПОСЛЕ проверки
                        count_after = self._get_promo_count_for_link(link_data['id'])
                        new_count = len(new_promos) if new_promos else 0

                        # КОМПАКТНЫЙ ВЫВОД (Вариант 1)
                        if new_count > 0:
                            logger.info(f"🔍 Проверка: {link_data['name']}")
                            logger.info(f"🎉 Проверено успешно | Было: {count_before} → Стало: {count_after} | Новых: {new_count}")
                        else:
                            logger.info(f"🔍 Проверка: {link_data['name']}")
                            logger.info(f"✅ Проверено успешно | Было: {count_before} → Стало: {count_after} | Новых: 0")

                        # Отправляем уведомления о новых промоакциях
                        if new_promos:
                            await self.notification_service.send_bulk_notifications(
                                self.YOUR_CHAT_ID, new_promos
                            )
                            total_new_promos += new_count

                    # Обновляем время последней проверки в НОВОЙ сессии
                    with get_db_session() as db:
                        link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                        if link:
                            link.last_checked = current_time
                            db.commit()

                    total_checked += 1
                else:
                    # Логируем оставшееся время
                    remaining_time = link_data['check_interval'] - time_since_last_check.total_seconds()
                    logger.debug(f"⏰ Пропускаем {link_data['name']} - след. проверка через {remaining_time:.0f}сек")

            # ИТОГОВАЯ СВОДКА
            if total_checked > 0:
                logger.info("━" * 60)
                logger.info(f"📊 ИТОГО: Проверено {total_checked} биржи | Найдено {total_new_promos} новых промоакций")
            else:
                logger.info("ℹ️ Нет активных ссылок для проверки в этот раз")

        except Exception as e:
            logger.error(f"❌ Ошибка автоматической проверки: {e}")

    async def manual_check_all_links(self, chat_id: int):
        """Ручная проверка - ТОЛЬКО АКТИВНЫЕ ссылки (Вариант 2: Детальная таблица)"""
        try:
            import time
            start_time = time.time()

            # Заголовок
            logger.info("╔" + "═" * 62 + "╗")
            logger.info("║" + "         🔍 РЕЗУЛЬТАТЫ РУЧНОЙ ПРОВЕРКИ".ljust(62) + "║")
            logger.info("╚" + "═" * 62 + "╝")
            logger.info("")

            # Собираем данные ссылок в контексте сессии
            links_data = []
            with get_db_session() as db:
                links = db.query(ApiLink).filter(ApiLink.is_active == True).all()

                if not links:
                    logger.warning("⚠️ Нет активных ссылок для проверки")
                    await self.bot.send_message(chat_id, "❌ Нет активных ссылок для проверки")
                    return

                # Детач данных
                for link in links:
                    links_data.append({
                        'id': link.id,
                        'name': link.name,
                        'url': link.url,
                        'exchange': link.exchange or 'Unknown',
                        'category': link.category or 'general',
                        'api_url': link.api_url,
                        'page_url': link.page_url,
                        'min_apr': link.min_apr  # КРИТИЧНО: Добавлен min_apr для фильтрации
                    })

            # Результаты проверки для таблицы
            check_results = []
            total_new_promos = 0
            total_promos_in_db = 0

            # Обрабатываем ссылки
            for link_data in links_data:
                if self._shutdown_event.is_set():
                    logger.warning("⏹️ Проверка прервана пользователем")
                    await self.bot.send_message(chat_id, "⏹️ Проверка прervана")
                    return

                try:
                    category = link_data.get('category', 'general')

                    if category == 'staking':
                        # СТЕЙКИНГ
                        # Автоопределение биржи если exchange не указан
                        from utils.exchange_detector import detect_exchange_from_url
                        api_url = link_data.get('api_url') or link_data['url']
                        exchange = link_data.get('exchange')
                        if not exchange or exchange in ['Unknown', 'None', '']:
                            exchange = detect_exchange_from_url(api_url)
                            logger.info(f"🔍 Автоопределение биржи: {exchange}")

                        # Получаем min_apr из настроек
                        min_apr = link_data.get('min_apr')

                        loop = asyncio.get_event_loop()
                        new_stakings = await loop.run_in_executor(
                            None,
                            self.parser_service.parse_staking_link,
                            link_data['id'],
                            api_url,
                            exchange,
                            link_data.get('page_url'),
                            min_apr
                        )

                        new_count = len(new_stakings) if new_stakings else 0
                        count_after = 0  # Для стейкинга не считаем total_promos_in_db

                        # Определяем статус
                        if new_count > 0:
                            status = "💰 Новые стейкинги!"
                        else:
                            status = "✅ Без изменений"

                        # Сохраняем результат
                        check_results.append({
                            'name': link_data['name'],
                            'before': '-',
                            'after': '-',
                            'new': new_count,
                            'status': status
                        })

                        # Отправляем уведомления о стейкингах
                        if new_stakings:
                            # Проверяем, это группа пулов OKX или обычные стейкинги
                            if new_stakings[0].get('_is_okx_group'):
                                # OKX: все пулы в одном сообщении
                                pools = new_stakings[0].get('_group_pools', new_stakings)
                                message = self.notification_service.format_okx_project(
                                    pools,
                                    page_url=link_data.get('page_url')
                                )
                                await self.bot.send_message(chat_id, message, parse_mode='HTML')
                            else:
                                # Обычные стейкинги: по одному уведомлению
                                for staking in new_stakings:
                                    message = self.notification_service.format_new_staking(
                                        staking,
                                        page_url=link_data.get('page_url')
                                    )
                                    await self.bot.send_message(chat_id, message, parse_mode='HTML')

                                    # КРИТИЧНО: Отмечаем уведомление как отправленное
                                    staking_db_id = staking.get('_staking_db_id')
                                    if staking_db_id:
                                        try:
                                            with get_db_session() as db:
                                                staking_record = db.query(StakingHistory).filter(
                                                    StakingHistory.id == staking_db_id
                                                ).first()

                                                if staking_record:
                                                    stability_tracker = StabilityTrackerService(db)
                                                    stability_tracker.mark_notification_sent(staking_record)
                                                    db.commit()
                                                    logger.info(f"✅ Отмечено как отправленное: {staking.get('coin')} (ID: {staking_db_id})")
                                        except Exception as e:
                                            logger.error(f"❌ Ошибка mark_notification_sent для {staking.get('coin')}: {e}")
                            total_new_promos += new_count

                    elif category == 'announcement':
                        # АНОНСЫ
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None,
                            self.parser_service.check_announcement_link,
                            link_data['id'],
                            link_data['url']
                        )

                        new_count = 1 if result and result.get('changed') else 0

                        # Определяем статус
                        if new_count > 0:
                            status = "📢 Изменения!"
                        else:
                            status = "✅ Без изменений"

                        # Сохраняем результат
                        check_results.append({
                            'name': link_data['name'],
                            'before': '-',
                            'after': '-',
                            'new': new_count,
                            'status': status
                        })

                        # Отправляем уведомление если были изменения
                        if result and result.get('changed'):
                            message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                            message += f"📝 Ссылка: {link_data['name']}\n"
                            message += f"🔍 Стратегия: {result.get('strategy')}\n"
                            message += f"💬 {result.get('message')}\n\n"
                            if result.get('matched_content'):
                                message += f"📄 Найдено:\n{result.get('matched_content')[:500]}\n\n"
                            
                            # Добавляем найденные ссылки на конкретные анонсы
                            if result.get('announcement_links'):
                                announcement_links = result.get('announcement_links')
                                message += f"🎯 <b>Найдено анонсов: {len(announcement_links)}</b>\n\n"
                                for i, ann in enumerate(announcement_links[:5], 1):  # Показываем топ-5
                                    title = ann.get('title', 'Без названия')
                                    url = ann.get('url', '')
                                    description = ann.get('description', '')
                                    keywords = ', '.join(ann.get('matched_keywords', []))
                                    
                                    message += f"{i}. <a href=\"{url}\">{title}</a>\n"
                                    if description:
                                        desc_short = description[:150] + '...' if len(description) > 150 else description
                                        message += f"   📝 {desc_short}\n"
                                    if keywords:
                                        message += f"   🔑 {keywords}\n"
                                    message += "\n"
                            else:
                                message += "⚠️ <i>Конкретные ссылки на анонсы не извлечены</i>\n"
                                
                                if result.get('debug_info'):
                                    debug = result['debug_info']
                                    message += f"<i>📊 Всего ссылок: {debug.get('total_links_on_page', 0)}</i>\n"
                                    message += f"<i>🌐 Браузерный парсинг: {'✅' if debug.get('browser_parsing_enabled') else '❌ ВЫКЛЮЧЕН'}</i>\n"
                                    if not debug.get('browser_parsing_enabled'):
                                        message += "<b>💡 Включите браузерный парсинг</b>\n"
                                
                                message += "<i>Откройте страницу ниже для просмотра</i>\n\n"
                            
                            message += f"🔗 <a href=\"{result.get('url')}\">Открыть страницу со всеми анонсами</a>"

                            await self.bot.send_message(chat_id, message, parse_mode='HTML')
                            total_new_promos += new_count

                    else:
                        # ОБЫЧНЫЕ ПРОМОАКЦИИ
                        # Получаем количество ДО проверки
                        count_before = self._get_promo_count_for_link(link_data['id'])

                        # Синхронный вызов в отдельном потоке
                        loop = asyncio.get_event_loop()
                        new_promos = await loop.run_in_executor(
                            None, self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
                        )

                        # Получаем количество ПОСЛЕ проверки
                        count_after = self._get_promo_count_for_link(link_data['id'])
                        new_count = len(new_promos) if new_promos else 0

                        # Определяем статус
                        if new_count > 0:
                            status = "🎉 Новые акции!"
                        else:
                            status = "✅ Без изменений"

                        # Сохраняем результат
                        check_results.append({
                            'name': link_data['name'],
                            'before': count_before,
                            'after': count_after,
                            'new': new_count,
                            'status': status
                        })

                        # Отправляем уведомления
                        if new_promos:
                            await self.notification_service.send_bulk_notifications(chat_id, new_promos)
                            total_new_promos += new_count

                    # Обновляем время проверки
                    with get_db_session() as db:
                        link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                        if link:
                            link.last_checked = datetime.utcnow()
                            db.commit()

                    total_promos_in_db += count_after

                except Exception as e:
                    # В случае ошибки добавляем в таблицу как ERROR
                    check_results.append({
                        'name': link_data['name'],
                        'before': 'ERROR',
                        'after': 'ERROR',
                        'new': '-',
                        'status': f"❌ {str(e)[:20]}..."
                    })
                    logger.error(f"❌ Ошибка проверки {link_data['name']}: {e}", exc_info=True)
                    continue

            # ВЫВОД ТАБЛИЦЫ (Вариант 2)
            logger.info("┌" + "─" * 12 + "┬" + "─" * 9 + "┬" + "─" * 9 + "┬" + "─" * 9 + "┬" + "─" * 18 + "┐")
            logger.info("│ " + "Биржа".ljust(10) + " │ " + "Было".ljust(7) + " │ " + "Стало".ljust(7) + " │ " + "Новых".ljust(7) + " │ " + "Статус".ljust(16) + " │")
            logger.info("├" + "─" * 12 + "┼" + "─" * 9 + "┼" + "─" * 9 + "┼" + "─" * 9 + "┼" + "─" * 18 + "┤")

            for result in check_results:
                name = result['name'][:10].ljust(10)
                before = str(result['before']).ljust(7)
                after = str(result['after']).ljust(7)
                new = str(result['new']).ljust(7)
                status = result['status'][:16].ljust(16)
                logger.info(f"│ {name} │ {before} │ {after} │ {new} │ {status} │")

            logger.info("└" + "─" * 12 + "┴" + "─" * 9 + "┴" + "─" * 9 + "┴" + "─" * 9 + "┴" + "─" * 18 + "┘")
            logger.info("")

            # ИТОГОВАЯ СТАТИСТИКА
            elapsed_time = time.time() - start_time
            success_count = len([r for r in check_results if r['before'] != 'ERROR'])
            error_count = len([r for r in check_results if r['before'] == 'ERROR'])

            logger.info(f"📊 Всего промоакций в базе: {total_promos_in_db}")
            logger.info(f"🆕 Добавлено новых: {total_new_promos}")
            logger.info(f"⏱️  Время проверки: {elapsed_time:.1f} сек")
            logger.info("")

            # Сообщение пользователю
            success_rate = (success_count / len(check_results) * 100) if check_results else 0
            message = (
                f"✅ Проверка завершена\n"
                f"📊 Всего бирж: {len(check_results)} | Успешно: {success_count} | Ошибок: {error_count}\n"
                f"🆕 Новых промоакций: {total_new_promos}\n"
                f"💾 База данных: {total_promos_in_db} промоакций\n"
                f"⏱️ Затрачено: {elapsed_time:.1f} сек"
            )

            await self.bot.send_message(chat_id, message)
            logger.info("=" * 64)

        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ручной проверки: {e}", exc_info=True)
            await self.bot.send_message(chat_id, "❌ Произошла ошибка при проверке")

    async def force_check_specific_link(self, chat_id: int, link_id: int):
        """Принудительная проверка конкретной ссылки (даже если она остановлена)"""
        try:
            # Получаем данные ссылки
            link_data = None
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if not link:
                    await self.bot.send_message(chat_id, "❌ Ссылка не найдена")
                    return

                # Детач данных
                link_data = {
                    'id': link.id,
                    'name': link.name,
                    'url': link.url,
                    'exchange': link.exchange or 'Unknown',
                    'category': link.category or 'general',
                    'api_url': link.api_url,
                    'page_url': link.page_url,
                    'min_apr': link.min_apr  # КРИТИЧНО: Добавлен min_apr для фильтрации
                }

            logger.info(f"🔧 Принудительная проверка ссылки {link_data['name']} (ID: {link_id})")

            # Проверяем категорию ссылки
            category = link_data.get('category', 'general')

            if category == 'staking':
                # СТЕЙКИНГ: используем parse_staking_link()
                logger.info(f"💰 Принудительная проверка стейкинга: {link_data['name']}")

                # Автоопределение биржи если exchange не указан
                from utils.exchange_detector import detect_exchange_from_url
                api_url = link_data.get('api_url') or link_data['url']
                exchange = link_data.get('exchange')
                if not exchange or exchange in ['Unknown', 'None', '']:
                    exchange = detect_exchange_from_url(api_url)
                    logger.info(f"🔍 Автоопределение биржи: {exchange}")

                # Получаем min_apr из настроек
                min_apr = link_data.get('min_apr')

                # Синхронный вызов в отдельном потоке
                loop = asyncio.get_event_loop()
                new_stakings = await loop.run_in_executor(
                    None,
                    self.parser_service.parse_staking_link,
                    link_data['id'],
                    api_url,
                    exchange,
                    link_data.get('page_url'),
                    min_apr
                )

                # Отправляем уведомления о стейкингах
                if new_stakings:
                    for staking in new_stakings:
                        message = self.notification_service.format_new_staking(
                            staking,
                            page_url=link_data.get('page_url')
                        )
                        await self.bot.send_message(chat_id, message, parse_mode='HTML')

                        # КРИТИЧНО: Отмечаем уведомление как отправленное
                        staking_db_id = staking.get('_staking_db_id')
                        if staking_db_id:
                            try:
                                with get_db_session() as db:
                                    staking_record = db.query(StakingHistory).filter(
                                        StakingHistory.id == staking_db_id
                                    ).first()

                                    if staking_record:
                                        stability_tracker = StabilityTrackerService(db)
                                        stability_tracker.mark_notification_sent(staking_record)
                                        db.commit()
                                        logger.info(f"✅ Отмечено как отправленное: {staking.get('coin')} (ID: {staking_db_id})")
                            except Exception as e:
                                logger.error(f"❌ Ошибка mark_notification_sent для {staking.get('coin')}: {e}")
                    await self.bot.send_message(chat_id, f"✅ Найдено {len(new_stakings)} новых стейкингов в ссылке '{link_data['name']}'")
                else:
                    await self.bot.send_message(chat_id, f"ℹ️ В ссылке '{link_data['name']}' новых стейкингов не найдено")

            elif category == 'announcement':
                # АНОНСЫ: используем check_announcement_link()
                logger.info(f"📢 Принудительная проверка анонсов: {link_data['name']}")

                # Синхронный вызов в отдельном потоке
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self.parser_service.check_announcement_link,
                    link_data['id'],
                    link_data['url']
                )

                # Отправляем уведомление если были изменения
                if result and result.get('changed'):
                    message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                    message += f"📝 Ссылка: {link_data['name']}\n"
                    message += f"🔍 Стратегия: {result.get('strategy')}\n"
                    message += f"💬 {result.get('message')}\n\n"
                    if result.get('matched_content'):
                        message += f"📄 Найдено:\n{result.get('matched_content')[:500]}\n\n"
                    
                    # Добавляем найденные ссылки на конкретные анонсы
                    if result.get('announcement_links'):
                        announcement_links = result.get('announcement_links')
                        message += f"🎯 <b>Найдено анонсов: {len(announcement_links)}</b>\n\n"
                        for i, ann in enumerate(announcement_links[:5], 1):  # Показываем топ-5
                            title = ann.get('title', 'Без названия')
                            url = ann.get('url', '')
                            description = ann.get('description', '')
                            keywords = ', '.join(ann.get('matched_keywords', []))
                            
                            message += f"{i}. <a href=\"{url}\">{title}</a>\n"
                            if description:
                                desc_short = description[:150] + '...' if len(description) > 150 else description
                                message += f"   📝 {desc_short}\n"
                            if keywords:
                                message += f"   🔑 {keywords}\n"
                            message += "\n"
                    else:
                        message += "⚠️ <i>Конкретные ссылки на анонсы не извлечены</i>\n"
                        
                        if result.get('debug_info'):
                            debug = result['debug_info']
                            message += f"<i>📊 Всего ссылок: {debug.get('total_links_on_page', 0)}</i>\n"
                            message += f"<i>🌐 Браузерный парсинг: {'✅' if debug.get('browser_parsing_enabled') else '❌ ВЫКЛЮЧЕН'}</i>\n"
                            if not debug.get('browser_parsing_enabled'):
                                message += "<b>💡 Включите браузерный парсинг</b>\n"
                        
                        message += "<i>Откройте страницу ниже для просмотра</i>\n\n"
                    
                    message += f"🔗 <a href=\"{result.get('url')}\">Открыть страницу со всеми анонсами</a>"

                    await self.bot.send_message(chat_id, message, parse_mode='HTML')
                    await self.bot.send_message(chat_id, f"✅ Найдены изменения в ссылке '{link_data['name']}'")
                else:
                    await self.bot.send_message(chat_id, f"ℹ️ В ссылке '{link_data['name']}' изменений не найдено")

            else:
                # ОБЫЧНЫЕ ПРОМОАКЦИИ: используем check_for_new_promos()
                # Синхронный вызов в отдельном потоке
                loop = asyncio.get_event_loop()
                new_promos = await loop.run_in_executor(
                    None, self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
                )

                # Отправляем уведомления
                if new_promos:
                    await self.notification_service.send_bulk_notifications(chat_id, new_promos)
                    await self.bot.send_message(chat_id, f"✅ Найдено {len(new_promos)} новых промоакций в ссылке '{link_data['name']}'")
                else:
                    await self.bot.send_message(chat_id, f"ℹ️ В ссылке '{link_data['name']}' новых промоакций не найдено")

            # Обновляем время проверки в новой сессии
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                if link:
                    link.last_checked = datetime.utcnow()
                    db.commit()

        except Exception as e:
            logger.error(f"❌ Ошибка принудительной проверки ссылки {link_id}: {e}")
            await self.bot.send_message(chat_id, f"❌ Ошибка при проверке ссылки")

    def setup_scheduler(self):
        """Настройка планировщика"""
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self.smart_auto_check,
            trigger=IntervalTrigger(minutes=1),  # Проверка каждую минуту
            id='smart_auto_check',
            max_instances=1
        )

    async def start(self):
        """Запуск бота"""
        try:
            await self.init_services()
            self.setup_scheduler()
            self.scheduler.start()

            # Запускаем Telegram Monitor в фоновом режиме (если включен)
            if self.telegram_monitor:
                logger.info("🚀 Запуск Telegram Monitor в фоновом режиме...")
                self.telegram_monitor_task = asyncio.create_task(self.telegram_monitor.start())

            logger.info("🤖 Crypto Promo Bot запускается...")
            logger.info("⏰ Автоматическая проверка активирована")
            logger.info("🎯 Проверяются ТОЛЬКО активные ссылки")
            logger.info("🚫 Остановленные ссылки игнорируются в автоматическом и ручном режиме")

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

        # Останавливаем Telegram Monitor (если запущен)
        if self.telegram_monitor:
            logger.info("🛑 Остановка Telegram Monitor...")
            await self.telegram_monitor.shutdown()
            if self.telegram_monitor_task:
                self.telegram_monitor_task.cancel()
                try:
                    await self.telegram_monitor_task
                except asyncio.CancelledError:
                    pass

        if self.scheduler:
            self.scheduler.shutdown()
        if self.bot:
            await self.bot.close()
        logger.info("👋 Бот завершил работу")

async def main():
    bot_instance = CryptoPromoBot()
    bot_manager.set_instance(bot_instance)
    
    logger.info("✅ Бот инициализирован и готов к запуску")
    await bot_instance.start()

if __name__ == "__main__":
    asyncio.run(main())