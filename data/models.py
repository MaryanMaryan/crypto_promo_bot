# data/models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from data.database import Base
import json

class ApiLink(Base):
    __tablename__ = 'api_links'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    url = Column(String)  # Основной URL (для обратной совместимости)
    # LEGACY: для обратной совместимости (будут удалены в будущих версиях)
    api_urls = Column(Text, default='[]')  # DEPRECATED: JSON массив API URL
    html_urls = Column(Text, default='[]')  # DEPRECATED: JSON массив HTML URL
    exchange = Column(String, nullable=True)  # DEPRECATED: не используется
    # НОВЫЕ ОДИНОЧНЫЕ ПОЛЯ
    api_url = Column(String, nullable=True)  # Одиночный API URL
    html_url = Column(String, nullable=True)  # Одиночный HTML URL (опциональный)
    parsing_type = Column(String, default='combined')  # Тип парсинга: api, html, browser, combined, telegram
    check_interval = Column(Integer, default=300)
    is_active = Column(Boolean, default=True)
    added_by = Column(Integer)
    last_checked = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # НОВЫЕ ПОЛЯ ДЛЯ СТЕЙКИНГА:
    category = Column(String, default='general')  # 'staking', 'launchpool', 'airdrop', 'announcement'
    page_url = Column(String, nullable=True)  # Ссылка на страницу акций

    # Фильтры для стейкинга (только для category='staking'):
    min_apr = Column(Float, nullable=True)  # Минимальный APR для показа
    track_fill = Column(Boolean, default=False)  # Отслеживать заполненность
    statuses_filter = Column(String, nullable=True)  # JSON список статусов: ["ONGOING", "INTERESTING"]
    types_filter = Column(String, nullable=True)  # JSON список типов: ["Flexible", "Fixed"]

    # ПОЛЯ ДЛЯ TELEGRAM ПАРСИНГА (только для parsing_type='telegram'):
    telegram_channel = Column(String, nullable=True)  # @channel_name или ссылка
    telegram_keywords = Column(Text, nullable=True, default='[]')  # JSON список ключевых слов
    telegram_account_id = Column(Integer, ForeignKey('telegram_accounts.id'), nullable=True)  # Назначенный аккаунт

    # Связи
    telegram_account = relationship("TelegramAccount", backref="assigned_links")

    def get_api_urls(self):
        """Получить список API URL"""
        try:
            urls = json.loads(self.api_urls) if self.api_urls else []
            return urls if urls else []
        except:
            return []

    def set_api_urls(self, urls):
        """Установить список API URL"""
        self.api_urls = json.dumps(urls) if urls else '[]'

    def get_html_urls(self):
        """Получить список HTML URL"""
        try:
            urls = json.loads(self.html_urls) if self.html_urls else []
            return urls if urls else []
        except:
            return []

    def set_html_urls(self, urls):
        """Установить список HTML URL"""
        self.html_urls = json.dumps(urls) if urls else '[]'

    def get_all_urls(self):
        """Получить все URL (API + HTML)"""
        return {
            'api': self.get_api_urls(),
            'html': self.get_html_urls()
        }

    def get_primary_api_url(self):
        """Получить основной API URL (новая система или первый из старых)"""
        if self.api_url:
            return self.api_url
        # Fallback для старых данных
        legacy_urls = self.get_api_urls()
        return legacy_urls[0] if legacy_urls else None

    def get_primary_html_url(self):
        """Получить основной HTML URL (новая система или первый из старых)"""
        if self.html_url:
            return self.html_url
        # Fallback для старых данных
        legacy_urls = self.get_html_urls()
        return legacy_urls[0] if legacy_urls else None

    def has_legacy_data(self):
        """Проверяет, использует ли запись старую систему"""
        return (not self.api_url and len(self.get_api_urls()) > 0)

    def get_telegram_keywords(self):
        """Получить список ключевых слов для Telegram"""
        try:
            keywords = json.loads(self.telegram_keywords) if self.telegram_keywords else []
            return keywords if keywords else []
        except:
            return []

    def set_telegram_keywords(self, keywords):
        """Установить список ключевых слов для Telegram"""
        self.telegram_keywords = json.dumps(keywords) if keywords else '[]'

    def add_telegram_keyword(self, keyword):
        """Добавить ключевое слово для Telegram"""
        keywords = self.get_telegram_keywords()
        if keyword.lower() not in [k.lower() for k in keywords]:
            keywords.append(keyword)
            self.set_telegram_keywords(keywords)
            return True
        return False

    def remove_telegram_keyword(self, keyword):
        """Удалить ключевое слово для Telegram"""
        keywords = self.get_telegram_keywords()
        keywords = [k for k in keywords if k.lower() != keyword.lower()]
        self.set_telegram_keywords(keywords)

