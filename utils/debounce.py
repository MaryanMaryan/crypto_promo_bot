# utils/debounce.py
"""
Debounce декоратор и middleware для защиты от спама кнопок в Telegram боте.

Использование:

1. РЕКОМЕНДУЕМЫЙ СПОСОБ — Middleware (автоматически для всех callbacks):
    
    from utils.debounce import DebounceMiddleware
    
    # В main.py при настройке dispatcher:
    dp.callback_query.middleware(DebounceMiddleware())

2. Точечно через декоратор:
    
    from utils.debounce import debounce_callback
    
    @router.callback_query(F.data == "some_action")
    @debounce_callback(seconds=0.5)
    async def handle_some_action(callback: CallbackQuery):
        ...
"""

import asyncio
import time
import logging
from functools import wraps
from typing import Callable, Optional, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import config

logger = logging.getLogger(__name__)

# Хранилище последних вызовов по пользователю
# Формат: {user_id: last_call_timestamp}
_user_last_calls: dict[int, float] = {}

# Хранилище для callback_data + user_id (более точный debounce)
# Формат: {(user_id, callback_data): last_call_timestamp}
_callback_last_calls: dict[tuple[int, str], float] = {}

# Периодическая очистка старых записей (каждые 5 минут)
_cleanup_interval = 300  # 5 минут
_last_cleanup = time.time()


def _cleanup_old_entries():
    """Очистка старых записей из кэша (старше 5 минут)."""
    global _last_cleanup, _user_last_calls, _callback_last_calls
    
    now = time.time()
    if now - _last_cleanup < _cleanup_interval:
        return
    
    _last_cleanup = now
    cutoff = now - _cleanup_interval
    
    # Очищаем user_last_calls
    old_count = len(_user_last_calls)
    _user_last_calls = {k: v for k, v in _user_last_calls.items() if v > cutoff}
    
    # Очищаем callback_last_calls
    _callback_last_calls = {k: v for k, v in _callback_last_calls.items() if v > cutoff}
    
    cleaned = old_count - len(_user_last_calls)
    if cleaned > 0:
        logger.debug(f"🧹 Debounce: очищено {cleaned} устаревших записей")


class DebounceMiddleware(BaseMiddleware):
    """
    Middleware для автоматического debounce всех callback handlers.
    
    Использование:
        dp.callback_query.middleware(DebounceMiddleware())
        
    Или с кастомными настройками:
        dp.callback_query.middleware(DebounceMiddleware(seconds=1.0, per_button=False))
    """
    
    def __init__(self, seconds: Optional[float] = None, per_button: bool = True):
        """
        Args:
            seconds: Интервал блокировки в секундах. По умолчанию из config.DEBOUNCE_SECONDS
            per_button: Если True — debounce для каждой кнопки отдельно.
                        Если False — debounce для всех кнопок пользователя.
        """
        super().__init__()
        self.debounce_seconds = seconds if seconds is not None else config.DEBOUNCE_SECONDS
        self.per_button = per_button
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        _cleanup_old_entries()
        
        # Работаем только с CallbackQuery
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        
        callback: CallbackQuery = event
        user_id = callback.from_user.id if callback.from_user else None
        
        if user_id is None:
            return await handler(event, data)
        
        now = time.time()
        
        if self.per_button:
            # Debounce для конкретной кнопки
            callback_data = callback.data or ""
            key = (user_id, callback_data)
            last_call = _callback_last_calls.get(key, 0)
            
            if now - last_call < self.debounce_seconds:
                # Слишком быстрый повторный вызов — игнорируем
                logger.debug(f"⏳ Debounce: игнорируем callback '{callback_data}' от user {user_id}")
                # Отвечаем на callback чтобы убрать "часики"
                try:
                    await callback.answer()
                except Exception:
                    pass
                return None
            
            _callback_last_calls[key] = now
        else:
            # Debounce для всех кнопок пользователя
            last_call = _user_last_calls.get(user_id, 0)
            
            if now - last_call < self.debounce_seconds:
                logger.debug(f"⏳ Debounce: игнорируем callback от user {user_id}")
                try:
                    await callback.answer()
                except Exception:
                    pass
                return None
            
            _user_last_calls[user_id] = now
        
        return await handler(event, data)


