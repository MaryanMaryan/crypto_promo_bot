"""
Модуль для отображения loading индикаторов в UI

Предоставляет:
- Декораторы для автоматического отображения загрузки
- Менеджеры контекста для loading состояний
- Анимированные сообщения о статусе

Использование:
    from utils.loading_indicator import with_loading, LoadingContext
    
    # Декоратор
    @with_loading("⏳ Загрузка данных...")
    async def my_handler(callback: CallbackQuery):
        ...
    
    # Контекстный менеджер
    async with LoadingContext(callback, "🔄 Обработка..."):
        await long_operation()
"""

import asyncio
import logging
import functools
from typing import Optional, Callable, Any, Union
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)


class LoadingContext:
    """
    Контекстный менеджер для отображения индикатора загрузки
    
    Автоматически показывает сообщение о загрузке при входе
    и удаляет/обновляет его при выходе
    
    Usage:
        async with LoadingContext(callback, "⏳ Загрузка...") as loading:
            result = await heavy_operation()
            loading.update("📊 Обработка результатов...")
            await process(result)
    """
    
    def __init__(
        self,
        source: Union[Message, CallbackQuery],
        loading_text: str = "⏳ Загрузка...",
        success_text: Optional[str] = None,
        error_text: str = "❌ Произошла ошибка",
        delete_on_complete: bool = True,
        edit_original: bool = False
    ):
        """
        Args:
            source: Message или CallbackQuery для отображения загрузки
            loading_text: Текст при загрузке
            success_text: Текст при успешном завершении (None = удалить сообщение)
            error_text: Текст при ошибке
            delete_on_complete: Удалять сообщение при успешном завершении
            edit_original: Редактировать оригинальное сообщение вместо создания нового
        """
        self.source = source
        self.loading_text = loading_text
        self.success_text = success_text
        self.error_text = error_text
        self.delete_on_complete = delete_on_complete
        self.edit_original = edit_original
        
        self._loading_message: Optional[Message] = None
        self._original_message: Optional[Message] = None
        self._answered: bool = False
    
    async def __aenter__(self) -> 'LoadingContext':
        """Показать индикатор загрузки"""
        try:
            if isinstance(self.source, CallbackQuery):
                # Сначала отвечаем на callback чтобы убрать "часики"
                if not self._answered:
                    try:
                        await self.source.answer()
                        self._answered = True
                    except:
                        pass
                
                self._original_message = self.source.message
                
                if self.edit_original:
                    # Редактируем оригинальное сообщение
                    try:
                        await self._original_message.edit_text(
                            self.loading_text,
                            parse_mode="HTML"
                        )
                        self._loading_message = self._original_message
                    except:
                        # Fallback - отправляем новое
                        self._loading_message = await self._original_message.answer(
                            self.loading_text,
                            parse_mode="HTML"
                        )
                else:
                    # Отправляем новое сообщение
                    self._loading_message = await self._original_message.answer(
                        self.loading_text,
                        parse_mode="HTML"
                    )
            else:
                # Message - отправляем ответ
                self._loading_message = await self.source.answer(
                    self.loading_text,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"Не удалось показать loading: {e}")
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Убрать индикатор загрузки"""
        try:
            if exc_type is not None:
                # Произошла ошибка
                if self._loading_message and not self.edit_original:
                    try:
                        await self._loading_message.edit_text(
                            self.error_text,
                            parse_mode="HTML"
                        )
                    except:
                        pass
            else:
                # Успешное завершение
                if self._loading_message:
                    if self.delete_on_complete and not self.edit_original:
                        try:
                            await self._loading_message.delete()
                        except:
                            pass
                    elif self.success_text:
                        try:
                            await self._loading_message.edit_text(
                                self.success_text,
                                parse_mode="HTML"
                            )
                        except:
                            pass
        except Exception as e:
            logger.warning(f"Не удалось обновить loading message: {e}")
        
        return False  # Не подавляем исключения
    
    async def update(self, text: str):
        """Обновить текст загрузки"""
        if self._loading_message:
            try:
                await self._loading_message.edit_text(text, parse_mode="HTML")
            except:
                pass
    
    async def delete(self):
        """Удалить сообщение загрузки"""
        if self._loading_message:
            try:
                await self._loading_message.delete()
                self._loading_message = None
            except:
                pass


def with_loading(
    loading_text: str = "⏳ Загрузка...",
    success_text: Optional[str] = None,
    error_text: str = "❌ Произошла ошибка",
    delete_on_complete: bool = True,
    edit_original: bool = False,
    answer_callback: bool = True
):
    """
    Декоратор для автоматического отображения loading индикатора
    
    Args:
        loading_text: Текст загрузки
        success_text: Текст успеха (None = удалить)
        error_text: Текст ошибки
        delete_on_complete: Удалять сообщение загрузки
        edit_original: Редактировать оригинальное сообщение
        answer_callback: Автоматически отвечать на callback
    
    Usage:
        @with_loading("⏳ Загрузка данных биржи...")
        async def handler(callback: CallbackQuery):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Ищем CallbackQuery или Message в аргументах
            source = None
            for arg in args:
                if isinstance(arg, (CallbackQuery, Message)):
                    source = arg
                    break
            
            if source is None:
                # Не нашли - вызываем без loading
                return await func(*args, **kwargs)
            
            # Отвечаем на callback сразу
            if answer_callback and isinstance(source, CallbackQuery):
                try:
                    await source.answer()
                except:
                    pass
            
            async with LoadingContext(
                source=source,
                loading_text=loading_text,
                success_text=success_text,
                error_text=error_text,
                delete_on_complete=delete_on_complete,
                edit_original=edit_original
            ):
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


