# data/database.py
from __future__ import annotations
from sqlalchemy import create_engine, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session, joinedload
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import threading

Base = declarative_base()

# Импортируем модели после определения Base
from data.models import *

# Глобальные объекты БД
_engine = None
_SessionFactory = None
_lock = threading.RLock()

def init_database():
    """Инициализация подключения к БД с connection pooling"""
    global _engine, _SessionFactory
    
    with _lock:
        if _engine is not None:
            return
            
        database_url = 'sqlite:///data/database.db'
        
        # Настройки для SQLite
        engine_kwargs = {
            'echo': False,
            'connect_args': {
                'check_same_thread': False,
                'timeout': 60.0,  # Увеличиваем timeout до 60 секунд
                'isolation_level': None  # Autocommit mode для лучшей конкурентности
            }
        }
        
        engine_kwargs.update({
            'poolclass': StaticPool,
            'pool_pre_ping': True
        })
        
        _engine = create_engine(database_url, **engine_kwargs)
        _SessionFactory = sessionmaker(bind=_engine)
        
        # Создаем таблицы
        create_tables()
        initialize_default_settings()
        
        # Включаем WAL режим для лучшей конкурентности
        try:
            with _engine.connect() as conn:
                conn.execute(text('PRAGMA journal_mode=WAL'))
                conn.execute(text('PRAGMA busy_timeout=60000'))  # 60 секунд
                conn.commit()
            logging.info("✅ База данных инициализирована (WAL режим включен)")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось включить WAL режим: {e}")
            logging.info("✅ База данных инициализирована")

@contextmanager
def get_db_session():
    """Контекстный менеджер для сессий БД"""
    session = None
    try:
        if _SessionFactory is None:
            init_database()
            
        session = _SessionFactory()
        yield session
        session.commit()
        
    except Exception as e:
        logging.error(f"❌ Ошибка в транзакции БД: {e}")
        if session:
            session.rollback()
        raise
            
    finally:
        if session:
            session.close()

def get_db():
    """Устаревшая функция для обратной совместимости"""
    logging.warning("⚠️ Используется устаревший get_db(), используйте get_db_session()")
    return _SessionFactory() if _SessionFactory else None

# Создаем индексы
def create_indexes():
    """Создание индексов для оптимизации"""
    indexes = [
        Index('idx_proxy_status_speed', ProxyServer.status, ProxyServer.speed_ms),
        Index('idx_proxy_priority', ProxyServer.priority),
        Index('idx_ua_status_success', UserAgent.status, UserAgent.success_rate),
        Index('idx_stats_exchange_time', RotationStats.exchange, RotationStats.timestamp),
        Index('idx_stats_proxy_ua', RotationStats.proxy_id, RotationStats.user_agent_id),
        Index('idx_aggregated_date_exchange', AggregatedStats.date, AggregatedStats.exchange),
        # Индексы для Telegram
        Index('idx_tg_channel_username', TelegramChannel.channel_username),
        Index('idx_tg_channel_active', TelegramChannel.is_active),
        Index('idx_tg_message_channel_date', TelegramMessage.channel_id, TelegramMessage.message_date),
        Index('idx_tg_message_notification', TelegramMessage.notification_sent)
    ]
    return indexes

