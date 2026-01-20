"""
Очередь задач парсинга с приоритетами.
Использует asyncio.PriorityQueue для управления задачами.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Dict, Any, Optional, List, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    """Приоритеты задач (меньше = выше приоритет)"""
    CRITICAL = 0      # Критические проверки (ошибки, восстановление)
    HIGH = 1          # Ручная проверка пользователем
    NORMAL = 2        # Автоматическая проверка
    LOW = 3           # Фоновые задачи


class TaskStatus:
    """Статусы задач"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(order=True)
class ParsingTask:
    """
    Задача парсинга с приоритетом.
    Используется для очереди с приоритетами.
    """
    priority: int  # Для сортировки в PriorityQueue
    created_at: float = field(compare=False)  # Время создания
    task_id: str = field(default_factory=lambda: str(uuid4()), compare=False)
    
    # Данные задачи (не участвуют в сравнении)
    link_id: int = field(default=0, compare=False)
    link_name: str = field(default="", compare=False)
    url: str = field(default="", compare=False)
    category: str = field(default="general", compare=False)
    parsing_type: str = field(default="combined", compare=False)
    exchange: str = field(default="", compare=False)
    api_url: Optional[str] = field(default=None, compare=False)
    page_url: Optional[str] = field(default=None, compare=False)
    min_apr: Optional[float] = field(default=None, compare=False)
    extra_data: Dict[str, Any] = field(default_factory=dict, compare=False)
    
    # Метаданные
    status: str = field(default=TaskStatus.PENDING, compare=False)
    attempt: int = field(default=0, compare=False)
    max_attempts: int = field(default=3, compare=False)
    result: Optional[Any] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    started_at: Optional[float] = field(default=None, compare=False)
    completed_at: Optional[float] = field(default=None, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует задачу в словарь"""
        return {
            'task_id': self.task_id,
            'priority': TaskPriority(self.priority).name,
            'link_id': self.link_id,
            'link_name': self.link_name,
            'url': self.url,
            'category': self.category,
            'status': self.status,
            'attempt': self.attempt,
            'created_at': datetime.fromtimestamp(self.created_at).isoformat() if self.created_at else None,
        }


class ParsingQueue:
    """
    Очередь задач парсинга с приоритетами.
    
    Особенности:
    - Приоритеты: CRITICAL > HIGH > NORMAL > LOW
    - Отслеживание статуса задач
    - Сбор результатов асинхронно
    - Graceful shutdown
    """
    
    def __init__(self, max_size: int = 100):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_size)
        self._tasks: Dict[str, ParsingTask] = {}  # Все задачи по ID
        self._results: asyncio.Queue = asyncio.Queue()  # Результаты выполнения
        self._shutdown = False
        self._lock = asyncio.Lock()
        
        # Статистика
        self._stats = {
            'total_added': 0,
            'total_completed': 0,
            'total_failed': 0,
            'total_cancelled': 0,
        }
        
        logger.info("📋 ParsingQueue инициализирована")
    
    async def add_task(
        self,
        link_id: int,
        link_name: str,
        url: str,
        category: str = "general",
        parsing_type: str = "combined",
        exchange: str = "",
        api_url: Optional[str] = None,
        page_url: Optional[str] = None,
        min_apr: Optional[float] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Добавляет задачу в очередь.
        
        Returns:
            task_id: Уникальный ID задачи
        """
        if self._shutdown:
            raise RuntimeError("Очередь завершена, новые задачи не принимаются")
        
        task = ParsingTask(
            priority=priority,
            created_at=datetime.utcnow().timestamp(),
            link_id=link_id,
            link_name=link_name,
            url=url,
            category=category,
            parsing_type=parsing_type,
            exchange=exchange,
            api_url=api_url,
            page_url=page_url,
            min_apr=min_apr,
            extra_data=extra_data or {}
        )
        
        async with self._lock:
            await self._queue.put(task)
            self._tasks[task.task_id] = task
            self._stats['total_added'] += 1
        
        logger.debug(f"📥 Задача добавлена: {link_name} (priority={TaskPriority(priority).name})")
        return task.task_id
    
    async def get_task(self) -> Optional[ParsingTask]:
        """
        Получает следующую задачу из очереди.
        Блокирующий вызов, ждёт появления задачи.
        
        Returns:
            ParsingTask или None при shutdown
        """
        if self._shutdown and self._queue.empty():
            return None
        
        try:
            task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            task.status = TaskStatus.IN_PROGRESS
            task.started_at = datetime.utcnow().timestamp()
            task.attempt += 1
            return task
        except asyncio.TimeoutError:
            return None
    
    async def complete_task(self, task: ParsingTask, result: Any = None, error: Optional[str] = None):
        """Отмечает задачу как завершённую"""
        task.completed_at = datetime.utcnow().timestamp()
        task.result = result
        
        if error:
            task.status = TaskStatus.FAILED
            task.error = error
            self._stats['total_failed'] += 1
            
            # Повторная попытка если не превышен лимит
            if task.attempt < task.max_attempts:
                logger.warning(f"⚠️ Задача {task.link_name} упала, повтор ({task.attempt}/{task.max_attempts})")
                task.status = TaskStatus.PENDING
                await self._queue.put(task)
            else:
                logger.error(f"❌ Задача {task.link_name} провалена после {task.max_attempts} попыток")
        else:
            task.status = TaskStatus.COMPLETED
            self._stats['total_completed'] += 1
        
        # Отправляем результат
        await self._results.put(task)
        self._queue.task_done()
    
    async def get_result(self, timeout: float = 1.0) -> Optional[ParsingTask]:
        """
        Получает результат выполнения задачи.
        
        Returns:
            Завершённая задача или None при timeout
        """
        try:
            return await asyncio.wait_for(self._results.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    async def get_all_results(self, timeout: float = 5.0) -> List[ParsingTask]:
        """Получает все доступные результаты"""
        results = []
        end_time = asyncio.get_event_loop().time() + timeout
        
        while asyncio.get_event_loop().time() < end_time:
            try:
                result = await asyncio.wait_for(
                    self._results.get(), 
                    timeout=min(0.5, end_time - asyncio.get_event_loop().time())
                )
                results.append(result)
            except asyncio.TimeoutError:
                break
        
        return results
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Получает статус задачи по ID"""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None
    
    @property
    def pending_count(self) -> int:
        """Количество задач в очереди"""
        return self._queue.qsize()
    
    @property
    def is_empty(self) -> bool:
        """Очередь пуста?"""
        return self._queue.empty()
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику очереди"""
        return {
            **self._stats,
            'pending': self.pending_count,
            'tasks_tracked': len(self._tasks),
        }
    
    async def clear(self):
        """Очищает очередь (отменяет все задачи)"""
        async with self._lock:
            cancelled = 0
            while not self._queue.empty():
                try:
                    task = self._queue.get_nowait()
                    task.status = TaskStatus.CANCELLED
                    self._stats['total_cancelled'] += 1
                    cancelled += 1
                except asyncio.QueueEmpty:
                    break
            
            if cancelled:
                logger.info(f"🗑️ Очередь очищена, отменено {cancelled} задач")
    
    async def shutdown(self):
        """Завершает работу очереди"""
        self._shutdown = True
        await self.clear()
        logger.info("📋 ParsingQueue завершена")
    
    @property
    def is_shutdown(self) -> bool:
        return self._shutdown


# Глобальный экземпляр очереди
_parsing_queue: Optional[ParsingQueue] = None


def get_parsing_queue() -> ParsingQueue:
    """Возвращает глобальный экземпляр очереди"""
    global _parsing_queue
    if _parsing_queue is None:
        _parsing_queue = ParsingQueue()
    return _parsing_queue


async def shutdown_parsing_queue():
    """Завершает глобальную очередь"""
    global _parsing_queue
    if _parsing_queue is not None:
        await _parsing_queue.shutdown()
        _parsing_queue = None
