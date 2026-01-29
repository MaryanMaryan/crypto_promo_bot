# utils/resource_monitor.py
"""
RESOURCE MONITOR - Мониторинг системных ресурсов

Функционал:
- Мониторинг RAM/CPU использования
- Алерты при превышении порогов
- Логирование статистики
- Graceful degradation при нехватке ресурсов
"""

import asyncio
import logging
import os
import sys
import time
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import config

logger = logging.getLogger(__name__)

# Опциональный импорт psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("⚠️ psutil не установлен. Resource Monitor будет работать в ограниченном режиме. "
                   "Установите: pip install psutil")


class ResourceLevel(Enum):
    """Уровни состояния ресурсов"""
    NORMAL = "normal"       # Всё хорошо
    WARNING = "warning"     # Приближаемся к лимиту
    CRITICAL = "critical"   # Критически мало ресурсов


@dataclass
class ResourceSnapshot:
    """Снимок состояния ресурсов"""
    timestamp: float = field(default_factory=time.time)
    
    # RAM
    ram_used_mb: float = 0.0
    ram_available_mb: float = 0.0
    ram_total_mb: float = 0.0
    ram_percent: float = 0.0
    
    # CPU
    cpu_percent: float = 0.0
    cpu_count: int = 0
    
    # Process
    process_ram_mb: float = 0.0
    process_cpu_percent: float = 0.0
    process_threads: int = 0
    
    # Уровни
    ram_level: ResourceLevel = ResourceLevel.NORMAL
    cpu_level: ResourceLevel = ResourceLevel.NORMAL
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': datetime.fromtimestamp(self.timestamp).isoformat(),
            'ram': {
                'used_mb': round(self.ram_used_mb, 1),
                'available_mb': round(self.ram_available_mb, 1),
                'total_mb': round(self.ram_total_mb, 1),
                'percent': round(self.ram_percent, 1),
                'level': self.ram_level.value,
            },
            'cpu': {
                'percent': round(self.cpu_percent, 1),
                'count': self.cpu_count,
                'level': self.cpu_level.value,
            },
            'process': {
                'ram_mb': round(self.process_ram_mb, 1),
                'cpu_percent': round(self.process_cpu_percent, 1),
                'threads': self.process_threads,
            },
        }


@dataclass
class ResourceThresholds:
    """Пороги для определения уровней ресурсов"""
    ram_warning_percent: float = 70.0
    ram_critical_percent: float = 85.0
    cpu_warning_percent: float = 70.0
    cpu_critical_percent: float = 90.0


