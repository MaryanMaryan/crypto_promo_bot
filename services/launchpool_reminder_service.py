# services/launchpool_reminder_service.py
"""
Сервис напоминаний о скором окончании Launchpool
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LaunchpoolReminder:
    """Информация о напоминании"""
    project_id: str
    token_symbol: str
    exchange: str
    end_time: datetime
    hours_left: float
    link_id: int


class LaunchpoolReminderService:
    """
    Сервис для отслеживания напоминаний о скором окончании Launchpool.
    
    Хранит в памяти список уже отправленных напоминаний, 
    чтобы не дублировать их.
    """
    
    def __init__(self):
        # Set уже отправленных напоминаний: (link_id, project_id, hours_threshold)
        self._sent_reminders: Set[tuple] = set()
        
    def check_project_for_reminder(
        self,
        project: Any,
        link_id: int,
        notify_hours_before_end: int
    ) -> Optional[LaunchpoolReminder]:
        """
        Проверяет, нужно ли отправить напоминание для проекта.
        
        Args:
            project: LaunchpoolProject объект
            link_id: ID ссылки
            notify_hours_before_end: За сколько часов напоминать
            
        Returns:
            LaunchpoolReminder если нужно напомнить, иначе None
        """
        if notify_hours_before_end <= 0:
            return None
            
        end_time = getattr(project, 'end_time', None)
        if not end_time:
            return None
            
        # Конвертируем в datetime если нужно
        if isinstance(end_time, str):
            try:
                end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except:
                return None
        
        now = datetime.utcnow()
        
        # Проект уже закончился
        if end_time <= now:
            return None
            
        # Вычисляем сколько часов осталось
        time_left = end_time - now
        hours_left = time_left.total_seconds() / 3600
        
        # Проверяем, попадает ли в окно напоминания
        if hours_left > notify_hours_before_end:
            return None
            
        # Проверяем, не отправляли ли уже
        project_id = getattr(project, 'id', str(project))
        reminder_key = (link_id, project_id, notify_hours_before_end)
        
        if reminder_key in self._sent_reminders:
            return None
            
        # Создаём напоминание
        return LaunchpoolReminder(
            project_id=project_id,
            token_symbol=getattr(project, 'token_symbol', 'UNKNOWN'),
            exchange=getattr(project, 'exchange', 'Unknown'),
            end_time=end_time,
            hours_left=hours_left,
            link_id=link_id
        )
    
    def mark_reminder_sent(self, reminder: LaunchpoolReminder, hours_threshold: int):
        """Отмечает напоминание как отправленное"""
        key = (reminder.link_id, reminder.project_id, hours_threshold)
        self._sent_reminders.add(key)
        logger.info(f"📝 Напоминание отмечено: {reminder.token_symbol} (link={reminder.link_id})")
    
    def check_projects_for_reminders(
        self,
        projects: List[Any],
        link_id: int,
        notify_hours_before_end: int
    ) -> List[LaunchpoolReminder]:
        """
        Проверяет список проектов на необходимость напоминаний.
        
        Returns:
            Список напоминаний для отправки
        """
        if notify_hours_before_end <= 0:
            return []
            
        reminders = []
        for project in projects:
            reminder = self.check_project_for_reminder(
                project=project,
                link_id=link_id,
                notify_hours_before_end=notify_hours_before_end
            )
            if reminder:
                reminders.append(reminder)
                
        if reminders:
            logger.info(f"⏰ Найдено {len(reminders)} напоминаний о скором окончании")
            
        return reminders
    
    def format_reminder_message(self, reminder: LaunchpoolReminder) -> str:
        """Форматирует сообщение напоминания"""
        hours = int(reminder.hours_left)
        minutes = int((reminder.hours_left - hours) * 60)
        
        if hours > 0:
            time_str = f"{hours}ч {minutes}мин"
        else:
            time_str = f"{minutes} минут"
            
        end_str = reminder.end_time.strftime("%d.%m.%Y %H:%M UTC")
        
        message = (
            f"⏰ <b>Напоминание: Launchpool скоро закончится!</b>\n\n"
            f"🏦 Биржа: <b>{reminder.exchange}</b>\n"
            f"🪙 Токен: <b>{reminder.token_symbol}</b>\n"
            f"⌛ Осталось: <b>{time_str}</b>\n"
            f"📅 Окончание: {end_str}\n\n"
            f"<i>Успейте поучаствовать!</i>"
        )
        
        return message
    
    def clear_old_reminders(self, days: int = 7):
        """
        Очищает старые записи о напоминаниях.
        Вызывается периодически для очистки памяти.
        """
        # Простая реализация - просто очищаем всё старше N дней
        # В реальности можно хранить время отправки
        pass
    
    def get_stats(self) -> Dict[str, int]:
        """Статистика сервиса"""
        return {
            'total_sent': len(self._sent_reminders)
        }


# Глобальный экземпляр сервиса
_reminder_service: Optional[LaunchpoolReminderService] = None


def get_reminder_service() -> LaunchpoolReminderService:
    """Получить глобальный экземпляр сервиса напоминаний"""
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = LaunchpoolReminderService()
    return _reminder_service
