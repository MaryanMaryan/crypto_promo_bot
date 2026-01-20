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

    # НАСТРОЙКИ УМНЫХ УВЕДОМЛЕНИЙ (для category='staking'):
    notify_new_stakings = Column(Boolean, default=True)  # Уведомлять о новых стейкингах
    notify_apr_changes = Column(Boolean, default=True)  # Уведомлять об изменениях APR
    notify_fill_changes = Column(Boolean, default=False)  # Уведомлять о заполненности
    notify_min_apr_change = Column(Float, default=5.0)  # Минимальное изменение APR (абсолютное)
    flexible_stability_hours = Column(Integer, default=6)  # Часы стабильности для Flexible
    fixed_notify_immediately = Column(Boolean, default=True)  # Уведомлять о Fixed сразу
    notify_only_stable_flexible = Column(Boolean, default=True)  # Только стабильные Flexible
    notify_combined_as_fixed = Column(Boolean, default=True)  # Combined как Fixed (сразу)
    last_notification_sent = Column(DateTime, nullable=True)  # Последнее уведомление

    # ПОЛЯ ДЛЯ УМНОГО ПАРСИНГА АНОНСОВ (для category='announcement'):
    announcement_strategy = Column(String, nullable=True)  # Стратегия парсинга: 'any_change', 'element_change', 'any_keyword', 'all_keywords', 'regex'
    announcement_keywords = Column(Text, nullable=True, default='[]')  # JSON список ключевых слов для поиска
    announcement_regex = Column(String, nullable=True)  # Регулярное выражение для поиска
    announcement_css_selector = Column(String, nullable=True)  # CSS селектор для отслеживания конкретного элемента
    announcement_last_snapshot = Column(Text, nullable=True)  # Последний снимок страницы или элемента (hash или содержимое)
    announcement_last_check = Column(DateTime, nullable=True)  # Время последней проверки

    # СПЕЦИАЛЬНЫЙ ПАРСЕР (переопределяет стандартную логику):
    special_parser = Column(String, nullable=True)  # 'weex', 'okx_boost', etc. - использовать специальный парсер вместо стандартного

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

    # Методы для работы с ключевыми словами анонсов
    def get_announcement_keywords(self):
        """Получить список ключевых слов для анонсов"""
        try:
            keywords = json.loads(self.announcement_keywords) if self.announcement_keywords else []
            return keywords if keywords else []
        except:
            return []

    def set_announcement_keywords(self, keywords):
        """Установить список ключевых слов для анонсов"""
        self.announcement_keywords = json.dumps(keywords) if keywords else '[]'

    def add_announcement_keyword(self, keyword):
        """Добавить ключевое слово для анонсов"""
        keywords = self.get_announcement_keywords()
        if keyword.lower() not in [k.lower() for k in keywords]:
            keywords.append(keyword)
            self.set_announcement_keywords(keywords)
            return True
        return False

    def remove_announcement_keyword(self, keyword):
        """Удалить ключевое слово для анонсов"""
        keywords = self.get_announcement_keywords()
        keywords = [k for k in keywords if k.lower() != keyword.lower()]
        self.set_announcement_keywords(keywords)

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
    
    # НОВЫЕ ПОЛЯ для детальной информации о промоакциях
    participants_count = Column(Integer, nullable=True)  # Количество участников
    winners_count = Column(Integer, nullable=True)  # Количество призовых мест
    reward_per_winner = Column(String, nullable=True)  # Награда на одного победителя (например "400 FOGO")
    reward_per_winner_usd = Column(Float, nullable=True)  # Награда в USD
    conditions = Column(String, nullable=True)  # Условия участия (Spot, Futures, Invite и т.д.)
    reward_type = Column(String, nullable=True)  # Тип награды (Share Rewards, Fixed Rewards)
    max_reward_per_user = Column(String, nullable=True)  # Максимальная награда на пользователя
    total_prize_pool_usd = Column(Float, nullable=True)  # Призовой пул в USD
    status = Column(String, nullable=True)  # Статус: ongoing, upcoming, ended
    last_updated = Column(DateTime, nullable=True)  # Время последнего обновления данных

    # ПОЛЯ ДЛЯ MEXC AIRDROP (раздельные пулы)
    token_pool = Column(Float, nullable=True)  # Пул токенов (например 500000.0 COCO)
    token_pool_currency = Column(String, nullable=True)  # Валюта токен-пула (например "COCO")
    bonus_usdt = Column(Float, nullable=True)  # Бонусный пул в USDT (например 25000.0)
    token_price = Column(Float, nullable=True)  # Цена токена в USD (для расчёта эквивалента пула)
    
    # ПОЛЯ ДЛЯ MEXC LAUNCHPAD (полные данные API)
    promo_type = Column(String, nullable=True)  # Тип промо: mexc_launchpad, mexc_airdrop, okx_boost и т.д.
    raw_data = Column(Text, nullable=True)  # JSON с полными данными из API
    
    api_link = relationship("ApiLink", backref="promos")
    
    def get_estimated_winners(self) -> int:
        """Рассчитывает примерное количество призовых мест если не указано"""
        if self.winners_count:
            return self.winners_count
        
        # Пытаемся рассчитать: пул / награда = места
        if self.total_prize_pool_usd and self.reward_per_winner_usd and self.reward_per_winner_usd > 0:
            return int(self.total_prize_pool_usd / self.reward_per_winner_usd)
        
        return 0
    
    def get_competition_ratio(self) -> float:
        """Рассчитывает коэффициент конкуренции (участники / места)"""
        winners = self.get_estimated_winners()
        if winners > 0 and self.participants_count:
            return round(self.participants_count / winners, 1)
        return 0.0

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
    product_type = Column(String, nullable=True)  # 'SIMPLE_EARN', 'DUAL_CURRENCY', 'ETH_TWO' (для Binance и других)
    status = Column(String, nullable=True)  # 'Active', 'Sold Out', 'ONGOING', 'INTERESTING'
    category = Column(String, nullable=True)  # 'ACTIVITY', 'DEMAND' (Kucoin)
    category_text = Column(String, nullable=True)  # Текстовое описание категории (Kucoin)
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

    # ПОЛЯ ДЛЯ СИСТЕМЫ УМНЫХ УВЕДОМЛЕНИЙ:
    lock_type = Column(String, nullable=True)  # 'Fixed', 'Flexible', 'Combined'
    stable_since = Column(DateTime, nullable=True)  # Когда APR стал стабильным
    last_apr_change = Column(DateTime, nullable=True)  # Последнее изменение APR
    previous_apr = Column(Float, nullable=True)  # Предыдущий APR для расчета дельт
    notification_sent_at = Column(DateTime, nullable=True)  # Когда отправлено уведомление
    is_notification_pending = Column(Boolean, default=False)  # Ожидает ли уведомление (для Flexible)

    # ПОЛЯ ДЛЯ ОБЪЕДИНЁННЫХ ПРОДУКТОВ Fixed/Flexible (Gate.io):
    fixed_apr = Column(Float, nullable=True)  # APR для Fixed части
    fixed_term_days = Column(Integer, nullable=True)  # Срок Fixed в днях
    fixed_user_limit = Column(Float, nullable=True)  # Лимит пользователя для Fixed
    flexible_apr = Column(Float, nullable=True)  # APR для Flexible части
    flexible_user_limit = Column(Float, nullable=True)  # Лимит пользователя для Flexible

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