class PromoHistory(Base):
    __tablename__ = 'promo_history'
    
    id = Column(Integer, primary_key=True)
    api_link_id = Column(Integer, ForeignKey('api_links.id'))
    promo_id = Column(String)
    exchange = Column(String)
    title = Column(String)
    description = Column(Text)
    total_prize_pool = Column(String)
    award_token = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    link = Column(String)
    icon = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    api_link = relationship("ApiLink", backref="promos")

class ProxyServer(Base):
    __tablename__ = 'proxy_servers'
    
    id = Column(Integer, primary_key=True)
    address = Column(String, unique=True)
    protocol = Column(String)
    status = Column(String, default="testing")
    speed_ms = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    priority = Column(Integer, default=5)
    last_used = Column(DateTime)
    last_success = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)

class UserAgent(Base):
    __tablename__ = 'user_agents'
    
    id = Column(Integer, primary_key=True)
    user_agent_string = Column(String, unique=True)
    browser_type = Column(String)
    browser_version = Column(String)
    platform = Column(String)
    device_type = Column(String)
    status = Column(String, default="active")
    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    last_used = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)

class RotationStats(Base):
    __tablename__ = 'rotation_stats'
    
    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, ForeignKey('proxy_servers.id'))
    user_agent_id = Column(Integer, ForeignKey('user_agents.id'))
    exchange = Column(String)
    request_result = Column(String)
    response_code = Column(Integer)
    response_time_ms = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    proxy = relationship("ProxyServer", backref="stats")
    user_agent = relationship("UserAgent", backref="stats")

class AggregatedStats(Base):
    __tablename__ = 'aggregated_stats'
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    exchange = Column(String)
    total_requests = Column(Integer, default=0)
    successful_requests = Column(Integer, default=0)
    blocked_requests = Column(Integer, default=0)
    average_response_time = Column(Float, default=0.0)
    best_proxy_id = Column(Integer, ForeignKey('proxy_servers.id'))
    best_user_agent_id = Column(Integer, ForeignKey('user_agents.id'))
    
    best_proxy = relationship("ProxyServer", foreign_keys=[best_proxy_id])
    best_user_agent = relationship("UserAgent", foreign_keys=[best_user_agent_id])

class RotationSettings(Base):
    __tablename__ = 'rotation_settings'

    id = Column(Integer, primary_key=True)
    rotation_interval = Column(Integer, default=1800)
    auto_optimize = Column(Boolean, default=True)
    stats_retention_days = Column(Integer, default=90)
    archive_inactive_days = Column(Integer, default=30)
    last_rotation = Column(DateTime)
    last_cleanup = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TelegramSettings(Base):
    """Глобальные настройки Telegram API (общие для всех аккаунтов)"""
    __tablename__ = 'telegram_settings'

    id = Column(Integer, primary_key=True)
    api_id = Column(String, nullable=True)  # Telegram API ID (общий для всех аккаунтов)
    api_hash = Column(String, nullable=True)  # Telegram API Hash (общий для всех аккаунтов)
    # DEPRECATED поля (для обратной совместимости):
    phone_number = Column(String, nullable=True)
    session_file = Column(String, default='sessions/telegram_parser_session')
    is_configured = Column(Boolean, default=False)
    last_auth = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TelegramAccount(Base):
    """Модель для хранения нескольких Telegram аккаунтов-парсеров"""
    __tablename__ = 'telegram_accounts'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # Название аккаунта (для удобства)
    phone_number = Column(String, nullable=False, unique=True)  # Номер телефона
    session_file = Column(String, nullable=False, unique=True)  # Уникальное имя файла сессии
    is_active = Column(Boolean, default=True)  # Активен ли аккаунт
    is_authorized = Column(Boolean, default=False)  # Авторизован ли
    last_used = Column(DateTime, nullable=True)  # Последнее использование
    added_by = Column(Integer, nullable=False)  # ID пользователя, добавившего аккаунт
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Статистика использования
    messages_parsed = Column(Integer, default=0)  # Количество обработанных сообщений
    channels_monitored = Column(Integer, default=0)  # Количество отслеживаемых каналов
    last_error = Column(Text, nullable=True)  # Последняя ошибка

    # Система fallback (блокировки)
    is_blocked = Column(Boolean, default=False)  # Заблокирован ли аккаунт
    blocked_at = Column(DateTime, nullable=True)  # Когда был заблокирован
    blocked_reason = Column(String, nullable=True)  # Причина блокировки (тип ошибки)