class LoadingAnimation:
    """
    Анимированный индикатор загрузки с обновлением
    
    Показывает анимацию точек или spinner
    
    Usage:
        async with LoadingAnimation(message, "Загрузка") as anim:
            await long_task()
    """
    
    FRAMES = ["⏳", "⌛", "🔄", "⚙️"]
    DOTS = [".", "..", "...", ""]
    
    def __init__(
        self,
        source: Union[Message, CallbackQuery],
        base_text: str = "Загрузка",
        interval: float = 1.0,
        use_dots: bool = True
    ):
        self.source = source
        self.base_text = base_text
        self.interval = interval
        self.use_dots = use_dots
        
        self._message: Optional[Message] = None
        self._task: Optional[asyncio.Task] = None
        self._frame = 0
        self._running = False
    
    async def __aenter__(self) -> 'LoadingAnimation':
        # Получаем сообщение
        if isinstance(self.source, CallbackQuery):
            try:
                await self.source.answer()
            except:
                pass
            self._message = await self.source.message.answer(
                f"⏳ {self.base_text}...",
                parse_mode="HTML"
            )
        else:
            self._message = await self.source.answer(
                f"⏳ {self.base_text}...",
                parse_mode="HTML"
            )
        
        # Запускаем анимацию
        self._running = True
        self._task = asyncio.create_task(self._animate())
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._message:
            try:
                await self._message.delete()
            except:
                pass
        
        return False
    
    async def _animate(self):
        """Анимация в фоне"""
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                
                if not self._running:
                    break
                
                self._frame = (self._frame + 1) % len(self.FRAMES)
                frame = self.FRAMES[self._frame]
                
                if self.use_dots:
                    dots = self.DOTS[self._frame % len(self.DOTS)]
                    text = f"{frame} {self.base_text}{dots}"
                else:
                    text = f"{frame} {self.base_text}"
                
                if self._message:
                    await self._message.edit_text(text, parse_mode="HTML")
            
            except asyncio.CancelledError:
                break
            except:
                pass
    
    async def update_text(self, text: str):
        """Обновить базовый текст"""
        self.base_text = text


# Предопределённые тексты загрузки
class LoadingTexts:
    """Константы для текстов загрузки"""
    
    LOADING = "⏳ Загрузка..."
    LOADING_DATA = "⏳ Загрузка данных..."
    LOADING_EXCHANGE = "⏳ Загрузка данных биржи..."
    PARSING = "🔄 Парсинг..."
    PROCESSING = "⚙️ Обработка..."
    SAVING = "💾 Сохранение..."
    CHECKING = "🔍 Проверка..."
    
    # Биржи
    LOADING_STAKINGS = "📊 Загрузка стейкингов..."
    LOADING_PROMOS = "🎁 Загрузка промоакций..."
    
    # Успех
    SUCCESS = "✅ Готово!"
    DATA_LOADED = "✅ Данные загружены"
    
    # Ошибки
    ERROR = "❌ Произошла ошибка"
    ERROR_LOADING = "❌ Ошибка загрузки"
    ERROR_TIMEOUT = "⏰ Время ожидания истекло"


async def show_temporary_message(
    source: Union[Message, CallbackQuery],
    text: str,
    duration: float = 3.0
):
    """
    Показать временное сообщение которое исчезнет через N секунд
    
    Args:
        source: Message или CallbackQuery
        text: Текст сообщения
        duration: Время показа в секундах
    """
    try:
        if isinstance(source, CallbackQuery):
            # Используем callback.answer с show_alert для важных сообщений
            if duration > 5:
                await source.answer(text, show_alert=True)
            else:
                msg = await source.message.answer(text, parse_mode="HTML")
                await asyncio.sleep(duration)
                try:
                    await msg.delete()
                except:
                    pass
        else:
            msg = await source.answer(text, parse_mode="HTML")
            await asyncio.sleep(duration)
            try:
                await msg.delete()
            except:
                pass
    except Exception as e:
        logger.warning(f"Не удалось показать временное сообщение: {e}")
