# utils/executor.py
"""
Глобальный ThreadPoolExecutor для параллельного выполнения блокирующих операций.

Использование:
    from utils.executor import get_executor, run_sync
    
    # Вариант 1: Напрямую через loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(get_executor(), sync_function, arg1, arg2)
    
    # Вариант 2: Удобная обёртка
    result = await run_sync(sync_function, arg1, arg2)
"""

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

import config

logger = logging.getLogger(__name__)

# Глобальный executor (создаётся лениво)
_executor: ThreadPoolExecutor | None = None

T = TypeVar('T')


def get_executor() -> ThreadPoolExecutor:
    """
    Получить глобальный ThreadPoolExecutor.
    Создаётся при первом вызове, переиспользуется далее.
    """
    global _executor
    
    if _executor is None:
        max_workers = config.EXECUTOR_MAX_WORKERS
        _executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="parsing_worker"
        )
        logger.info(f"🔧 Создан глобальный ThreadPoolExecutor с {max_workers} потоками")
        
        # Автоматически закрываем при завершении программы
        atexit.register(_shutdown_executor)
    
    return _executor


def _shutdown_executor():
    """Корректное завершение executor при выходе из программы."""
    global _executor
    
    if _executor is not None:
        logger.info("🛑 Завершение ThreadPoolExecutor...")
        _executor.shutdown(wait=True, cancel_futures=False)
        _executor = None
        logger.info("✅ ThreadPoolExecutor завершён")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Удобная обёртка для запуска синхронной функции в executor.
    
    Пример:
        result = await run_sync(parser.parse, url, timeout=30)
    """
    loop = asyncio.get_event_loop()
    
    # Если есть kwargs — оборачиваем в lambda
    if kwargs:
        return await loop.run_in_executor(
            get_executor(),
            lambda: func(*args, **kwargs)
        )
    else:
        return await loop.run_in_executor(
            get_executor(),
            func,
            *args
        )


def get_executor_stats() -> dict:
    """Получить статистику executor (для мониторинга)."""
    global _executor
    
    if _executor is None:
        return {"status": "not_initialized"}
    
    return {
        "status": "running",
        "max_workers": config.EXECUTOR_MAX_WORKERS,
        # ThreadPoolExecutor не предоставляет прямой доступ к очереди,
        # но можно добавить кастомную статистику позже
    }