class StakingHistory(Base):
    __tablename__ = 'staking_history'

    id = Column(Integer, primary_key=True)

    # Основная информация
    exchange = Column(String, nullable=False)  # 'Kucoin', 'Bybit'
    product_id = Column(String, nullable=False)  # ID от биржи
    coin = Column(String, nullable=False)  # 'BTC', 'ETH', 'DOGE'
    reward_coin = Column(String, nullable=True)  # Для Bybit (награда в другой монете)

    # Условия стейкинга
    apr = Column(Float, nullable=False)  # 200.0, 100.0
    type = Column(String, nullable=True)  # 'Flexible', 'Fixed 30d', 'MULTI_TIME'
    status = Column(String, nullable=True)  # 'Active', 'Sold Out', 'ONGOING', 'INTERESTING'
    category = Column(String, nullable=True)  # 'ACTIVITY', 'DEMAND' (Kucoin)
    term_days = Column(Integer, nullable=True)  # 14, 30, 90

    # Лимиты и пулы
    user_limit_tokens = Column(Float, nullable=True)  # 5000 IR, 7.24 DOGE
    user_limit_usd = Column(Float, nullable=True)  # $664, $2.50
    total_places = Column(Integer, nullable=True)  # 298 мест

    # Данные о заполненности (если доступны)
    max_capacity = Column(Float, nullable=True)  # Максимальная вместимость
    current_deposit = Column(Float, nullable=True)  # Текущий депозит
    fill_percentage = Column(Float, nullable=True)  # Процент заполнения

    # Цены токенов
    token_price_usd = Column(Float, nullable=True)  # Цена основной монеты
    reward_token_price_usd = Column(Float, nullable=True)  # Цена наградной монеты

    # Временные метки
    start_time = Column(String, nullable=True)  # ISO format
    end_time = Column(String, nullable=True)  # ISO format
    first_seen = Column(DateTime, default=datetime.utcnow)  # Когда впервые нашли
    last_updated = Column(DateTime, default=datetime.utcnow)  # Последнее обновление

    # Флаги
    notification_sent = Column(Boolean, default=False)  # Отправили ли уведомление о новом

    # Уникальность по бирже и product_id
    __table_args__ = (
        UniqueConstraint('exchange', 'product_id', name='_exchange_product_uc'),
    )

