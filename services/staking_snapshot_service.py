"""
services/staking_snapshot_service.py
Сервис для создания снимков стейкингов и расчета дельт изменений
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy import desc
from data.database import get_db_session
from data.models import StakingHistory, StakingSnapshot

logger = logging.getLogger(__name__)


class StakingSnapshotService:
    """Сервис для управления снимками стейкингов"""

    MIN_SNAPSHOT_INTERVAL = 3600  # 1 час в секундах

    def should_create_snapshot(self, staking_history_id: int) -> bool:
        """
        Проверяет, прошло ли >= 1 час с последнего снимка

        Args:
            staking_history_id: ID записи StakingHistory

        Returns:
            True если нужно создать снимок, False если еще рано
        """
        try:
            with get_db_session() as session:
                # Получаем последний снимок
                last_snapshot = session.query(StakingSnapshot).filter(
                    StakingSnapshot.staking_history_id == staking_history_id
                ).order_by(desc(StakingSnapshot.snapshot_time)).first()

                if not last_snapshot:
                    # Нет снимков - создаем первый
                    return True

                # Проверяем интервал
                time_since_last = (datetime.utcnow() - last_snapshot.snapshot_time).total_seconds()
                should_create = time_since_last >= self.MIN_SNAPSHOT_INTERVAL

                if should_create:
                    logger.debug(f"✅ Прошло {time_since_last:.0f}с с последнего снимка - создаем новый")
                else:
                    logger.debug(f"⏳ Прошло только {time_since_last:.0f}с - ждем {self.MIN_SNAPSHOT_INTERVAL - time_since_last:.0f}с")

                return should_create

        except Exception as e:
            logger.error(f"❌ Ошибка проверки интервала снимка: {e}")
            return False

    def create_snapshot(self, staking_history: StakingHistory) -> Optional[StakingSnapshot]:
        """
        Создает снимок если прошло >= 1 час с последнего

        Args:
            staking_history: Объект StakingHistory для создания снимка

        Returns:
            Созданный StakingSnapshot или None если снимок не создан
        """
        try:
            # Проверяем интервал
            if not self.should_create_snapshot(staking_history.id):
                return None

            # Создаем снимок
            with get_db_session() as session:
                snapshot = StakingSnapshot(
                    staking_history_id=staking_history.id,
                    exchange=staking_history.exchange,
                    product_id=staking_history.product_id,
                    coin=staking_history.coin,
                    apr=staking_history.apr,
                    fill_percentage=staking_history.fill_percentage,
                    token_price_usd=staking_history.token_price_usd,
                    status=staking_history.status,
                    snapshot_time=datetime.utcnow()
                )

                session.add(snapshot)
                session.commit()

                logger.info(
                    f"📸 Создан снимок: {staking_history.exchange} {staking_history.coin} "
                    f"APR={staking_history.apr}% Fill={staking_history.fill_percentage}%"
                )

                return snapshot

        except Exception as e:
            logger.error(f"❌ Ошибка создания снимка: {e}")
            return None

    def get_last_snapshot(self, staking_history_id: int) -> Optional[StakingSnapshot]:
        """
        Получает последний снимок для расчета дельт

        Args:
            staking_history_id: ID записи StakingHistory

        Returns:
            Последний StakingSnapshot или None
        """
        try:
            with get_db_session() as session:
                snapshot = session.query(StakingSnapshot).filter(
                    StakingSnapshot.staking_history_id == staking_history_id
                ).order_by(desc(StakingSnapshot.snapshot_time)).first()

                return snapshot

        except Exception as e:
            logger.error(f"❌ Ошибка получения последнего снимка: {e}")
            return None

    def calculate_deltas(self, current: StakingHistory, previous: Optional[StakingSnapshot]) -> Dict:
        """
        Рассчитывает дельты между текущим значением и предыдущим снимком

        Args:
            current: Текущая запись StakingHistory
            previous: Предыдущий снимок StakingSnapshot

        Returns:
            Словарь с дельтами: {
                'apr_delta': float,
                'fill_delta': float or None,
                'price_delta_pct': float or None,
                'has_previous': bool
            }
        """
        if not previous:
            return {
                'apr_delta': 0.0,
                'fill_delta': None,
                'price_delta_pct': None,
                'has_previous': False
            }

        # Дельта APR
        apr_delta = current.apr - previous.apr

        # Дельта заполненности
        fill_delta = None
        if current.fill_percentage is not None and previous.fill_percentage is not None:
            fill_delta = current.fill_percentage - previous.fill_percentage

        # Дельта цены (в процентах)
        price_delta_pct = None
        if current.token_price_usd is not None and previous.token_price_usd is not None and previous.token_price_usd > 0:
            price_delta_pct = ((current.token_price_usd - previous.token_price_usd) / previous.token_price_usd) * 100

        return {
            'apr_delta': apr_delta,
            'fill_delta': fill_delta,
            'price_delta_pct': price_delta_pct,
            'has_previous': True
        }

    def get_stakings_with_deltas(self, exchange: str, min_apr: float = None) -> List[Dict]:
        """
        Получает активные стейкинги с дельтами для UI

        Args:
            exchange: Название биржи (регистронезависимо)
            min_apr: Минимальный APR для фильтрации (опционально)

        Returns:
            Список словарей с данными стейкинга, дельтами и алертами
        """
        try:
            with get_db_session() as session:
                # Базовый запрос
                query = session.query(StakingHistory).filter(
                    StakingHistory.exchange.ilike(f"%{exchange}%"),
                    StakingHistory.status != 'Sold Out'  # Исключаем распроданные
                )

                # Фильтр по APR
                if min_apr is not None:
                    query = query.filter(StakingHistory.apr >= min_apr)

                # Сортировка по APR (сначала самые высокие)
                stakings = query.order_by(desc(StakingHistory.apr)).all()

                logger.info(f"📊 Найдено {len(stakings)} стейкингов для {exchange} (min_apr={min_apr})")

                result = []
                for staking in stakings:
                    # Получаем последний снимок В ТОЙ ЖЕ СЕССИИ
                    previous_snapshot = session.query(StakingSnapshot).filter(
                        StakingSnapshot.staking_history_id == staking.id
                    ).order_by(desc(StakingSnapshot.snapshot_time)).first()

                    # Рассчитываем дельты
                    deltas = self.calculate_deltas(staking, previous_snapshot)

                    # Проверяем алерты
                    alerts = self.check_alerts(staking, deltas)

                    # ВАЖНО: Сериализуем данные стейкинга внутри сессии
                    staking_dict = {
                        'id': staking.id,
                        'exchange': staking.exchange,
                        'product_id': staking.product_id,
                        'coin': staking.coin,
                        'reward_coin': staking.reward_coin,
                        'apr': staking.apr,
                        'type': staking.type,
                        'status': staking.status,
                        'category': staking.category,
                        'term_days': staking.term_days,
                        'user_limit_tokens': staking.user_limit_tokens,
                        'user_limit_usd': staking.user_limit_usd,
                        'total_places': staking.total_places,
                        'max_capacity': staking.max_capacity,
                        'current_deposit': staking.current_deposit,
                        'fill_percentage': staking.fill_percentage,
                        'token_price_usd': staking.token_price_usd,
                        'reward_token_price_usd': staking.reward_token_price_usd,
                        'start_time': staking.start_time,
                        'end_time': staking.end_time,
                        'first_seen': staking.first_seen,
                        'last_updated': staking.last_updated
                    }

                    result.append({
                        'staking': staking_dict,
                        'deltas': deltas,
                        'alerts': alerts
                    })

                return result

        except Exception as e:
            logger.error(f"❌ Ошибка получения стейкингов с дельтами: {e}", exc_info=True)
            return []

    def check_alerts(self, staking: StakingHistory, deltas: Dict) -> List[str]:
        """
        Проверяет условия алертов

        Args:
            staking: Запись StakingHistory
            deltas: Словарь с дельтами

        Returns:
            Список строк с алертами
        """
        alerts = []

        # Алерт: Пул почти заполнен (>90%)
        if staking.fill_percentage is not None and staking.fill_percentage > 90:
            alerts.append("⚠️ Пул почти заполнен!")

        # Алерт: APR резко вырос (>50%)
        if deltas.get('apr_delta', 0) > 50:
            alerts.append(f"🔥 APR резко вырос (+{deltas['apr_delta']:.1f}%)!")

        # Алерт: Новый стейкинг (нет предыдущего снимка)
        if not deltas.get('has_previous', False):
            alerts.append("🆕 Новый стейкинг!")

        return alerts

    def get_snapshot_count(self, staking_history_id: int) -> int:
        """
        Получает количество снимков для стейкинга

        Args:
            staking_history_id: ID записи StakingHistory

        Returns:
            Количество снимков
        """
        try:
            with get_db_session() as session:
                count = session.query(StakingSnapshot).filter(
                    StakingSnapshot.staking_history_id == staking_history_id
                ).count()

                return count

        except Exception as e:
            logger.error(f"❌ Ошибка подсчета снимков: {e}")
            return 0

    def get_snapshot_history(self, staking_history_id: int, limit: int = 24) -> List[StakingSnapshot]:
        """
        Получает последние N снимков для построения графиков/трендов

        Args:
            staking_history_id: ID записи StakingHistory
            limit: Количество последних снимков

        Returns:
            Список снимков, отсортированных по времени (новые первыми)
        """
        try:
            with get_db_session() as session:
                snapshots = session.query(StakingSnapshot).filter(
                    StakingSnapshot.staking_history_id == staking_history_id
                ).order_by(desc(StakingSnapshot.snapshot_time)).limit(limit).all()

                return snapshots

        except Exception as e:
            logger.error(f"❌ Ошибка получения истории снимков: {e}")
            return []