def debounce(seconds: Optional[float] = None) -> Callable:
    """
    Debounce декоратор для любых async handlers.
    Блокирует повторные вызовы от одного пользователя в течение указанного времени.
    
    Args:
        seconds: Интервал блокировки в секундах. По умолчанию из config.DEBOUNCE_SECONDS
    
    Пример:
        @debounce(seconds=1.0)
        async def handle_something(message: Message):
            ...
    """
    debounce_seconds = seconds if seconds is not None else config.DEBOUNCE_SECONDS
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            _cleanup_old_entries()
            
            # Ищем user_id в аргументах
            user_id = None
            for arg in args:
                if hasattr(arg, 'from_user') and arg.from_user:
                    user_id = arg.from_user.id
                    break
            
            if user_id is None:
                # Не смогли определить пользователя — выполняем без debounce
                return await func(*args, **kwargs)
            
            now = time.time()
            last_call = _user_last_calls.get(user_id, 0)
            
            if now - last_call < debounce_seconds:
                # Слишком быстрый повторный вызов — игнорируем
                logger.debug(f"⏳ Debounce: игнорируем вызов от user {user_id} (слишком быстро)")
                return None
            
            # Обновляем время последнего вызова
            _user_last_calls[user_id] = now
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def debounce_callback(seconds: Optional[float] = None, per_button: bool = True) -> Callable:
    """
    Debounce декоратор специально для callback handlers.
    
    Args:
        seconds: Интервал блокировки в секундах. По умолчанию из config.DEBOUNCE_SECONDS
        per_button: Если True — debounce для каждой кнопки отдельно.
                    Если False — debounce для всех кнопок пользователя.
    
    Пример:
        @router.callback_query(F.data == "check_all")
        @debounce_callback(seconds=0.5)
        async def handle_check_all(callback: CallbackQuery):
            ...
    """
    debounce_seconds = seconds if seconds is not None else config.DEBOUNCE_SECONDS
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(callback: CallbackQuery, *args, **kwargs):
            _cleanup_old_entries()
            
            user_id = callback.from_user.id if callback.from_user else None
            
            if user_id is None:
                return await func(callback, *args, **kwargs)
            
            now = time.time()
            
            if per_button:
                # Debounce для конкретной кнопки
                callback_data = callback.data or ""
                key = (user_id, callback_data)
                last_call = _callback_last_calls.get(key, 0)
                
                if now - last_call < debounce_seconds:
                    # Слишком быстрый повторный вызов той же кнопки
                    logger.debug(f"⏳ Debounce: игнорируем callback '{callback_data}' от user {user_id}")
                    # Отвечаем на callback чтобы убрать "часики" в Telegram
                    try:
                        await callback.answer()
                    except Exception:
                        pass
                    return None
                
                _callback_last_calls[key] = now
            else:
                # Debounce для всех кнопок пользователя
                last_call = _user_last_calls.get(user_id, 0)
                
                if now - last_call < debounce_seconds:
                    logger.debug(f"⏳ Debounce: игнорируем callback от user {user_id}")
                    try:
                        await callback.answer()
                    except Exception:
                        pass
                    return None
                
                _user_last_calls[user_id] = now
            
            return await func(callback, *args, **kwargs)
        
        return wrapper
    return decorator


def get_debounce_stats() -> dict:
    """Получить статистику debounce (для мониторинга)."""
    return {
        "user_entries": len(_user_last_calls),
        "callback_entries": len(_callback_last_calls),
        "debounce_seconds": config.DEBOUNCE_SECONDS,
    }