class ExchangeCredentials(Base):
    """Учетные данные для авторизации на биржах (для получения полных данных о стейкингах)"""
    __tablename__ = 'exchange_credentials'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # Название (например "Основной Bybit")
    exchange = Column(String, nullable=False)  # 'bybit', 'kucoin', 'okx'
    
    # API ключи
    api_key = Column(String, nullable=False)
    api_secret = Column(String, nullable=False)  # TODO: зашифровать в будущем
    passphrase = Column(String, nullable=True)  # Для Kucoin и OKX
    
    # Статус и метаданные
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # Прошел ли проверку
    last_verified = Column(DateTime, nullable=True)
    last_used = Column(DateTime, nullable=True)
    
    # Статистика
    requests_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    
    # Метаданные
    added_by = Column(Integer, nullable=False)  # User ID кто добавил
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Индексы
    __table_args__ = (
        Index('idx_exchange_active', 'exchange', 'is_active'),
    )
    
    def mask_api_key(self) -> str:
        """Маскировать API ключ для отображения"""
        if len(self.api_key) > 8:
            return self.api_key[:4] + '****' + self.api_key[-4:]
        return '****'
    
    def mask_api_secret(self) -> str:
        """Маскировать API secret для отображения"""
        return '**********'


class UserLinkSubscription(Base):
    """Подписки пользователей на уведомления по конкретным ссылкам"""
    __tablename__ = 'user_link_subscriptions'

    id = Column(Integer, primary_key=True)

    # Связи
    user_id = Column(Integer, nullable=False)  # Telegram user ID
    api_link_id = Column(Integer, ForeignKey('api_links.id'), nullable=False)

    # Настройки уведомлений пользователя
    notify_new = Column(Boolean, default=True)  # Уведомлять о новых стейкингах
    notify_apr_changes = Column(Boolean, default=True)  # Уведомлять об изменениях APR
    notify_fill_changes = Column(Boolean, default=False)  # Уведомлять о заполненности

    # Мета-информация
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связь
    api_link = relationship("ApiLink", backref="subscriptions")

    # Уникальность: один пользователь может подписаться на ссылку только раз
    __table_args__ = (
        UniqueConstraint('user_id', 'api_link_id', name='_user_link_uc'),
    )


class PromoParticipantsHistory(Base):
    """История участников промоакций для отслеживания динамики"""
    __tablename__ = 'promo_participants_history'

    id = Column(Integer, primary_key=True)
    
    # Идентификация промо
    exchange = Column(String, nullable=False)  # Биржа: GateCandy, OKX и др.
    promo_id = Column(String, nullable=False)  # ID промо (gate_247, okx_123)
    promo_title = Column(String, nullable=True)  # Название для удобства
    
    # Данные
    participants_count = Column(Integer, nullable=False)  # Количество участников
    
    # Временная метка
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_promo_history_lookup', 'exchange', 'promo_id', 'recorded_at'),
    )