class StakingSnapshot(Base):
    """Снимки стейкингов для отслеживания истории изменений APR, заполненности и цен"""
    __tablename__ = 'staking_snapshots'

    id = Column(Integer, primary_key=True)

    # Связь с основной записью стейкинга
    staking_history_id = Column(Integer, ForeignKey('staking_history.id'), nullable=False)

    # Дубликаты для независимости запросов
    exchange = Column(String, nullable=False)  # 'Kucoin', 'Bybit', 'OKX'
    product_id = Column(String, nullable=False)  # ID от биржи
    coin = Column(String, nullable=False)  # 'BTC', 'ETH', 'USDT'

    # Снимок данных на момент проверки
    apr = Column(Float, nullable=False)  # APR на момент снимка
    fill_percentage = Column(Float, nullable=True)  # Заполненность пула
    token_price_usd = Column(Float, nullable=True)  # Цена токена в USD
    status = Column(String, nullable=True)  # 'Active', 'Sold Out'

    # Временная метка снимка
    snapshot_time = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Связь
    staking_history = relationship("StakingHistory", backref="snapshots")

    # Индексы для быстрых запросов
    __table_args__ = (
        Index('idx_snapshot_staking_time', 'staking_history_id', 'snapshot_time'),
        Index('idx_snapshot_exchange_product', 'exchange', 'product_id'),
    )

class TelegramChannel(Base):
    __tablename__ = 'telegram_channels'

    id = Column(Integer, primary_key=True)

    # Информация о канале
    channel_username = Column(String, unique=True)  # @channel_name или ссылка
    channel_title = Column(String, nullable=True)  # Название канала
    channel_id = Column(Integer, nullable=True)  # Telegram ID канала

    # Ключевые слова для поиска (JSON массив)
    keywords = Column(Text, default='[]')  # ["airdrop", "промо", "campaign"]

    # Настройки мониторинга
    is_active = Column(Boolean, default=True)
    check_interval = Column(Integer, default=60)  # Проверка каждые 60 сек

    # Статистика
    total_messages_found = Column(Integer, default=0)
    last_message_date = Column(DateTime, nullable=True)
    last_checked = Column(DateTime, nullable=True)

    # Мета-информация
    added_by = Column(Integer)  # User ID кто добавил
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_keywords(self):
        """Получить список ключевых слов"""
        try:
            return json.loads(self.keywords) if self.keywords else []
        except:
            return []

    def set_keywords(self, keywords_list):
        """Установить список ключевых слов"""
        self.keywords = json.dumps(keywords_list) if keywords_list else '[]'

    def add_keyword(self, keyword):
        """Добавить ключевое слово"""
        keywords = self.get_keywords()
        if keyword.lower() not in [k.lower() for k in keywords]:
            keywords.append(keyword)
            self.set_keywords(keywords)
            return True
        return False

    def remove_keyword(self, keyword):
        """Удалить ключевое слово"""
        keywords = self.get_keywords()
        keywords = [k for k in keywords if k.lower() != keyword.lower()]
        self.set_keywords(keywords)

class TelegramMessage(Base):
    __tablename__ = 'telegram_messages'

    id = Column(Integer, primary_key=True)

    # Связь с каналом
    channel_id = Column(Integer, ForeignKey('telegram_channels.id'))

    # Информация о сообщении
    message_id = Column(Integer)  # ID сообщения в Telegram
    message_text = Column(Text)  # Полный текст сообщения
    message_date = Column(DateTime)  # Дата публикации

    # Найденные данные
    matched_keywords = Column(Text, default='[]')  # Какие ключевые слова совпали
    extracted_links = Column(Text, default='[]')  # Извлеченные ссылки из текста
    extracted_dates = Column(Text, nullable=True)  # Найденные даты (период акции)

    # Обработка
    notification_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)

    # Мета-информация
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связь
    channel = relationship("TelegramChannel", backref="messages")

    # Уникальность: один message_id на канал
    __table_args__ = (
        UniqueConstraint('channel_id', 'message_id', name='_channel_message_uc'),
    )

    def get_matched_keywords(self):
        """Получить список совпавших ключевых слов"""
        try:
            return json.loads(self.matched_keywords) if self.matched_keywords else []
        except:
            return []

    def set_matched_keywords(self, keywords_list):
        """Установить список совпавших ключевых слов"""
        self.matched_keywords = json.dumps(keywords_list) if keywords_list else '[]'

    def get_extracted_links(self):
        """Получить список извлеченных ссылок"""
        try:
            return json.loads(self.extracted_links) if self.extracted_links else []
        except:
            return []

    def set_extracted_links(self, links_list):
        """Установить список извлеченных ссылок"""
        self.extracted_links = json.dumps(links_list) if links_list else '[]'