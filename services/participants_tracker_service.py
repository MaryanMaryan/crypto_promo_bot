"""
Сервис для отслеживания истории участников промоакций
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from data.database import get_db_session
from data.models import PromoParticipantsHistory

logger = logging.getLogger(__name__)


class ParticipantsTrackerService:
    """Сервис для отслеживания и анализа динамики участников промоакций"""
    
    # Интервалы для отчётов (в часах)
    TRACKING_INTERVALS = [6, 12, 24]
    
    @staticmethod
    def record_participants(exchange: str, promo_id: str, participants: int, title: str = None) -> bool:
        """
        Записать количество участников в историю
        
        Args:
            exchange: Название биржи (GateCandy, OKX и т.д.)
            promo_id: Уникальный ID промо
            participants: Количество участников
            title: Название промо (опционально)
            
        Returns:
            True если запись успешна
        """
        try:
            with get_db_session() as db:
                # Проверяем, есть ли недавняя запись (последние 5 минут) чтобы не дублировать
                five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
                recent = db.query(PromoParticipantsHistory).filter(
                    PromoParticipantsHistory.exchange == exchange,
                    PromoParticipantsHistory.promo_id == promo_id,
                    PromoParticipantsHistory.recorded_at >= five_minutes_ago
                ).first()
                
                if recent:
                    # Обновляем существующую запись если изменилось кол-во
                    if recent.participants_count != participants:
                        recent.participants_count = participants
                        recent.recorded_at = datetime.utcnow()
                        if title:
                            recent.promo_title = title
                        db.commit()
                        logger.debug(f"📊 Обновлена запись: {exchange}/{promo_id} = {participants}")
                    return True
                
                # Создаём новую запись
                record = PromoParticipantsHistory(
                    exchange=exchange,
                    promo_id=promo_id,
                    promo_title=title,
                    participants_count=participants,
                    recorded_at=datetime.utcnow()
                )
                db.add(record)
                db.commit()
                logger.debug(f"📊 Новая запись: {exchange}/{promo_id} = {participants}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Ошибка записи участников: {e}")
            return False
    
    @staticmethod
    def get_participants_stats(exchange: str, promo_id: str) -> Dict[str, any]:
        """
        Получить статистику участников за разные периоды
        
        Args:
            exchange: Название биржи
            promo_id: ID промо
            
        Returns:
            Словарь с данными:
            {
                'current': 8572,
                '6h': {'count': 4572, 'diff': 4000, 'percent': 87.5},
                '12h': {'count': 572, 'diff': 8000, 'percent': 1399.0},
                '24h': {'count': 500, 'diff': 8072, 'percent': 1614.4},
                'last_update': {'count': 8500, 'diff': 72, 'time_ago': '15 мин.'}
            }
        """
        try:
            with get_db_session() as db:
                now = datetime.utcnow()
                
                # Получаем последнюю (текущую) запись
                current_record = db.query(PromoParticipantsHistory).filter(
                    PromoParticipantsHistory.exchange == exchange,
                    PromoParticipantsHistory.promo_id == promo_id
                ).order_by(PromoParticipantsHistory.recorded_at.desc()).first()
                
                if not current_record:
                    return {}
                
                current_count = current_record.participants_count
                result = {'current': current_count}
                
                # Статистика за каждый интервал
                for hours in ParticipantsTrackerService.TRACKING_INTERVALS:
                    time_ago = now - timedelta(hours=hours)
                    
                    # Ищем ближайшую запись к этому времени
                    record = db.query(PromoParticipantsHistory).filter(
                        PromoParticipantsHistory.exchange == exchange,
                        PromoParticipantsHistory.promo_id == promo_id,
                        PromoParticipantsHistory.recorded_at <= time_ago
                    ).order_by(PromoParticipantsHistory.recorded_at.desc()).first()
                    
                    if record:
                        old_count = record.participants_count
                        diff = current_count - old_count
                        percent = (diff / old_count * 100) if old_count > 0 else 0
                        
                        result[f'{hours}h'] = {
                            'count': old_count,
                            'diff': diff,
                            'percent': round(percent, 1)
                        }
                
                # Предпоследняя запись для "с последнего обновления"
                prev_record = db.query(PromoParticipantsHistory).filter(
                    PromoParticipantsHistory.exchange == exchange,
                    PromoParticipantsHistory.promo_id == promo_id,
                    PromoParticipantsHistory.id != current_record.id
                ).order_by(PromoParticipantsHistory.recorded_at.desc()).first()
                
                if prev_record:
                    diff = current_count - prev_record.participants_count
                    time_diff = now - prev_record.recorded_at
                    
                    # Форматируем время назад
                    if time_diff.days > 0:
                        time_ago_str = f"{time_diff.days} дн."
                    elif time_diff.seconds >= 3600:
                        time_ago_str = f"{time_diff.seconds // 3600} ч."
                    else:
                        time_ago_str = f"{time_diff.seconds // 60} мин."
                    
                    result['last_update'] = {
                        'count': prev_record.participants_count,
                        'diff': diff,
                        'time_ago': time_ago_str
                    }
                
                return result
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики участников: {e}")
            return {}
    
    @staticmethod
    def record_batch(exchange: str, promos: List[Dict]) -> int:
        """
        Записать участников для нескольких промо сразу
        
        Args:
            exchange: Название биржи
            promos: Список промоакций с полями promo_id, participants_count или participants, title
            
        Returns:
            Количество записанных
        """
        count = 0
        for promo in promos:
            promo_id = promo.get('promo_id')
            # Поддерживаем оба варианта названия поля
            participants = promo.get('participants_count') or promo.get('participants')
            title = promo.get('title')
            
            if promo_id and participants:
                try:
                    participants_int = int(float(str(participants).replace(',', '').replace(' ', '')))
                    if ParticipantsTrackerService.record_participants(exchange, promo_id, participants_int, title):
                        count += 1
                except (ValueError, TypeError):
                    pass
        
        return count
    
    @staticmethod
    def cleanup_old_records(days: int = 7) -> int:
        """
        Удалить старые записи для экономии места
        
        Args:
            days: Записи старше этого количества дней будут удалены
            
        Returns:
            Количество удалённых записей
        """
        try:
            with get_db_session() as db:
                cutoff = datetime.utcnow() - timedelta(days=days)
                
                deleted = db.query(PromoParticipantsHistory).filter(
                    PromoParticipantsHistory.recorded_at < cutoff
                ).delete()
                
                db.commit()
                logger.info(f"🧹 Удалено {deleted} старых записей истории участников")
                return deleted
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки истории: {e}")
            return 0


# Синглтон для удобного доступа
_tracker_instance = None


def get_participants_tracker() -> ParticipantsTrackerService:
    """Получить экземпляр сервиса отслеживания участников"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = ParticipantsTrackerService()
    return _tracker_instance
