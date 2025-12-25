# data/database.py
from sqlalchemy import create_engine, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
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
            'connect_args': {'check_same_thread': False}
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
        Index('idx_aggregated_date_exchange', AggregatedStats.date, AggregatedStats.exchange)
    ]
    return indexes

# ТРАНЗАКЦИОННЫЕ ОПЕРАЦИИ
@contextmanager
def transaction_session():
    """Контекстный менеджер для транзакций с retry логикой"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        with get_db_session() as session:
            try:
                yield session
                return
                
            except Exception as e:
                retry_count += 1
                logging.warning(f"⚠️ Повтор транзакции {retry_count}/{max_retries}: {e}")
                
                if retry_count == max_retries:
                    logging.error(f"❌ Транзакция провалена после {max_retries} попыток")
                    raise

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
            self._migration_006_add_staking_fields
        ])
    
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
                'category': "TEXT DEFAULT 'general'",
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

# Автоматическая инициализация при импорте
init_database()
migration_runner = DatabaseMigration()
migration_runner.run_migrations()