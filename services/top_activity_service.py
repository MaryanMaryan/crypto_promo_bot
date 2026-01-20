"""
Сервис агрегации ТОП активностей со всех бирж.
Собирает лучшие стейкинги и промоакции, сортирует по потенциальному заработку.
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, and_, func

from data.database import get_db_session
from data.models import StakingHistory, PromoHistory, ApiLink
from utils.price_fetcher import get_price_fetcher

logger = logging.getLogger(__name__)


class TopActivityService:
    """Сервис для получения ТОП активностей со всех бирж"""
    
    # Дефолтный срок для Flexible стейкинга (для расчёта дневного заработка)
    DEFAULT_FLEXIBLE_DAYS = 1
    
    # Максимальный % заполненности для показа
    MAX_FILL_PERCENTAGE = 95.0
    
    # Максимальный лимит депозита для показа в ТОП (реалистичные суммы)
    MAX_USER_LIMIT_USD = 50000.0
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def calculate_staking_profit(self, staking: Dict) -> Dict:
        """
        Рассчитывает потенциальный заработок со стейкинга.
        
        Args:
            staking: Словарь с данными стейкинга
            
        Returns:
            Словарь с profit, period, profit_display
        """
        apr = staking.get('apr', 0) or 0
        user_limit_usd = staking.get('user_limit_usd', 0) or 0
        term_days = staking.get('term_days') or self.DEFAULT_FLEXIBLE_DAYS
        staking_type = staking.get('type', '') or ''
        
        # Определяем тип стейкинга
        is_flexible = 'flex' in staking_type.lower() if staking_type else False
        
        # Если нет лимита в USD, пробуем рассчитать через токены
        if not user_limit_usd and staking.get('user_limit_tokens') and staking.get('token_price_usd'):
            user_limit_usd = staking['user_limit_tokens'] * staking['token_price_usd']
        
        # Если всё ещё нет - используем дефолт
        if not user_limit_usd:
            user_limit_usd = 100  # Дефолтный депозит для расчёта
        
        # Расчёт заработка
        # annual_profit = deposit * APR%
        # actual_profit = annual_profit * (days / 365)
        annual_profit = user_limit_usd * (apr / 100)
        actual_profit = annual_profit * (term_days / 365)
        
        # Формируем период
        if is_flexible:
            period = "день"
            profit_display = f"${actual_profit:.2f}/день"
        else:
            if term_days < 30:
                period = f"{term_days}д"
            else:
                period = f"{term_days}д"
            profit_display = f"${actual_profit:.2f}"
        
        return {
            'profit': actual_profit,
            'period': period,
            'profit_display': profit_display,
            'is_flexible': is_flexible,
            'term_days': term_days
        }
    
    def calculate_promo_reward(self, promo: Dict) -> Dict:
        """
        Рассчитывает ожидаемую награду с промоакции.
        
        Args:
            promo: Словарь с данными промоакции
            
        Returns:
            Словарь с expected_reward, win_chance, raw_reward
        """
        reward_usd = promo.get('reward_per_winner_usd', 0) or 0
        participants = promo.get('participants_count', 0) or 0
        winners = promo.get('winners_count', 0) or 0
        total_pool_usd = promo.get('total_prize_pool_usd', 0) or 0
        exchange = promo.get('exchange', '').lower()
        
        # Пытаемся получить total_prize_pool как число (может быть не в USD)
        total_pool_raw = promo.get('total_prize_pool')
        total_pool_tokens = 0
        if total_pool_raw:
            try:
                total_pool_tokens = float(total_pool_raw)
            except (ValueError, TypeError):
                pass
        
        # Токен награды
        award_token = promo.get('award_token', '')
        
        # Пытаемся извлечь числовое значение и токен из reward_per_winner (например "2,000 SCOR" -> 2000, SCOR)
        reward_per_winner_raw = promo.get('reward_per_winner', '')
        reward_per_winner_tokens = 0
        reward_token_symbol = award_token  # Используем award_token как дефолт
        
        if reward_per_winner_raw:
            try:
                # Извлекаем число и токен из строки типа "2,000 SCOR" или "100 USDT"
                parts = str(reward_per_winner_raw).replace(',', '').split()
                if len(parts) >= 1:
                    reward_per_winner_tokens = float(parts[0])
                if len(parts) >= 2:
                    reward_token_symbol = parts[1].upper()
            except (ValueError, TypeError, IndexError):
                pass
        
        # Если нет токена в reward_per_winner, используем award_token
        if not reward_token_symbol:
            reward_token_symbol = award_token
        
        # Рассчитываем reward_per_user если есть данные
        reward_per_user = 0
        reward_per_user_display = None
        reward_usd_display = None  # Для показа USD эквивалента
        
        # Получаем цену токена через price fetcher
        token_price_usd = None
        if reward_token_symbol and reward_token_symbol not in ('USDT', 'USDC', 'USD'):
            try:
                price_fetcher = get_price_fetcher()
                token_price_usd = price_fetcher.get_token_price(reward_token_symbol, exchange)
                if token_price_usd:
                    logger.debug(f"💰 Price fetcher: {reward_token_symbol} = ${token_price_usd:.6f}")
            except Exception as e:
                logger.debug(f"⚠️ Ошибка получения цены {reward_token_symbol}: {e}")
        
        # Приоритет 1: если есть reward_per_winner (строка типа "2,000 SCOR") - используем напрямую
        if promo.get('reward_per_winner'):
            reward_per_user_display = promo.get('reward_per_winner')
            reward_per_user = reward_per_winner_tokens or reward_usd
            
            # Рассчитываем USD эквивалент через price fetcher
            if token_price_usd and reward_per_winner_tokens:
                usd_value = reward_per_winner_tokens * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value  # Обновляем для сортировки
            elif reward_usd:
                reward_usd_display = f"~${reward_usd:,.2f}"
                
        # Приоритет 2: если есть reward_per_winner_usd но нет reward_per_winner
        elif reward_usd:
            reward_per_user = reward_usd
            reward_per_user_display = f"${reward_usd:,.2f}"
            
        # Приоритет 3: если есть пул и кол-во победителей - считаем награду на победителя
        elif total_pool_tokens and winners:
            reward_per_user = total_pool_tokens / winners
            if award_token:
                reward_per_user_display = f"{reward_per_user:,.0f} {award_token}"
            else:
                reward_per_user_display = f"{reward_per_user:,.0f}"
            
            # Рассчитываем USD эквивалент через price fetcher
            if token_price_usd:
                usd_value = reward_per_user * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value
            elif total_pool_usd and winners:
                reward_usd_display = f"~${total_pool_usd / winners:,.2f}"
                
        # Приоритет 4: Bybit Token Splash - стандартно 1000 мест если нет данных
        elif total_pool_tokens and 'bybit' in exchange and not winners and not participants:
            # Для Bybit Token Splash типичное кол-во мест = 1000
            estimated_winners = 1000
            reward_per_user = total_pool_tokens / estimated_winners
            if award_token:
                reward_per_user_display = f"~{reward_per_user:,.0f} {award_token}"
            else:
                reward_per_user_display = f"~{reward_per_user:,.0f}"
            winners = estimated_winners  # Для шанса выигрыша
            
            # Рассчитываем USD эквивалент через price fetcher
            if token_price_usd:
                usd_value = reward_per_user * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value
                
        # Приоритет 5: если есть пул и участники - считаем среднюю награду (менее точно)
        elif total_pool_tokens and participants:
            reward_per_user = total_pool_tokens / participants
            if award_token:
                reward_per_user_display = f"≈{reward_per_user:,.0f} {award_token}"
            else:
                reward_per_user_display = f"≈{reward_per_user:,.0f}"
            
            # Рассчитываем USD эквивалент через price fetcher
            if token_price_usd:
                usd_value = reward_per_user * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value
            elif total_pool_usd and participants:
                reward_usd_display = f"~${total_pool_usd / participants:,.2f}"
        
        # Рассчитываем шанс выигрыша
        win_chance = 0
        if winners and participants:
            win_chance = min((winners / participants) * 100, 100)
        
        return {
            'expected_reward': reward_usd or reward_per_user or total_pool_tokens or 0,  # Для сортировки (в USD если есть)
            'reward_per_user': reward_per_user,
            'reward_per_user_display': reward_per_user_display,  # Главное поле для отображения
            'reward_usd_display': reward_usd_display,  # USD эквивалент награды
            'win_chance': win_chance,
            'raw_reward': reward_usd,
            'total_pool_usd': total_pool_usd,
            'total_pool_tokens': total_pool_tokens,
            'participants': participants,
            'winners': winners,
            'award_token': award_token,
            'token_price_usd': token_price_usd,  # Цена токена
            'reward_display': reward_per_user_display,  # Обратная совместимость
            'has_user_reward': reward_per_user_display is not None  # Флаг наличия награды
        }
    
    def get_top_stakings(
        self,
        limit: int = 10,
        min_apr: float = None,
        staking_type: str = None,  # 'fixed', 'flexible', None = all
        exclude_filled: bool = True
    ) -> List[Dict]:
        """
        Получает ТОП стейкингов со всех бирж, отсортированных по заработку.
        
        Args:
            limit: Количество записей
            min_apr: Минимальный APR для фильтрации
            staking_type: Тип стейкинга (fixed/flexible)
            exclude_filled: Исключать заполненные пулы
            
        Returns:
            Список стейкингов с расчётами заработка
        """
        try:
            import time
            current_timestamp_ms = int(time.time() * 1000)
            
            with get_db_session() as session:
                # Базовый запрос
                query = session.query(StakingHistory).filter(
                    StakingHistory.status != 'Sold Out'
                )
                
                # Фильтр по заполненности
                if exclude_filled:
                    query = query.filter(
                        or_(
                            StakingHistory.fill_percentage == None,
                            StakingHistory.fill_percentage < self.MAX_FILL_PERCENTAGE
                        )
                    )
                
                # Фильтр по времени окончания (исключаем истёкшие)
                query = query.filter(
                    or_(
                        StakingHistory.end_time == None,
                        StakingHistory.end_time == '',
                        StakingHistory.end_time > str(current_timestamp_ms)
                    )
                )
                
                # Фильтр по минимальному APR
                if min_apr is not None:
                    query = query.filter(StakingHistory.apr >= min_apr)
                
                # Фильтр по типу стейкинга
                if staking_type:
                    if staking_type.lower() == 'fixed':
                        query = query.filter(
                            ~StakingHistory.type.ilike('%flex%')
                        )
                    elif staking_type.lower() == 'flexible':
                        query = query.filter(
                            StakingHistory.type.ilike('%flex%')
                        )
                
                # Получаем все записи для сортировки по заработку
                stakings = query.all()
                
                # Конвертируем в словари и рассчитываем заработок
                result = []
                for staking in stakings:
                    # Рассчитываем user_limit_usd если нет
                    user_limit_usd = staking.user_limit_usd
                    if not user_limit_usd and staking.user_limit_tokens and staking.token_price_usd:
                        user_limit_usd = staking.user_limit_tokens * staking.token_price_usd
                    
                    # ФИЛЬТР: Пропускаем стейкинги с нереалистичными лимитами (> $50,000)
                    if user_limit_usd and user_limit_usd > self.MAX_USER_LIMIT_USD:
                        continue
                    
                    staking_dict = {
                        'id': staking.id,
                        'exchange': staking.exchange,
                        'product_id': staking.product_id,
                        'coin': staking.coin,
                        'reward_coin': staking.reward_coin,
                        'apr': staking.apr,
                        'type': staking.type,
                        'product_type': staking.product_type,
                        'status': staking.status,
                        'term_days': staking.term_days,
                        'user_limit_usd': user_limit_usd,  # Используем рассчитанное значение
                        'user_limit_tokens': staking.user_limit_tokens,
                        'token_price_usd': staking.token_price_usd,
                        'fill_percentage': staking.fill_percentage,
                        'max_capacity': staking.max_capacity,
                        'current_deposit': staking.current_deposit,
                        'start_time': staking.start_time,
                        'end_time': staking.end_time,
                        'first_seen': staking.first_seen,
                        'last_updated': staking.last_updated
                    }
                    
                    # Рассчитываем заработок
                    profit_data = self.calculate_staking_profit(staking_dict)
                    staking_dict.update(profit_data)
                    
                    # Рассчитываем оставшееся время
                    staking_dict['time_remaining'] = self._calculate_time_remaining(staking.end_time)
                    
                    result.append(staking_dict)
                
                # Сортируем по заработку (profit) по убыванию
                result.sort(key=lambda x: x.get('profit', 0), reverse=True)
                
                # Возвращаем топ N
                return result[:limit]
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения ТОП стейкингов: {e}", exc_info=True)
            return []
    
    def get_top_promos(
        self,
        limit: int = 10,
        min_reward: float = None,
        status_filter: str = None  # 'ongoing', 'upcoming', None = all active
    ) -> List[Dict]:
        """
        Получает ТОП промоакций со всех бирж, отсортированных по награде.
        
        Args:
            limit: Количество записей
            min_reward: Минимальная награда в USD
            status_filter: Фильтр по статусу
            
        Returns:
            Список промоакций с расчётами
        """
        try:
            now = datetime.utcnow()
            
            with get_db_session() as session:
                # Базовый запрос - только активные или предстоящие
                query = session.query(PromoHistory).filter(
                    or_(
                        PromoHistory.status.ilike('%ongoing%'),
                        PromoHistory.status.ilike('%active%'),
                        PromoHistory.status.ilike('%upcoming%'),
                        PromoHistory.status == None  # Если статус не указан
                    )
                )
                
                # Фильтр по времени окончания (не истёкшие)
                query = query.filter(
                    or_(
                        PromoHistory.end_time == None,
                        PromoHistory.end_time > now
                    )
                )
                
                # Фильтр по минимальной награде
                if min_reward is not None:
                    query = query.filter(
                        or_(
                            PromoHistory.reward_per_winner_usd >= min_reward,
                            PromoHistory.total_prize_pool_usd >= min_reward
                        )
                    )
                
                # Фильтр по статусу
                if status_filter:
                    query = query.filter(
                        PromoHistory.status.ilike(f'%{status_filter}%')
                    )
                
                promos = query.all()
                
                # Конвертируем в словари и рассчитываем награду
                result = []
                for promo in promos:
                    promo_dict = {
                        'id': promo.id,
                        'exchange': promo.exchange,
                        'title': promo.title,
                        'description': promo.description,
                        'award_token': promo.award_token,
                        'total_prize_pool': promo.total_prize_pool,
                        'total_prize_pool_usd': promo.total_prize_pool_usd,
                        'reward_per_winner': promo.reward_per_winner,
                        'reward_per_winner_usd': promo.reward_per_winner_usd,
                        'participants_count': promo.participants_count,
                        'winners_count': promo.winners_count,
                        'conditions': promo.conditions,
                        'status': promo.status,
                        'start_time': promo.start_time,
                        'end_time': promo.end_time,
                        'link': promo.link,
                        'created_at': promo.created_at,
                        'last_updated': promo.last_updated
                    }
                    
                    # Рассчитываем награду
                    reward_data = self.calculate_promo_reward(promo_dict)
                    promo_dict.update(reward_data)
                    
                    # ФИЛЬТР: Показываем только промо где есть понятная награда на пользователя
                    if not promo_dict.get('has_user_reward'):
                        continue
                    
                    # ФИЛЬТР: Пропускаем промо с нереалистично большой наградой (> $10,000)
                    expected_reward = promo_dict.get('expected_reward', 0)
                    if expected_reward and expected_reward > 10000:
                        continue
                    
                    # Рассчитываем оставшееся время
                    promo_dict['time_remaining'] = self._calculate_promo_time_remaining(promo.start_time, promo.end_time)
                    
                    result.append(promo_dict)
                
                # Сортируем: по награде в USD (expected_reward содержит USD если цена известна)
                result.sort(
                    key=lambda x: (
                        x.get('expected_reward', 0),    # Награда в USD (приоритет)
                        x.get('participants', 0) > 0    # Потом с участниками
                    ),
                    reverse=True
                )
                
                # Возвращаем топ N
                return result[:limit]
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения ТОП промоакций: {e}", exc_info=True)
            return []
    
    def get_combined_top(self, limit: int = 10) -> List[Dict]:
        """
        Получает комбинированный ТОП (стейкинги + промо) отсортированный по заработку.
        
        Args:
            limit: Количество записей
            
        Returns:
            Список всех активностей
        """
        try:
            # Получаем топ стейкингов и промо
            stakings = self.get_top_stakings(limit=limit)
            promos = self.get_top_promos(limit=limit)
            
            # Помечаем тип
            for s in stakings:
                s['activity_type'] = 'staking'
                s['sort_value'] = s.get('profit', 0)
            
            for p in promos:
                p['activity_type'] = 'promo'
                p['sort_value'] = p.get('expected_reward', 0)
            
            # Объединяем и сортируем
            combined = stakings + promos
            combined.sort(key=lambda x: x.get('sort_value', 0), reverse=True)
            
            return combined[:limit]
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения комбинированного ТОП: {e}", exc_info=True)
            return []
    
    def _calculate_time_remaining(self, end_time_str: str) -> str:
        """Рассчитывает оставшееся время для стейкинга"""
        if not end_time_str:
            return "нет данных"
        
        try:
            # end_time хранится как timestamp в миллисекундах (строка)
            end_timestamp = int(end_time_str) / 1000
            end_dt = datetime.fromtimestamp(end_timestamp)
            now = datetime.now()
            
            if end_dt <= now:
                return "завершён"
            
            delta = end_dt - now
            days = delta.days
            hours = delta.seconds // 3600
            
            if days > 0:
                return f"{days}д {hours}ч"
            elif hours > 0:
                return f"{hours}ч"
            else:
                minutes = (delta.seconds % 3600) // 60
                return f"{minutes}м"
                
        except (ValueError, TypeError, OSError):
            return "нет данных"
    
    def _calculate_promo_time_remaining(self, start_time, end_time) -> Dict:
        """Рассчитывает оставшееся время для промоакции"""
        result = {
            'start_str': 'нет данных',
            'end_str': 'нет данных',
            'remaining_str': 'нет данных',
            'remaining_days': None
        }
        
        try:
            now = datetime.utcnow()
            
            # Вспомогательная функция для парсинга даты
            def parse_datetime(dt_value):
                if dt_value is None:
                    return None
                if isinstance(dt_value, datetime):
                    return dt_value
                if isinstance(dt_value, str):
                    # Пробуем разные форматы
                    for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                        try:
                            return datetime.strptime(dt_value, fmt)
                        except ValueError:
                            continue
                return None
            
            # Парсим даты
            start_dt = parse_datetime(start_time)
            end_dt = parse_datetime(end_time)
            
            # Форматируем даты
            if start_dt:
                result['start_str'] = start_dt.strftime('%d.%m')
            elif start_time:
                result['start_str'] = str(start_time)[:10]
            
            if end_dt:
                result['end_str'] = end_dt.strftime('%d.%m.%Y')
                
                # Рассчитываем оставшееся время
                if end_dt > now:
                    delta = end_dt - now
                    result['remaining_days'] = delta.days
                    if delta.days > 0:
                        result['remaining_str'] = f"{delta.days}д до конца"
                    else:
                        hours = delta.seconds // 3600
                        result['remaining_str'] = f"{hours}ч до конца"
                else:
                    result['remaining_str'] = "завершена"
            elif end_time:
                result['end_str'] = str(end_time)[:10]
                    
        except Exception as e:
            self.logger.debug(f"Ошибка расчёта времени промо: {e}")
        
        return result
    
    def get_statistics(self) -> Dict:
        """
        Получает общую статистику по всем активностям.
        
        Returns:
            Словарь со статистикой
        """
        try:
            with get_db_session() as session:
                # Считаем стейкинги
                total_stakings = session.query(StakingHistory).count()
                active_stakings = session.query(StakingHistory).filter(
                    StakingHistory.status != 'Sold Out'
                ).count()
                
                # Считаем промоакции
                total_promos = session.query(PromoHistory).count()
                now = datetime.utcnow()
                active_promos = session.query(PromoHistory).filter(
                    or_(
                        PromoHistory.end_time == None,
                        PromoHistory.end_time > now
                    )
                ).count()
                
                # Уникальные биржи
                staking_exchanges = session.query(
                    func.count(func.distinct(StakingHistory.exchange))
                ).scalar() or 0
                
                promo_exchanges = session.query(
                    func.count(func.distinct(PromoHistory.exchange))
                ).scalar() or 0
                
                return {
                    'total_stakings': total_stakings,
                    'active_stakings': active_stakings,
                    'total_promos': total_promos,
                    'active_promos': active_promos,
                    'staking_exchanges': staking_exchanges,
                    'promo_exchanges': promo_exchanges
                }
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}


# Глобальный экземпляр сервиса
_top_activity_service = None


def get_top_activity_service() -> TopActivityService:
    """Получить глобальный экземпляр сервиса"""
    global _top_activity_service
    if _top_activity_service is None:
        _top_activity_service = TopActivityService()
    return _top_activity_service
