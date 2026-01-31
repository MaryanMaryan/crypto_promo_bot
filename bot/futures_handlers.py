"""
bot/futures_handlers.py
Обработчики для поиска фьючерсов по токену.

Функционал:
- Поиск фьючерсов по названию токена (просто отправить "BTC" в чат)
- Команда /futures или /f для явного поиска
- Кнопки "Подробнее" и "Обновить"
"""

import re
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from utils.futures_fetcher import (
    get_futures_fetcher, 
    format_futures_compact, 
    format_futures_detailed,
    FuturesSearchResult
)
from utils.loading_indicator import LoadingContext

logger = logging.getLogger(__name__)

# Роутер для фьючерсов
futures_router = Router()

# Паттерн для определения токена (1-10 букв/цифр)
TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9]{1,10}$')

# Кэш последних результатов для быстрого переключения вида
_results_cache: dict = {}  # {user_id: {symbol: FuturesSearchResult}}


def get_futures_keyboard(symbol: str, is_detailed: bool = False) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру для результатов поиска фьючерсов"""
    builder = InlineKeyboardBuilder()
    
    if is_detailed:
        builder.button(text="⬅️ Компактный вид", callback_data=f"futures:compact:{symbol}")
    else:
        builder.button(text="📋 Подробнее", callback_data=f"futures:detailed:{symbol}")
    
    builder.button(text="🔄 Обновить", callback_data=f"futures:refresh:{symbol}")
    builder.adjust(2)
    
    return builder.as_markup()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id in ADMIN_IDS


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@futures_router.message(Command("futures", "f"))
async def cmd_futures(message: Message):
    """Обработчик команды /futures или /f"""
    if not is_admin(message.from_user.id):
        return
    
    # Получаем символ из команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "🔍 <b>Поиск фьючерсов</b>\n\n"
            "Использование: <code>/futures BTC</code> или <code>/f ETH</code>\n\n"
            "Или просто отправьте название токена (например: <code>SOL</code>)",
            parse_mode="HTML"
        )
        return
    
    symbol = args[1].upper().strip()
    await search_and_show_futures(message, symbol)


@futures_router.message(F.text)
async def handle_text_message(message: Message):
    """
    Обработчик текстовых сообщений для поиска фьючерсов.
    
    Срабатывает когда:
    1. Пользователь - админ
    2. Сообщение похоже на токен (1-10 букв/цифр)
    
    ВАЖНО: Этот обработчик должен быть зарегистрирован ПОСЛЕДНИМ,
    чтобы не перехватывать другие команды.
    """
    # Проверяем админа
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    # Проверяем, похоже ли на токен
    if not TOKEN_PATTERN.match(text):
        return
    
    # Игнорируем слишком короткие (1 символ) и слова не похожие на токен
    if len(text) < 2:
        return
    
    # Игнорируем некоторые частые слова которые не токены
    ignore_words = {'ok', 'hi', 'no', 'yes', 'да', 'нет', 'ок', 'on', 'off', 'test', 'help'}
    if text.lower() in ignore_words:
        return
    
    symbol = text.upper()
    await search_and_show_futures(message, symbol)


async def search_and_show_futures(message: Message, symbol: str):
    """Выполняет поиск и показывает результаты"""
    user_id = message.from_user.id
    
    async with LoadingContext(message, "🔍 Поиск фьючерсов..."):
        fetcher = get_futures_fetcher()
        result = await fetcher.search(symbol, use_cache=False)
    
    # Сохраняем в кэш для быстрого переключения вида
    if user_id not in _results_cache:
        _results_cache[user_id] = {}
    _results_cache[user_id][symbol] = result
    
    # Проверяем, нашли ли что-то
    if result.available_count == 0:
        await message.answer(
            f"❌ <b>Фьючерс {symbol} не найден</b>\n\n"
            f"Проверено {result.total_count} бирж — ни на одной нет фьючерса для этого токена.\n\n"
            f"💡 Возможно:\n"
            f"• Токен ещё не листингован\n"
            f"• Неправильное название\n"
            f"• Фьючерс был делистингован",
            parse_mode="HTML"
        )
        return
    
    # Форматируем и отправляем
    text = format_futures_compact(result)
    keyboard = get_futures_keyboard(symbol, is_detailed=False)
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


# ==================== CALLBACK ОБРАБОТЧИКИ ====================

@futures_router.callback_query(F.data.startswith("futures:"))
async def handle_futures_callback(callback: CallbackQuery):
    """Обработчик callback-ов для фьючерсов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для администраторов", show_alert=True)
        return
    
    # Парсим callback data: futures:action:symbol
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Неверный формат", show_alert=True)
        return
    
    _, action, symbol = parts
    user_id = callback.from_user.id
    
    if action == "detailed":
        await show_detailed_view(callback, symbol, user_id)
    elif action == "compact":
        await show_compact_view(callback, symbol, user_id)
    elif action == "refresh":
        await refresh_futures(callback, symbol, user_id)
    else:
        await callback.answer("❌ Неизвестное действие", show_alert=True)


async def show_detailed_view(callback: CallbackQuery, symbol: str, user_id: int):
    """Показывает детальный вид"""
    await callback.answer()
    
    # Пробуем взять из кэша
    result = _results_cache.get(user_id, {}).get(symbol)
    
    if not result:
        # Если нет в кэше - запрашиваем заново
        fetcher = get_futures_fetcher()
        result = await fetcher.search(symbol)
        if user_id not in _results_cache:
            _results_cache[user_id] = {}
        _results_cache[user_id][symbol] = result
    
    text = format_futures_detailed(result)
    keyboard = get_futures_keyboard(symbol, is_detailed=True)
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"Не удалось отредактировать сообщение: {e}")


async def show_compact_view(callback: CallbackQuery, symbol: str, user_id: int):
    """Показывает компактный вид"""
    await callback.answer()
    
    # Пробуем взять из кэша
    result = _results_cache.get(user_id, {}).get(symbol)
    
    if not result:
        fetcher = get_futures_fetcher()
        result = await fetcher.search(symbol)
        if user_id not in _results_cache:
            _results_cache[user_id] = {}
        _results_cache[user_id][symbol] = result
    
    text = format_futures_compact(result)
    keyboard = get_futures_keyboard(symbol, is_detailed=False)
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"Не удалось отредактировать сообщение: {e}")


async def refresh_futures(callback: CallbackQuery, symbol: str, user_id: int):
    """Обновляет данные о фьючерсах"""
    await callback.answer("🔄 Обновляю...")
    
    fetcher = get_futures_fetcher()
    result = await fetcher.search(symbol, use_cache=False)
    
    # Обновляем кэш
    if user_id not in _results_cache:
        _results_cache[user_id] = {}
    _results_cache[user_id][symbol] = result
    
    # Определяем текущий вид по кнопкам
    is_detailed = False
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if "Компактный" in (btn.text or ""):
                    is_detailed = True
                    break
    
    if is_detailed:
        text = format_futures_detailed(result)
    else:
        text = format_futures_compact(result)
    
    keyboard = get_futures_keyboard(symbol, is_detailed=is_detailed)
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"Не удалось отредактировать сообщение: {e}")


# ==================== РЕГИСТРАЦИЯ РОУТЕРА ====================

def setup_futures_handlers(parent_router: Router):
    """
    Регистрирует роутер фьючерсов в родительском роутере.
    
    ВАЖНО: Вызывать ПОСЛЕ регистрации всех остальных обработчиков,
    чтобы handle_text_message не перехватывал другие команды.
    """
    parent_router.include_router(futures_router)
    logger.info("✅ Обработчики фьючерсов зарегистрированы")
