# utils/admin_middleware.py
"""
Middleware для проверки, что пользователь является администратором бота.

Только пользователи с chat_id, указанным в ADMIN_CHAT_ID (в .env),
могут использовать бота.

Использование:
    from utils.admin_middleware import AdminMiddleware
    
    # В main.py при настройке dispatcher:
    dp.message.middleware(AdminMiddleware())
    dp.callback_query.middleware(AdminMiddleware())
"""

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

import config

logger = logging.getLogger(__name__)


class AdminMiddleware(BaseMiddleware):
    """
    Middleware для проверки доступа администратора.
    
    Отклоняет все сообщения и callback от пользователей,
    которые не являются администратором (ADMIN_CHAT_ID).
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        # Определяем user_id в зависимости от типа события
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
        
        # Если не удалось определить пользователя — пропускаем (служебные сообщения)
        if user_id is None:
            return await handler(event, data)
        
        # Проверяем, является ли пользователь администратором
        # Поддержка нескольких админов через ADMIN_IDS
        admin_ids = getattr(config, 'ADMIN_IDS', [config.ADMIN_CHAT_ID])
        if user_id not in admin_ids:
            # Тихо игнорируем — не отвечаем, чтобы не давать спамерам обратную связь
            # и не создавать нагрузку на бота
            logger.debug(
                f"⛔ Игнорируем запрос от user_id={user_id}"
            )
            
            # Для callback нужно ответить, иначе будет бесконечная загрузка
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            
            # Не вызываем handler — запрос отклонён
            return None
        
        # Пользователь — администратор, пропускаем запрос
        return await handler(event, data)