# ТРАНЗАКЦИОННЫЕ ОПЕРАЦИИ
@contextmanager
def transaction_session():
    """Контекстный менеджер для транзакций с retry логикой"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        session = None
        try:
            if _SessionFactory is None:
                init_database()
            
            session = _SessionFactory()
            yield session
            session.commit()
            return
            
        except Exception as e:
            if session:
                session.rollback()  # ВАЖНО: делаем rollback при ошибке
            
            # Проверяем, является ли ошибка "database is locked"
            if "database is locked" in str(e).lower() and retry_count < max_retries - 1:
                retry_count += 1
                logging.warning(f"⚠️ Повтор транзакции {retry_count}/{max_retries}: {e}")
                import time
                time.sleep(0.5 * retry_count)  # Экспоненциальная задержка
                continue
            else:
                # Для других ошибок или когда retry исчерпаны
                if retry_count > 0:
                    logging.error(f"❌ Транзакция провалена после {retry_count} попыток")
                raise
                
        finally:
            if session:
                session.close()

def atomic_operation(operation_func, *args, **kwargs):
    """Выполнение операции в транзакции с автоматическим retry"""
    with transaction_session() as session:
        return operation_func(session, *args, **kwargs)

# СИСТЕМА МИГРАЦИЙ
class DatabaseMigration:
    def __init__(self):
        self.migrations = []
        self._register_migrations()
    
    def _register_migrations(self):
        """Регистрация всех миграций"""
        self.migrations.extend([
            self._migration_001_initial,
            self._migration_002_add_indexes,
            self._migration_003_add_multiple_urls,
            self._migration_004_convert_to_single_urls,
            self._migration_005_add_parsing_type,
            self._migration_006_add_staking_fields,
            self._migration_007_add_telegram_tables,
            self._migration_008_add_telegram_accounts,
            self._migration_009_add_staking_snapshots,
            self._migration_010_add_announcement_fields,
            self._migration_011_add_exchange_credentials,
            self._migration_012_add_combined_staking_fields,
            self._migration_013_add_promo_raw_data,
            self._migration_014_add_is_favorite
        ])

    def _migration_010_add_announcement_fields(self, session):
        """Добавление полей для умного парсинга анонсов (announcement_*)"""
        try:
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]
            fields_to_add = {
                'announcement_strategy': 'TEXT',
                'announcement_keywords': "TEXT DEFAULT '[]'",
                'announcement_regex': 'TEXT',
                'announcement_css_selector': 'TEXT',
                'announcement_last_snapshot': 'TEXT',
                'announcement_last_check': 'DATETIME'
            }
            added_count = 0
            for field_name, field_type in fields_to_add.items():
                if field_name not in columns:
                    session.execute(text(f"ALTER TABLE api_links ADD COLUMN {field_name} {field_type}"))
                    logging.info(f"✅ Добавлен столбец {field_name}")
                    added_count += 1
            if added_count > 0:
                session.commit()
                logging.info(f"✅ Миграция 010: Добавлено {added_count} полей для анонсов")
            else:
                logging.info("ℹ️ Все поля анонсов уже существуют")
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 010: {e}")
            raise
    
    def _migration_011_add_exchange_credentials(self, session):
        """Миграция 011: Создание таблицы exchange_credentials для API ключей бирж"""
        try:
            # Проверяем существование таблицы
            result = session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='exchange_credentials'"
            ))
            if result.fetchone() is not None:
                logging.info("ℹ️ Таблица exchange_credentials уже существует")
                return
            
            # Создаём таблицу
            session.execute(text("""
                CREATE TABLE exchange_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR NOT NULL,
                    exchange VARCHAR NOT NULL,
                    api_key VARCHAR NOT NULL,
                    api_secret VARCHAR NOT NULL,
                    passphrase VARCHAR,
                    is_active BOOLEAN DEFAULT 1,
                    is_verified BOOLEAN DEFAULT 0,
                    last_verified DATETIME,
                    last_used DATETIME,
                    requests_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    added_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Создаём индекс
            session.execute(text(
                "CREATE INDEX idx_exchange_active ON exchange_credentials(exchange, is_active)"
            ))
            
            session.commit()
            logging.info("✅ Миграция 011: Создана таблица exchange_credentials")
            
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 011: {e}")
            raise
    
    def _migration_001_initial(self, session):
        """Первоначальная миграция"""
        pass
    
    def _migration_002_add_indexes(self, session):
        """Миграция для добавления индексов"""
        pass

    def _migration_003_add_multiple_urls(self, session):
        """Миграция для добавления полей api_urls и html_urls"""
        try:
            # Проверяем, есть ли уже эти столбцы
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]

            # Добавляем api_urls если его нет
            if 'api_urls' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN api_urls TEXT DEFAULT '[]'"))
                logging.info("✅ Добавлен столбец api_urls")

            # Добавляем html_urls если его нет
            if 'html_urls' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN html_urls TEXT DEFAULT '[]'"))
                logging.info("✅ Добавлен столбец html_urls")

            session.commit()
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 003: {e}")
            raise

    def _migration_004_convert_to_single_urls(self, session):
        """Миграция 004: Конвертация множественных URL в одиночные"""
        import json

        try:
            # Шаг 1: Проверка существующих столбцов
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]

            # Шаг 2: Добавление новых столбцов
            if 'api_url' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN api_url TEXT"))
                logging.info("✅ Добавлен столбец api_url")

            if 'html_url' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN html_url TEXT"))
                logging.info("✅ Добавлен столбец html_url")

            session.commit()

            # Шаг 3: Конвертация данных используя raw SQL
            # Получаем данные напрямую через SQL
            result = session.execute(text("SELECT id, url, api_urls, html_urls, api_url, html_url, exchange FROM api_links"))
            rows = result.fetchall()
            converted_count = 0

            for row in rows:
                link_id = row[0]
                url = row[1]
                api_urls_json = row[2]
                html_urls_json = row[3]
                current_api_url = row[4]
                current_html_url = row[5]

                # Пропускаем если уже конвертировано
                if current_api_url:
                    continue

                # Конвертируем API URLs
                new_api_url = None
                try:
                    api_urls_list = json.loads(api_urls_json) if api_urls_json else []
                    if api_urls_list:
                        new_api_url = api_urls_list[0]
                    elif url:
                        new_api_url = url
                except:
                    if url:
                        new_api_url = url

                # Конвертируем HTML URLs
                new_html_url = None
                try:
                    html_urls_list = json.loads(html_urls_json) if html_urls_json else []
                    if html_urls_list:
                        new_html_url = html_urls_list[0]
                except:
                    pass

                # Обновляем через SQL
                if new_api_url:
                    session.execute(text(
                        "UPDATE api_links SET api_url = :api_url, html_url = :html_url, exchange = NULL WHERE id = :id"
                    ), {"api_url": new_api_url, "html_url": new_html_url, "id": link_id})
                    converted_count += 1

            session.commit()
            logging.info(f"✅ Миграция 004: Конвертировано {converted_count} ссылок")
            logging.info(f"   - JSON массивы → одиночные URL")
            logging.info(f"   - Поле exchange очищено")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 004: {e}")
            raise

    def _migration_005_add_parsing_type(self, session):
        """Миграция 005: Добавление поля parsing_type"""
        try:
            # Проверка существующих столбцов
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]

            # Добавление поля parsing_type
            if 'parsing_type' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN parsing_type TEXT DEFAULT 'combined'"))
                logging.info("✅ Добавлен столбец parsing_type")
                session.commit()
            else:
                logging.info("ℹ️ Столбец parsing_type уже существует")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 005: {e}")
            raise

    def _migration_006_add_staking_fields(self, session):
        """Миграция 006: Добавление полей для стейкинга"""
        try:
            # Проверка существующих столбцов
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]

            # Добавление новых полей для стейкинга
            fields_to_add = {
                'category': "TEXT DEFAULT 'launches'",
                'page_url': "TEXT",
                'min_apr': "REAL",
                'track_fill': "INTEGER DEFAULT 0",
                'statuses_filter': "TEXT",
                'types_filter': "TEXT"
            }

            added_count = 0
            for field_name, field_type in fields_to_add.items():
                if field_name not in columns:
                    session.execute(text(f"ALTER TABLE api_links ADD COLUMN {field_name} {field_type}"))
                    logging.info(f"✅ Добавлен столбец {field_name}")
                    added_count += 1

            if added_count > 0:
                session.commit()
                logging.info(f"✅ Миграция 006: Добавлено {added_count} полей для стейкинга")
            else:
                logging.info("ℹ️ Все поля стейкинга уже существуют")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 006: {e}")
            raise

    def _migration_007_add_telegram_tables(self, session):
        """Миграция 007: Добавление таблиц для Telegram-парсера"""
        try:
            from sqlalchemy import inspect
            inspector = inspect(session.bind)
            tables = inspector.get_table_names()

            if 'telegram_channels' in tables:
                logging.info("✅ Таблица telegram_channels уже существует")
            else:
                logging.info("📡 Создание таблицы telegram_channels...")

            if 'telegram_messages' in tables:
                logging.info("✅ Таблица telegram_messages уже существует")
            else:
                logging.info("📡 Создание таблицы telegram_messages...")

            # Таблицы создаются автоматически через Base.metadata.create_all()
            logging.info("✅ Миграция 007: Telegram таблицы проверены/созданы")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 007: {e}")
            raise

    def _migration_008_add_telegram_accounts(self, session):
        """Миграция 008: Добавление таблицы telegram_accounts для множественных аккаунтов"""
        try:
            from sqlalchemy import inspect
            inspector = inspect(session.bind)
            tables = inspector.get_table_names()

            if 'telegram_accounts' in tables:
                logging.info("✅ Таблица telegram_accounts уже существует")
            else:
                logging.info("📱 Создание таблицы telegram_accounts...")
                # Таблица создается автоматически через Base.metadata.create_all()

            logging.info("✅ Миграция 008: Таблица telegram_accounts проверена/создана")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 008: {e}")
            raise

    def _migration_009_add_staking_snapshots(self, session):
        """Миграция 009: Добавление таблицы staking_snapshots для истории изменений"""
        try:
            from sqlalchemy import inspect
            inspector = inspect(session.bind)
            tables = inspector.get_table_names()

            if 'staking_snapshots' in tables:
                logging.info("✅ Таблица staking_snapshots уже существует")
            else:
                logging.info("📸 Создание таблицы staking_snapshots...")
                # Таблица создается автоматически через Base.metadata.create_all()
                from data.models import StakingSnapshot
                StakingSnapshot.__table__.create(session.bind, checkfirst=True)
                logging.info("✅ Таблица staking_snapshots создана")

            logging.info("✅ Миграция 009: Таблица staking_snapshots проверена/создана")

        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 009: {e}")
            raise

    def _migration_012_add_combined_staking_fields(self, session):
        """Миграция 012: Добавление полей для объединённых продуктов Fixed/Flexible (Gate.io)"""
        try:
            result = session.execute(text("PRAGMA table_info(staking_history)"))
            columns = [row[1] for row in result.fetchall()]
            
            fields_to_add = {
                'fixed_apr': 'REAL',
                'fixed_term_days': 'INTEGER',
                'fixed_user_limit': 'REAL',
                'flexible_apr': 'REAL',
                'flexible_user_limit': 'REAL'
            }
            
            added_count = 0
            for field_name, field_type in fields_to_add.items():
                if field_name not in columns:
                    session.execute(text(f"ALTER TABLE staking_history ADD COLUMN {field_name} {field_type}"))
                    logging.info(f"✅ Добавлен столбец {field_name}")
                    added_count += 1
            
            if added_count > 0:
                session.commit()
                logging.info(f"✅ Миграция 012: Добавлено {added_count} полей для Fixed/Flexible продуктов")
            else:
                logging.info("ℹ️ Все поля Fixed/Flexible уже существуют")
                
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 012: {e}")
            raise

    def _migration_013_add_promo_raw_data(self, session):
        """Миграция 013: Добавление полей promo_type и raw_data в promo_history для хранения полных данных API"""
        try:
            result = session.execute(text("PRAGMA table_info(promo_history)"))
            columns = [row[1] for row in result.fetchall()]
            
            fields_to_add = {
                'promo_type': 'TEXT',  # mexc_launchpad, mexc_airdrop, okx_boost, bybit_launchpad и т.д.
                'raw_data': 'TEXT'  # JSON с полными данными из API
            }
            
            added_count = 0
            for field_name, field_type in fields_to_add.items():
                if field_name not in columns:
                    session.execute(text(f"ALTER TABLE promo_history ADD COLUMN {field_name} {field_type}"))
                    logging.info(f"✅ Добавлен столбец {field_name} в promo_history")
                    added_count += 1
            
            if added_count > 0:
                session.commit()
                logging.info(f"✅ Миграция 013: Добавлено {added_count} полей для raw_data")
            else:
                logging.info("ℹ️ Все поля raw_data уже существуют")
                
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 013: {e}")
            raise

    def _migration_014_add_is_favorite(self, session):
        """Миграция 014: Добавление поля is_favorite для избранных ссылок"""
        try:
            result = session.execute(text("PRAGMA table_info(api_links)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'is_favorite' not in columns:
                session.execute(text("ALTER TABLE api_links ADD COLUMN is_favorite INTEGER DEFAULT 0"))
                logging.info("✅ Добавлен столбец is_favorite")
                session.commit()
                logging.info("✅ Миграция 014: Добавлено поле is_favorite")
            else:
                logging.info("ℹ️ Столбец is_favorite уже существует")
                
        except Exception as e:
            logging.error(f"❌ Ошибка в миграции 014: {e}")
            raise

    def run_migrations(self):
        """Запуск всех миграций"""
        logging.info("🔄 Проверка миграций базы данных...")
        
        with get_db_session() as session:
            for i, migration in enumerate(self.migrations, 1):
                try:
                    migration(session)
                    logging.info(f"✅ Миграция {i}/{len(self.migrations)} выполнена")
                except Exception as e:
                    logging.error(f"❌ Ошибка в миграции {i}: {e}")
                    raise

# ОБНОВЛЕННЫЕ ФУНКЦИИ
def create_tables():
    """Создание таблиц с обработкой ошибок"""
    try:
        Base.metadata.create_all(_engine)
        logging.info("✅ Все таблицы созданы/проверены")
    except Exception as e:
        logging.error(f"❌ Ошибка создания таблиц: {e}")
        raise

def initialize_default_settings():
    """Инициализация настроек по умолчанию в транзакции"""
    def _init_settings(session):
        if not session.query(RotationSettings).first():
            default_settings = RotationSettings()
            session.add(default_settings)
            logging.info("✅ Созданы настройки ротации по умолчанию")
    
    atomic_operation(_init_settings)

def cleanup_old_data():
    """Очистка старых данных в транзакции"""
    def _cleanup(session):
        settings = session.query(RotationSettings).first()
        if not settings:
            return
            
        # Очистка детальной статистики
        cutoff_date = datetime.utcnow() - timedelta(days=settings.stats_retention_days)
        deleted_stats = session.query(RotationStats).filter(
            RotationStats.timestamp < cutoff_date
        ).delete()
        
        # Архивация неактивных прокси
        archive_cutoff = datetime.utcnow() - timedelta(days=settings.archive_inactive_days)
        
        archived_proxies = session.query(ProxyServer).filter(
            ProxyServer.status == 'inactive',
            ProxyServer.last_used < archive_cutoff,
            ProxyServer.archived_at.is_(None)
        ).update({
            'status': 'archived',
            'archived_at': datetime.utcnow()
        })
        
        archived_ua = session.query(UserAgent).filter(
            UserAgent.status == 'inactive', 
            UserAgent.last_used < archive_cutoff,
            UserAgent.archived_at.is_(None)
        ).update({
            'status': 'archived',
            'archived_at': datetime.utcnow()
        })
        
        settings.last_cleanup = datetime.utcnow()
        
        logging.info(f"🗑️ Очистка: удалено {deleted_stats} записей, "
                    f"архивировано {archived_proxies} прокси и {archived_ua} UA")
    
    atomic_operation(_cleanup)


# =============================================================================
# ASYNC ФУНКЦИИ ДЛЯ ОТЗЫВЧИВОГО UI
# =============================================================================

import asyncio
from typing import List, Optional, Any, Callable, TypeVar
from concurrent.futures import ThreadPoolExecutor

# Глобальный executor для async операций с БД
_db_executor: Optional[ThreadPoolExecutor] = None

def _get_db_executor() -> ThreadPoolExecutor:
    """Получить executor для async БД операций"""
    global _db_executor
    if _db_executor is None:
        _db_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="db_async_")
    return _db_executor


async def run_in_db_executor(func: Callable, *args, **kwargs) -> Any:
    """
    Выполнить синхронную функцию в отдельном потоке
    
    Использование:
        result = await run_in_db_executor(my_sync_function, arg1, arg2)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_get_db_executor(), lambda: func(*args, **kwargs))


async def get_links_async(
    category: Optional[str] = None,
    is_active: Optional[bool] = None
) -> List[ApiLink]:
    """
    Асинхронно получить список ссылок
    
    Args:
        category: Фильтр по категории ('airdrop', 'staking', etc.)
        is_active: Фильтр по активности
    
    Returns:
        Список ApiLink объектов
    """
    from utils.cache import get_cache_manager, CacheKeys
    
    # Формируем ключ кэша
    cache_key = f"links:all:{category or 'all'}:{is_active}"
    cache = get_cache_manager()
    
    # Проверяем кэш
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    def _get_links():
        with get_db_session() as db:
            query = db.query(ApiLink).options(
                joinedload(ApiLink.telegram_account)  # Предзагружаем связанный telegram_account
            )
            
            if category:
                query = query.filter(ApiLink.category == category)
            if is_active is not None:
                query = query.filter(ApiLink.is_active == is_active)
            
            # Загружаем связанные объекты (уже включая telegram_account через joinedload)
            links = query.all()
            
            # Детачим объекты от сессии
            for link in links:
                # Также детачим telegram_account если загружен
                if link.telegram_account:
                    db.expunge(link.telegram_account)
                db.expunge(link)
            
            return links
    
    links = await run_in_db_executor(_get_links)
    
    # Кэшируем на 30 секунд
    cache.set(cache_key, links, ttl=30)
    
    return links


async def get_link_by_id_async(link_id: int) -> Optional[ApiLink]:
    """
    Асинхронно получить ссылку по ID
    
    Args:
        link_id: ID ссылки
    
    Returns:
        ApiLink объект или None
    """
    from utils.cache import get_cache_manager, CacheKeys
    
    cache_key = CacheKeys.link_by_id(link_id)
    cache = get_cache_manager()
    
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    def _get_link():
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if link:
                db.expunge(link)
            return link
    
    link = await run_in_db_executor(_get_link)
    
    if link:
        cache.set(cache_key, link, ttl=30)
    
    return link


async def get_active_links_count_async() -> int:
    """Асинхронно получить количество активных ссылок"""
    from utils.cache import get_cache_manager
    
    cache = get_cache_manager()
    cache_key = "links:active_count"
    
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    def _count():
        with get_db_session() as db:
            return db.query(ApiLink).filter(ApiLink.is_active == True).count()
    
    count = await run_in_db_executor(_count)
    cache.set(cache_key, count, ttl=30)
    
    return count


async def get_links_by_category_async(category: str) -> List[ApiLink]:
    """
    Асинхронно получить ссылки по категории
    
    Args:
        category: Категория ('airdrop', 'staking', 'launchpool', 'announcement')
    """
    return await get_links_async(category=category)


async def get_favorite_links_async() -> List[ApiLink]:
    """
    Асинхронно получить избранные ссылки
    
    Returns:
        Список ApiLink объектов с is_favorite=True
    """
    from utils.cache import get_cache_manager
    
    cache_key = "links:favorites"
    cache = get_cache_manager()
    
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    def _get_favorites():
        with get_db_session() as db:
            query = db.query(ApiLink).options(
                joinedload(ApiLink.telegram_account)
            ).filter(ApiLink.is_favorite == True)
            
            links = query.all()
            
            for link in links:
                if link.telegram_account:
                    db.expunge(link.telegram_account)
                db.expunge(link)
            
            return links
    
    links = await run_in_db_executor(_get_favorites)
    cache.set(cache_key, links, ttl=30)
    
    return links


async def update_link_async(link_id: int, **updates) -> bool:
    """
    Асинхронно обновить поля ссылки
    
    Args:
        link_id: ID ссылки
        **updates: Поля для обновления (например, is_active=False)
    
    Returns:
        True если обновлено успешно
    """
    from utils.cache import invalidate_links_cache
    
    def _update():
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                return False
            
            for key, value in updates.items():
                if hasattr(link, key):
                    setattr(link, key, value)
            
            return True
    
    result = await run_in_db_executor(_update)
    
    # Инвалидируем кэш
    if result:
        invalidate_links_cache()
    
    return result


async def delete_link_async(link_id: int) -> bool:
    """
    Асинхронно удалить ссылку
    
    Args:
        link_id: ID ссылки
    
    Returns:
        True если удалено успешно
    """
    from utils.cache import invalidate_links_cache
    
    def _delete():
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                return False
            
            db.delete(link)
            return True
    
    result = await run_in_db_executor(_delete)
    
    if result:
        invalidate_links_cache()
    
    return result


async def create_link_async(**link_data) -> Optional[ApiLink]:
    """
    Асинхронно создать новую ссылку
    
    Args:
        **link_data: Поля для новой ссылки
    
    Returns:
        Созданный ApiLink объект или None
    """
    from utils.cache import invalidate_links_cache
    
    def _create():
        with get_db_session() as db:
            link = ApiLink(**link_data)
            db.add(link)
            db.flush()
            db.refresh(link)
            db.expunge(link)
            return link
    
    link = await run_in_db_executor(_create)
    
    if link:
        invalidate_links_cache()
    
    return link


# Автоматическая инициализация при импорте
init_database()
migration_runner = DatabaseMigration()
migration_runner.run_migrations()