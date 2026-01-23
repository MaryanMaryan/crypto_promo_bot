"""
Базовый класс для парсеров Launchpool/Launchpad
Все биржи наследуют от этого класса
"""

import logging
import requests
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LaunchpoolPool:
    """Данные о конкретном пуле для стейкинга"""
    stake_coin: str  # Токен для стейкинга (BTC, ETH, BGB, etc.)
    stake_coin_icon: str = ""
    apr: float = 0.0  # APR в процентах (800 = 800%)
    apy: float = 0.0  # APY если есть
    min_stake: float = 0.0  # Минимальный депозит
    max_stake: float = 0.0  # Максимальный депозит (0 = без лимита)
    max_stake_vip: float = 0.0  # Макс для VIP
    total_staked: float = 0.0  # Всего застейкано
    pool_reward: float = 0.0  # Награды выделено на этот пул
    participants: int = 0  # Участников в этом пуле
    is_new_user_only: bool = False  # Только для новых
    labels: List[str] = field(default_factory=list)  # Метки (Hot, New, etc.)
    extra_data: Dict[str, Any] = field(default_factory=dict)  # Дополнительные данные для Launchpad
    
    def calculate_earnings(self, deposit: float, days_left: int) -> float:
        """Расчёт заработка по формуле: Депозит × APR × (Дней / 365)"""
        if self.apr <= 0 or days_left <= 0:
            return 0.0
        return deposit * (self.apr / 100) * (days_left / 365)