class ResourceMonitor:
    """
    Мониторинг системных ресурсов.
    
    Использование:
        monitor = ResourceMonitor()
        await monitor.start()
        
        # Получить текущее состояние
        snapshot = monitor.get_current_snapshot()
        
        # Проверить, достаточно ли ресурсов
        if monitor.is_critical:
            # Уменьшить нагрузку
            
        await monitor.stop()
    """
    
    def __init__(
        self,
        check_interval: int = None,
        ram_warning_percent: float = None,
        ram_critical_percent: float = None,
        cpu_warning_percent: float = None,
        cpu_critical_percent: float = None,
        on_warning: Optional[Callable[[ResourceSnapshot], Awaitable[None]]] = None,
        on_critical: Optional[Callable[[ResourceSnapshot], Awaitable[None]]] = None
    ):
        """
        Args:
            check_interval: Интервал проверки в секундах
            ram_warning_percent: Порог предупреждения RAM (%)
            ram_critical_percent: Критический порог RAM (%)
            cpu_warning_percent: Порог предупреждения CPU (%)
            cpu_critical_percent: Критический порог CPU (%)
            on_warning: Callback при warning состоянии
            on_critical: Callback при critical состоянии
        """
        self.check_interval = check_interval or getattr(config, 'RESOURCE_MONITOR_INTERVAL', 300)  # 5 минут
        
        self.thresholds = ResourceThresholds(
            ram_warning_percent=ram_warning_percent or getattr(config, 'RESOURCE_RAM_WARNING_PERCENT', 70.0),
            ram_critical_percent=ram_critical_percent or getattr(config, 'RESOURCE_RAM_CRITICAL_PERCENT', 85.0),
            cpu_warning_percent=cpu_warning_percent or getattr(config, 'RESOURCE_CPU_WARNING_PERCENT', 70.0),
            cpu_critical_percent=cpu_critical_percent or getattr(config, 'RESOURCE_CPU_CRITICAL_PERCENT', 90.0),
        )
        
        self.on_warning = on_warning
        self.on_critical = on_critical
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_snapshot: Optional[ResourceSnapshot] = None
        self._history: List[ResourceSnapshot] = []
        self._max_history = 100
        
        # Счётчики событий
        self._warning_count = 0
        self._critical_count = 0
        self._last_alert_time: Optional[float] = None
        self._alert_cooldown = 300  # Минимум 5 минут между алертами
        
        # Счётчик подряд идущих критических состояний (для фильтрации кратковременных пиков)
        self._consecutive_critical = 0
        self._critical_threshold = 2  # Отправлять уведомление только после 2+ подряд критических замеров
        
        # Кэш процесса
        self._process: Optional[Any] = None
        
        logger.info(
            f"📊 ResourceMonitor инициализирован: interval={self.check_interval}s, "
            f"RAM warning={self.thresholds.ram_warning_percent}%/critical={self.thresholds.ram_critical_percent}%"
        )
    
    async def start(self):
        """Запускает мониторинг"""
        if self._running:
            return
        
        if not PSUTIL_AVAILABLE:
            logger.warning("⚠️ psutil недоступен, мониторинг ресурсов отключён")
            return
        
        self._running = True
        self._process = psutil.Process(os.getpid())
        
        # Делаем первый снимок сразу
        self._current_snapshot = self._take_snapshot()
        
        # Запускаем фоновый мониторинг
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("📊 ResourceMonitor запущен")
    
    async def stop(self):
        """Останавливает мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("📊 ResourceMonitor остановлен")
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                
                if not self._running:
                    break
                
                snapshot = self._take_snapshot()
                self._current_snapshot = snapshot
                self._history.append(snapshot)
                
                # Ограничиваем историю
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]
                
                # Логируем статус
                self._log_snapshot(snapshot)
                
                # Проверяем пороги и вызываем callbacks
                await self._check_thresholds(snapshot)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка мониторинга ресурсов: {e}")
                await asyncio.sleep(60)  # Пауза после ошибки
    
    def _take_snapshot(self) -> ResourceSnapshot:
        """Делает снимок текущего состояния ресурсов"""
        snapshot = ResourceSnapshot()
        
        if not PSUTIL_AVAILABLE:
            return snapshot
        
        try:
            # Системная память
            mem = psutil.virtual_memory()
            snapshot.ram_total_mb = mem.total / (1024 * 1024)
            snapshot.ram_used_mb = mem.used / (1024 * 1024)
            snapshot.ram_available_mb = mem.available / (1024 * 1024)
            snapshot.ram_percent = mem.percent
            
            # CPU с усреднением (3 замера по 0.5 сек = 1.5 сек)
            # Это избегает ложных алертов на кратковременные пики при браузерном парсинге
            cpu_samples = []
            for _ in range(3):
                cpu_samples.append(psutil.cpu_percent(interval=0.5))
            snapshot.cpu_percent = sum(cpu_samples) / len(cpu_samples)
            snapshot.cpu_count = psutil.cpu_count()
            
            # Процесс
            if self._process:
                try:
                    snapshot.process_ram_mb = self._process.memory_info().rss / (1024 * 1024)
                    snapshot.process_cpu_percent = self._process.cpu_percent()
                    snapshot.process_threads = self._process.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Определяем уровни
            snapshot.ram_level = self._determine_level(
                snapshot.ram_percent,
                self.thresholds.ram_warning_percent,
                self.thresholds.ram_critical_percent
            )
            snapshot.cpu_level = self._determine_level(
                snapshot.cpu_percent,
                self.thresholds.cpu_warning_percent,
                self.thresholds.cpu_critical_percent
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения метрик: {e}")
        
        return snapshot
    
    def _determine_level(self, value: float, warning: float, critical: float) -> ResourceLevel:
        """Определяет уровень ресурса"""
        if value >= critical:
            return ResourceLevel.CRITICAL
        elif value >= warning:
            return ResourceLevel.WARNING
        return ResourceLevel.NORMAL
    
    def _log_snapshot(self, snapshot: ResourceSnapshot):
        """Логирует снимок"""
        level = logging.INFO
        
        if snapshot.ram_level == ResourceLevel.CRITICAL or snapshot.cpu_level == ResourceLevel.CRITICAL:
            level = logging.WARNING
        elif snapshot.ram_level == ResourceLevel.WARNING or snapshot.cpu_level == ResourceLevel.WARNING:
            level = logging.INFO
        else:
            level = logging.DEBUG
        
        logger.log(
            level,
            f"📊 Ресурсы: RAM {snapshot.ram_percent:.1f}% ({snapshot.ram_used_mb:.0f}/{snapshot.ram_total_mb:.0f}MB), "
            f"CPU {snapshot.cpu_percent:.1f}%, "
            f"Process: {snapshot.process_ram_mb:.0f}MB / {snapshot.process_threads} threads"
        )
    
    async def _check_thresholds(self, snapshot: ResourceSnapshot):
        """Проверяет пороги и вызывает callbacks"""
        now = time.time()
        
        # Проверяем cooldown
        if self._last_alert_time and (now - self._last_alert_time) < self._alert_cooldown:
            return
        
        is_critical = snapshot.ram_level == ResourceLevel.CRITICAL or snapshot.cpu_level == ResourceLevel.CRITICAL
        is_warning = snapshot.ram_level == ResourceLevel.WARNING or snapshot.cpu_level == ResourceLevel.WARNING
        
        # Отслеживаем подряд идущие критические состояния
        if is_critical:
            self._consecutive_critical += 1
        else:
            self._consecutive_critical = 0  # Сброс при нормальном состоянии
        
        if is_critical:
            self._critical_count += 1
            
            # Отправляем уведомление только если критическое состояние держится 2+ замеров подряд
            # Это фильтрует кратковременные пики CPU при браузерном парсинге
            if self._consecutive_critical >= self._critical_threshold:
                self._last_alert_time = now
                
                logger.warning(
                    f"🔴 CRITICAL (持続): RAM {snapshot.ram_percent:.1f}%, CPU {snapshot.cpu_percent:.1f}% "
                    f"(подряд: {self._consecutive_critical})"
                )
                
                if self.on_critical:
                    try:
                        await self.on_critical(snapshot)
                    except Exception as e:
                        logger.error(f"❌ Ошибка в on_critical callback: {e}")
            else:
                # Кратковременный пик - только логируем без уведомления
                logger.info(
                    f"📊 Пик ресурсов (кратковременный): RAM {snapshot.ram_percent:.1f}%, CPU {snapshot.cpu_percent:.1f}%"
                )
        
        elif is_warning:
            self._warning_count += 1
            self._last_alert_time = now
            
            logger.warning(
                f"🟡 WARNING: RAM {snapshot.ram_percent:.1f}%, CPU {snapshot.cpu_percent:.1f}%"
            )
            
            if self.on_warning:
                try:
                    await self.on_warning(snapshot)
                except Exception as e:
                    logger.error(f"❌ Ошибка в on_warning callback: {e}")
    
    def get_current_snapshot(self) -> Optional[ResourceSnapshot]:
        """Возвращает последний снимок"""
        return self._current_snapshot
    
    def take_snapshot_now(self) -> ResourceSnapshot:
        """Делает снимок прямо сейчас (без ожидания цикла)"""
        snapshot = self._take_snapshot()
        self._current_snapshot = snapshot
        return snapshot
    
    @property
    def is_critical(self) -> bool:
        """Проверяет, в критическом ли состоянии система"""
        if not self._current_snapshot:
            return False
        return (
            self._current_snapshot.ram_level == ResourceLevel.CRITICAL or
            self._current_snapshot.cpu_level == ResourceLevel.CRITICAL
        )
    
    @property
    def is_warning(self) -> bool:
        """Проверяет, в состоянии предупреждения ли система"""
        if not self._current_snapshot:
            return False
        return (
            self._current_snapshot.ram_level == ResourceLevel.WARNING or
            self._current_snapshot.cpu_level == ResourceLevel.WARNING
        )
    
    @property
    def ram_percent(self) -> float:
        """Текущий процент использования RAM"""
        return self._current_snapshot.ram_percent if self._current_snapshot else 0.0
    
    @property
    def cpu_percent(self) -> float:
        """Текущий процент использования CPU"""
        return self._current_snapshot.cpu_percent if self._current_snapshot else 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику мониторинга"""
        return {
            'current': self._current_snapshot.to_dict() if self._current_snapshot else None,
            'warning_count': self._warning_count,
            'critical_count': self._critical_count,
            'history_size': len(self._history),
            'thresholds': {
                'ram_warning': self.thresholds.ram_warning_percent,
                'ram_critical': self.thresholds.ram_critical_percent,
                'cpu_warning': self.thresholds.cpu_warning_percent,
                'cpu_critical': self.thresholds.cpu_critical_percent,
            },
            'psutil_available': PSUTIL_AVAILABLE,
        }
    
    def get_status_message(self) -> str:
        """Формирует сообщение о статусе ресурсов для Telegram"""
        if not self._current_snapshot:
            return "📊 Resource Monitor: нет данных"
        
        s = self._current_snapshot
        
        # Эмодзи для уровней
        ram_emoji = "🟢" if s.ram_level == ResourceLevel.NORMAL else ("🟡" if s.ram_level == ResourceLevel.WARNING else "🔴")
        cpu_emoji = "🟢" if s.cpu_level == ResourceLevel.NORMAL else ("🟡" if s.cpu_level == ResourceLevel.WARNING else "🔴")
        
        lines = [
            "📊 <b>System Resources:</b>",
            f"  {ram_emoji} RAM: {s.ram_percent:.1f}% ({s.ram_used_mb:.0f}/{s.ram_total_mb:.0f} MB)",
            f"  {cpu_emoji} CPU: {s.cpu_percent:.1f}% ({s.cpu_count} cores)",
            "",
            "🤖 <b>Bot Process:</b>",
            f"  • RAM: {s.process_ram_mb:.1f} MB",
            f"  • Threads: {s.process_threads}",
        ]
        
        if self._warning_count > 0 or self._critical_count > 0:
            lines.append("")
            lines.append(f"⚠️ Alerts: {self._warning_count} warnings, {self._critical_count} critical")
        
        return "\n".join(lines)
    
    def get_recommended_workers(self, max_workers: int = 5) -> int:
        """
        Рекомендует количество воркеров на основе ресурсов.
        
        Используется для Graceful Degradation:
        - NORMAL: max_workers
        - WARNING: max_workers // 2
        - CRITICAL: 1
        """
        if not self._current_snapshot:
            return max_workers
        
        if self.is_critical:
            return 1
        elif self.is_warning:
            return max(1, max_workers // 2)
        return max_workers


# Глобальный экземпляр
_resource_monitor: Optional[ResourceMonitor] = None


def get_resource_monitor() -> Optional[ResourceMonitor]:
    """Возвращает глобальный Resource Monitor"""
    return _resource_monitor


async def init_resource_monitor(**kwargs) -> ResourceMonitor:
    """Инициализирует и запускает глобальный Resource Monitor"""
    global _resource_monitor
    _resource_monitor = ResourceMonitor(**kwargs)
    await _resource_monitor.start()
    return _resource_monitor


async def shutdown_resource_monitor():
    """Останавливает глобальный Resource Monitor"""
    global _resource_monitor
    if _resource_monitor:
        await _resource_monitor.stop()
        _resource_monitor = None
