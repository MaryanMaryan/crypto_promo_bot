"""
Сервис отслеживания стабильности стейкингов для умных уведомлений

Основная логика:
- Fixed стейкинги: уведомлять сразу при появлении и изменении APR >= 5%
- Flexible стейкинги: ждать 6 часов стабильности APR, затем уведомлять
- Combined (Fixed+Flexible): уведомлять сразу как Fixed

Отслеживает:
- Тип стейкинга (lock_type)
- Стабильность APR (stable_since, last_apr_change)
- Изменения APR (previous_apr)
- Флаги уведомлений (is_notification_pending, notification_sent_at)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from data.models import StakingHistory, ApiLink

logger = logging.getLogger(__name__)


class StabilityTrackerService:
    """Сервис для отслеживания стабильности стейкингов и управления уведомлениями"""

    def __init__(self, db_session: Session):
        self.db = db_session

    # ========== ОПРЕДЕЛЕНИЕ ТИПОВ СТЕЙКИНГА ==========

    def _is_fixed(self, staking_type: str) -> bool:
        """Проверка, является ли стейкинг Fixed (фиксированный срок)"""
        if not staking_type:
            return False

        fixed_keywords = ['fixed', 'locked', 'lock', 'multi_time']
        staking_type_lower = staking_type.lower()

        # Проверяем наличие ключевых слов Fixed
        return any(keyword in staking_type_lower for keyword in fixed_keywords)

    def _is_flexible(self, staking_type: str) -> bool:
        """Проверка, является ли стейкинг Flexible (гибкий)"""
        if not staking_type:
            return False

        staking_type_lower = staking_type.lower()
        return 'flexible' in staking_type_lower

    def _is_combined(self, staking_type: str) -> bool:
        """Проверка, является ли стейкинг Combined (Fixed+Flexible)"""
        if not staking_type:
            return False

        staking_type_lower = staking_type.lower()

        # Combined если содержит оба: fixed и flexible
        has_fixed = any(kw in staking_type_lower for kw in ['fixed', 'locked', 'lock'])
        has_flexible = 'flexible' in staking_type_lower

        return has_fixed and has_flexible

    def determine_lock_type(self, staking_type: str) -> str:
        """
        Определение типа блокировки стейкинга

        Returns:
            'Combined' | 'Fixed' | 'Flexible' | 'Unknown'
        """
        if self._is_combined(staking_type):
            return 'Combined'
        elif self._is_fixed(staking_type):
            return 'Fixed'
        elif self._is_flexible(staking_type):
            return 'Flexible'
        else:
            return 'Unknown'

    # ========== ПРОВЕРКА ИЗМЕНЕНИЙ APR ==========

    def _has_significant_apr_change(
        self,
        old_apr: Optional[float],
        new_apr: float,
        threshold: float = 5.0
    ) -> bool:
        """
        Проверка значимого изменения APR (АБСОЛЮТНОЕ измерение)

        Args:
            old_apr: Предыдущий APR
            new_apr: Новый APR
            threshold: Минимальное изменение (по умолчанию 5.0)

        Returns:
            True если изменение >= threshold

        Примеры:
            old_apr=20.0, new_apr=25.0 -> изменение 5.0 -> True
            old_apr=20.0, new_apr=23.0 -> изменение 3.0 -> False
            old_apr=100.0, new_apr=110.0 -> изменение 10.0 -> True
        """
        if old_apr is None:
            return False

        apr_diff = abs(new_apr - old_apr)
        return apr_diff >= threshold

    # ========== ОТСЛЕЖИВАНИЕ СТАБИЛЬНОСТИ ==========

    def check_stability(
        self,
        staking: StakingHistory,
        api_link: ApiLink,
        current_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Проверка стабильности стейкинга и определение необходимости уведомления

        Args:
            staking: Запись стейкинга из БД
            api_link: Настройки ссылки (содержит настройки уведомлений)
            current_time: Текущее время (для тестирования)

        Returns:
            {
                'should_notify': bool,  # Нужно ли уведомлять
                'notification_type': str,  # 'new' | 'apr_change' | 'stable_flexible' | None
                'reason': str,  # Причина уведомления
                'is_stable': bool,  # Стабилен ли APR
                'hours_stable': float  # Часов стабильности
            }
        """
        if current_time is None:
            current_time = datetime.utcnow()

        result = {
            'should_notify': False,
            'notification_type': None,
            'reason': '',
            'is_stable': False,
            'hours_stable': 0
        }

        # Определяем тип блокировки
        lock_type = staking.lock_type or self.determine_lock_type(staking.type or '')

        # Получаем настройки уведомлений
        min_apr_change = api_link.notify_min_apr_change or 5.0
        stability_hours = api_link.flexible_stability_hours or 6
        notify_immediately_fixed = api_link.fixed_notify_immediately if api_link.fixed_notify_immediately is not None else True
        notify_combined_as_fixed = api_link.notify_combined_as_fixed if api_link.notify_combined_as_fixed is not None else True

        # ЛОГИКА ДЛЯ COMBINED (обрабатываем как Fixed)
        if lock_type == 'Combined' and notify_combined_as_fixed:
            # Combined уведомляется сразу
            if not staking.notification_sent:
                result['should_notify'] = True
                result['notification_type'] = 'new'
                result['reason'] = 'New Combined staking (notify immediately)'
                return result

            # Проверяем изменение APR
            if self._has_significant_apr_change(staking.previous_apr, staking.apr, min_apr_change):
                result['should_notify'] = True
                result['notification_type'] = 'apr_change'
                result['reason'] = f'APR changed by {abs(staking.apr - (staking.previous_apr or 0)):.2f}%'
                return result

        # ЛОГИКА ДЛЯ FIXED
        elif lock_type == 'Fixed':
            if notify_immediately_fixed:
                # Новый Fixed стейкинг
                if not staking.notification_sent:
                    result['should_notify'] = True
                    result['notification_type'] = 'new'
                    result['reason'] = 'New Fixed staking (notify immediately)'
                    return result

                # Проверяем изменение APR
                if self._has_significant_apr_change(staking.previous_apr, staking.apr, min_apr_change):
                    result['should_notify'] = True
                    result['notification_type'] = 'apr_change'
                    result['reason'] = f'APR changed by {abs(staking.apr - (staking.previous_apr or 0)):.2f}%'
                    return result

        # ЛОГИКА ДЛЯ FLEXIBLE
        elif lock_type == 'Flexible':
            # Проверяем, есть ли стабильность
            if staking.stable_since:
                hours_stable = (current_time - staking.stable_since).total_seconds() / 3600
                result['hours_stable'] = hours_stable
                result['is_stable'] = hours_stable >= stability_hours

                # Если стабилен достаточно долго и еще не уведомили
                if result['is_stable'] and staking.is_notification_pending:
                    result['should_notify'] = True
                    result['notification_type'] = 'stable_flexible'
                    result['reason'] = f'Flexible APR stable for {hours_stable:.1f}h (threshold: {stability_hours}h)'
                    return result

        return result

    def update_stability_status(
        self,
        staking: StakingHistory,
        new_apr: float,
        api_link: ApiLink,
        current_time: Optional[datetime] = None
    ) -> None:
        """
        Обновление статуса стабильности при изменении APR

        Логика:
        - Если APR изменился >= threshold -> сброс stable_since, pending=True
        - Если APR стабилен -> обновляем stable_since (если еще не установлен)
        - Для Fixed/Combined -> pending=False (уведомляем сразу)
        - Для Flexible -> pending=True (уведомляем после стабилизации)

        Args:
            staking: Запись стейкинга
            new_apr: Новый APR
            api_link: Настройки ссылки
            current_time: Текущее время (для тестирования)
        """
        if current_time is None:
            current_time = datetime.utcnow()

        # Определяем тип блокировки
        lock_type = staking.lock_type or self.determine_lock_type(staking.type or '')

        # Получаем настройки
        min_apr_change = api_link.notify_min_apr_change or 5.0

        # Проверяем изменение APR
        apr_changed = self._has_significant_apr_change(staking.apr, new_apr, min_apr_change)

        if apr_changed:
            logger.info(
                f"📊 APR changed for {staking.exchange} {staking.coin}: "
                f"{staking.apr:.2f}% -> {new_apr:.2f}%"
            )

            # Сохраняем предыдущий APR
            staking.previous_apr = staking.apr
            staking.last_apr_change = current_time

            # Сбрасываем стабильность
            staking.stable_since = None

            # Для Flexible устанавливаем pending
            if lock_type == 'Flexible':
                staking.is_notification_pending = True
                logger.info(f"  ⏳ Flexible staking - waiting for stability...")
            else:
                # Fixed/Combined уведомляем сразу
                staking.is_notification_pending = False

        else:
            # APR не изменился значимо

            # Если это Flexible и stable_since еще не установлен
            if lock_type == 'Flexible' and not staking.stable_since:
                staking.stable_since = current_time
                staking.is_notification_pending = True
                logger.info(f"  🕐 Flexible staking - starting stability tracking...")

        # Обновляем lock_type если не установлен
        if not staking.lock_type:
            staking.lock_type = lock_type

        # Обновляем APR
        staking.apr = new_apr

    def mark_notification_sent(
        self,
        staking: StakingHistory,
        current_time: Optional[datetime] = None
    ) -> None:
        """
        Отметить, что уведомление отправлено

        Args:
            staking: Запись стейкинга
            current_time: Текущее время (для тестирования)
        """
        if current_time is None:
            current_time = datetime.utcnow()

        staking.notification_sent = True
        staking.notification_sent_at = current_time
        staking.is_notification_pending = False

        logger.info(f"✅ Notification marked as sent for {staking.exchange} {staking.coin}")

    def get_pending_notifications(self, api_link: ApiLink) -> List[StakingHistory]:
        """
        Получить все стейкинги, ожидающие уведомления

        Args:
            api_link: Настройки ссылки

        Returns:
            Список стейкингов, готовых к уведомлению
        """
        # Получаем все стейкинги этой ссылки с pending флагом
        pending_stakings = self.db.query(StakingHistory).filter(
            StakingHistory.is_notification_pending == True
        ).all()

        ready_to_notify = []

        for staking in pending_stakings:
            result = self.check_stability(staking, api_link)
            if result['should_notify']:
                ready_to_notify.append(staking)

        return ready_to_notify
