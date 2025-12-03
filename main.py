import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import router
from data.database import init_database, get_db_session, ApiLink
from bot.parser_service import ParserService
from bot.notification_service import NotificationService
from bot.bot_manager import bot_manager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8256535319:AAE5YfagYcC1RF7M77UaJf7wyReiAniRli8"

class CryptoPromoBot:
    def __init__(self):
        self.bot = None
        self.dp = None
        self.scheduler = None
        self.parser_service = None
        self.notification_service = None
        self.YOUR_CHAT_ID = 7193869664
        self._shutdown_event = asyncio.Event()

    async def init_services(self):
        """Инициализация всех сервисов"""
        from data.database import init_database, DatabaseMigration
        
        init_database()
        
        # Запуск миграций
        migration_runner = DatabaseMigration()
        migration_runner.run_migrations()
        
        self.bot = Bot(token=BOT_TOKEN)
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)
        self.parser_service = ParserService()
        self.notification_service = NotificationService(self.bot)
        
        # Регистрируем роутеры
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

    async def smart_auto_check(self):
        """Умная автоматическая проверка - ТОЛЬКО АКТИВНЫЕ ссылки"""
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
                        'exchange': link.exchange or 'Unknown'
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
                    logger.info(f"🔍 Автоматически проверяем {link_data['name']} (интервал: {link_data['check_interval']}сек)")

                    # Синхронный вызов в отдельном потоке
                    loop = asyncio.get_event_loop()
                    new_promos = await loop.run_in_executor(
                        None, self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
                    )

                    # Отправляем уведомления о новых промоакциях
                    if new_promos:
                        await self.notification_service.send_bulk_notifications(
                            self.YOUR_CHAT_ID, new_promos
                        )
                        logger.info(f"📨 Отправлено {len(new_promos)} уведомлений")
                        total_new_promos += len(new_promos)

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

            if total_checked > 0:
                logger.info(f"✅ Автоматически проверено {total_checked} активных ссылок, найдено {total_new_promos} новых промоакций!")
            else:
                logger.info("ℹ️ Нет активных ссылок для проверки в этот раз")

        except Exception as e:
            logger.error(f"❌ Ошибка автоматической проверки: {e}")

    async def manual_check_all_links(self, chat_id: int):
        """Ручная проверка - ТОЛЬКО АКТИВНЫЕ ссылки"""
        try:
            logger.info(f"🔄 Ручная проверка АКТИВНЫХ ссылок от пользователя {chat_id}")
            logger.info("=" * 80)

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
                        'exchange': link.exchange or 'Unknown'
                    })

            logger.info(f"📊 Найдено {len(links_data)} активных ссылок для проверки:")
            for i, link_data in enumerate(links_data, 1):
                logger.info(f"   {i}. {link_data['name']} - {link_data['url']}")

            total_new_promos = 0
            checked_links = 0
            errors = []

            # Обрабатываем ссылки
            for link_data in links_data:
                if self._shutdown_event.is_set():
                    logger.warning("⏹️ Проверка прервана пользователем")
                    await self.bot.send_message(chat_id, "⏹️ Проверка прервана")
                    return

                try:
                    logger.info("-" * 80)
                    logger.info(f"🔍 НАЧАЛО ПРОВЕРКИ: {link_data['name']} (ID: {link_data['id']})")
                    logger.info(f"   URL: {link_data['url']}")
                    logger.info(f"   Биржа: {link_data['exchange']}")

                    # Синхронный вызов в отдельном потоке
                    loop = asyncio.get_event_loop()
                    new_promos = await loop.run_in_executor(
                        None, self.parser_service.check_for_new_promos, link_data['id'], link_data['url']
                    )

                    if new_promos:
                        logger.info(f"🎉 НАЙДЕНО {len(new_promos)} новых промоакций в {link_data['name']}:")
                        for i, promo in enumerate(new_promos, 1):
                            logger.info(f"   {i}. {promo.get('title', 'Без названия')} (ID: {promo.get('promo_id', 'N/A')})")

                        # Отправляем уведомления
                        await self.notification_service.send_bulk_notifications(chat_id, new_promos)
                        total_new_promos += len(new_promos)
                    else:
                        logger.info(f"ℹ️ В {link_data['name']} новых промоакций не найдено")

                    # Обновляем время проверки в новой сессии
                    with get_db_session() as db:
                        link = db.query(ApiLink).filter(ApiLink.id == link_data['id']).first()
                        if link:
                            link.last_checked = datetime.utcnow()
                            db.commit()
                            logger.debug(f"✅ Обновлено время последней проверки для {link_data['name']}")

                    checked_links += 1
                    logger.info(f"✅ ЗАВЕРШЕНА ПРОВЕРКА: {link_data['name']}")

                except Exception as e:
                    error_msg = f"{link_data['name']}: {str(e)}"
                    logger.error(f"❌ ОШИБКА ПРОВЕРКИ {link_data['name']}: {e}", exc_info=True)
                    errors.append(error_msg)
                    continue

            logger.info("=" * 80)
            logger.info(f"📊 ИТОГИ РУЧНОЙ ПРОВЕРКИ:")
            logger.info(f"   ✅ Проверено ссылок: {checked_links}/{len(links_data)}")
            logger.info(f"   🆕 Найдено новых промоакций: {total_new_promos}")
            logger.info(f"   ❌ Ошибок: {len(errors)}")
            if errors:
                logger.info(f"   Ошибки: {errors}")

            # Итоговое сообщение
            message = f"✅ Проверено: {checked_links} ссылок\n🆕 Найдено: {total_new_promos} промоакций"
            if errors:
                message += f"\n\n❌ Ошибки ({len(errors)}):\n" + "\n".join(errors[:3])
                if len(errors) > 3:
                    message += f"\n... и еще {len(errors) - 3} ошибок"

            await self.bot.send_message(chat_id, message)
            logger.info("=" * 80)

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
                    'exchange': link.exchange or 'Unknown'
                }

            logger.info(f"🔧 Принудительная проверка ссылки {link_data['name']} (ID: {link_id})")

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