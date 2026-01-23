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
        promo_type = promo.get('promo_type', '').lower()
        
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
        token_price_usd = None  # Инициализируем здесь
        
        # ОПТИМИЗАЦИЯ: Сначала проверяем есть ли reward_per_winner_usd в БД
        # Если есть - не нужно запрашивать price_fetcher!
        # Проверяем ВСЕ случаи где USD уже известен
        use_cached_usd = reward_usd > 0 or total_pool_usd > 0
        
        if not use_cached_usd:
            # Нет USD в БД - получаем цену токена через price fetcher
            if reward_token_symbol and reward_token_symbol not in ('USDT', 'USDC', 'USD'):
                try:
                    price_fetcher = get_price_fetcher()
                    token_price_usd = price_fetcher.get_token_price(reward_token_symbol, exchange)
                    if token_price_usd:
                        logger.debug(f"💰 Price fetcher: {reward_token_symbol} = ${token_price_usd:.6f}")
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка получения цены {reward_token_symbol}: {e}")
        
        # Приоритет 1: есть reward_per_winner И reward_per_winner_usd - используем кэш
        if promo.get('reward_per_winner') and reward_usd > 0:
            reward_per_user_display = promo.get('reward_per_winner')
            reward_per_user = reward_per_winner_tokens or reward_usd
            reward_usd_display = f"~${reward_usd:,.2f}"
            logger.debug(f"💾 Кэш: {reward_per_user_display} ({reward_usd_display})")
        
        # Приоритет 2: есть reward_per_winner но нет USD - рассчитываем через price_fetcher
        elif promo.get('reward_per_winner'):
            reward_per_user_display = promo.get('reward_per_winner')
            reward_per_user = reward_per_winner_tokens or reward_usd
            
            if token_price_usd and reward_per_winner_tokens:
                usd_value = reward_per_winner_tokens * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value
            elif reward_usd:
                reward_usd_display = f"~${reward_usd:,.2f}"
                
        # Приоритет 3: только reward_per_winner_usd без строки
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
                
        # Приоритет 4: Bybit Token Splash - оценка если нет winners_count
        # Для Bybit если есть пул но нет winners - используем оценку 1000 мест
        elif total_pool_tokens and 'bybit' in exchange.lower() and not winners:
            # Для Bybit Token Splash типичное кол-во мест = 1000-5000
            # Используем консервативную оценку 1000
            estimated_winners = 1000
            reward_per_user = total_pool_tokens / estimated_winners
            if award_token:
                reward_per_user_display = f"≈{reward_per_user:,.0f} {award_token}"
            else:
                reward_per_user_display = f"≈{reward_per_user:,.0f}"
            
            # Рассчитываем USD эквивалент через price fetcher
            if token_price_usd:
                usd_value = reward_per_user * token_price_usd
                reward_usd_display = f"~${usd_value:,.2f}"
                reward_usd = usd_value
            elif total_pool_usd:
                reward_usd_display = f"~${total_pool_usd / estimated_winners:,.2f}"
        
        # Приоритет 4.5: OKX Boost (X-Launch) - ВСЕ участники получают награду пропорционально
        # В OKX X-Launch пул делится между всеми участниками (нет понятия "победителей")
        elif (promo_type == 'okx_boost' or 'okx' in exchange) and participants and (total_pool_usd or total_pool_tokens):
            # Делим пул на всех участников
            if total_pool_usd and participants:
                reward_per_user_usd = total_pool_usd / participants
                reward_usd = reward_per_user_usd
                reward_usd_display = f"~${reward_per_user_usd:,.2f}"
            
            if total_pool_tokens and participants:
                reward_per_user = total_pool_tokens / participants
                if award_token:
                    reward_per_user_display = f"~{reward_per_user:,.0f} {award_token}"
                else:
                    reward_per_user_display = f"~{reward_per_user:,.0f}"
            elif reward_usd:
                reward_per_user = reward_usd
                reward_per_user_display = reward_usd_display
                
        # Приоритет 5: если есть пул, победители и участники - считаем награду на победителя
        # НЕ делим на participants - это даёт нереалистичные значения!
        elif total_pool_tokens and winners and participants:
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
        
        # Приоритет 6: Fallback - пул есть, но нет данных о победителях
        # НЕ используем total_pool для сортировки - это вводит в заблуждение
        elif total_pool_tokens:
            # Не рассчитываем reward_per_user - нет данных для корректного расчёта
            reward_per_user = 0
            reward_per_user_display = None  # Не показываем некорректную награду
        
        # Рассчитываем шанс выигрыша
        win_chance = 0
        if winners and participants:
            win_chance = min((winners / participants) * 100, 100)
        
        # OKX Boost: все участники - победители (100% шанс)
        if promo_type == 'okx_boost' or ('okx' in exchange and participants and not winners):
            win_chance = 100.0
        
        return {
            'expected_reward': reward_usd or reward_per_user or 0,  # Для сортировки (НЕ используем total_pool!)
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
    
    # =========================================================================
    # МЕТОДИ ДЛЯ КАТЕГОРІЙ ПРОМОАКЦІЙ
    # =========================================================================
    
    # Маппінг категорій
    PROMO_CATEGORIES = {
        'airdrop': {
            'name': 'Аірдропи',
            'icon': '🪂',
            'promo_types': ['airdrop', 'okx_boost'],  # okx_boost теж аірдроп
        },
        'candybomb': {
            'name': 'Кендибомби',
            'icon': '🍬',
            'promo_types': ['candybomb', 'candy', 'candydrop'],
        },
        'launchpad': {
            'name': 'Лаунчпади',
            'icon': '🚀',
            'promo_types': ['launchpad'],
        },
        'launchpool': {
            'name': 'Лаунчпули',
            'icon': '🌊',
            'promo_types': ['launchpool'],
        },
        'other': {
            'name': 'Інші',
            'icon': '🗂️',
            'promo_types': ['other', 'rewards', 'flash_earn', 'boost'],
        },
    }
    
    # Категорії, що виключаються з ТОП
    EXCLUDED_PROMO_TYPES = ['announcement', 'staking']
    
    def get_promo_counts_by_category(self) -> Dict[str, int]:
        """
        Отримує кількість активних промо в кожній категорії.
        
        Returns:
            Словник {category: count}
        """
        try:
            now = datetime.utcnow()
            
            with get_db_session() as session:
                # Отримуємо всі активні промо
                active_promos = session.query(PromoHistory.promo_type).filter(
                    or_(
                        PromoHistory.end_time == None,
                        PromoHistory.end_time > now
                    ),
                    ~PromoHistory.promo_type.in_(self.EXCLUDED_PROMO_TYPES)
                ).all()
                
                # Рахуємо по категоріях
                counts = {cat: 0 for cat in self.PROMO_CATEGORIES.keys()}
                
                for (promo_type,) in active_promos:
                    category = self._get_category_for_promo_type(promo_type)
                    counts[category] = counts.get(category, 0) + 1
                
                return counts
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка подсчёта категорий: {e}")
            return {cat: 0 for cat in self.PROMO_CATEGORIES.keys()}
    
    def _get_category_for_promo_type(self, promo_type: str) -> str:
        """Визначає категорію для promo_type"""
        if not promo_type:
            return 'other'
        
        promo_type_lower = promo_type.lower()
        
        for category, config in self.PROMO_CATEGORIES.items():
            if promo_type_lower in config['promo_types']:
                return category
        
        # Fallback - шукаємо за частковим збігом
        for category, config in self.PROMO_CATEGORIES.items():
            for pt in config['promo_types']:
                if pt in promo_type_lower or promo_type_lower in pt:
                    return category
        
        return 'other'
    
    def get_top_promos_by_category(
        self,
        category: str,
        limit: int = 50,
        min_apr: float = 0
    ) -> List[Dict]:
        """
        Отримує ТОП промоакцій конкретної категорії.
        
        Args:
            category: Категорія (airdrop, candybomb, launchpad, launchpool, other)
            limit: Максимальна кількість
            min_apr: Мінімальний APR для фільтрації (для launchpool)
            
        Returns:
            Список промоакцій з розрахунками
        """
        try:
            now = datetime.utcnow()
            
            # Отримуємо promo_types для категорії
            config = self.PROMO_CATEGORIES.get(category)
            if not config:
                self.logger.warning(f"⚠️ Невідома категорія: {category}")
                return []
            
            promo_types = config['promo_types']
            
            with get_db_session() as session:
                # Базовий запит - активні промо потрібної категорії
                if category == 'other':
                    # Для "Інші" беремо все що не входить в основні категорії
                    main_types = []
                    for cat, cfg in self.PROMO_CATEGORIES.items():
                        if cat != 'other':
                            main_types.extend(cfg['promo_types'])
                    
                    query = session.query(PromoHistory).filter(
                        or_(
                            PromoHistory.end_time == None,
                            PromoHistory.end_time > now
                        ),
                        ~PromoHistory.promo_type.in_(main_types + self.EXCLUDED_PROMO_TYPES)
                    )
                else:
                    query = session.query(PromoHistory).filter(
                        or_(
                            PromoHistory.end_time == None,
                            PromoHistory.end_time > now
                        ),
                        PromoHistory.promo_type.in_(promo_types)
                    )
                
                promos = query.all()
                
                # Конвертуємо в словники і розраховуємо
                result = []
                for promo in promos:
                    promo_dict = self._promo_to_dict(promo)
                    
                    # Розраховуємо нагороду в залежності від категорії
                    if category == 'launchpad':
                        reward_data = self._calculate_launchpad_profit(promo_dict)
                    elif category == 'launchpool':
                        reward_data = self._calculate_launchpool_earnings(promo_dict)
                    else:
                        reward_data = self.calculate_promo_reward(promo_dict)
                    
                    promo_dict.update(reward_data)
                    promo_dict['category'] = category
                    promo_dict['category_icon'] = config['icon']
                    promo_dict['category_name'] = config['name']
                    
                    # Час до закінчення
                    promo_dict['time_remaining'] = self._calculate_promo_time_remaining(
                        promo.start_time, promo.end_time
                    )
                    
                    result.append(promo_dict)
                
                # Фільтрація по мінімальному APR для launchpool
                if category == 'launchpool' and min_apr > 0:
                    result = [p for p in result if p.get('max_apr', 0) >= min_apr]
                
                # Сортування по нагороді на переможця
                result = self._sort_promos_by_reward_per_winner(result)
                
                return result[:limit]
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения ТОП {category}: {e}", exc_info=True)
            return []
    
    def _promo_to_dict(self, promo: PromoHistory) -> Dict:
        """Конвертує PromoHistory в словник"""
        import json
        
        raw_data = None
        if promo.raw_data:
            try:
                raw_data = json.loads(promo.raw_data)
            except:
                pass
        
        return {
            'id': promo.id,
            'promo_id': promo.promo_id,
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
            'promo_type': promo.promo_type,
            'start_time': promo.start_time,
            'end_time': promo.end_time,
            'link': promo.link,
            'created_at': promo.created_at,
            'last_updated': promo.last_updated,
            'raw_data': raw_data,
        }
    
    def _calculate_launchpad_profit(self, promo: Dict) -> Dict:
        """
        Розраховує потенційний профіт для лаунчпаду.
        
        Формула: profit = (takingMax / takingPrice) * (marketPrice - takingPrice)
        """
        result = {
            'expected_reward': 0,
            'profit_display': None,
            'taking_price': None,
            'market_price': None,
            'max_allocation': None,
            'has_user_reward': False,
        }
        
        try:
            raw_data = promo.get('raw_data', {})
            if not raw_data:
                return result
            
            # Шукаємо дані в launchpadTakingCoins (MEXC формат)
            taking_coins = raw_data.get('launchpadTakingCoins', [])
            if not taking_coins:
                # Можливо дані безпосередньо в raw_data
                taking_coins = [raw_data]
            
            best_profit = 0
            for coin in taking_coins:
                taking_price = self._safe_float(coin.get('takingPrice') or coin.get('price'))
                market_price = self._safe_float(coin.get('marketPrice'))
                max_allocation = self._safe_float(coin.get('takingMax') or coin.get('personTakingLimit'))
                
                if taking_price and market_price and max_allocation and taking_price > 0:
                    tokens = max_allocation / taking_price
                    profit = tokens * (market_price - taking_price)
                    
                    if profit > best_profit:
                        best_profit = profit
                        result['taking_price'] = taking_price
                        result['market_price'] = market_price
                        result['max_allocation'] = max_allocation
                        result['expected_reward'] = profit
                        result['profit_display'] = f"~${profit:,.2f}"
                        result['has_user_reward'] = True
            
        except Exception as e:
            self.logger.debug(f"⚠️ Помилка розрахунку launchpad profit: {e}")
        
        return result
    
    def _calculate_launchpool_earnings(self, promo: Dict) -> Dict:
        """
        Розраховує заробіток з лаунчпулу для ВСІХ пулів.
        
        Формула: earnings = max_stake * (apr / 100) * (time_fraction) * token_price
        де time_fraction = days_left / 365 або hours_left / 8760 якщо days_left = 0
        """
        result = {
            'expected_reward': 0,
            'earnings_display': None,
            'max_apr': 0,
            'best_pool': None,
            'days_left': 0,
            'hours_left': 0,
            'has_user_reward': False,
            'pool_earnings': [],  # Заробіток по кожному пулу
        }
        
        try:
            raw_data = promo.get('raw_data', {})
            if not raw_data:
                return result
            
            pools = raw_data.get('pools', [])
            days_left = raw_data.get('days_left', 0)
            hours_left = raw_data.get('hours_left', 0)
            token_symbol = raw_data.get('token_symbol', promo.get('award_token', ''))
            
            # Розраховуємо time_fraction - частку року для розрахунку APR
            # Якщо є дні - використовуємо дні, якщо тільки години - використовуємо години
            if days_left > 0:
                time_fraction = days_left / 365
            elif hours_left > 0:
                time_fraction = hours_left / 8760  # 8760 = 365 * 24 годин на рік
            else:
                time_fraction = 0
            
            if not pools or time_fraction <= 0:
                return result
            
            # Отримуємо ціну токена
            token_price = None
            exchange = promo.get('exchange', '').lower()
            if token_symbol:
                try:
                    price_fetcher = get_price_fetcher()
                    token_price = price_fetcher.get_token_price(token_symbol, exchange)
                except:
                    pass
            
            # Розраховуємо заробіток для ВСІХ пулів
            best_earnings = 0
            pool_earnings_list = []
            
            for pool in pools:
                apr = pool.get('apr', 0) or 0
                max_stake = pool.get('max_stake', 0) or 0
                stake_coin = pool.get('stake_coin', '')
                
                if apr > 0 and time_fraction > 0:
                    # Розрахунок заробітку в токенах з використанням time_fraction
                    if max_stake > 0:
                        earnings_tokens = max_stake * (apr / 100) * time_fraction
                    else:
                        earnings_tokens = 0
                    
                    # Конвертуємо в USD якщо є ціна
                    earnings_usd = earnings_tokens * token_price if token_price and earnings_tokens > 0 else 0
                    
                    # Формуємо дисплей заробітку
                    if earnings_usd > 0:
                        earnings_str = f"~${earnings_usd:,.2f}"
                    elif earnings_tokens > 0:
                        earnings_str = f"~{earnings_tokens:,.2f} {token_symbol}"
                    else:
                        earnings_str = None
                    
                    pool_earnings_list.append({
                        'stake_coin': stake_coin,
                        'apr': apr,
                        'max_stake': max_stake,
                        'earnings_tokens': earnings_tokens,
                        'earnings_usd': earnings_usd,
                        'earnings_display': earnings_str,
                    })
                    
                    # Оновлюємо найкращий результат
                    if earnings_usd > best_earnings or (earnings_usd == 0 and apr > result['max_apr']):
                        best_earnings = earnings_usd
                        result['max_apr'] = apr
                        result['best_pool'] = stake_coin
                        result['expected_reward'] = earnings_usd
                        result['has_user_reward'] = earnings_usd > 0
                        
                        if earnings_usd > 0:
                            result['earnings_display'] = f"~${earnings_usd:,.2f}"
                        elif earnings_tokens > 0:
                            result['earnings_display'] = f"~{earnings_tokens:,.2f} {token_symbol}"
            
            result['days_left'] = days_left
            result['hours_left'] = hours_left
            result['pool_earnings'] = pool_earnings_list
            
        except Exception as e:
            self.logger.debug(f"⚠️ Помилка розрахунку launchpool earnings: {e}")
        
        return result
    
    def _sort_promos_by_reward_per_winner(self, promos: List[Dict]) -> List[Dict]:
        """
        Сортує промо по нагороді на переможця.
        Якщо raw_reward = 0, розраховуємо з пулу/кількості учасників.
        """
        def get_reward_per_winner(p):
            # Спочатку пробуємо raw_reward
            raw = p.get('raw_reward', 0) or 0
            if raw > 0:
                return raw
            
            # Якщо немає - розраховуємо з пулу / учасників (як у форматері)
            pool_usd = p.get('total_prize_pool_usd', 0) or 0
            participants = p.get('participants_count', 0) or p.get('participants', 0) or 0
            
            if pool_usd > 0 and participants > 0:
                return pool_usd / participants
            
            return 0
        
        with_reward = []
        without_reward = []
        
        for p in promos:
            reward = get_reward_per_winner(p)
            p['_sort_reward'] = reward  # Зберігаємо для сортування
            if reward > 0:
                with_reward.append(p)
            else:
                without_reward.append(p)
        
        # Сортуємо по нагороді на переможця
        with_reward.sort(key=lambda x: x.get('_sort_reward', 0), reverse=True)
        
        # Сортуємо без нагороди за датою закінчення
        def get_end_time_sort_key(p):
            end_time = p.get('end_time')
            if end_time is None:
                return datetime.max
            if isinstance(end_time, datetime):
                return end_time
            return datetime.max
        
        without_reward.sort(key=get_end_time_sort_key)
        
        return with_reward + without_reward
    
    def _sort_promos_by_pool_usd(self, promos: List[Dict]) -> List[Dict]:
        """
        Сортує промо по загальному пулу USD (total_prize_pool_usd).
        Для candybomb та інших категорій де важливий розмір пулу.
        """
        with_usd = []
        without_usd = []
        
        for p in promos:
            pool_usd = p.get('total_prize_pool_usd', 0) or 0
            if pool_usd > 0:
                with_usd.append(p)
            else:
                without_usd.append(p)
        
        # Сортуємо по загальному пулу USD
        with_usd.sort(key=lambda x: x.get('total_prize_pool_usd', 0) or 0, reverse=True)
        
        # Сортуємо без USD за датою закінчення
        def get_end_time_sort_key(p):
            end_time = p.get('end_time')
            if end_time is None:
                return datetime.max
            if isinstance(end_time, datetime):
                return end_time
            return datetime.max
        
        without_usd.sort(key=get_end_time_sort_key)
        
        return with_usd + without_usd
    
    def _sort_promos_by_reward_and_date(self, promos: List[Dict]) -> List[Dict]:
        """
        Сортує промо: спочатку з USD (за спаданням), потім без USD (за датою закінчення).
        Використовуємо raw_reward (тільки USD) для коректного порівняння.
        """
        with_usd = []
        without_usd = []
        
        for p in promos:
            # Використовуємо raw_reward (тільки USD) для сортування
            raw_usd = p.get('raw_reward', 0) or 0
            if raw_usd > 0:
                with_usd.append(p)
            else:
                without_usd.append(p)
        
        # Сортуємо з USD за нагородою (raw_reward = тільки USD)
        with_usd.sort(key=lambda x: x.get('raw_reward', 0) or 0, reverse=True)
        
        # Сортуємо без USD за датою закінчення
        def get_end_time_sort_key(p):
            end_time = p.get('end_time')
            if end_time is None:
                return datetime.max
            if isinstance(end_time, datetime):
                return end_time
            return datetime.max
        
        without_usd.sort(key=get_end_time_sort_key)
        
        return with_usd + without_usd
    
    def _safe_float(self, value) -> float:
        """Безпечне перетворення в float"""
        if value is None:
            return 0.0
        try:
            return float(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return 0.0
    
    def get_extended_statistics(self) -> Dict:
        """
        Отримує розширену статистику з розбивкою по категоріях.
        
        Returns:
            Словник зі статистикою включаючи категорії
        """
        stats = self.get_statistics()
        
        # Додаємо статистику по категоріях
        category_counts = self.get_promo_counts_by_category()
        stats['promo_categories'] = category_counts
        
        return stats


# Глобальный экземпляр сервиса
_top_activity_service = None


def get_top_activity_service() -> TopActivityService:
    """Получить глобальный экземпляр сервиса"""
    global _top_activity_service
    if _top_activity_service is None:
        _top_activity_service = TopActivityService()
    return _top_activity_service
