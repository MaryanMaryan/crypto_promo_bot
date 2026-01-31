import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import router
from bot.telegram_account_handlers import router as telegram_account_router
from bot.exchange_credentials_handlers import router as exchange_credentials_router
from data.database import init_database, get_db_session, ApiLink
from data.models import StakingHistory, PromoHistory
from utils.launchpool_filter import filter_launchpool_projects, get_link_launchpool_filters
from services.stability_tracker_service import StabilityTrackerService
from bot.parser_service import ParserService
from bot.notification_service import NotificationService
from bot.bot_manager import bot_manager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone
import os
import signal
import sys

# Импортируем конфигурацию из config.py
import config

# Глобальный executor для параллельного парсинга
from utils.executor import get_executor

# Browser Pool для переиспользования браузеров
from utils.browser_pool import init_browser_pool, shutdown_browser_pool

# Worker Pool для параллельного парсинга
from services.parsing_worker import (
    init_worker_pool, shutdown_worker_pool, get_worker_pool,
    ParsingWorkerPool
)
from utils.parsing_queue import TaskPriority, ParsingTask

# Circuit Breaker для защиты от недоступных бирж
from utils.circuit_breaker import init_circuit_breaker, get_circuit_breaker

# Resource Monitor для мониторинга ресурсов
from utils.resource_monitor import init_resource_monitor, shutdown_resource_monitor, get_resource_monitor

# Настройка логирования (с ротацией в файл)
from utils.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