@dataclass 
class LaunchpoolProject:
    """Данные о проекте Launchpool"""
    # Основная информация
    id: str  # ID проекта
    exchange: str  # Название биржи
    type: str  # "launchpool" или "launchpad"
    
    # Токен
    token_symbol: str  # SKR, ELSA, etc.
    token_name: str  # Полное название
    token_icon: str = ""
    
    # Статус
    status: str = "unknown"  # active, upcoming, ended
    status_text: str = ""  # Текст статуса для отображения
    
    # Награды
    total_pool_usd: float = 0.0  # Общий пул в USD
    total_pool_tokens: float = 0.0  # Общий пул в токенах
    
    # Время
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Пулы для стейкинга
    pools: List[LaunchpoolPool] = field(default_factory=list)
    
    # Ссылки
    project_url: str = ""  # Ссылка на страницу проекта на бирже
    website: str = ""
    twitter: str = ""
    whitepaper: str = ""
    
    # Дополнительно
    description: str = ""
    total_participants: int = 0
    
    @property
    def days_left(self) -> int:
        """Сколько дней осталось"""
        if not self.end_time:
            return 0
        delta = self.end_time - datetime.now()
        return max(0, delta.days)
    
    @property
    def hours_left(self) -> int:
        """Сколько часов осталось (остаток после дней)"""
        if not self.end_time:
            return 0
        delta = self.end_time - datetime.now()
        return max(0, delta.seconds // 3600)
    
    @property
    def time_remaining_str(self) -> str:
        """Форматированная строка оставшегося времени"""
        if not self.end_time:
            return "—"
        
        delta = self.end_time - datetime.now()
        if delta.total_seconds() <= 0:
            return "Завершено"
        
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if days > 0:
            return f"{days} д. {hours} ч."
        elif hours > 0:
            return f"{hours} ч. {minutes} мин."
        else:
            return f"{minutes} мин."
    
    @property
    def max_apr(self) -> float:
        """Максимальный APR среди всех пулов"""
        if not self.pools:
            return 0.0
        return max(p.apr for p in self.pools)
    
    def get_status_emoji(self) -> str:
        """Эмодзи статуса"""
        status_map = {
            'active': '✅',
            'ongoing': '✅',
            'upcoming': '🟡',
            'waiting': '🟡',
            'ended': '⏹️',
            'finished': '⏹️',
        }
        return status_map.get(self.status.lower(), '❓')
    
    def get_status_text(self) -> str:
        """Текст статуса на русском"""
        if self.status_text:
            return self.status_text
        
        status_map = {
            'active': 'Активный',
            'ongoing': 'Активный',
            'upcoming': 'Скоро начнётся',
            'waiting': 'Скоро начнётся',
            'ended': 'Завершён',
            'finished': 'Завершён',
        }
        return status_map.get(self.status.lower(), 'Неизвестно')


class LaunchpoolBaseParser(ABC):
    """
    Базовый класс для всех Launchpool/Launchpad парсеров
    
    Каждая биржа должна реализовать:
    - fetch_data() - получение данных с API
    - parse_projects() - парсинг в LaunchpoolProject
    """
    
    EXCHANGE_NAME: str = "Unknown"
    EXCHANGE_TYPE: str = "launchpool"  # launchpool или launchpad
    BASE_URL: str = ""
    API_URL: str = ""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.session = requests.Session()
        self._setup_headers()
    
    def _setup_headers(self):
        """Настройка заголовков для запросов"""
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
    
    @abstractmethod
    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """
        Получение сырых данных с API биржи
        Должен возвращать JSON ответ или None при ошибке
        """
        pass
    
    @abstractmethod
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """
        Парсинг сырых данных в список LaunchpoolProject
        """
        pass
    
    def get_projects(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Основной метод - получает и парсит проекты
        
        Args:
            status_filter: Фильтр по статусу ('active', 'upcoming', 'ended', None=все)
        
        Returns:
            Список LaunchpoolProject
        """
        try:
            self.logger.info(f"🔍 {self.EXCHANGE_NAME}: Загрузка {self.EXCHANGE_TYPE} проектов...")
            
            # Получаем данные
            data = self.fetch_data()
            if not data:
                self.logger.error(f"❌ {self.EXCHANGE_NAME}: Не удалось получить данные")
                return []
            
            # Парсим
            projects = self.parse_projects(data)
            self.logger.info(f"✅ {self.EXCHANGE_NAME}: Найдено {len(projects)} проектов")
            
            # Фильтруем по статусу если нужно
            if status_filter:
                projects = [p for p in projects if p.status.lower() == status_filter.lower()]
                self.logger.info(f"   После фильтра '{status_filter}': {len(projects)} проектов")
            
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ {self.EXCHANGE_NAME}: Ошибка: {e}", exc_info=True)
            return []
    
    def format_project(self, project: LaunchpoolProject) -> str:
        """
        Форматирование проекта для отправки в Telegram
        
        Использует согласованный формат:
        🌊 BYBIT LAUNCHPOOL
        ...
        """
        lines = []
        
        # Заголовок
        emoji = "🌊" if project.type == "launchpool" else "🚀"
        lines.append(f"{emoji} {project.exchange.upper()} {project.type.upper()}")
        lines.append("")
        lines.append(f"🏦 Биржа: {project.exchange} {project.type.capitalize()}")
        lines.append(f"⏱️ Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("━" * 34)
        lines.append("")
        
        # Токен
        lines.append(f"🪙 {project.token_name} ({project.token_symbol})")
        lines.append(f"📊 Статус: {project.get_status_emoji()} {project.get_status_text()}")
        
        if project.total_pool_usd > 0:
            lines.append(f"💰 Общий пул наград: ${project.total_pool_usd:,.2f}")
        elif project.total_pool_tokens > 0:
            lines.append(f"💰 Общий пул наград: {project.total_pool_tokens:,.0f} {project.token_symbol}")
        
        lines.append(f"⏰ Осталось: {project.time_remaining_str}")
        
        # Пулы для стейкинга
        for i, pool in enumerate(project.pools, 1):
            lines.append("")
            lines.append("━" * 34)
            
            # Название пула
            pool_name = f"📦 ПУЛ #{i}: {pool.stake_coin}"
            if pool.labels:
                pool_name += " " + " ".join(pool.labels)
            # Добавляем 🔥 если это лучший APR и ещё нет такого лейбла
            if i == 1 and pool.apr == project.max_apr and pool.apr > 100 and "🔥" not in pool.labels:
                pool_name += " 🔥"
            lines.append(pool_name)
            lines.append("━" * 34)
            
            # APR
            lines.append(f"   📈 APR: {pool.apr:.2f}%")
            
            # Лимиты
            if pool.max_stake > 0:
                lines.append(f"   🔒 Макс. депозит: {pool.max_stake:,.0f} {pool.stake_coin}")
            else:
                lines.append(f"   🔒 Макс. депозит: Без лимита")
            
            # Расчёт заработка
            days_left = project.days_left
            if days_left > 0 and pool.apr > 0:
                lines.append("")
                lines.append(f"   💰 ЗАРАБОТОК ЗА {days_left}д:")
                lines.append(f"      Депозит        │ Заработок")
                lines.append(f"      ───────────────┼───────────")
                
                # Определяем суммы для расчёта
                if pool.max_stake > 0:
                    # Есть лимит - показываем 25%, 50%, 100%
                    amounts = [
                        pool.max_stake * 0.25,
                        pool.max_stake * 0.5,
                        pool.max_stake
                    ]
                    for amt in amounts:
                        earnings = pool.calculate_earnings(amt, days_left)
                        star = " ⭐" if amt == pool.max_stake else ""
                        lines.append(f"      {amt:,.0f} {pool.stake_coin[:4]:4} │ ~{earnings:,.2f} {pool.stake_coin[:4]}{star}")
                else:
                    # Нет лимита - показываем $1000, $2500, $5000
                    for usd in [1000, 2500, 5000]:
                        earnings_pct = (pool.apr / 100) * (days_left / 365) * 100
                        earnings_usd = usd * (pool.apr / 100) * (days_left / 365)
                        star = " ⭐" if usd == 5000 else ""
                        lines.append(f"      ${usd:,}         │ ~${earnings_usd:,.2f}{star}")
        
        # Период
        lines.append("")
        lines.append("⏰ ПЕРИОД:")
        if project.start_time:
            lines.append(f"   • Старт: {project.start_time.strftime('%d.%m.%Y %H:%M')} UTC")
        if project.end_time:
            lines.append(f"   • Конец: {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC")
        
        # Ссылки
        if project.project_url or project.website:
            lines.append("")
            if project.project_url:
                lines.append(f"🔗 Страница: {project.project_url}")
            if project.website:
                lines.append(f"🌐 Сайт: {project.website}")
        
        lines.append("━" * 34)
        
        return "\n".join(lines)
    
    def format_all_projects(self, projects: List[LaunchpoolProject]) -> str:
        """Форматирование всех проектов"""
        if not projects:
            return f"❌ {self.EXCHANGE_NAME}: Нет активных {self.EXCHANGE_TYPE} проектов"
        
        formatted = []
        for project in projects:
            formatted.append(self.format_project(project))
        
        return "\n\n".join(formatted)
    
    def get_promotions(self) -> List[Dict[str, Any]]:
        """
        Метод-адаптер для совместимости с ParserService.
        Конвертирует LaunchpoolProject в формат промоакций.
        
        Returns:
            Список промоакций в формате, ожидаемом ParserService
        """
        try:
            # Получаем только активные проекты
            projects = self.get_projects(status_filter='active')
            
            promotions = []
            for project in projects:
                # Формируем уникальный promo_id
                promo_id = f"{self.EXCHANGE_NAME.lower()}_{self.EXCHANGE_TYPE}_{project.id}"
                
                # Форматируем описание
                formatted_text = self.format_project(project)
                
                # Получаем максимальный APR
                max_apr = project.max_apr
                
                # Формируем title
                title = f"🌊 {project.token_name} ({project.token_symbol}) - {project.get_status_text()}"
                
                promo = {
                    'promo_id': promo_id,
                    'title': title,
                    'description': formatted_text,
                    'link': project.project_url or self.BASE_URL,
                    'total_prize_pool': project.total_pool_usd if project.total_pool_usd > 0 else None,
                    'award_token': project.token_symbol,
                    'start_time': project.start_time,
                    'end_time': project.end_time,
                    'participants_count': project.total_participants,
                    
                    # Дополнительные поля для launchpool
                    'exchange': self.EXCHANGE_NAME,
                    'type': self.EXCHANGE_TYPE,
                    'max_apr': max_apr,
                    'pools_count': len(project.pools),
                    
                    # Флаг что это launchpool (для особой обработки)
                    'is_launchpool': True,
                    'formatted_message': formatted_text,  # Готовое сообщение для Telegram
                }
                
                promotions.append(promo)
                
            self.logger.info(f"✅ {self.EXCHANGE_NAME}: Преобразовано {len(promotions)} проектов в промоакции")
            return promotions
            
        except Exception as e:
            self.logger.error(f"❌ {self.EXCHANGE_NAME}: Ошибка get_promotions: {e}", exc_info=True)
            return []
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """Информация о стратегии парсинга (для совместимости с ParserService)"""
        return {
            'strategy_used': f'{self.EXCHANGE_NAME}_{self.EXCHANGE_TYPE}_api',
            'parser_type': 'launchpool',
            'exchange': self.EXCHANGE_NAME,
        }
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Статистика ошибок (для совместимости с ParserService)"""
        return {'total_errors': 0}
    
    # === Вспомогательные методы ===
    
    @staticmethod
    def parse_timestamp(ts: Any, is_milliseconds: bool = True) -> Optional[datetime]:
        """Парсинг timestamp в datetime"""
        if not ts:
            return None
        try:
            if isinstance(ts, str):
                # ISO format
                if 'T' in ts:
                    return datetime.fromisoformat(ts.replace('Z', '+00:00').replace('+00:00', ''))
                ts = int(ts)
            
            if is_milliseconds:
                ts = ts / 1000
            
            return datetime.fromtimestamp(ts)
        except Exception:
            return None
    
    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        """Безопасное преобразование в float"""
        if value is None:
            return default
        try:
            return float(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_int(value: Any, default: int = 0) -> int:
        """Безопасное преобразование в int"""
        if value is None:
            return default
        try:
            return int(float(str(value).replace(',', '')))
        except (ValueError, TypeError):
            return default