class CryptoPromoBot:
    def __init__(self):
        self.bot = None
        self.dp = None
        self.scheduler = None
        self.parser_service = None
        self.notification_service = None
        self.worker_pool = None  # Пул воркеров для параллельного парсинга
        self.telegram_monitor = None  # Telegram Monitor
        self.telegram_monitor_task = None  # Задача мониторинга Telegram
        self.YOUR_CHAT_ID = config.ADMIN_CHAT_ID
        self.notification_recipients = config.ALL_NOTIFICATION_RECIPIENTS  # Все получатели уведомлений
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
            
            # Инициализируем пул браузеров если включен
            if config.BROWSER_POOL_ENABLED:
                try:
                    await init_browser_pool()
                    logger.info(f"🌐 Browser Pool запущен (размер: {config.BROWSER_POOL_SIZE})")
                except Exception as e:
                    logger.error(f"⚠️ Не удалось запустить Browser Pool: {e}")
                    logger.info("ℹ️ Будет использоваться стандартный browser_parser")

        init_database()
        
        # Запуск миграций
        migration_runner = DatabaseMigration()
        migration_runner.run_migrations()

        self.bot = Bot(token=config.BOT_TOKEN)
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)
        self.parser_service = ParserService()
        self.notification_service = NotificationService(self.bot)

        # Подключаем middleware для проверки администратора (ВАЖНО: первым!)
        from utils.admin_middleware import AdminMiddleware
        self.dp.message.middleware(AdminMiddleware())
        self.dp.callback_query.middleware(AdminMiddleware())
        logger.info(f"🔒 Admin middleware включен (admin_id={config.ADMIN_CHAT_ID})")

        # Подключаем middleware для защиты от спама кнопок
        from utils.debounce import DebounceMiddleware
        self.dp.callback_query.middleware(DebounceMiddleware())
        logger.info(f"🛡️ Debounce middleware включен ({config.DEBOUNCE_SECONDS}с)")

        # Инициализация Telegram Monitor (если включен)
        if config.TELEGRAM_PARSER_ENABLED:
            from services.telegram_monitor import TelegramMonitor
            self.telegram_monitor = TelegramMonitor(self.bot)
            logger.info("📡 Telegram Monitor инициализирован")
        else:
            logger.info("ℹ️ Telegram Parser отключен (TELEGRAM_PARSER_ENABLED=false)")

        # Инициализация Circuit Breaker для защиты от недоступных бирж
        if getattr(config, 'CIRCUIT_BREAKER_ENABLED', True):
            init_circuit_breaker()
            logger.info(
                f"🔌 Circuit Breaker включен (threshold={config.CIRCUIT_BREAKER_FAILURE_THRESHOLD}, "
                f"recovery={config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT}s)"
            )
        
        # Инициализация Resource Monitor для мониторинга ресурсов
        if getattr(config, 'RESOURCE_MONITOR_ENABLED', True):
            try:
                await init_resource_monitor(
                    check_interval=config.RESOURCE_MONITOR_INTERVAL,
                    ram_warning_percent=config.RESOURCE_RAM_WARNING_PERCENT,
                    ram_critical_percent=config.RESOURCE_RAM_CRITICAL_PERCENT,
                    on_warning=self._on_resource_warning,
                    on_critical=self._on_resource_critical
                )
                logger.info(f"📊 Resource Monitor включен (interval={config.RESOURCE_MONITOR_INTERVAL}s)")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось запустить Resource Monitor: {e}")

        # Инициализация Worker Pool для параллельного парсинга
        if config.PARALLEL_PARSING_ENABLED:
            try:
                self.worker_pool = await init_worker_pool(
                    parser_service=self.parser_service,
                    num_workers=config.PARALLEL_PARSING_WORKERS,
                    notification_callback=self._handle_parsing_result
                )
                logger.info(f"⚡ Worker Pool запущен ({config.PARALLEL_PARSING_WORKERS} воркеров)")
            except Exception as e:
                logger.error(f"⚠️ Не удалось запустить Worker Pool: {e}")
                logger.info("ℹ️ Будет использоваться последовательный парсинг")
        else:
            logger.info("ℹ️ Параллельный парсинг отключен (PARALLEL_PARSING_ENABLED=false)")

        # Регистрируем роутеры (telegram_account_router ПЕРВЫМ для перехвата bypass_telegram)
        self.dp.include_router(telegram_account_router)
        self.dp.include_router(exchange_credentials_router)
        self.dp.include_router(router)
        
        # Регистрируем роутер фьючерсов ПОСЛЕДНИМ (чтобы не перехватывать другие команды)
        from bot.futures_handlers import setup_futures_handlers
        setup_futures_handlers(self.dp)

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

    async def send_to_all_recipients(self, message: str, parse_mode: str = 'HTML'):
        """
        Отправляет сообщение ВСЕМ получателям уведомлений.
        Используется для рассылки новых промоакций.
        """
        for chat_id in self.notification_recipients:
            try:
                await self.bot.send_message(chat_id, message, parse_mode=parse_mode, disable_web_page_preview=True)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить сообщение в чат {chat_id}: {e}")

    async def send_notifications_to_all(self, promos):
        """
        Отправляет уведомления о промоакциях ВСЕМ получателям.
        """
        for chat_id in self.notification_recipients:
            try:
                await self.notification_service.send_bulk_notifications(chat_id, promos)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить уведомления в чат {chat_id}: {e}")

    async def _handle_parsing_result(self, task: ParsingTask, result: dict):
        """
        Callback для обработки результатов параллельного парсинга.
        Отправляет уведомления о найденных промоакциях/стейкингах.
        """
        try:
            # ВСЕГДА обновляем время последней проверки (независимо от результата)
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == task.link_id).first()
                if link:
                    link.last_checked = datetime.utcnow()
                    db.commit()
                    logger.debug(f"⏰ Обновлено last_checked для {task.link_name}")
            
            if not result or result.get('new_count', 0) == 0:
                return
            
            category = result.get('category', 'promo')
            items = result.get('items', [])
            
            # Дополнительная фильтрация маркеров _no_new (на всякий случай)
            items = [item for item in items if not item.get('_no_new')]
            if not items:
                return
            
            if category == 'staking':
                # Отправляем уведомления о стейкингах
                for staking in items:
                    # Проверяем, это группа пулов OKX
                    if staking.get('_is_okx_group'):
                        pools = staking.get('_group_pools', [staking])
                        message = self.notification_service.format_okx_project(
                            pools,
                            page_url=task.page_url
                        )
                        await self.send_to_all_recipients(message)
                    else:
                        message = self.notification_service.format_new_staking(
                            staking,
                            page_url=task.page_url
                        )
                        await self.send_to_all_recipients(message)
                        
                        # Отмечаем уведомление как отправленное
                        staking_db_id = staking.get('_staking_db_id')
                        if staking_db_id:
                            try:
                                with get_db_session() as db:
                                    staking_record = db.query(StakingHistory).filter(
                                        StakingHistory.id == staking_db_id
                                    ).first()
                                    if staking_record:
                                        stability_tracker = StabilityTrackerService(db)
                                        notification_type = staking.get('_notification_type', 'new')
                                        stability_tracker.mark_notification_sent(staking_record, notification_type)
                                        db.commit()
                            except Exception as e:
                                logger.error(f"❌ Ошибка mark_notification_sent: {e}")
            
            elif category == 'announcement':
                # Отправляем уведомления об анонсах
                for item in items:
                    if not item.get('changed'):
                        continue
                    
                    # Если есть new_promos - используем красивое форматирование
                    new_promos = item.get('new_promos', [])
                    if new_promos:
                        logger.info(f"📦 Announcement с special_parser: отправка {len(new_promos)} промоакций через красивое форматирование")
                        await self.send_notifications_to_all(new_promos)
                    else:
                        # Стандартный формат для обычных анонсов (без special_parser)
                        message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                        message += f"📝 Ссылка: {task.link_name}\n"
                        message += f"🔍 Стратегия: {item.get('strategy')}\n"
                        message += f"💬 {item.get('message')}\n\n"
                        
                        if item.get('announcement_links'):
                            announcement_links = item.get('announcement_links')
                            message += f"🎯 <b>Найдено анонсов: {len(announcement_links)}</b>\n\n"
                            for i, ann in enumerate(announcement_links[:5], 1):
                                title = ann.get('title', 'Без названия')
                                url = ann.get('url', '')
                                message += f"{i}. <a href=\"{url}\">{title}</a>\n"
                        
                        message += f"\n🔗 <a href=\"{item.get('url')}\">Открыть страницу</a>"
                        
                        await self.send_to_all_recipients(message)
            
            else:
                # Обычные промоакции
                if items:
                    # Разделяем обычные промоакции и изменения названий
                    regular_promos = []
                    title_changes = []
                    
                    for item in items:
                        if item.get('_is_title_change'):
                            title_changes.append(item)
                        else:
                            regular_promos.append(item)
                    
                    # Отправляем уведомления об обычных промоакциях
                    if regular_promos:
                        await self.send_notifications_to_all(regular_promos)
                    
                    # Отправляем уведомления об изменениях названий (Weex rewards)
                    if title_changes:
                        logger.info(f"📝 Отправка {len(title_changes)} уведомлений об изменениях названий")
                        for change in title_changes:
                            for chat_id in self.notification_recipients:
                                try:
                                    await self.notification_service.send_title_change_notification(chat_id, change)
                                except Exception as e:
                                    logger.warning(f"⚠️ Не удалось отправить уведомление об изменении названия в чат {chat_id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обработки результата парсинга: {e}", exc_info=True)

    async def _on_resource_warning(self, snapshot):
        """Callback при предупреждении о ресурсах (RAM/CPU > 70%)"""
        logger.warning(
            f"⚠️ Ресурсы: RAM {snapshot.ram_percent:.1f}%, CPU {snapshot.cpu_percent:.1f}% "
            f"(process: {snapshot.process_ram_mb:.0f}MB)"
        )
    
    async def _on_resource_critical(self, snapshot):
        """Callback при критическом состоянии ресурсов (RAM/CPU > 85%)"""
        logger.error(
            f"🔴 КРИТИЧЕСКИЕ ресурсы: RAM {snapshot.ram_percent:.1f}%, CPU {snapshot.cpu_percent:.1f}%"
        )
        
        # Опционально: отправка уведомления админу
        try:
            message = (
                f"🔴 <b>КРИТИЧЕСКОЕ СОСТОЯНИЕ РЕСУРСОВ</b>\n\n"
                f"💾 RAM: {snapshot.ram_percent:.1f}% ({snapshot.ram_used_mb:.0f}/{snapshot.ram_total_mb:.0f} MB)\n"
                f"🖥️ CPU: {snapshot.cpu_percent:.1f}%\n"
                f"🤖 Bot process: {snapshot.process_ram_mb:.0f} MB\n\n"
                f"⚠️ Graceful degradation активирован"
            )
            await self.bot.send_message(
                self.YOUR_CHAT_ID,
                message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"❌ Не удалось отправить алерт о ресурсах: {e}")

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
        """
        Умная автоматическая проверка - ТОЛЬКО АКТИВНЫЕ ссылки.
        Использует параллельный парсинг (если включен) или последовательный (fallback).
        """
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
                current_time = datetime.utcnow()
                for link in links:
                    # Проверяем, нужно ли проверять эту ссылку
                    time_since_last_check = current_time - (link.last_checked or datetime.min)
                    needs_check = time_since_last_check.total_seconds() >= link.check_interval
                    
                    if not needs_check:
                        remaining_time = link.check_interval - time_since_last_check.total_seconds()
                        logger.debug(f"⏰ Пропускаем {link.name} - след. проверка через {remaining_time:.0f}сек")
                        continue
                    
                    # Пропускаем Telegram ссылки
                    if link.parsing_type == 'telegram':
                        logger.debug(f"⏭️ Пропускаем Telegram ссылку {link.name} - обрабатывается через TelegramMonitor")
                        continue
                    
                    links_data.append({
                        'id': link.id,
                        'name': link.name,
                        'url': link.url,
                        'check_interval': link.check_interval,
                        'last_checked': link.last_checked,
                        'exchange': link.exchange or 'Unknown',
                        'category': link.category or 'launches',
                        'parsing_type': link.parsing_type or '',
                        'api_url': link.api_url,
                        'page_url': link.page_url,
                        'min_apr': link.min_apr,
                        'special_parser': link.special_parser,  # Для BingX/Bitget
                    })

            if not links_data:
                logger.info("ℹ️ Нет ссылок для проверки в этот раз")
                return

            # ПАРАЛЛЕЛЬНЫЙ ПАРСИНГ (если включен и worker pool запущен)
            if config.PARALLEL_PARSING_ENABLED and self.worker_pool:
                await self._smart_auto_check_parallel(links_data)
            else:
                # ПОСЛЕДОВАТЕЛЬНЫЙ ПАРСИНГ (fallback)
                await self._smart_auto_check_sequential(links_data)

        except Exception as e:
            logger.error(f"❌ Ошибка автоматической проверки: {e}", exc_info=True)

    async def _smart_auto_check_parallel(self, links_data: list):
        """
        Параллельная автоматическая проверка через Worker Pool.
        Все ссылки добавляются в очередь и обрабатываются воркерами.
        """
        import time
        start_time = time.time()
        
        logger.info(f"⚡ Параллельная проверка {len(links_data)} ссылок...")
        
        # Добавляем все ссылки в очередь
        task_ids = await self.worker_pool.add_links(
            links_data,
            priority=TaskPriority.NORMAL
        )
        
        logger.info(f"📥 Добавлено {len(task_ids)} задач в очередь")
        
        # Уведомления отправляются через callback _handle_parsing_result
        # Поэтому здесь просто ждём немного для обновления статистики
        await asyncio.sleep(0.5)
        
        # Статистика (воркеры работают асинхронно)
        stats = self.worker_pool.get_stats()
        busy = stats.get('busy_workers', 0)
        pending = stats.get('pending_tasks', 0)
        
        elapsed = time.time() - start_time
        logger.info(f"📊 Запущено: {len(task_ids)} задач | Воркеров занято: {busy} | В очереди: {pending} ({elapsed:.1f}с)")

    async def _smart_auto_check_sequential(self, links_data: list):
        """
        Последовательная автоматическая проверка (fallback).
        Используется если параллельный парсинг отключен.
        """
        total_checked = 0
        total_new_promos = 0

        for link_data in links_data:
            if self._shutdown_event.is_set():
                logger.info("⏹️ Проверка прервана из-за завершения работы")
                return

            category = link_data.get('category', 'launches')
            current_time = datetime.utcnow()

            if category == 'staking':
                # СТЕЙКИНГ: используем parse_staking_link()
                logger.info(f"💰 Проверка стейкинга: {link_data['name']}")

                from utils.exchange_detector import detect_exchange_from_url
                api_url = link_data.get('api_url') or link_data['url']
                exchange = link_data.get('exchange')
                if not exchange or exchange in ['Unknown', 'None', '']:
                    exchange = detect_exchange_from_url(api_url)

                min_apr = link_data.get('min_apr')
                loop = asyncio.get_event_loop()
                new_stakings = await loop.run_in_executor(
                    get_executor(),
                    self.parser_service.parse_staking_link,
                    link_data['id'],
                    api_url,
                    exchange,
                    link_data.get('page_url'),
                    min_apr
                )

                # Фильтруем маркеры _no_new - они не являются реальными стейкингами
                new_stakings = [s for s in (new_stakings or []) if not s.get('_no_new')]
                new_count = len(new_stakings)
                if new_count > 0:
                    logger.info(f"🎉 Найдено {new_count} новых стейкингов")
                    
                    if new_stakings and new_stakings[0].get('_is_okx_group'):
                        pools = new_stakings[0].get('_group_pools', new_stakings)
                        message = self.notification_service.format_okx_project(
                            pools, page_url=link_data.get('page_url')
                        )
                        await self.send_to_all_recipients(message)
                    else:
                        for staking in new_stakings:
                            message = self.notification_service.format_new_staking(
                                staking, page_url=link_data.get('page_url')
                            )
                            await self.send_to_all_recipients(message)
                            
                            staking_db_id = staking.get('_staking_db_id')
                            if staking_db_id:
                                try:
                                    with get_db_session() as db:
                                        staking_record = db.query(StakingHistory).filter(
                                            StakingHistory.id == staking_db_id
                                        ).first()
                                        if staking_record:
                                            stability_tracker = StabilityTrackerService(db)
                                            notification_type = staking.get('_notification_type', 'new')
                                            stability_tracker.mark_notification_sent(staking_record, notification_type)
                                            db.commit()
                                except Exception as e:
                                    logger.error(f"❌ Ошибка mark_notification_sent: {e}")
                    
                    total_new_promos += new_count

            elif category == 'announcement':
                # АНОНСЫ
                logger.info(f"📢 Проверка анонсов: {link_data['name']}")
                
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    get_executor(),
                    self.parser_service.check_announcement_link,
                    link_data['id'],
                    link_data['url']
                )

                if result and result.get('changed'):
                    logger.info(f"🎉 Обнаружены изменения в анонсах!")
                    
                    # Если есть new_promos - используем красивое форматирование
                    new_promos = result.get('new_promos', [])
                    strategy = result.get('strategy', '')
                    
                    if new_promos:
                        logger.info(f"📦 Announcement с special_parser: отправка {len(new_promos)} промоакций через красивое форматирование")
                        await self.send_notifications_to_all(new_promos)
                        total_new_promos += len(new_promos)
                    elif strategy.startswith('weex_useragent:'):
                        # Для weex_useragent - сообщение уже красиво отформатировано
                        message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                        message += f"📝 Ссылка: {link_data['name']}\n"
                        message += f"🔍 Стратегия: {strategy}\n"
                        message += f"💬 {result.get('message')}\n\n"
                        message += f"🔗 <a href=\"{result.get('url')}\">Открыть страницу</a>"
                        await self.send_to_all_recipients(message)
                        total_new_promos += 1
                    else:
                        # Стандартный формат для обычных анонсов
                        message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                        message += f"📝 Ссылка: {link_data['name']}\n"
                        message += f"🔍 Стратегия: {result.get('strategy')}\n"
                        message += f"💬 {result.get('message')}\n\n"
                        
                        if result.get('announcement_links'):
                            announcement_links = result.get('announcement_links')
                            message += f"🎯 <b>Найдено анонсов: {len(announcement_links)}</b>\n\n"
                            for i, ann in enumerate(announcement_links[:5], 1):
                                title = ann.get('title', 'Без названия')
                                url = ann.get('url', '')
                                message += f"{i}. <a href=\"{url}\">{title}</a>\n"
                        
                        message += f"\n🔗 <a href=\"{result.get('url')}\">Открыть страницу</a>"
                        await self.send_to_all_recipients(message)
                        total_new_promos += 1

            else:
                # WEEX WELCOME BONUS ПАРСЕР
                special_parser = link_data.get('special_parser')
                
                if special_parser == 'weex_welcome':
                    logger.info(f"🎁 Проверка WEEX Welcome Bonus: {link_data['name']}")
                    
                    try:
                        from parsers.weex_welcome_parser import WeexWelcomeParser
                        
                        parser = WeexWelcomeParser()
                        
                        # Получаем текущие награды
                        loop = asyncio.get_event_loop()
                        new_rewards = await loop.run_in_executor(
                            get_executor(),
                            parser.get_promotions
                        )
                        
                        if not new_rewards:
                            logger.warning(f"⚠️ Не удалось получить награды WEEX Welcome")
                            continue
                        
                        # Получаем старый snapshot из БД
                        with get_db_session() as db:
                            link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                            old_snapshot = link.announcement_last_snapshot if link else None
                        
                        old_rewards = parser.deserialize_from_snapshot(old_snapshot) if old_snapshot else []
                        
                        if not old_rewards:
                            # Первый запуск - отправляем snapshot
                            logger.info(f"📸 Первый запуск - сохраняем snapshot ({len(new_rewards)} наград)")
                            
                            message = parser.format_snapshot_message(new_rewards)
                            await self.send_to_all_recipients(message)
                            
                            # Сохраняем snapshot
                            new_snapshot = parser.serialize_for_snapshot(new_rewards)
                            with get_db_session() as db:
                                db_link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                                if db_link:
                                    db_link.announcement_last_snapshot = new_snapshot
                                    db.commit()
                            
                            total_new_promos += 1
                        else:
                            # Сравниваем с предыдущим состоянием
                            changes = parser.compare_states(old_rewards, new_rewards)
                            
                            if changes['has_changes']:
                                logger.info(f"🎉 Обнаружены изменения в WEEX Welcome: {changes['summary']}")
                                
                                message = parser.format_changes_message(changes)
                                await self.send_to_all_recipients(message)
                                
                                # Обновляем snapshot
                                new_snapshot = parser.serialize_for_snapshot(new_rewards)
                                with get_db_session() as db:
                                    db_link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                                    if db_link:
                                        db_link.announcement_last_snapshot = new_snapshot
                                        db.commit()
                                
                                total_new_promos += 1
                            else:
                                logger.info(f"✅ WEEX Welcome: без изменений")
                        
                    except Exception as e:
                        logger.error(f"❌ Ошибка weex_welcome: {e}", exc_info=True)
                
                # LAUNCHPOOL ПАРСЕРЫ: требуют асинхронной проверки с фильтрацией
                elif special_parser in ['bingx_launchpool', 'bitget_launchpool', 'bybit_launchpool', 
                                       'gate_launchpool', 'mexc_launchpool', 'bitget_poolx']:
                    logger.info(f"🌊 Проверка {special_parser}: {link_data['name']}")
                    
                    try:
                        # Динамический импорт парсера
                        parser = None
                        display_name = special_parser.replace('_', ' ').title()
                        
                        if special_parser == 'bingx_launchpool':
                            from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
                            parser = BingxLaunchpoolParser()
                            display_name = "BingX Launchpool"
                        elif special_parser == 'bitget_launchpool':
                            from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
                            parser = BitgetLaunchpoolParser()
                            display_name = "Bitget Launchpool"
                        elif special_parser == 'bybit_launchpool':
                            from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
                            parser = BybitLaunchpoolParser()
                            display_name = "Bybit Launchpool"
                        elif special_parser == 'gate_launchpool':
                            from parsers.gate_launchpool_parser import GateLaunchpoolParser
                            parser = GateLaunchpoolParser()
                            display_name = "Gate.io Launchpool"
                        elif special_parser == 'mexc_launchpool':
                            from parsers.mexc_launchpool_parser import MexcLaunchpoolParser
                            parser = MexcLaunchpoolParser()
                            display_name = "MEXC Launchpool"
                        elif special_parser == 'bitget_poolx':
                            from parsers.bitget_poolx_parser import BitgetPoolxParser
                            parser = BitgetPoolxParser()
                            display_name = "Bitget PoolX"
                        
                        if not parser:
                            logger.warning(f"⚠️ Неизвестный launchpool парсер: {special_parser}")
                            continue
                        
                        # Получаем проекты асинхронно
                        projects = await parser.get_projects_async()
                        active_upcoming = [p for p in projects if p.status in ['active', 'upcoming']]
                        
                        # Получаем фильтры из настроек ссылки
                        with get_db_session() as db:
                            link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                            if link:
                                filters = get_link_launchpool_filters(link)
                            else:
                                filters = {}
                        
                        # Применяем фильтры
                        filtered_projects = filter_launchpool_projects(
                            active_upcoming,
                            min_pool_usd=filters.get('min_pool_usd', 0),
                            min_apr=filters.get('min_apr', 0),
                            stake_coins_filter=filters.get('stake_coins_filter', []),
                            min_user_limit_usd=filters.get('min_user_limit_usd', 0)
                        )
                        
                        # Проверяем на новые проекты (сравниваем с историей)
                        new_projects = []
                        for project in filtered_projects:
                            promo_id = f"{special_parser}_{project.token_symbol}"
                            with get_db_session() as db:
                                existing = db.query(PromoHistory).filter(
                                    PromoHistory.promo_id == promo_id
                                ).first()
                                if not existing:
                                    new_projects.append(project)
                                    # Сохраняем в историю
                                    history = PromoHistory(
                                        api_link_id=link_data['id'],
                                        promo_id=promo_id,
                                        exchange=display_name,
                                        title=f"{project.token_symbol} - {project.token_name}",
                                        status=project.status,
                                        promo_type='launchpool'
                                    )
                                    db.add(history)
                                    db.commit()
                        
                        # Отправляем уведомления о новых проектах
                        if new_projects:
                            logger.info(f"🎉 {display_name}: {len(new_projects)} НОВЫХ проектов!")
                            for project in new_projects:
                                message = f"🌊 <b>НОВЫЙ {display_name.upper()}</b>\n\n"
                                message += f"🪙 <b>{project.token_symbol}</b> - {project.token_name}\n"
                                message += f"📊 Статус: {project.get_status_text()}\n"
                                if project.pools:
                                    max_apr = max([p.apr for p in project.pools if p.apr > 0], default=0)
                                    if max_apr > 0:
                                        message += f"📈 Макс. APR: {max_apr:.0f}%\n"
                                    stake_coins = set(p.stake_coin for p in project.pools if p.stake_coin)
                                    if stake_coins:
                                        message += f"💰 Стейк монеты: {', '.join(stake_coins)}\n"
                                
                                for chat_id in self.notification_recipients:
                                    try:
                                        await self.bot.send_message(chat_id, message, parse_mode='HTML')
                                    except Exception as e:
                                        logger.warning(f"⚠️ Не удалось отправить в {chat_id}: {e}")
                            
                            total_new_promos += len(new_projects)
                        
                        if filtered_projects:
                            logger.info(f"✅ {link_data['name']}: {len(filtered_projects)} проектов (после фильтрации)")
                        else:
                            logger.info(f"✅ {link_data['name']}: нет проектов по фильтрам")
                            
                    except Exception as e:
                        logger.error(f"❌ Ошибка {special_parser}: {e}")
                else:
                    # ОБЫЧНЫЕ ПРОМОАКЦИИ
                    count_before = self._get_promo_count_for_link(link_data['id'])
                    
                    loop = asyncio.get_event_loop()
                    new_promos = await loop.run_in_executor(
                        get_executor(),
                        self.parser_service.check_for_new_promos,
                        link_data['id'],
                        link_data['url']
                    )

                    count_after = self._get_promo_count_for_link(link_data['id'])
                    new_count = len(new_promos) if new_promos else 0

                    if new_count > 0:
                        logger.info(f"🔍 {link_data['name']}: {count_before} → {count_after} | Новых: {new_count}")
                        await self.send_notifications_to_all(new_promos)
                        total_new_promos += new_count
                    else:
                        logger.info(f"✅ {link_data['name']}: без изменений")

            # Обновляем время последней проверки
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                if link:
                    link.last_checked = current_time
                    db.commit()

            total_checked += 1

        # ИТОГОВАЯ СВОДКА
        if total_checked > 0:
            logger.info("━" * 60)
            logger.info(f"📊 ИТОГО: Проверено {total_checked} ссылок | Найдено {total_new_promos} новых")
        else:
            logger.info("ℹ️ Нет ссылок для проверки")

    async def manual_check_all_links(self, chat_id: int):
        """
        Ручная проверка - ТОЛЬКО АКТИВНЫЕ ссылки.
        Использует параллельный парсинг для ускорения.
        """
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
                    # Пропускаем Telegram ссылки (они в реальном времени)
                    if link.parsing_type == 'telegram':
                        continue
                    
                    links_data.append({
                        'id': link.id,
                        'name': link.name,
                        'url': link.url,
                        'exchange': link.exchange or 'Unknown',
                        'category': link.category or 'launches',
                        'parsing_type': link.parsing_type or 'combined',
                        'api_url': link.api_url,
                        'page_url': link.page_url,
                        'min_apr': link.min_apr,
                        'special_parser': link.special_parser,  # Для BingX/Bitget
                    })

            if not links_data:
                await self.bot.send_message(chat_id, "❌ Нет ссылок для проверки (только Telegram)")
                return

            # ПАРАЛЛЕЛЬНЫЙ ПАРСИНГ (если включен и worker pool запущен)
            if config.PARALLEL_PARSING_ENABLED and self.worker_pool:
                await self._manual_check_parallel(chat_id, links_data, start_time)
            else:
                # ПОСЛЕДОВАТЕЛЬНЫЙ ПАРСИНГ (fallback)
                await self._manual_check_sequential(chat_id, links_data, start_time)

        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ручной проверки: {e}", exc_info=True)
            await self.bot.send_message(chat_id, "❌ Произошла ошибка при проверке")

    async def _manual_check_parallel(self, chat_id: int, links_data: list, start_time: float):
        """
        Параллельная ручная проверка через Worker Pool.
        Все ссылки обрабатываются одновременно.
        """
        import time
        
        logger.info(f"⚡ Параллельная проверка {len(links_data)} ссылок...")
        await self.bot.send_message(chat_id, f"⚡ Параллельная проверка {len(links_data)} ссылок...")
        
        # Добавляем все ссылки в очередь с HIGH приоритетом (ручная проверка)
        task_ids = await self.worker_pool.add_links(
            links_data,
            priority=TaskPriority.HIGH
        )
        
        logger.info(f"📥 Добавлено {len(task_ids)} задач в очередь")
        
        # Ждём завершения ТОЛЬКО наших задач (чтобы не смешивать с auto_check)
        # Увеличенный таймаут для ручной проверки - некоторые парсеры работают долго (OKX boost ~50с)
        results = await self.worker_pool.wait_for_completion(timeout=600.0, task_ids=task_ids)
        
        # Собираем статистику
        check_results = []
        total_new_promos = 0
        total_promos_in_db = 0
        
        for task in results:
            result = task.result or {}
            new_count = result.get('new_count', 0)
            category = result.get('category', 'promo')
            
            if category == 'staking':
                status = "💰 Новые стейкинги!" if new_count > 0 else "✅ Без изменений"
                check_results.append({
                    'name': task.link_name,
                    'before': '-',
                    'after': '-',
                    'new': new_count,
                    'status': status
                })
            elif category == 'announcement':
                status = "📢 Изменения!" if new_count > 0 else "✅ Без изменений"
                check_results.append({
                    'name': task.link_name,
                    'before': '-',
                    'after': '-',
                    'new': new_count,
                    'status': status
                })
            else:
                status = "🎉 Новые акции!" if new_count > 0 else "✅ Без изменений"
                count_after = self._get_promo_count_for_link(task.link_id)
                check_results.append({
                    'name': task.link_name,
                    'before': '-',
                    'after': count_after,
                    'new': new_count,
                    'status': status
                })
                total_promos_in_db += count_after
            
            total_new_promos += new_count
            
            # Обновляем время проверки
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == task.link_id).first()
                if link:
                    link.last_checked = datetime.utcnow()
                    db.commit()
        
        # Добавляем задачи с ошибками
        for task_id in task_ids:
            task_status = self.worker_pool._queue.get_task_status(task_id) if self.worker_pool._queue else None
            if task_status and task_status.get('status') == 'failed':
                check_results.append({
                    'name': task_status.get('link_name', 'Unknown')[:10],
                    'before': 'ERROR',
                    'after': 'ERROR',
                    'new': '-',
                    'status': "❌ Ошибка",
                    'result_type': 'error'
                })
        
        # Выводим статистику
        await self._output_check_results(chat_id, check_results, total_new_promos, total_promos_in_db, start_time)

    async def _manual_check_sequential(self, chat_id: int, links_data: list, start_time: float):
        """Последовательная ручная проверка (fallback)."""
        import time
        
        check_results = []
        total_new_promos = 0
        total_promos_in_db = 0

        for link_data in links_data:
            if self._shutdown_event.is_set():
                logger.warning("⏹️ Проверка прервана пользователем")
                await self.bot.send_message(chat_id, "⏹️ Проверка прервана")
                return

            try:
                category = link_data.get('category', 'launches')
                count_after = 0

                if category == 'staking':
                    from utils.exchange_detector import detect_exchange_from_url
                    api_url = link_data.get('api_url') or link_data['url']
                    exchange = link_data.get('exchange')
                    if not exchange or exchange in ['Unknown', 'None', '']:
                        exchange = detect_exchange_from_url(api_url)
                        logger.info(f"🔍 Автоопределение биржи: {exchange}")

                    min_apr = link_data.get('min_apr')
                    loop = asyncio.get_event_loop()
                    new_stakings = await loop.run_in_executor(
                        get_executor(),
                        self.parser_service.parse_staking_link,
                        link_data['id'],
                        api_url,
                        exchange,
                        link_data.get('page_url'),
                        min_apr
                    )

                    new_count = len(new_stakings) if new_stakings else 0
                    
                    # Получаем метаданные о парсинге
                    total_parsed = 0
                    is_no_new = False
                    if new_stakings:
                        total_parsed = new_stakings[0].get('_total_parsed', new_count)
                        is_no_new = new_stakings[0].get('_no_new', False)
                        if is_no_new:
                            new_count = 0  # Это маркер, не реальные данные
                    
                    # Определяем статус с учётом парсинга
                    if total_parsed > 0:
                        status = "💰 Новые стейкинги!" if new_count > 0 else f"✅ Спарсено {total_parsed}"
                    else:
                        status = "⚠️ 0 результатов"
                    
                    check_results.append({
                        'name': link_data['name'],
                        'before': '-',
                        'after': total_parsed,
                        'new': new_count,
                        'status': status
                    })

                    if new_stakings and not is_no_new:
                        # Фильтруем маркеры _no_new - они не являются реальными стейкингами
                        real_stakings = [s for s in new_stakings if not s.get('_no_new')]
                        
                        if real_stakings and real_stakings[0].get('_is_okx_group'):
                            pools = real_stakings[0].get('_group_pools', real_stakings)
                            message = self.notification_service.format_okx_project(pools, page_url=link_data.get('page_url'))
                            await self.bot.send_message(chat_id, message, parse_mode='HTML')
                        else:
                            for staking in real_stakings:
                                message = self.notification_service.format_new_staking(staking, page_url=link_data.get('page_url'))
                                await self.bot.send_message(chat_id, message, parse_mode='HTML')
                                
                                staking_db_id = staking.get('_staking_db_id')
                                if staking_db_id:
                                    try:
                                        with get_db_session() as db:
                                            staking_record = db.query(StakingHistory).filter(StakingHistory.id == staking_db_id).first()
                                            if staking_record:
                                                stability_tracker = StabilityTrackerService(db)
                                                notification_type = staking.get('_notification_type', 'new')
                                                stability_tracker.mark_notification_sent(staking_record, notification_type)
                                                db.commit()
                                    except Exception as e:
                                        logger.error(f"❌ Ошибка mark_notification_sent: {e}")
                        total_new_promos += new_count

                elif category == 'announcement':
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        get_executor(),
                        self.parser_service.check_announcement_link,
                        link_data['id'],
                        link_data['url']
                    )

                    new_count = 1 if result and result.get('changed') else 0
                    status = "📢 Изменения!" if new_count > 0 else "✅ Без изменений"
                    
                    check_results.append({
                        'name': link_data['name'],
                        'before': '-',
                        'after': '-',
                        'new': new_count,
                        'status': status
                    })

                    if result and result.get('changed'):
                        # Використовуємо новий форматтер для анонсів
                        from utils.message_formatters import AnnouncementAlertFormatter
                        message = AnnouncementAlertFormatter.format(
                            link_name=link_data['name'],
                            result=result,
                            link_url=link_data.get('url')
                        )
                        await self.bot.send_message(chat_id, message, parse_mode='HTML', disable_web_page_preview=True)
                        total_new_promos += new_count

                else:
                    count_before = self._get_promo_count_for_link(link_data['id'])
                    loop = asyncio.get_event_loop()
                    new_promos = await loop.run_in_executor(
                        get_executor(),
                        self.parser_service.check_for_new_promos,
                        link_data['id'],
                        link_data['url']
                    )

                    count_after = self._get_promo_count_for_link(link_data['id'])
                    new_count = len(new_promos) if new_promos else 0
                    status = "🎉 Новые акции!" if new_count > 0 else "✅ Без изменений"
                    
                    check_results.append({
                        'name': link_data['name'],
                        'before': count_before,
                        'after': count_after,
                        'new': new_count,
                        'status': status
                    })

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
                check_results.append({
                    'name': link_data['name'],
                    'before': 'ERROR',
                    'after': 'ERROR',
                    'new': '-',
                    'status': f"❌ {str(e)[:20]}...",
                    'result_type': 'error'
                })
                logger.error(f"❌ Ошибка проверки {link_data['name']}: {e}", exc_info=True)

        await self._output_check_results(chat_id, check_results, total_new_promos, total_promos_in_db, start_time)

    async def _output_check_results(self, chat_id: int, check_results: list, total_new_promos: int, total_promos_in_db: int, start_time: float):
        """Выводит результаты проверки в лог и пользователю."""
        import time
        
        # ВЫВОД ТАБЛИЦЫ
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
        
        # Подсчёт статусов по явному полю result_type
        success_count = 0
        error_count = 0
        error_names = []
        
        for r in check_results:
            result_type = r.get('result_type', 'success')
            if result_type == 'error' or r['before'] == 'ERROR':
                error_count += 1
                error_names.append(r['name'])
            else:
                success_count += 1

        logger.info(f"📊 Всего промоакций в базе: {total_promos_in_db}")
        logger.info(f"🆕 Добавлено новых: {total_new_promos}")
        logger.info(f"⏱️  Время проверки: {elapsed_time:.1f} сек")
        logger.info("")

        # Сообщение пользователю
        if error_count > 0:
            message = (
                f"⚠️ Проверка завершена\n"
                f"📊 Всего: {len(check_results)} | ✅ {success_count} | ❌ {error_count}\n"
                f"🆕 Новых промоакций: {total_new_promos}\n"
                f"💾 База данных: {total_promos_in_db} промоакций\n\n"
                f"⏱️ Затрачено: {elapsed_time:.1f} сек\n\n"
                f"❌ Ошибки: {', '.join(error_names[:5])}"
            )
            if len(error_names) > 5:
                message += "..."
        else:
            message = (
                f"✅ Проверка завершена\n"
                f"📊 Всего: {len(check_results)} | ✅ {success_count}\n"
                f"🆕 Новых промоакций: {total_new_promos}\n"
                f"💾 База данных: {total_promos_in_db} промоакций\n\n"
                f"⏱️ Затрачено: {elapsed_time:.1f} сек"
            )

        await self.bot.send_message(chat_id, message)
        logger.info("=" * 64)

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
                    'category': link.category or 'launches',
                    'parsing_type': link.parsing_type,  # Добавлено для проверки Telegram
                    'telegram_channel': link.telegram_channel,  # Для Telegram Monitor
                    'telegram_account_id': link.telegram_account_id,  # Для Telegram Monitor
                    'api_url': link.api_url,
                    'page_url': link.page_url,
                    'min_apr': link.min_apr,  # КРИТИЧНО: Добавлен min_apr для фильтрации
                    'special_parser': link.special_parser,  # Для BingX/Bitget
                }

            logger.info(f"🔧 Принудительная проверка ссылки {link_data['name']} (ID: {link_id})")

            # Проверяем тип парсинга и категорию ссылки
            parsing_type = link_data.get('parsing_type')
            category = link_data.get('category', 'launches')
            special_parser = link_data.get('special_parser')
            
            # LAUNCHPOOL ПАРСЕРЫ: требуют асинхронной проверки с фильтрацией
            LAUNCHPOOL_PARSERS = ['bingx_launchpool', 'bitget_launchpool', 'bybit_launchpool', 
                                   'gate_launchpool', 'mexc_launchpool', 'bitget_poolx']
            
            if special_parser in LAUNCHPOOL_PARSERS:
                logger.info(f"🌊 Принудительная проверка {special_parser}: {link_data['name']}")
                
                try:
                    # Динамический импорт парсера
                    parser = None
                    display_name = special_parser.replace('_', ' ').title()
                    
                    if special_parser == 'bingx_launchpool':
                        from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
                        parser = BingxLaunchpoolParser()
                        display_name = "BingX Launchpool"
                    elif special_parser == 'bitget_launchpool':
                        from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
                        parser = BitgetLaunchpoolParser()
                        display_name = "Bitget Launchpool"
                    elif special_parser == 'bybit_launchpool':
                        from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
                        parser = BybitLaunchpoolParser()
                        display_name = "Bybit Launchpool"
                    elif special_parser == 'gate_launchpool':
                        from parsers.gate_launchpool_parser import GateLaunchpoolParser
                        parser = GateLaunchpoolParser()
                        display_name = "Gate.io Launchpool"
                    elif special_parser == 'mexc_launchpool':
                        from parsers.mexc_launchpool_parser import MexcLaunchpoolParser
                        parser = MexcLaunchpoolParser()
                        display_name = "MEXC Launchpool"
                    elif special_parser == 'bitget_poolx':
                        from parsers.bitget_poolx_parser import BitgetPoolxParser
                        parser = BitgetPoolxParser()
                        display_name = "Bitget PoolX"
                    
                    if not parser:
                        await self.bot.send_message(chat_id, f"⚠️ Неизвестный launchpool парсер: {special_parser}")
                        return
                    
                    # Получаем проекты асинхронно
                    projects = await parser.get_projects_async()
                    
                    if projects:
                        # Фильтруем только active и upcoming
                        active_upcoming = [p for p in projects if p.status in ['active', 'upcoming']]
                        
                        # Получаем фильтры из настроек ссылки
                        with get_db_session() as db:
                            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                            if link:
                                filters = get_link_launchpool_filters(link)
                            else:
                                filters = {}
                        
                        # Применяем фильтры
                        filtered_projects = filter_launchpool_projects(
                            active_upcoming,
                            min_pool_usd=filters.get('min_pool_usd', 0),
                            min_apr=filters.get('min_apr', 0),
                            stake_coins_filter=filters.get('stake_coins_filter', []),
                            min_user_limit_usd=filters.get('min_user_limit_usd', 0)
                        )
                        
                        # Формируем информацию о фильтрах
                        filter_info = ""
                        if any([filters.get('min_pool_usd', 0) > 0, filters.get('min_apr', 0) > 0, 
                                filters.get('stake_coins_filter'), filters.get('min_user_limit_usd', 0) > 0]):
                            filter_info = "\n🔍 <b>Активные фильтры:</b>\n"
                            if filters.get('min_pool_usd', 0) > 0:
                                filter_info += f"   • Мин. пул: ${filters['min_pool_usd']:,.0f}\n"
                            if filters.get('min_apr', 0) > 0:
                                filter_info += f"   • Мин. APR: {filters['min_apr']:.0f}%\n"
                            if filters.get('stake_coins_filter'):
                                filter_info += f"   • Монеты: {', '.join(filters['stake_coins_filter'])}\n"
                            if filters.get('min_user_limit_usd', 0) > 0:
                                filter_info += f"   • Мин. лимит: ${filters['min_user_limit_usd']:,.0f}\n"
                            filter_info += f"\n📊 Всего: {len(active_upcoming)} → После фильтров: {len(filtered_projects)}\n"
                        
                        if filtered_projects:
                            message = f"🌊 <b>{display_name.upper()}</b>\n\n"
                            message += f"✅ Найдено проектов: {len(filtered_projects)}\n"
                            message += filter_info
                            message += "\n"
                            
                            for p in filtered_projects:
                                status_emoji = p.get_status_emoji()
                                message += f"{status_emoji} <b>{p.token_symbol}</b> - {p.token_name}\n"
                                message += f"   📊 Статус: {p.get_status_text()}\n"
                                if p.pools:
                                    max_apr = max([pool.apr for pool in p.pools if pool.apr > 0], default=0)
                                    if max_apr > 0:
                                        message += f"   📈 Макс. APR: {max_apr:.0f}%\n"
                                    stake_coins = set(pool.stake_coin for pool in p.pools if pool.stake_coin)
                                    if stake_coins:
                                        message += f"   💰 Стейк: {', '.join(stake_coins)}\n"
                                message += "\n"
                            
                            await self.bot.send_message(chat_id, message, parse_mode='HTML')
                        else:
                            msg = f"ℹ️ В {display_name} нет проектов по вашим фильтрам"
                            if filter_info:
                                msg += f"\n{filter_info}"
                            await self.bot.send_message(chat_id, msg, parse_mode='HTML')
                    else:
                        await self.bot.send_message(
                            chat_id, 
                            f"ℹ️ В {display_name} проекты не найдены"
                        )
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка {special_parser}: {e}", exc_info=True)
                    await self.bot.send_message(chat_id, f"❌ Ошибка при проверке: {str(e)[:100]}")
                return
            
            # TELEGRAM: используем TelegramMonitor для проверки
            if parsing_type == 'telegram':
                logger.info(f"📱 Принудительная проверка Telegram ссылки: {link_data['name']}")
                
                if not self.telegram_monitor:
                    await self.bot.send_message(
                        chat_id, 
                        "❌ Telegram Monitor не инициализирован.\n"
                        "Проверьте настройки Telegram аккаунта."
                    )
                    return
                
                telegram_channel = link_data.get('telegram_channel')
                if not telegram_channel:
                    await self.bot.send_message(
                        chat_id, 
                        "❌ Telegram канал не указан для этой ссылки.\n"
                        "Укажите канал в настройках ссылки."
                    )
                    return
                
                # Принудительная проверка через TelegramMonitor
                try:
                    result = await self.telegram_monitor.force_check_channel(link_id)
                    
                    if result and result.get('new_messages'):
                        messages = result.get('new_messages', [])
                        await self.bot.send_message(
                            chat_id,
                            f"✅ Найдено {len(messages)} новых сообщений в Telegram канале '{link_data['name']}'"
                        )
                    else:
                        await self.bot.send_message(
                            chat_id,
                            f"ℹ️ В Telegram канале '{link_data['name']}' новых сообщений не найдено"
                        )
                except Exception as e:
                    logger.error(f"❌ Ошибка Telegram проверки: {e}")
                    await self.bot.send_message(
                        chat_id,
                        f"❌ Ошибка при проверке Telegram канала: {e}"
                    )
                return

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

                # Синхронный вызов в отдельном потоке (используем глобальный executor)
                loop = asyncio.get_event_loop()
                new_stakings = await loop.run_in_executor(
                    get_executor(),
                    self.parser_service.parse_staking_link,
                    link_data['id'],
                    api_url,
                    exchange,
                    link_data.get('page_url'),
                    min_apr
                )

                # Фильтруем маркеры _no_new - они не являются реальными стейкингами
                new_stakings = [s for s in (new_stakings or []) if not s.get('_no_new')]
                
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
                                        notification_type = staking.get('_notification_type', 'new')
                                        stability_tracker.mark_notification_sent(staking_record, notification_type)
                                        db.commit()
                                        logger.info(f"✅ Отмечено как отправленное: {staking.get('coin')} (ID: {staking_db_id})")
                            except Exception as e:
                                logger.error(f"❌ Ошибка mark_notification_sent для {staking.get('coin')}: {e}")
                    await self.bot.send_message(chat_id, f"✅ Найдено {len(new_stakings)} новых стейкингов в ссылке '{link_data['name']}'")
                else:
                    await self.bot.send_message(chat_id, f"ℹ️ В ссылке '{link_data['name']}' новых стейкингов не найдено")

            elif category == 'announcement':
                # WEEX WELCOME BONUS ПАРСЕР
                if special_parser == 'weex_welcome':
                    logger.info(f"🎁 Принудительная проверка WEEX Welcome Bonus: {link_data['name']}")
                    
                    try:
                        from parsers.weex_welcome_parser import WeexWelcomeParser
                        
                        parser = WeexWelcomeParser()
                        
                        # Получаем текущие награды
                        loop = asyncio.get_event_loop()
                        new_rewards = await loop.run_in_executor(
                            get_executor(),
                            parser.get_promotions
                        )
                        
                        if not new_rewards:
                            await self.bot.send_message(chat_id, f"⚠️ Не удалось получить награды WEEX Welcome")
                            return
                        
                        # Получаем старый snapshot из БД
                        with get_db_session() as db:
                            link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                            old_snapshot = link.announcement_last_snapshot if link else None
                        
                        old_rewards = parser.deserialize_from_snapshot(old_snapshot) if old_snapshot else []
                        
                        if not old_rewards:
                            # Первый запуск - отправляем snapshot
                            logger.info(f"📸 Первый запуск - сохраняем snapshot ({len(new_rewards)} наград)")
                            
                            message = parser.format_snapshot_message(new_rewards)
                            await self.bot.send_message(chat_id, message, parse_mode='HTML', disable_web_page_preview=True)
                            
                            # Сохраняем snapshot
                            new_snapshot = parser.serialize_for_snapshot(new_rewards)
                            with get_db_session() as db:
                                db_link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                                if db_link:
                                    db_link.announcement_last_snapshot = new_snapshot
                                    db.commit()
                            
                            await self.bot.send_message(chat_id, f"✅ Обнаружено {len(new_rewards)} наград в WEEX Welcome (первый запуск)")
                        else:
                            # Сравниваем с предыдущим состоянием
                            changes = parser.compare_states(old_rewards, new_rewards)
                            
                            if changes['has_changes']:
                                logger.info(f"🎉 Обнаружены изменения в WEEX Welcome: {changes['summary']}")
                                
                                message = parser.format_changes_message(changes)
                                await self.bot.send_message(chat_id, message, parse_mode='HTML', disable_web_page_preview=True)
                                
                                # Обновляем snapshot
                                new_snapshot = parser.serialize_for_snapshot(new_rewards)
                                with get_db_session() as db:
                                    db_link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                                    if db_link:
                                        db_link.announcement_last_snapshot = new_snapshot
                                        db.commit()
                                
                                await self.bot.send_message(chat_id, f"✅ Найдены изменения в WEEX Welcome: {changes['summary']}")
                            else:
                                logger.info(f"✅ WEEX Welcome: без изменений")
                                await self.bot.send_message(chat_id, f"ℹ️ В ссылке '{link_data['name']}' изменений не найдено")
                        
                        # Обновляем время проверки
                        with get_db_session() as db:
                            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                            if link:
                                link.last_checked = datetime.utcnow()
                                db.commit()
                        
                        return  # Выход из функции после обработки
                        
                    except Exception as e:
                        logger.error(f"❌ Ошибка принудительной проверки weex_welcome: {e}", exc_info=True)
                        await self.bot.send_message(chat_id, f"❌ Ошибка при проверке WEEX Welcome: {str(e)}")
                        return
                
                # ОБЫЧНЫЕ АНОНСЫ: используем check_announcement_link()
                logger.info(f"📢 Принудительная проверка анонсов: {link_data['name']}")

                # Синхронный вызов в отдельном потоке (используем глобальный executor)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    get_executor(),
                    self.parser_service.check_announcement_link,
                    link_data['id'],
                    link_data['url']
                )

                # Отправляем уведомление если были изменения
                if result and result.get('changed'):
                    # Если есть new_promos - используем красивое форматирование
                    new_promos = result.get('new_promos', [])
                    strategy = result.get('strategy', '')
                    
                    if new_promos:
                        logger.info(f"📦 Announcement с special_parser: отправка {len(new_promos)} промоакций через красивое форматирование")
                        await self.send_notifications_to_all(new_promos)
                        await self.bot.send_message(chat_id, f"✅ Найдено {len(new_promos)} новых промоакций в ссылке '{link_data['name']}'")
                    elif strategy.startswith('weex_useragent:'):
                        # Для weex_useragent - сообщение уже красиво отформатировано
                        message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                        message += f"📝 Ссылка: {link_data['name']}\n"
                        message += f"🔍 Стратегия: {strategy}\n"
                        message += f"💬 {result.get('message')}\n\n"
                        message += f"🔗 <a href=\"{result.get('url')}\">Открыть страницу</a>"
                        await self.bot.send_message(chat_id, message, parse_mode='HTML')
                        await self.bot.send_message(chat_id, f"✅ Найдены изменения в ссылке '{link_data['name']}'")
                    else:
                        # Стандартный формат для обычных анонсов
                        message = f"📢 <b>Обнаружены изменения в анонсах</b>\n\n"
                        message += f"📝 Ссылка: {link_data['name']}\n"
                        message += f"🔍 Стратегия: {strategy}\n"
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
                # Синхронный вызов в отдельном потоке (используем глобальный executor)
                loop = asyncio.get_event_loop()
                new_promos = await loop.run_in_executor(
                    get_executor(), self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
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

        # Останавливаем Resource Monitor (если запущен)
        try:
            await shutdown_resource_monitor()
            logger.info("📊 Resource Monitor остановлен")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка остановки Resource Monitor: {e}")

        # Останавливаем Worker Pool (если запущен)
        if self.worker_pool:
            try:
                await shutdown_worker_pool()
                logger.info("⚡ Worker Pool остановлен")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка остановки Worker Pool: {e}")

        # Останавливаем Browser Pool (если запущен)
        if config.BROWSER_POOL_ENABLED:
            try:
                await shutdown_browser_pool()
                logger.info("🌐 Browser Pool остановлен")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка остановки Browser Pool: {e}")

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
    # Windows fix: Suppress subprocess cleanup warnings
    # На Windows, коли Playwright запускається з ThreadPool (без event loop),
    # виникають попередження при cleanup subprocess. Це косметична проблема.
    if sys.platform == 'win32':
        import warnings
        import io
        
        # Suppress warnings
        warnings.filterwarnings('ignore', category=ResourceWarning, message='.*subprocess.*')
        warnings.filterwarnings('ignore', message='.*Event loop is closed.*')
        warnings.filterwarnings('ignore', message='.*I/O operation on closed pipe.*')
        
        # Wrap sys.stderr to filter Playwright subprocess cleanup errors
        original_stderr = sys.stderr
        
        class FilteredStderr:
            def __init__(self, original):
                self.original = original
                self.buffer = []
                self.in_exception = False
                self.exception_buffer = []
                
            def write(self, text):
                # Detect start of exception block (both variants)
                if 'Exception ignored in:' in text or 'Traceback (most recent call last):' in text:
                    self.in_exception = True
                    self.exception_buffer = [text]
                    return
                
                # If we're collecting an exception block
                if self.in_exception:
                    self.exception_buffer.append(text)
                    
                    # Check if this is the end of the traceback (empty line or new log line with timestamp)
                    if text.strip() == '' or (len(self.exception_buffer) > 5 and text.startswith('2026-')):
                        # Check if the complete block should be filtered
                        full_text = ''.join(self.exception_buffer)
                        should_filter = any(phrase in full_text for phrase in [
                            'BaseSubprocessTransport.__del__',
                            '_ProactorBasePipeTransport.__del__',
                            'proactor_events.py',
                            'base_subprocess.py',
                            'windows_utils.py'
                        ])
                        
                        if should_filter:
                            # Suppress the entire exception block
                            self.exception_buffer = []
                            self.in_exception = False
                            # If this is a new log line, write it
                            if text.startswith('2026-'):
                                self.original.write(text)
                        else:
                            # Output the collected block if it's not filtered
                            for line in self.exception_buffer:
                                self.original.write(line)
                            self.exception_buffer = []
                            self.in_exception = False
                    return
                
                # Normal output
                self.original.write(text)
            
            def flush(self):
                self.original.flush()
            
            def fileno(self):
                return self.original.fileno()
        
        sys.stderr = FilteredStderr(original_stderr)
        logger.info("🪟 Windows: підавлення попереджень Playwright subprocess cleanup")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем")
    except Exception as e:
        logger.error(f"❌ Критична помилка: {e}", exc_info=True)