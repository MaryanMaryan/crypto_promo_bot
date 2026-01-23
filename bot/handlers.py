from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest

# Константы для навигации
NAV_MANAGEMENT = "NAV_MANAGEMENT"
NAV_DELETE = "NAV_DELETE"
NAV_INTERVAL = "NAV_INTERVAL"
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from data.database import (
    get_db_session, atomic_operation,
    # Новые async функции для отзывчивого UI
    get_links_async, get_link_by_id_async, get_active_links_count_async,
    get_links_by_category_async, update_link_async, delete_link_async, create_link_async,
    get_favorite_links_async
)
from data.models import ApiLink
from bot.parser_service import ParserService
from bot.notification_service import NotificationService
from bot.bot_manager import bot_manager
import logging
import asyncio
from urllib.parse import urlparse
from datetime import datetime

# Глобальный executor для параллельного парсинга
from utils.executor import get_executor

# ИМПОРТЫ ДЛЯ НОВЫХ СИСТЕМ
from utils.proxy_manager import get_proxy_manager
from utils.user_agent_manager import get_user_agent_manager
from utils.statistics_manager import get_statistics_manager
from bot.keyboards import get_airdrop_management_keyboard, get_current_promos_keyboard
from utils.rotation_manager import get_rotation_manager
from utils.url_template_builder import URLTemplateAnalyzer, get_url_builder

# ИМПОРТЫ ДЛЯ ОТЗЫВЧИВОГО UI (Фаза 4)
from utils.cache import get_cache_manager, invalidate_links_cache
from utils.loading_indicator import LoadingContext, with_loading, LoadingTexts, show_temporary_message


navigation_stack = {}
# Глобальный словарь для новых систем выбора
user_selections = {}
# Глобальный словарь для хранения состояния просмотра стейкингов
current_stakings_state = {}
# Глобальный словарь для хранения состояния просмотра промоакций
current_promos_state = {}

router = Router()
logger = logging.getLogger(__name__)
parser_service = ParserService()

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ CALLBACK
# =============================================================================

async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """
    Безопасный вызов callback.answer() с обработкой timeout.
    Игнорирует ошибки TelegramBadRequest (query too old).
    """
    try:
        from aiogram.exceptions import TelegramBadRequest
        if text:
            await callback.answer(text, show_alert=show_alert)
        else:
            await callback.answer()
    except TelegramBadRequest as e:
        # Игнорируем ошибки "query too old"
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            logger.debug(f"Callback timeout игнорируется: {e}")
        else:
            raise

def push_navigation(user_id: int, context, data=None):
    """Добавить новый контекст в стек навигации пользователя"""
    if user_id not in navigation_stack:
        navigation_stack[user_id] = []
    navigation_stack[user_id].append({"context": context, "data": data or {}})

def pop_navigation(user_id: int):
    """Удалить последний контекст из стека"""
    if user_id in navigation_stack and navigation_stack[user_id]:
        return navigation_stack[user_id].pop()
    return None

def get_current_navigation(user_id: int):
    """Получить текущий контекст навигации"""
    if user_id in navigation_stack and navigation_stack[user_id]:
        return navigation_stack[user_id][-1]
    return None

def clear_navigation(user_id: int):
    """Очистить всю историю навигации пользователя"""
    if user_id in navigation_stack:
        navigation_stack[user_id] = []

# СУЩЕСТВУЮЩИЕ СОСТОЯНИЯ FSM
class AddLinkStates(StatesGroup):
    waiting_for_category = State()  # НОВОЕ: Выбор категории
    waiting_for_name = State()  # Шаг 1: Название биржи
    waiting_for_parsing_type = State()  # Шаг 2: Выбор типа парсинга
    waiting_for_api_url = State()  # Шаг 3: API ссылка (опционально, зависит от типа)
    waiting_for_html_url = State()  # Шаг 4: HTML ссылка (опционально, зависит от типа)
    waiting_for_page_url = State()  # НОВОЕ: Ссылка на страницу акций
    waiting_for_example_url = State()  # Шаг 5: Пример ссылки на промоакцию (опционально)
    waiting_for_interval = State()  # Шаг 6: Интервал проверки
    # Для стейкинга:
    waiting_for_min_apr = State()  # НОВОЕ: Минимальный APR
    waiting_for_statuses = State()  # НОВОЕ: Выбор статусов
    # Для Telegram:
    waiting_for_telegram_channel = State()  # НОВОЕ: Ввод канала Telegram
    waiting_for_telegram_keywords = State()  # НОВОЕ: Ввод ключевых слов Telegram
    waiting_for_telegram_account = State()  # НОВОЕ: Выбор Telegram аккаунта для ссылки
    # Для анонсов:
    waiting_for_announcement_url = State()  # НОВОЕ: Ввод URL для анонсов
    waiting_for_announcement_page_type = State()  # НОВОЕ: Тип страницы (HTML/Browser)
    waiting_for_announcement_strategy = State()  # НОВОЕ: Выбор стратегии парсинга анонсов
    waiting_for_announcement_keywords = State()  # НОВОЕ: Ввод ключевых слов для анонсов
    waiting_for_announcement_regex = State()  # НОВОЕ: Ввод regex для анонсов
    waiting_for_announcement_selector = State()  # НОВОЕ: Ввод CSS селектора для анонсов
    # Специальный парсер:
    waiting_for_special_parser = State()  # НОВОЕ: Выбор специального парсера
    # Выбор парсера (новый шаг):
    waiting_for_parser_selection = State()  # НОВОЕ: Выбор парсера для обработки

class IntervalStates(StatesGroup):
    waiting_for_interval = State()

class RenameLinkStates(StatesGroup):
    waiting_for_new_name = State()

class ConfigureParsingStates(StatesGroup):
    waiting_for_link_selection = State()  # Выбор ссылки для настройки
    waiting_for_parsing_type_edit = State()  # Изменение типа парсинга
    waiting_for_api_url_edit = State()  # Изменение API URL
    waiting_for_html_url_edit = State()  # Изменение HTML URL
    waiting_for_telegram_channel_edit = State()  # Изменение Telegram канала
    waiting_for_telegram_keywords_edit = State()  # Изменение Telegram ключевых слов
    waiting_for_category_edit = State()  # Изменение категории ссылки
    # Для редактирования анонсов:
    waiting_for_announcement_strategy_edit = State()  # Изменение стратегии анонсов
    waiting_for_announcement_keywords_edit = State()  # Изменение ключевых слов анонсов
    waiting_for_announcement_regex_edit = State()  # Изменение regex анонсов
    waiting_for_announcement_css_edit = State()  # Изменение CSS селектора анонсов

# НОВЫЕ FSM СОСТОЯНИЯ
class ProxyManagementStates(StatesGroup):
    waiting_for_proxy_address = State()
    waiting_for_proxy_protocol = State()

class UserAgentStates(StatesGroup):
    waiting_for_user_agent = State()

class RotationSettingsStates(StatesGroup):
    waiting_for_rotation_interval = State()
    waiting_for_stats_retention = State()
    waiting_for_archive_inactive = State()

# СТАРЫЕ СОСТОЯНИЯ TelegramAPIStates УДАЛЕНЫ - используется TelegramAccountStates из bot/states.py

# РАСШИРЕННОЕ ГЛАВНОЕ МЕНЮ (INLINE VERSION)
def get_main_menu_inline():
    """Главное меню с inline-кнопками"""
    builder = InlineKeyboardBuilder()
    
    # Ряд 1: Избранные + ТОП Активности
    builder.add(InlineKeyboardButton(text="⭐ Избранные", callback_data="main_favorites"))
    builder.add(InlineKeyboardButton(text="🚀 ТОП Активности", callback_data="top_activity_menu"))
    
    # Ряд 2: Добавить + Проверить всё
    builder.add(InlineKeyboardButton(text="➕ Добавить", callback_data="main_add_link"))
    builder.add(InlineKeyboardButton(text="🔄 Проверить всё", callback_data="main_check_all"))
    
    # Ряд 3: Управление ссылками + Список ссылок
    builder.add(InlineKeyboardButton(text="⚙️ Управление ссылками", callback_data="main_manage_links"))
    builder.add(InlineKeyboardButton(text="📊 Список ссылок", callback_data="main_list_links"))
    
    # Ряд 4: Обход блокировок (на весь ряд)
    builder.add(InlineKeyboardButton(text="🛡️ Обход блокировок", callback_data="main_bypass"))

    # Раскладка: 2, 2, 2, 1
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_main_reply_keyboard():
    """Минимальная клавиатура внизу экрана для быстрого доступа"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🏠 Меню"))
    builder.add(KeyboardButton(text="➕ Добавить ссылку"))
    builder.add(KeyboardButton(text="🔄 Проверить всё"))
    builder.adjust(2, 1)  # Первый ряд: 2 кнопки (Меню, Добавить), второй ряд: 1 кнопка (Проверить всё)
    return builder.as_markup(resize_keyboard=True)


# Совместимость со старым кодом
def get_main_menu():
    return get_main_reply_keyboard()


# =============================================================================
# УНИФИЦИРОВАННЫЕ КЛАВИАТУРЫ УПРАВЛЕНИЯ ССЫЛКАМИ (РЕФАКТОРИНГ)
# =============================================================================

def get_unified_link_management_keyboard(link):
    """
    Унифицированная клавиатура управления ссылкой для всех категорий.
    
    Структура:
    - Текущие промоакции/стейкинги (если применимо)
    - Сменить категорию
    - Настройки (подменю)
    - Остановить/Включить парсинг (динамическая кнопка)
    - Назад
    """
    builder = InlineKeyboardBuilder()
    
    # 1. Кнопка "Текущие промоакции/стейкинги" (зависит от категории)
    category = link.category or 'launches'
    has_promo_parser = link.special_parser and link.special_parser not in ('announcement', 'telegram')
    
    if category == 'staking':
        builder.add(InlineKeyboardButton(
            text="📈 Текущие стейкинги", 
            callback_data="manage_view_current_stakings"
        ))
    elif category in ['airdrop', 'candybomb', 'drops', 'launches', 'launchpool', 'launchpad']:
        builder.add(InlineKeyboardButton(
            text="🎁 Текущие промоакции", 
            callback_data="manage_view_current_promos"
        ))
    elif category == 'announcement' and has_promo_parser:
        # Announcement со special_parser показываем кнопку текущих промо
        builder.add(InlineKeyboardButton(
            text="🎁 Текущие промоакции", 
            callback_data="manage_view_current_promos"
        ))
    
    # 2. Сменить категорию
    builder.add(InlineKeyboardButton(
        text="🔄 Сменить категорию", 
        callback_data=f"edit_category_{link.id}"
    ))
    
    # 3. Настройки (подменю)
    builder.add(InlineKeyboardButton(
        text="⚙️ Настройки", 
        callback_data="manage_settings_submenu"
    ))
    
    # 4. Динамическая кнопка Остановить/Включить
    if link.is_active:
        builder.add(InlineKeyboardButton(
            text="⏸ Остановить парсинг", 
            callback_data="manage_pause"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text="▶️ Включить парсинг", 
            callback_data="manage_resume"
        ))
    
    # 5. Назад
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад", 
        callback_data="back_to_link_list"
    ))
    
    builder.adjust(1)
    return builder.as_markup()


def get_link_settings_submenu_keyboard(link):
    """
    Подменю настроек ссылки.
    
    Структура:
    - Изменить интервал
    - Переименовать
    - Настроить парсинг (ведет в детальные настройки)
    - Telegram аккаунт (только для telegram)
    - Принудительная проверка
    - Удалить ссылку
    - Назад
    """
    builder = InlineKeyboardBuilder()
    
    # Основные настройки
    builder.add(InlineKeyboardButton(
        text="⏰ Изменить интервал", 
        callback_data="manage_interval"
    ))
    builder.add(InlineKeyboardButton(
        text="✏️ Переименовать", 
        callback_data="manage_rename"
    ))
    builder.add(InlineKeyboardButton(
        text="🎯 Настроить парсинг", 
        callback_data="manage_configure_parsing"
    ))
    
    # Специальная кнопка для Telegram ссылок
    if link.parsing_type == 'telegram':
        builder.add(InlineKeyboardButton(
            text="📱 Telegram аккаунт", 
            callback_data="manage_change_tg_account"
        ))
    
    # Действия
    builder.add(InlineKeyboardButton(
        text="🔧 Принудительная проверка", 
        callback_data="manage_force_check"
    ))
    builder.add(InlineKeyboardButton(
        text="🗑️ Удалить ссылку", 
        callback_data="manage_delete"
    ))
    
    # Назад к главному меню ссылки
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад", 
        callback_data=f"manage_link_{link.id}"
    ))
    
    builder.adjust(1)
    return builder.as_markup()


def get_back_to_link_keyboard(link_id: int):
    """
    Клавиатура с кнопкой возврата к управлению ссылкой.
    Используется после выполнения действий (изменение интервала, категории и т.д.)
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад к ссылке", 
        callback_data=f"manage_link_{link_id}"
    ))
    return builder.as_markup()


def get_back_to_settings_keyboard(link_id: int):
    """
    Клавиатура с кнопкой возврата к настройкам ссылки.
    Используется после изменения настроек парсинга.
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="⬅️ К настройкам", 
        callback_data="manage_settings_submenu"
    ))
    builder.add(InlineKeyboardButton(
        text="🏠 К ссылке", 
        callback_data=f"manage_link_{link_id}"
    ))
    builder.adjust(1)
    return builder.as_markup()


# LEGACY: Старые функции для обратной совместимости (перенаправляют на унифицированные)
def get_management_keyboard(link=None):
    """Legacy функция - перенаправляет на унифицированную клавиатуру"""
    if link:
        return get_unified_link_management_keyboard(link)
    # Fallback для случаев без link
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⚙️ Настройки", callback_data="manage_settings_submenu"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_link_list"))
    builder.adjust(1)
    return builder.as_markup()

def get_category_management_menu():
    """Подменю выбора категории для управления ссылками"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Все ссылки", callback_data="category_all"))
    builder.add(InlineKeyboardButton(text="🎁 Дропы", callback_data="category_drops"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаучи", callback_data="category_launches"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main_menu"))
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()

def get_staking_management_keyboard(link=None):
    """Legacy функция для staking - перенаправляет на унифицированную клавиатуру"""
    if link:
        return get_unified_link_management_keyboard(link)
    # Fallback без link объекта
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📈 Текущие стейкинги", callback_data="manage_view_current_stakings"))
    builder.add(InlineKeyboardButton(text="🔄 Сменить категорию", callback_data="manage_change_category"))
    builder.add(InlineKeyboardButton(text="⚙️ Настройки", callback_data="manage_settings_submenu"))
    builder.add(InlineKeyboardButton(text="⏸ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_link_list"))
    builder.adjust(1)
    return builder.as_markup()

def get_current_stakings_keyboard(current_page: int, total_pages: int, last_updated: str = None) -> InlineKeyboardMarkup:
    """Клавиатура навигации для текущих стейкингов
    
    Args:
        current_page: Текущая страница
        total_pages: Всего страниц
        last_updated: Время последнего обновления (для отображения)
    """
    builder = InlineKeyboardBuilder()

    # Кнопки навигации
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="stakings_page_prev"))
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data="stakings_page_next"))

    if nav_buttons:
        builder.row(*nav_buttons)

    # Принудительная проверка (запуск парсера)
    builder.row(
        InlineKeyboardButton(text="🔍 Принудительная проверка", callback_data="stakings_force_parse")
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки APR", callback_data="stakings_configure_apr")
    )

    # Настройки уведомлений (НОВАЯ КНОПКА)
    builder.row(
        InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="notification_settings_show")
    )

    # Закрыть
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="manage_cancel"))

    return builder.as_markup()

def get_notification_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек умных уведомлений"""
    builder = InlineKeyboardBuilder()

    # Новые кнопки для launchpool уведомлений
    builder.add(InlineKeyboardButton(
        text="📊 Изменить порог изменения APR",
        callback_data="notification_settings_change_apr_threshold"
    ))
    builder.add(InlineKeyboardButton(
        text="📅 Изменения периода (вкл/выкл)",
        callback_data="notification_toggle_period_changes"
    ))
    builder.add(InlineKeyboardButton(
        text="🎁 Изменения общего пула наград (вкл/выкл)",
        callback_data="notification_toggle_reward_pool_changes"
    ))
    # Внутри обработчика callback 'notification_other_settings' будут показаны остальные настройки:
    # - Изменения APR (вкл/выкл)
    # - Изменения статуса пула (вкл/выкл)
    # - Изменения расчетной доходности (вкл/выкл)
    # - Только выбранные токены (вкл/выкл)
    # - Только новые пулы (вкл/выкл)
    # - и другие специфические опции
    builder.add(InlineKeyboardButton(
        text="⚙️ Другие настройки",
        callback_data="notification_other_settings"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Назад",
        callback_data="manage_view_current_promos"
    ))

    builder.adjust(1)
    return builder.as_markup()

def get_stability_hours_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора времени стабилизации"""
    builder = InlineKeyboardBuilder()

    hours = [1, 2, 3, 4, 6, 8, 12, 24, 48]
    for hour in hours:
        text = f"{hour} час" if hour == 1 else f"{hour} часа" if hour < 5 else f"{hour} часов"
        builder.add(InlineKeyboardButton(
            text=text,
            callback_data=f"set_stability_{hour}"
        ))

    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="notification_settings_show"))
    builder.adjust(3)  # По 3 кнопки в ряд
    return builder.as_markup()

def get_apr_threshold_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора порога изменения APR"""
    builder = InlineKeyboardBuilder()

    thresholds = [1, 2, 3, 5, 10, 15, 20, 50]
    for threshold in thresholds:
        builder.add(InlineKeyboardButton(
            text=f"{threshold}%",
            callback_data=f"set_apr_threshold_{threshold}"
        ))

    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="notification_settings_show"))
    builder.adjust(4)  # По 4 кнопки в ряд
    return builder.as_markup()

def get_other_notification_settings_keyboard(link) -> InlineKeyboardMarkup:
    """Клавиатура других настроек уведомлений"""
    builder = InlineKeyboardBuilder()
    
    notify_apr = getattr(link, 'notify_apr_changes', True)
    notify_fill = getattr(link, 'notify_fill_changes', False)
    notify_new = getattr(link, 'notify_new_stakings', True)
    notify_stable = getattr(link, 'notify_only_stable_flexible', True)
    notify_combined = getattr(link, 'notify_combined_as_fixed', True)
    
    builder.add(InlineKeyboardButton(
        text=f"{'✅' if notify_apr else '❌'} Изменения APR",
        callback_data="notification_toggle_apr_changes"
    ))
    builder.add(InlineKeyboardButton(
        text=f"{'✅' if notify_fill else '❌'} Заполненность пулов",
        callback_data="notification_toggle_fill_changes"
    ))
    builder.add(InlineKeyboardButton(
        text=f"{'✅' if notify_new else '❌'} Новые пулы",
        callback_data="notification_toggle_new_stakings"
    ))
    builder.add(InlineKeyboardButton(
        text=f"{'✅' if notify_stable else '❌'} Только стабильные",
        callback_data="notification_toggle_only_stable"
    ))
    builder.add(InlineKeyboardButton(
        text=f"{'✅' if notify_combined else '❌'} Combined как Fixed",
        callback_data="notification_toggle_combined_as_fixed"
    ))
    builder.add(InlineKeyboardButton(
        text="⏱️ Время стабилизации",
        callback_data="notification_settings_change_stability"
    ))
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="notification_settings_show"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_links_keyboard(links, action_type="delete"):
    builder = InlineKeyboardBuilder()

    # Словарь иконок для типов парсинга
    parsing_icons = {
        'combined': '🔄',
        'api': '📡',
        'html': '🌐',
        'browser': '🌐',
        'telegram': '📱'
    }

    # Словарь иконок для категорий
    category_icons = {
        'launches': '🚀',
        'launchpad': '🚀',
        'launchpool': '🌊',
        'drops': '🎁',
        'airdrop': '🪂',
        'candybomb': '🍬',
        'staking': '💰',
        'announcement': '📢'
    }

    for link in links:
        status_icon = "✅" if link.is_active else "❌"
        
        # Добавляем звезду если в избранном
        favorite_icon = "⭐" if hasattr(link, 'is_favorite') and link.is_favorite else ""

        # Добавляем иконку типа парсинга, если поле существует
        parsing_icon = ""
        if hasattr(link, 'parsing_type'):
            parsing_type = link.parsing_type or 'combined'
            parsing_icon = parsing_icons.get(parsing_type, '🔄') + " "

        # Добавляем иконку категории, если поле существует
        category_icon = ""
        if hasattr(link, 'category'):
            category = link.category or 'launches'
            category_icon = category_icons.get(category, '📁') + " "

        builder.add(InlineKeyboardButton(
            text=f"{status_icon}{favorite_icon} {category_icon}{parsing_icon}{link.name} ({link.check_interval}с)",
            callback_data=f"{action_type}_link_{link.id}"
        ))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(1)
    return builder.as_markup()

def get_interval_presets_keyboard(link_id):
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]
    for text, seconds in presets:
        builder.add(InlineKeyboardButton(
            text=text, callback_data=f"interval_preset_{link_id}_{seconds}"
        ))
    builder.add(InlineKeyboardButton(text="✏️ Ввести своё значение", callback_data=f"interval_custom_{link_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_settings_submenu"))
    builder.adjust(3, 3, 3, 1, 1)
    return builder.as_markup()

def get_confirmation_keyboard(link_id, action_type="delete"):
    builder = InlineKeyboardBuilder()
    if action_type == "delete":
        builder.add(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{link_id}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"manage_link_{link_id}"))
    builder.adjust(2)
    return builder.as_markup()

def get_toggle_parsing_keyboard(links, action_type="pause"):
    builder = InlineKeyboardBuilder()
    for link in links:
        status_icon = "✅" if link.is_active else "❌"
        action_text = "⏸️ Остановить" if action_type == "pause" else "▶️ Возобновить"
        builder.add(InlineKeyboardButton(
            text=f"{status_icon} {link.name}",
            callback_data=f"{action_type}_link_{link.id}"
        ))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(1)
    return builder.as_markup()

def get_configure_parsing_submenu(link_id, parsing_type='combined', category=None):
    """Подменю для настройки парсинга конкретной ссылки"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🎯 Изменить тип парсинга", callback_data=f"edit_parsing_type_{link_id}"))
    builder.add(InlineKeyboardButton(text="🗂️ Изменить категорию", callback_data=f"edit_category_{link_id}"))

    # Разные кнопки в зависимости от типа парсинга и категории
    if parsing_type == 'telegram':
        builder.add(InlineKeyboardButton(text="📱 Изменить Telegram канал", callback_data=f"edit_telegram_channel_{link_id}"))
        builder.add(InlineKeyboardButton(text="🔑 Изменить ключевые слова", callback_data=f"edit_telegram_keywords_{link_id}"))
    elif category == 'announcement':
        # Специальные кнопки для анонсов
        builder.add(InlineKeyboardButton(text="📋 Изменить стратегию парсинга", callback_data=f"edit_announcement_strategy_{link_id}"))
        builder.add(InlineKeyboardButton(text="🌐 Изменить HTML URL", callback_data=f"edit_html_url_{link_id}"))
        builder.add(InlineKeyboardButton(text="🔑 Изменить ключевые слова", callback_data=f"edit_announcement_keywords_{link_id}"))
        builder.add(InlineKeyboardButton(text="🎯 Изменить CSS селектор", callback_data=f"edit_announcement_css_{link_id}"))
        builder.add(InlineKeyboardButton(text="⚡ Изменить регулярное выражение", callback_data=f"edit_announcement_regex_{link_id}"))
    else:
        builder.add(InlineKeyboardButton(text="📡 Изменить API URL", callback_data=f"edit_api_url_{link_id}"))
        builder.add(InlineKeyboardButton(text="🌐 Изменить HTML URL", callback_data=f"edit_html_url_{link_id}"))

    builder.add(InlineKeyboardButton(text="⬅️ К настройкам", callback_data="manage_settings_submenu"))
    builder.add(InlineKeyboardButton(text="🏠 К ссылке", callback_data=f"manage_link_{link_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_category_edit_keyboard(link_id):
    """Клавиатура для выбора категории при редактировании ссылки"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⭐ Избранные", callback_data=f"set_category_{link_id}_favorite"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпады", callback_data=f"set_category_{link_id}_launchpad"))
    builder.add(InlineKeyboardButton(text="🌊 Лаунчпулы", callback_data=f"set_category_{link_id}_launchpool"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдропы", callback_data=f"set_category_{link_id}_airdrop"))
    builder.add(InlineKeyboardButton(text="🍬 CandyBomb", callback_data=f"set_category_{link_id}_candybomb"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data=f"set_category_{link_id}_staking"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data=f"set_category_{link_id}_announcement"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_link_{link_id}"))
    builder.adjust(1, 2, 2, 2, 1)
    return builder.as_markup()

def get_parsing_type_keyboard(link_id):
    """Клавиатура для выбора типа парсинга"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Комбинированный (API + HTML + Browser)", callback_data=f"set_parsing_type_{link_id}_combined"))
    builder.add(InlineKeyboardButton(text="📡 Только API", callback_data=f"set_parsing_type_{link_id}_api"))
    builder.add(InlineKeyboardButton(text="🌐 Только HTML", callback_data=f"set_parsing_type_{link_id}_html"))
    builder.add(InlineKeyboardButton(text="🌐 Только Browser", callback_data=f"set_parsing_type_{link_id}_browser"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data=f"set_parsing_type_{link_id}_telegram"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_configure_parsing"))
    builder.adjust(1)
    return builder.as_markup()

# СПЕЦИАЛЬНЫЕ ПАРСЕРЫ - конфигурация
SPECIAL_PARSERS_CONFIG = {
    'weex': {
        'name': 'WEEX Parser',
        'description': 'Перехват API через Playwright (для weex.com)',
        'domains': ['weex.com'],
        'emoji': '🔧'
    },
    'okx_boost': {
        'name': 'OKX Boost Parser',
        'description': 'Парсер для OKX X-Launch/Boost (web3.okx.com)',
        'domains': ['okx.com'],
        'emoji': '🚀'
    },
    'bybit_launchpool': {
        'name': 'Bybit Launchpool',
        'description': 'Парсер для Bybit Launchpool',
        'domains': ['bybit.com/en/trade/spot/launchpool'],
        'emoji': '🌊'
    }
}

# КОНФИГУРАЦИЯ ВСЕХ ПАРСЕРОВ - для выбора при добавлении ссылки
PARSERS_CONFIG = {
    'auto': {
        'name': 'Автоматический выбор',
        'emoji': '🤖',
        'categories': ['launches', 'airdrop', 'staking', 'launchpool', 'announcement'],
        'domains': [],  # Подходит для всех
        'priority': 0
    },
    'staking': {
        'name': 'Стейкинг парсер',
        'emoji': '📊',
        'categories': ['staking', 'launches'],  # Показывается для этих категорий
        'domains': ['bybit.com', 'kucoin.com', 'okx.com', 'binance.com', 'gate.io', 'mexc.com'],
        'priority': 1
    },
    'announcement': {
        'name': 'Анонс парсер',
        'emoji': '📢',
        'categories': ['announcement', 'launches'],
        'domains': [],  # Подходит для всех
        'priority': 2
    },
    'weex': {
        'name': 'WEEX парсер',
        'emoji': '🔧',
        'categories': ['airdrop', 'launchpool', 'launches'],
        'domains': ['weex.com'],
        'priority': 3
    },
    'okx_boost': {
        'name': 'OKX Boost парсер',
        'emoji': '🚀',
        'categories': ['airdrop', 'launchpool', 'launches'],
        'domains': ['okx.com'],
        'priority': 4
    },
    'bybit_launchpool': {
        'name': 'Bybit Launchpool',
        'emoji': '🌊',
        'categories': ['launchpool', 'launches'],
        'domains': ['bybit.com'],
        'priority': 5
    },
    'mexc_launchpool': {
        'name': 'MEXC Launchpool',
        'emoji': '🌊',
        'categories': ['launchpool', 'launches'],
        'domains': ['mexc.com'],
        'priority': 6
    },
    'gate_launchpool': {
        'name': 'Gate.io Launchpool',
        'emoji': '🌊',
        'categories': ['launchpool', 'launches'],
        'domains': ['gate.com', 'gate.io'],
        'priority': 7
    },
    'gate_launchpad': {
        'name': 'Gate.io Launchpad',
        'emoji': '🚀',
        'categories': ['launchpool', 'launches'],
        'domains': ['gate.com', 'gate.io'],
        'priority': 8
    },
    'bingx_launchpool': {
        'name': 'BingX Launchpool',
        'emoji': '🌊',
        'categories': ['launchpool', 'launches'],
        'domains': ['bingx.com'],
        'priority': 9
    },
    'bitget_launchpool': {
        'name': 'Bitget Launchpool',
        'emoji': '🌊',
        'categories': ['launchpool', 'launches'],
        'domains': ['bitget.com'],
        'priority': 10
    },
    'bitget_poolx': {
        'name': 'Bitget PoolX',
        'emoji': '💎',
        'categories': ['staking', 'launchpool'],
        'domains': ['bitget.com'],
        'priority': 11
    },
    'bitget_candybomb': {
        'name': 'Bitget CandyBomb',
        'emoji': '�',
        'categories': ['candybomb', 'airdrop', 'drops'],
        'domains': ['bitget.com'],
        'priority': 12
    },
    'phemex_candydrop': {
        'name': 'Phemex Candy Drop',
        'emoji': '🍬',
        'categories': ['candybomb', 'airdrop', 'drops'],
        'domains': ['phemex.com'],
        'priority': 13
    },
    'universal': {
        'name': 'Универсальный парсер',
        'emoji': '🌐',
        'categories': ['launches', 'drops', 'airdrop', 'candybomb', 'staking', 'launchpool', 'launchpad', 'announcement'],
        'domains': [],  # Подходит для всех
        'priority': 99
    }
}

def get_available_parsers_for_context(category: str, url: str = None) -> list:
    """
    Возвращает список доступных парсеров для контекста (категория + URL).
    Парсеры сортируются по приоритету, рекомендуемый парсер отмечается.
    
    Returns:
        list of tuples: [(parser_id, config, is_recommended), ...]
    """
    url_lower = (url or '').lower()
    available = []
    recommended_parser = None
    
    for parser_id, config in PARSERS_CONFIG.items():
        # Проверяем, подходит ли парсер для этой категории
        if category not in config['categories']:
            continue
        
        # Проверяем домен (если указан)
        domains = config.get('domains', [])
        if domains:
            # Парсер с ограничением по домену - показываем только если URL подходит
            domain_match = any(domain in url_lower for domain in domains)
            if not domain_match:
                continue
        
        available.append((parser_id, config))
    
    # Сортируем по приоритету
    available.sort(key=lambda x: x[1].get('priority', 99))
    
    # Определяем рекомендуемый парсер
    # Логика: если категория совпадает с типом парсера И домен подходит → рекомендуем
    for parser_id, config in available:
        if parser_id == 'auto':
            continue
        
        # Для стейкинга
        if category == 'staking' and parser_id == 'staking':
            domains = config.get('domains', [])
            if not domains or any(d in url_lower for d in domains):
                recommended_parser = parser_id
                break
        
        # Для анонсов
        if category == 'announcement' and parser_id == 'announcement':
            recommended_parser = parser_id
            break
        
        # Для airdrop/candybomb/launchpool/launchpad со специальными парсерами
        if category in ['airdrop', 'candybomb', 'drops', 'launchpool', 'launchpad', 'launches'] and parser_id in ['weex', 'okx_boost', 'bybit_launchpool', 'mexc_launchpool', 'gate_launchpool', 'gate_launchpad', 'bingx_launchpool', 'bitget_launchpool', 'bitget_poolx', 'bitget_candybomb', 'phemex_candydrop']:
            domains = config.get('domains', [])
            if domains and any(d in url_lower for d in domains):
                # Для Bitget проверяем точный URL чтобы выбрать правильный парсер
                if 'bitget.com' in url_lower:
                    if ('candy-bomb' in url_lower or 'candybomb' in url_lower) and parser_id == 'bitget_candybomb':
                        recommended_parser = parser_id
                        break
                    elif 'poolx' in url_lower and parser_id == 'bitget_poolx':
                        recommended_parser = parser_id
                        break
                    elif 'launchpool' in url_lower and parser_id == 'bitget_launchpool':
                        recommended_parser = parser_id
                        break
                else:
                    recommended_parser = parser_id
                    break
        
        # Для staking с bitget_poolx
        if category == 'staking' and parser_id == 'bitget_poolx':
            domains = config.get('domains', [])
            if domains and any(d in url_lower for d in domains):
                if 'poolx' in url_lower:
                    recommended_parser = parser_id
                    break
    
    # Формируем результат с флагом рекомендации
    result = []
    for parser_id, config in available:
        is_recommended = (parser_id == recommended_parser)
        result.append((parser_id, config, is_recommended))
    
    return result

def get_parser_selection_keyboard(category: str, url: str = None):
    """Клавиатура для выбора парсера"""
    builder = InlineKeyboardBuilder()
    parsers = get_available_parsers_for_context(category, url)
    
    for parser_id, config, is_recommended in parsers:
        emoji = config['emoji']
        name = config['name']
        
        if is_recommended:
            btn_text = f"{emoji} {name} ⭐"
        else:
            btn_text = f"{emoji} {name}"
        
        builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"select_parser_{parser_id}"))
    
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_input"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1)
    return builder.as_markup()

def detect_special_parser_for_url(url: str) -> list:
    """Определяет доступные специальные парсеры для URL"""
    if not url:
        return []
    
    url_lower = url.lower()
    available = []
    
    for parser_id, config in SPECIAL_PARSERS_CONFIG.items():
        for domain in config['domains']:
            if domain in url_lower:
                available.append(parser_id)
                break
    
    return available


def auto_detect_parser_for_launches(url: str, category: str) -> tuple:
    """
    Автоматически определяет парсер для лаучей по URL.
    
    Returns:
        tuple: (parser_id, parser_name, parser_emoji) или (None, None, None) если не распознан
    """
    if not url:
        return (None, None, None)
    
    url_lower = url.lower()
    
    # Специализированные парсеры для launchpool
    launchpool_parsers = {
        'bybit': ('bybit_launchpool', 'Bybit Launchpool', '🌊'),
        'mexc': ('mexc_launchpool', 'MEXC Launchpool', '🌊'),
        'gate': ('gate_launchpool', 'Gate.io Launchpool', '🌊'),
        'bingx': ('bingx_launchpool', 'BingX Launchpool', '🌊'),
        'bitget': ('bitget_launchpool', 'Bitget Launchpool', '🌊'),
    }
    
    # Специализированные парсеры для launchpad
    launchpad_parsers = {
        'gate': ('gate_launchpad', 'Gate.io Launchpad', '🚀'),
    }
    
    # Специальные парсеры для airdrop/промо
    special_parsers = {
        'weex': ('weex', 'WEEX Parser', '🔧'),
        'okx': ('okx_boost', 'OKX Boost', '🚀'),
    }
    
    # Определяем биржу по URL
    detected_exchange = None
    for exchange in ['bybit', 'mexc', 'gate', 'kucoin', 'okx', 'binance', 'weex', 'bingx', 'bitget', 'phemex']:
        if exchange in url_lower:
            detected_exchange = exchange
            break
    
    if not detected_exchange:
        return (None, None, None)
    
    # Для Bitget Candy Bomb - проверяем по URL
    if detected_exchange == 'bitget' and ('candy-bomb' in url_lower or 'candybomb' in url_lower):
        return ('bitget_candybomb', 'Bitget CandyBomb', '🎁')
    
    # Для Phemex Candy Drop - проверяем по URL
    if detected_exchange == 'phemex' and ('candy-drop' in url_lower or 'candydrop' in url_lower or '/events/candy' in url_lower):
        return ('phemex_candydrop', 'Phemex Candy Drop', '🍬')
    
    # Для launchpool - ищем специализированный парсер
    if category == 'launchpool':
        if detected_exchange in launchpool_parsers:
            return launchpool_parsers[detected_exchange]
    
    # Для launchpad - ищем специализированный парсер
    elif category == 'launchpad':
        if detected_exchange in launchpad_parsers:
            return launchpad_parsers[detected_exchange]
    
    # Проверяем специальные парсеры (weex, okx)
    if detected_exchange in special_parsers:
        return special_parsers[detected_exchange]
    
    # Не найден специализированный парсер
    return (None, None, None)


def get_special_parser_keyboard(available_parsers: list = None):
    """Клавиатура для выбора специального парсера"""
    builder = InlineKeyboardBuilder()
    
    # Опция не использовать специальный парсер
    builder.add(InlineKeyboardButton(text="⚙️ Стандартный парсер", callback_data="special_parser_none"))
    
    # Добавляем доступные специальные парсеры
    if available_parsers:
        for parser_id in available_parsers:
            if parser_id in SPECIAL_PARSERS_CONFIG:
                config = SPECIAL_PARSERS_CONFIG[parser_id]
                btn_text = f"{config['emoji']} {config['name']}"
                builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"special_parser_{parser_id}"))
    else:
        # Показываем все парсеры
        for parser_id, config in SPECIAL_PARSERS_CONFIG.items():
            btn_text = f"{config['emoji']} {config['name']}"
            builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"special_parser_{parser_id}"))
    
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1)
    return builder.as_markup()

# НОВЫЕ ИНЛАЙН-КЛАВИАТУРЫ ДЛЯ РАСШИРЕННЫХ СИСТЕМ
def get_proxy_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список прокси", callback_data="proxy_list"))
    builder.add(InlineKeyboardButton(text="➕ Добавить прокси", callback_data="proxy_add"))
    builder.add(InlineKeyboardButton(text="🧪 Тестировать все", callback_data="proxy_test_all"))
    builder.add(InlineKeyboardButton(text="🗑️ Удалить прокси", callback_data="proxy_delete"))
    builder.add(InlineKeyboardButton(text="🗑️ Удалить нерабочие", callback_data="proxy_delete_dead"))
    builder.add(InlineKeyboardButton(text="📊 Статистика прокси", callback_data="proxy_stats"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_bypass"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
    builder.adjust(2)
    return builder.as_markup()

def get_user_agent_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список User-Agent", callback_data="ua_list"))
    builder.add(InlineKeyboardButton(text="➕ Добавить User-Agent", callback_data="ua_add"))
    builder.add(InlineKeyboardButton(text="🔄 Сгенерировать новые", callback_data="ua_generate"))
    builder.add(InlineKeyboardButton(text="📊 Статистика UA", callback_data="ua_stats"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_bypass"))
    builder.adjust(2)
    return builder.as_markup()

def get_statistics_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📈 Общая статистика", callback_data="stats_overall"))
    builder.add(InlineKeyboardButton(text="🏢 По биржам", callback_data="stats_by_exchange"))
    builder.add(InlineKeyboardButton(text="🔗 Лучшие комбинации", callback_data="stats_best_combinations"))
    builder.add(InlineKeyboardButton(text="🔄 Статус ротации", callback_data="stats_rotation_status"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="stats_cancel"))
    builder.adjust(2)
    return builder.as_markup()

def get_rotation_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏰ Интервал ротации", callback_data="rotation_interval"))
    builder.add(InlineKeyboardButton(text="🔧 Автооптимизация", callback_data="rotation_auto_optimize"))
    builder.add(InlineKeyboardButton(text="🗑️ Очистка данных", callback_data="rotation_cleanup"))
    builder.add(InlineKeyboardButton(text="🔄 Принудительная ротация", callback_data="rotation_force"))
    builder.add(InlineKeyboardButton(text="📊 Текущие настройки", callback_data="rotation_current"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="rotation_cancel"))
    builder.adjust(2)
    return builder.as_markup()

def get_rotation_interval_keyboard():
    """Клавиатура для выбора интервала ротации с предустановленными значениями"""
    builder = InlineKeyboardBuilder()
    
    # Минуты
    builder.add(InlineKeyboardButton(text="⏱ 10 мин", callback_data="set_rotation_interval_600"))
    builder.add(InlineKeyboardButton(text="⏱ 20 мин", callback_data="set_rotation_interval_1200"))
    builder.add(InlineKeyboardButton(text="⏱ 30 мин", callback_data="set_rotation_interval_1800"))
    builder.add(InlineKeyboardButton(text="⏱ 60 мин", callback_data="set_rotation_interval_3600"))
    
    # Часы
    builder.add(InlineKeyboardButton(text="🕐 3 часа", callback_data="set_rotation_interval_10800"))
    builder.add(InlineKeyboardButton(text="🕐 6 часов", callback_data="set_rotation_interval_21600"))
    builder.add(InlineKeyboardButton(text="🕐 12 часов", callback_data="set_rotation_interval_43200"))
    builder.add(InlineKeyboardButton(text="🕐 24 часа", callback_data="set_rotation_interval_86400"))
    
    # Дополнительные опции
    builder.add(InlineKeyboardButton(text="✏️ Ввести свое значение", callback_data="rotation_interval_custom"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="rotation_cancel"))
    
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()

def get_rotation_management_keyboard():
    """Клавиатура управления настройками ротации из экрана текущих настроек"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="⏰ Интервал ротации", callback_data="rotation_interval"))
    builder.add(InlineKeyboardButton(text="🔧 Автооптимизация", callback_data="rotation_auto_optimize"))
    builder.add(InlineKeyboardButton(text="📊 Хранение статистики", callback_data="rotation_stats_retention"))
    builder.add(InlineKeyboardButton(text="📦 Архивация неактивных", callback_data="rotation_archive_inactive"))
    builder.add(InlineKeyboardButton(text="🗑️ Очистить статистику", callback_data="rotation_cleanup"))
    builder.add(InlineKeyboardButton(text="🔄 Принудительная ротация", callback_data="rotation_force"))
    builder.add(InlineKeyboardButton(text="❌ Назад", callback_data="bypass_rotation"))
    
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()

def get_stats_retention_keyboard():
    """Клавиатура для выбора срока хранения статистики"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="7 дней", callback_data="set_stats_retention_7"))
    builder.add(InlineKeyboardButton(text="14 дней", callback_data="set_stats_retention_14"))
    builder.add(InlineKeyboardButton(text="30 дней", callback_data="set_stats_retention_30"))
    builder.add(InlineKeyboardButton(text="60 дней", callback_data="set_stats_retention_60"))
    builder.add(InlineKeyboardButton(text="90 дней", callback_data="set_stats_retention_90"))
    builder.add(InlineKeyboardButton(text="✏️ Ввести свое значение", callback_data="stats_retention_custom"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="rotation_current"))
    
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()

def get_archive_inactive_keyboard():
    """Клавиатура для выбора срока архивации неактивных записей"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="3 дня", callback_data="set_archive_inactive_3"))
    builder.add(InlineKeyboardButton(text="7 дней", callback_data="set_archive_inactive_7"))
    builder.add(InlineKeyboardButton(text="14 дней", callback_data="set_archive_inactive_14"))
    builder.add(InlineKeyboardButton(text="30 дней", callback_data="set_archive_inactive_30"))
    builder.add(InlineKeyboardButton(text="✏️ Ввести свое значение", callback_data="archive_inactive_custom"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="rotation_current"))
    
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

def get_bypass_keyboard():
    """Клавиатура для подменю Обход блокировок"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔧 Управление прокси", callback_data="bypass_proxy"))
    builder.add(InlineKeyboardButton(text="👤 Управление User-Agent", callback_data="bypass_ua"))
    builder.add(InlineKeyboardButton(text="📱 Telegram API", callback_data="bypass_telegram"))
    builder.add(InlineKeyboardButton(text="🔑 API ключи бирж", callback_data="exchange_cred_menu"))
    builder.add(InlineKeyboardButton(text="⚙️ Настройки ротации", callback_data="bypass_rotation"))
    builder.add(InlineKeyboardButton(text="📈 Статистика системы", callback_data="bypass_stats"))
    builder.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu"))
    builder.adjust(2)
    return builder.as_markup()

# КЛАВИАТУРЫ ДЛЯ КОНТЕКСТНОЙ НАВИГАЦИИ
def get_cancel_keyboard_with_navigation():
    """Клавиатура отмены с навигацией назад"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_back"))
    builder.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu"))
    builder.adjust(2)
    return builder.as_markup()

# ОСНОВНЫЕ КОМАНДЫ БОТА
@router.message(Command("start"))
async def cmd_start(message: Message):
    # Очищаем историю навигации при возврате в главное меню
    clear_navigation(message.from_user.id)

    # Отправляем одно сообщение с inline-меню
    await message.answer(
        "🤖 <b>Добро пожаловать в Heisenberg pars!</b>\n\n"
        "Я помогу отслеживать промоакции криптобирж, "
        "отслеживать страницы анонсов, парсить телеграм каналы и чаты.\n\n"
        "Prod. @Heisenbergabuz",
        reply_markup=get_main_menu_inline(),
        parse_mode="HTML"
    )

# =============================================================================
# ОБРАБОТЧИКИ INLINE-КНОПОК ГЛАВНОГО МЕНЮ
# =============================================================================

@router.callback_query(F.data == "main_favorites")
async def main_favorites_handler(callback: CallbackQuery):
    """Inline: Раздел Избранные - показывает список избранных ссылок"""
    await show_favorites_page(callback, page=0)

@router.callback_query(F.data.startswith("favorites_page_"))
async def favorites_page_handler(callback: CallbackQuery):
    """Обработчик пагинации списка избранных"""
    page = int(callback.data.split("_")[-1])
    await show_favorites_page(callback, page=page)

async def show_favorites_page(callback: CallbackQuery, page: int = 0):
    """Показать страницу со списком избранных ссылок"""
    try:
        links = await get_favorite_links_async()
        
        # Словарь иконок для категорий
        category_icons = {
            'launches': '🚀', 'launchpad': '🚀', 'launchpool': '🌊',
            'drops': '🎁', 'airdrop': '🪂', 'candybomb': '🍬',
            'staking': '💰', 'announcement': '📢'
        }
        
        if not links:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="➕ Добавить в избранное", callback_data="main_add_link"))
            builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
            builder.adjust(1)
            
            await callback.message.edit_text(
                "⭐ <b>ИЗБРАННЫЕ ССЫЛКИ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📭 <i>Список пуст</i>\n\n"
                "Добавьте ссылки в избранное:\n"
                "• При добавлении новой ссылки выберите «⭐ Избранные»\n"
                "• Или измените категорию существующей ссылки в Управлении",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Подсчёт статистики
        active_count = sum(1 for link in links if link.is_active)
        paused_count = len(links) - active_count
        
        # Пагинация
        per_page = 10
        total_pages = max(1, (len(links) + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_links = links[start_idx:end_idx]
        
        # Формируем сообщение с улучшенным форматированием
        response = "⭐ <b>ИЗБРАННЫЕ ССЫЛКИ</b>\n"
        response += "━━━━━━━━━━━━━━━━━━━━━━\n"
        response += f"📊 {len(links)} ссылок • ✅ {active_count} активны • ⏸ {paused_count} пауза\n\n"
        
        for link in page_links:
            status = "✅" if link.is_active else "❌"
            category = link.category or 'launches'
            cat_icon = category_icons.get(category, '📁')
            # Интервал в минутах
            interval_min = link.check_interval // 60 if link.check_interval >= 60 else link.check_interval
            interval_suffix = "м" if link.check_interval >= 60 else "с"
            response += f"{cat_icon} <b>{link.name}</b> — {interval_min}{interval_suffix} {status}\n"
        
        # Клавиатура с пагинацией
        builder = InlineKeyboardBuilder()
        
        # Кнопки для управления каждой ссылкой (по 2 в ряд с иконками категорий)
        for link in page_links:
            category = link.category or 'launches'
            cat_icon = category_icons.get(category, '📁')
            builder.add(InlineKeyboardButton(
                text=f"{cat_icon} {link.name}",
                callback_data=f"favorite_manage_{link.id}"
            ))
        
        # Пагинация
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"favorites_page_{page-1}"))
        if total_pages > 1:
            nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="favorites_info"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"favorites_page_{page+1}"))
        
        if nav_buttons:
            builder.row(*nav_buttons)
        
        builder.row(
            InlineKeyboardButton(text="➕ Добавить", callback_data="main_add_link"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")
        )
        
        # Adjust: по 2 кнопки ссылок в ряд, затем навигация, затем кнопки внизу
        adjust_pattern = [2] * ((len(page_links) + 1) // 2)  # По 2 кнопки в ряд
        if nav_buttons:
            adjust_pattern.append(len(nav_buttons))
        adjust_pattern.append(2)
        builder.adjust(*adjust_pattern)
        
        await callback.message.edit_text(
            response,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в show_favorites_page: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@router.callback_query(F.data.startswith("favorite_manage_"))
async def favorite_manage_handler(callback: CallbackQuery):
    """Управление избранной ссылкой - показывает такое же меню как в Управлении ссылками"""
    try:
        link_id = int(callback.data.replace("favorite_manage_", ""))
        
        link = await get_link_by_id_async(link_id)
        if not link:
            await callback.answer("❌ Ссылка не найдена", show_alert=True)
            return
        
        # Сохраняем выбор пользователя для последующих действий
        user_id = callback.from_user.id
        user_selections[user_id] = link_id
        
        # Показываем инфо о ссылке с кнопками управления
        category_icons = {
            'launches': '🚀', 'launchpad': '🚀', 'launchpool': '🌊',
            'drops': '🎁', 'airdrop': '🪂', 'candybomb': '🍬',
            'staking': '💰', 'announcement': '📢'
        }
        category = link.category or 'launches'
        cat_icon = category_icons.get(category, '📁')
        status = "✅ Активна" if link.is_active else "❌ Остановлена"
        
        # Определяем тип клавиатуры в зависимости от категории
        if category == 'staking':
            keyboard = get_staking_management_keyboard()
        elif category in ('airdrop', 'candybomb', 'drops', 'launches', 'launchpool', 'launchpad', 'announcement'):
            keyboard = get_airdrop_management_keyboard()
        else:
            keyboard = get_management_keyboard(link)
        
        # Добавляем кнопку "Убрать из избранного"
        builder = InlineKeyboardBuilder()
        # Копируем кнопки из keyboard
        for row in keyboard.inline_keyboard:
            for btn in row:
                if btn.callback_data != "back_to_link_list":  # Заменим эту кнопку
                    builder.add(btn)
        
        # Добавляем специальные кнопки для избранного
        builder.add(InlineKeyboardButton(text="💔 Убрать из избранного", callback_data=f"remove_favorite_{link_id}"))
        builder.add(InlineKeyboardButton(text="⬅️ К избранным", callback_data="main_favorites"))
        builder.adjust(1)
        
        await callback.message.edit_text(
            f"⭐ <b>Избранная ссылка</b>\n\n"
            f"<b>Название:</b> {link.name}\n"
            f"<b>Категория:</b> {cat_icon} {category}\n"
            f"<b>Статус:</b> {status}\n"
            f"<b>Интервал:</b> {link.check_interval} сек\n"
            f"<b>URL:</b> <code>{(link.api_url or link.html_url or link.url or '-')[:50]}</code>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в favorite_manage_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@router.callback_query(F.data.startswith("remove_favorite_"))
async def remove_favorite_handler(callback: CallbackQuery):
    """Убрать ссылку из избранного"""
    try:
        link_id = int(callback.data.replace("remove_favorite_", ""))
        
        def remove_from_favorites(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.is_favorite = False
            return link.name
        
        link_name = atomic_operation(remove_from_favorites)
        
        # Инвалидируем кэш избранных
        from utils.cache import get_cache_manager
        cache = get_cache_manager()
        cache.invalidate("links:favorites")
        
        await callback.answer(f"💔 {link_name} удалена из избранного")
        
        # Возвращаемся к списку избранных
        await show_favorites_page(callback, page=0)
        
    except Exception as e:
        logger.error(f"Ошибка удаления из избранного: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data == "main_list_links")
async def main_list_links_handler(callback: CallbackQuery):
    """Inline: Список ссылок с пагинацией"""
    await show_links_page(callback, page=0)

@router.callback_query(F.data.startswith("links_page_"))
async def links_page_handler(callback: CallbackQuery):
    """Обработчик пагинации списка ссылок"""
    page = int(callback.data.split("_")[-1])
    await show_links_page(callback, page=page)

async def show_links_page(callback: CallbackQuery, page: int = 0):
    """Показать страницу со списком ссылок"""
    try:
        links = await get_links_async()

        if not links:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="➕ Добавить ссылку", callback_data="main_add_link"))
            builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
            builder.adjust(1)

            await callback.message.edit_text(
                "📊 <b>Список ссылок</b>\n\n"
                "У вас пока нет добавленных ссылок.\n"
                "Нажмите «Добавить ссылку» чтобы начать.",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Группируем ссылки по категориям
        categories = {}
        for link in links:
            category = link.category or 'launches'
            if category not in categories:
                categories[category] = []
            categories[category].append(link)

        # Словари для названий категорий
        category_names = {
            'launches': '🚀 ЛАУЧИ',
            'launchpad': '🚀 ЛАУНЧПАДЫ',
            'launchpool': '🌊 ЛАУНЧПУЛЫ',
            'staking': '💰 СТЕЙКИНГ',
            'airdrop': '🪂 АИРДРОП',
            'announcement': '📢 АНОНСЫ'
        }

        # Словари для иконок типов парсинга
        parsing_icons = {
            'api': '👾 API',
            'html': '🌐 HTML',
            'browser': '🖥 Browser',
            'telegram': '📱 Telegram',
            'combined': '🔄 Комбо'
        }

        # Формируем ответ
        response = "📊 <b>Список ссылок:</b>\n\n"

        # Сортируем категории по приоритету
        category_order = ['launches', 'staking', 'airdrop', 'launchpool', 'announcement']
        sorted_categories = [cat for cat in category_order if cat in categories]
        sorted_categories.extend([cat for cat in categories.keys() if cat not in category_order])

        # Выводим каждую категорию
        for idx, category in enumerate(sorted_categories):
            category_name = category_names.get(category, f'📁 {category.upper()}')

            # Добавляем разделитель и заголовок категории
            response += "━━━━━━━━━━━━━━━━━━━━━━\n"
            response += f"<b>{category_name}</b>\n"
            response += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for link in categories[category]:
                status_text = "Активна" if link.is_active else "Остановлена"
                status_emoji = "✅" if link.is_active else "❌"
                favorite_star = "⭐" if hasattr(link, 'is_favorite') and link.is_favorite else ""
                interval_minutes = link.check_interval // 60
                parsing_type = parsing_icons.get(link.parsing_type, '❓')

                # Формируем блок ссылки без эмодзи статуса в названии
                response += f"<b>{favorite_star}{link.name}</b>\n"
                response += f"Статус: {status_emoji} {status_text}\n"
                response += f"Парсинг: {parsing_type}\n"
                response += f"Интервал: {interval_minutes} мин\n"

                # Добавляем информацию о Telegram аккаунте, если это Telegram ссылка
                if link.telegram_channel and link.telegram_account:
                    account_status = "✅" if link.telegram_account.is_active else "❌"
                    response += f"📱 TG аккаунт: {account_status} {link.telegram_account.name}\n"

                # Формируем URL для отображения
                if link.telegram_channel:
                    response += f"URL: {link.telegram_channel}\n"
                elif link.api_url:
                    response += f"URL: {link.api_url}\n"
                elif link.html_url:
                    response += f"URL: {link.html_url}\n"
                elif link.page_url:
                    response += f"URL: {link.page_url}\n"
                else:
                    response += f"URL: не указан\n"

                response += "\n"

            # Добавляем пустую строку между категориями, кроме последней
            if idx < len(sorted_categories) - 1:
                response += "\n"

        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="➕ Добавить", callback_data="main_add_link"))
        builder.add(InlineKeyboardButton(text="⚙️ Управление", callback_data="main_manage_links"))
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
        builder.adjust(2, 1)

        await callback.message.edit_text(
            response,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в show_links_page: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "main_add_link")
async def main_add_link_handler(callback: CallbackQuery, state: FSMContext):
    """Inline: Добавить ссылку - переход к выбору категории"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⭐ Избранные", callback_data="add_category_favorite"))
    builder.add(InlineKeyboardButton(text="🚀 Лаучи", callback_data="add_category_launches"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
    builder.adjust(1, 2, 2, 1)

    await callback.message.edit_text(
        "➕ <b>Добавление ссылки</b>\n\n"
        "Выберите категорию для новой ссылки:\n\n"
        "⭐ <b>Избранные</b> - важные ссылки для быстрого доступа",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_category)
    await callback.answer()


@router.callback_query(F.data == "main_check_all")
async def main_check_all_handler(callback: CallbackQuery):
    """Inline: Проверить всё"""
    await callback.answer("🔄 Запускаю проверку всех активных ссылок...")
    
    # Получаем экземпляр бота
    bot_instance = bot_manager.get_instance()
    
    if not bot_instance:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
        await callback.message.edit_text(
            "❌ Бот не инициализирован",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return
    
    try:
        links = await get_links_async()
        active_links = [l for l in links if l.is_active]
        
        if not active_links:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
            
            await callback.message.edit_text(
                "🔄 <b>Проверка ссылок</b>\n\n"
                "❌ Нет активных ссылок для проверки.",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            return
        
        await callback.message.edit_text(
            f"🔄 <b>Проверка ссылок</b>\n\n"
            f"⏳ Проверяю {len(active_links)} активных ссылок...\n"
            f"Это может занять некоторое время.",
            parse_mode="HTML"
        )
        
        # Запускаем ручную проверку через экземпляр бота
        chat_id = callback.message.chat.id
        await bot_instance.manual_check_all_links(chat_id)
        
        # Добавляем кнопки после проверки
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔄 Повторить", callback_data="main_check_all"))
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
        builder.adjust(2)
        
        await callback.message.answer(
            "✅ Проверка завершена!",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка проверки: {e}")
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
        await callback.message.edit_text(
            f"❌ Ошибка при проверке: {str(e)[:100]}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "main_manage_links")
async def main_manage_links_handler(callback: CallbackQuery):
    """Inline: Управление ссылками - показываем категории"""
    push_navigation(callback.from_user.id, NAV_MANAGEMENT)
    
    await callback.message.edit_text(
        "⚙️ <b>Управление ссылками</b>\n\n"
        "Выберите раздел для управления:",
        reply_markup=get_category_management_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_bypass")
async def main_bypass_handler(callback: CallbackQuery):
    """Inline: Обход блокировок"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔧 Прокси", callback_data="bypass_proxy"))
    builder.add(InlineKeyboardButton(text="👤 User-Agent", callback_data="bypass_ua"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="bypass_stats"))
    builder.add(InlineKeyboardButton(text="⚙️ Ротация", callback_data="bypass_rotation"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
    builder.adjust(2, 2, 1)
    
    await callback.message.edit_text(
        "🛡️ <b>Обход блокировок</b>\n\n"
        "Настройте параметры для обхода защиты бирж:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_categories")
async def main_categories_handler(callback: CallbackQuery):
    """Inline: Быстрый переход к категориям"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Все ссылки", callback_data="category_all"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдропы", callback_data="category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаучи", callback_data="category_launches"))
    builder.add(InlineKeyboardButton(text="📢 Анонсы", callback_data="category_announcement"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
    builder.adjust(1, 2, 2, 1)
    
    await callback.message.edit_text(
        "🗂️ <b>Категории</b>\n\n"
        "Выберите категорию для просмотра:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_help")
async def main_help_handler(callback: CallbackQuery):
    """Inline: Помощь"""
    help_text = (
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "📊 <b>Список ссылок</b> — просмотр всех добавленных ссылок\n\n"
        "➕ <b>Добавить</b> — добавление новой ссылки для парсинга\n\n"
        "🔄 <b>Проверить всё</b> — ручная проверка всех активных ссылок\n\n"
        "⚙️ <b>Управление</b> — удаление, настройка, переименование ссылок\n\n"
        "🛡️ <b>Обход блокировок</b> — прокси, User-Agent, ротация\n\n"
        "🗂️ <b>Категории</b> — быстрый доступ к категориям (Airdrop, Staking и др.)\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Бот автоматически парсит ссылки с заданным интервалом и отправляет уведомления о новых промоакциях.</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
    
    await callback.message.edit_text(
        help_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


# =============================================================================
# КОМАНДЫ ПОМОЩИ
# =============================================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "ℹ️ Помощь по боту:\n\n"
        "• 📊 Список ссылок - ваши API ссылки\n"
        "• ➕ Добавить ссылку - новая биржа с кастомным именем\n"
        "• ⚙️ Управление ссылками - удаление, настройки, переименование, остановка/возобновление парсинга\n"
        "• 🔧 Управление прокси - добавление, тестирование, удаление прокси-серверов\n"
        "• 👤 Управление User-Agent - просмотр, добавление, генерация User-Agent\n"
        "• 📈 Статистика системы - общая статистика, статистика по биржам, лучшие комбинации\n"
        "• ⚙️ Настройки ротации - интервал ротации, автооптимизация, очистка данных\n"
        "• 🔄 Проверить всё - ручная проверка ТОЛЬКО АКТИВНЫХ ссылок\n"
        "• 🗂️ Категории - быстрый доступ к категориям\n\n"
        "Пример API ссылки:\n"
        "https://api.bybit.com/v5/promotion/list"
    )
    await message.answer(help_text)

@router.message(F.text == "❓ Помощь")
async def menu_help(message: Message):
    await cmd_help(message)

# СУЩЕСТВУЮЩИЕ ОБРАБОТЧИКИ МЕНЮ
@router.message(F.text == "📊 Список ссылок")
async def menu_list_links(message: Message):
    """Отображение списка ссылок с использованием async кэширования"""
    try:
        # Используем async функцию с кэшированием (Фаза 4)
        links = await get_links_async()
        
        if not links:
            await message.answer("📊 У вас пока нет добавленных ссылок")
            return
        
        response = "📊 Ваши API ссылки:\n\n"
        for link in links:
            status = "✅ Активна" if link.is_active else "❌ Остановлена"
            interval_minutes = link.check_interval // 60

            # Определяем отображение категории
            category = link.category or 'launches'
            category_icons = {
                'launches': '🚀 Лаучи',
                'launchpad': '🚀 Лаунчпады',
                'launchpool': '🌊 Лаунчпулы',
                'airdrop': '🪂 Аирдроп',
                'staking': '💰 Стейкинг',
                'announcement': '📢 Анонс'
            }
            category_display = category_icons.get(category, '🚀 Лаучи')

            # Определяем отображение типа парсинга
            parsing_type = link.parsing_type or 'combined'
            parsing_type_icons = {
                'combined': '🔄 Комбинированный',
                'api': '👾 API',
                'html': '🌐 HTML',
                'browser': '🌐 Browser',
                'telegram': '📱 Telegram'
            }
            parsing_display = parsing_type_icons.get(parsing_type, '🔄 Комбинированный')

            response += f"<b>{link.name}</b>\n"
            response += f"Категория: {category_display}\n"
            response += f"Статус: {status}\n"
            response += f"Парсинг: {parsing_display}\n"
            
            # НОВОЕ: Отображение выбранного парсера
            if link.special_parser:
                parser_info = PARSERS_CONFIG.get(link.special_parser, {})
                parser_emoji = parser_info.get('emoji', '🔧')
                parser_name = parser_info.get('name', link.special_parser)
                response += f"Парсер: {parser_emoji} {parser_name}\n"
            else:
                response += f"Парсер: 🤖 Автоматический\n"
            
            response += f"Интервал: {interval_minutes} мин\n"

            # НОВОЕ: Отображение Telegram аккаунта
            if link.parsing_type == 'telegram' and hasattr(link, 'telegram_account') and link.telegram_account:
                account = link.telegram_account

                # Иконка статуса аккаунта
                if account.is_blocked:
                    account_status = "❌"
                elif not account.is_active:
                    account_status = "💤"
                else:
                    account_status = "✅"

                # Имя аккаунта (обрезаем если длинное)
                account_name = account.name[:20] + "..." if len(account.name) > 20 else account.name
                response += f"📱 TG аккаунт: {account_status} {account_name}\n"

            response += f"URL: <code>{link.url}</code>\n\n"
        
        await message.answer(response, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка ссылок: {e}")
        await message.answer("❌ Ошибка при получении списка ссылок")

@router.message(F.text == "➕ Добавить ссылку")
async def menu_add_link(message: Message, state: FSMContext):
    """Начало процесса добавления ссылки - выбор категории"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⭐ Избранные", callback_data="add_category_favorite"))
    builder.add(InlineKeyboardButton(text="🚀 Лаучи", callback_data="add_category_launches"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1, 2, 2, 1)

    await message.answer(
        "🔗 <b>Добавление новой ссылки</b>\n\n"
        "🗂️ <b>Шаг 1:</b> Выберите категорию ссылки:\n\n"
        "⭐ <b>Избранные</b> - важные ссылки для быстрого доступа",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_category)

@router.callback_query(F.data.startswith("add_category_"), StateFilter(AddLinkStates.waiting_for_category))
async def handle_category_choice(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории при добавлении ссылки"""
    category = callback.data.replace("add_category_", "")

    # Если выбрали "Лаучи" - показываем подменю с Лаунчпады/Лаунчпулы
    if category == "launches":
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🚀 Лаунчпады", callback_data="add_category_launchpad"))
        builder.add(InlineKeyboardButton(text="🌊 Лаунчпулы", callback_data="add_category_launchpool"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
        builder.adjust(2, 2)
        
        await callback.message.edit_text(
            "🔗 <b>Добавление новой ссылки</b>\n\n"
            "✅ <b>Категория:</b> Лаучи\n\n"
            "🗂️ Выберите подкатегорию:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Если выбрали "Избранные" - показываем подменю выбора реальной категории
    if category == "favorite":
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🚀 Лаунчпады", callback_data="add_favorite_launchpad"))
        builder.add(InlineKeyboardButton(text="🌊 Лаунчпулы", callback_data="add_favorite_launchpool"))
        builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_favorite_airdrop"))
        builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_favorite_staking"))
        builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_favorite_announcement"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
        builder.adjust(2, 2, 1, 2)
        
        await callback.message.edit_text(
            "🔗 <b>Добавление в Избранные</b>\n\n"
            "⭐ Ссылка будет добавлена в <b>Избранные</b>\n\n"
            "🗂️ Выберите тип ссылки для правильного парсинга:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Сохраняем категорию в state
    await state.update_data(category=category)

    category_names = {
        'launches': 'Лаучи',
        'launchpad': 'Лаунчпады',
        'launchpool': 'Лаунчпулы',
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'announcement': 'Анонс'
    }
    category_display = category_names.get(category, category)

    # Добавляем кнопку "Назад" (для подкатегорий - возврат к меню Лаучи)
    builder = InlineKeyboardBuilder()
    if category in ['launchpad', 'launchpool']:
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="add_category_launches"))
    else:
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)

    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> {category_display}\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название биржи\n\n"
        f"Примеры:\n"
        f"• <i>Bybit Promotions</i>\n"
        f"• <i>MEXC Launchpad</i>\n"
        f"• <i>OKX Earn</i>\n\n"
        f"Это название поможет вам легко находить ссылку в списке.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data.startswith("add_favorite_"), StateFilter(AddLinkStates.waiting_for_category))
async def handle_favorite_category_choice(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа ссылки при добавлении в Избранные"""
    category = callback.data.replace("add_favorite_", "")
    
    # Сохраняем категорию и флаг избранного
    await state.update_data(category=category, is_favorite=True)
    
    category_names = {
        'launchpad': 'Лаунчпады',
        'launchpool': 'Лаунчпулы',
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'announcement': 'Анонс'
    }
    category_display = category_names.get(category, category)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="add_category_favorite"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"🔗 <b>Добавление в Избранные</b>\n\n"
        f"⭐ <b>В избранное</b> | 🗂️ <b>Тип:</b> {category_display}\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название биржи\n\n"
        f"Примеры:\n"
        f"• <i>Bybit Promotions</i>\n"
        f"• <i>MEXC Launchpad</i>\n"
        f"• <i>OKX Earn</i>\n\n"
        f"Это название поможет вам легко находить ссылку в списке.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()

@router.message(AddLinkStates.waiting_for_name)
async def process_name_input(message: Message, state: FSMContext):
    """Обработка ввода названия биржи"""
    custom_name = message.text.strip()

    if not custom_name:
        await message.answer("❌ Название не может быть пустым. Попробуйте снова:")
        return

    if len(custom_name) > 100:
        await message.answer("❌ Название слишком длинное (максимум 100 символов). Введите другое:")
        return

    # Сохраняем название
    await state.update_data(custom_name=custom_name)
    
    # Получаем категорию для определения следующего шага
    data = await state.get_data()
    category = data.get('category', 'launches')
    
    # =========================================================================
    # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ СТЕЙКИНГА - упрощённый процесс
    # =========================================================================
    if category == 'staking':
        # Для стейкинга: автоматически устанавливаем тип парсинга = api
        await state.update_data(parsing_type='api', selected_parser='staking')
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_staking"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await message.answer(
            f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
            f"📡 <b>Шаг 2/4:</b> Введите API ссылку для стейкинга\n\n"
            f"<b>Примеры API ссылок:</b>\n"
            f"• <code>https://api.bybit.com/v5/earn/product?category=FlexibleSaving</code>\n"
            f"• <code>https://www.kucoin.com/_api/earn-saving/products</code>\n"
            f"• <code>https://www.okx.com/priapi/v1/earn/staking/products</code>\n\n"
            f"💡 Парсер автоматически определит биржу по URL.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_api_url)
        return
    
    # =========================================================================
    # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ ЛАУЧЕЙ - упрощённый процесс
    # =========================================================================
    if category in ['launchpad', 'launchpool']:
        # Для лаучей: сразу переходим к вводу ссылки
        await state.update_data(parsing_type='combined')  # По умолчанию combined
        
        category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
        category_emoji = "🚀" if category == "launchpad" else "🌊"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_launches"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await message.answer(
            f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
            f"{category_emoji} <b>Шаг 2/3:</b> Введите ссылку на {category_display}\n\n"
            f"<b>Можете ввести:</b>\n"
            f"• API ссылку (например <code>https://api.bybit.com/...</code>)\n"
            f"• Ссылку на страницу (например <code>https://www.bybit.com/en/trade/spot/launchpool</code>)\n\n"
            f"💡 Бот автоматически определит подходящий парсер по URL.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_page_url)  # Используем page_url для лаучей
        return
    
    # =========================================================================
    # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ АИРДРОПА - упрощённый процесс
    # =========================================================================
    if category == 'airdrop':
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="📡 API", callback_data="airdrop_source_api"))
        builder.add(InlineKeyboardButton(text="🌐 Веб-страница", callback_data="airdrop_source_web"))
        builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="airdrop_source_telegram"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_airdrop"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(3, 2)
        
        await message.answer(
            f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
            f"🪂 <b>Шаг 2/4:</b> Выберите источник данных\n\n"
            f"<b>📡 API</b> - прямой endpoint (быстро, надёжно)\n"
            f"<b>🌐 Веб-страница</b> - парсинг HTML страницы\n"
            f"<b>📱 Telegram</b> - мониторинг канала по ключевым словам",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_parsing_type)  # Переиспользуем состояние
        return
    
    # =========================================================================
    # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ АНОНСОВ - упрощённый процесс
    # =========================================================================
    if category == 'announcement':
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🌐 Веб-страница", callback_data="announcement_source_web"))
        builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="announcement_source_telegram"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2, 2)
        
        await message.answer(
            f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
            f"📢 <b>Шаг 2/5:</b> Выберите источник данных\n\n"
            f"<b>🌐 Веб-страница</b> - мониторинг страницы анонсов\n"
            f"<b>📱 Telegram</b> - мониторинг канала по ключевым словам",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_parsing_type)
        return
    
    # =========================================================================
    # СТАНДАРТНАЯ ОБРАБОТКА ДЛЯ ОСТАЛЬНЫХ КАТЕГОРИЙ
    # =========================================================================
    # Создаем кнопки для выбора типа парсинга
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Комбинированный (API + HTML + Browser)", callback_data="parsing_type_combined"))
    builder.add(InlineKeyboardButton(text="📡 Только API", callback_data="parsing_type_api"))
    builder.add(InlineKeyboardButton(text="🌐 Только HTML", callback_data="parsing_type_html"))
    builder.add(InlineKeyboardButton(text="🌐 Только Browser", callback_data="parsing_type_browser"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="parsing_type_telegram"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 1, 1, 2)

    await message.answer(
        f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
        f"🎯 <b>Шаг 2/5:</b> Выберите тип парсинга\n\n"
        f"<b>Типы парсинга:</b>\n"
        f"• <b>Комбинированный</b> - пробует все методы (Browser → API → HTML)\n"
        f"• <b>Только API</b> - быстрый, но может быть заблокирован\n"
        f"• <b>Только HTML</b> - стабильный для статических страниц\n"
        f"• <b>Только Browser</b> - обходит капчи и динамический контент\n"
        f"• <b>Telegram</b> - мониторинг Telegram-каналов по ключевым словам\n\n"
        f"Рекомендуется <b>Комбинированный</b> для лучшей надежности.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parsing_type)

@router.callback_query(AddLinkStates.waiting_for_parsing_type, F.data.startswith("parsing_type_"))
async def process_parsing_type_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа парсинга"""
    parsing_type = callback.data.replace("parsing_type_", "")

    # Сохраняем тип парсинга
    await state.update_data(parsing_type=parsing_type)

    data = await state.get_data()
    custom_name = data.get('custom_name')

    # Создаем клавиатуру с кнопками "Назад" и "Отмена"
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    cancel_builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    cancel_builder.adjust(2)

    # Определяем, какие URL нужно запросить в зависимости от типа парсинга
    if parsing_type == 'api':
        # Для API парсинга нужен только API URL
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Только API</b>\n\n"
            f"📡 <b>Шаг 3/5:</b> Введите API ссылку\n\n"
            f"Пример:\n"
            f"<code>https://api.bybit.com/v5/promotion/list</code>\n\n"
            f"API ссылка используется для автоматического парсинга.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_api_url)

    elif parsing_type == 'html':
        # Проверяем категорию - для announcement нужно выбрать стратегию
        category = data.get('category', 'launches')

        if category == 'announcement':
            # Для анонсов предлагаем выбрать стратегию парсинга
            strategy_builder = InlineKeyboardBuilder()
            strategy_builder.add(InlineKeyboardButton(text="🔍 Любые изменения", callback_data="strategy_any_change"))
            strategy_builder.add(InlineKeyboardButton(text="🎯 Изменения в элементе", callback_data="strategy_element_change"))
            strategy_builder.add(InlineKeyboardButton(text="📝 Любое ключевое слово", callback_data="strategy_any_keyword"))
            strategy_builder.add(InlineKeyboardButton(text="📚 Все ключевые слова", callback_data="strategy_all_keywords"))
            strategy_builder.add(InlineKeyboardButton(text="⚡ Регулярное выражение", callback_data="strategy_regex"))
            strategy_builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
            strategy_builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
            strategy_builder.adjust(1, 1, 1, 1, 1, 2)

            await callback.message.edit_text(
                f"✅ Выбран тип: <b>Только HTML</b>\n\n"
                f"🎯 <b>Шаг 3/6:</b> Выберите стратегию парсинга анонсов\n\n"
                f"<b>Стратегии:</b>\n\n"
                f"🔍 <b>Любые изменения</b> - отслеживание любых изменений на странице\n"
                f"🎯 <b>Изменения в элементе</b> - отслеживание конкретного элемента (CSS Selector)\n"
                f"📝 <b>Любое ключевое слово</b> - поиск любого из заданных слов\n"
                f"📚 <b>Все ключевые слова</b> - все слова должны присутствовать\n"
                f"⚡ <b>Регулярное выражение</b> - поиск по regex паттерну\n\n"
                f"Выберите подходящую стратегию:",
                reply_markup=strategy_builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_announcement_strategy)
        else:
            # Для обычных категорий - просто запрашиваем HTML URL
            await callback.message.edit_text(
                f"✅ Выбран тип: <b>Только HTML</b>\n\n"
                f"🌐 <b>Шаг 3/5:</b> Введите HTML ссылку\n\n"
                f"Пример:\n"
                f"<code>https://www.bybit.com/en/trade/spot/token-splash</code>\n\n"
                f"HTML ссылка используется для парсинга статических страниц.",
                reply_markup=cancel_builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_html_url)

    elif parsing_type == 'browser':
        # Для Browser парсинга нужен HTML URL (браузер открывает страницу)
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Только Browser</b>\n\n"
            f"🌐 <b>Шаг 3/5:</b> Введите ссылку для браузерного парсинга\n\n"
            f"Пример:\n"
            f"<code>https://www.mexc.com/token-airdrop</code>\n\n"
            f"Браузер откроет эту страницу и выполнит JavaScript для получения данных.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_html_url)

    elif parsing_type == 'telegram':
        # Для Telegram парсинга запрашиваем канал
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Telegram</b>\n\n"
            f"📱 <b>Шаг 3/5:</b> Введите имя или ссылку Telegram-канала\n\n"
            f"Примеры:\n"
            f"<code>@binance</code>\n"
            f"<code>https://t.me/binance</code>\n"
            f"<code>t.me/binance</code>\n\n"
            f"Бот будет мониторить сообщения из этого канала по ключевым словам.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_telegram_channel)

    else:  # combined
        # Для комбинированного парсинга запрашиваем API URL сначала
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Комбинированный</b>\n\n"
            f"📡 <b>Шаг 3/5:</b> Введите API ссылку\n\n"
            f"Пример:\n"
            f"<code>https://api.bybit.com/v5/promotion/list</code>\n\n"
            f"API ссылка используется для автоматического парсинга.\n"
            f"Далее вы сможете добавить HTML/Browser URL как fallback.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_api_url)

    await callback.answer()

# ОБРАБОТЧИКИ ДЛЯ СТРАТЕГИЙ АНОНСОВ
@router.callback_query(AddLinkStates.waiting_for_announcement_strategy, F.data.startswith("strategy_"))
async def process_announcement_strategy_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора стратегии парсинга анонсов"""
    strategy = callback.data.replace("strategy_", "")

    # Сохраняем стратегию
    await state.update_data(announcement_strategy=strategy)

    data = await state.get_data()
    custom_name = data.get('custom_name')

    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    cancel_builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    cancel_builder.adjust(2)

    # В зависимости от стратегии запрашиваем разные данные
    if strategy == 'any_change':
        # Для стратегии "любые изменения" сразу запрашиваем HTML URL
        await callback.message.edit_text(
            f"✅ Стратегия: <b>Отслеживание любых изменений</b>\n\n"
            f"🌐 <b>Шаг 4/6:</b> Введите HTML ссылку на страницу анонсов\n\n"
            f"Пример:\n"
            f"<code>https://www.mexc.com/ru-RU/announcements/</code>\n\n"
            f"Бот будет отслеживать любые изменения на этой странице.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_html_url)

    elif strategy == 'element_change':
        # Для стратегии "изменения в элементе" запрашиваем CSS селектор
        await callback.message.edit_text(
            f"✅ Стратегия: <b>Отслеживание изменений в элементе</b>\n\n"
            f"🎯 <b>Шаг 4/6:</b> Введите CSS селектор элемента\n\n"
            f"Примеры:\n"
            f"<code>.announcement-list</code>\n"
            f"<code>#news-container</code>\n"
            f"<code>div.news-item:first-child</code>\n\n"
            f"Бот будет отслеживать изменения только в этом элементе.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_selector)

    elif strategy == 'any_keyword':
        # Для стратегии "любое ключевое слово" запрашиваем ключевые слова
        await callback.message.edit_text(
            f"✅ Стратегия: <b>Поиск любого ключевого слова</b>\n\n"
            f"📝 <b>Шаг 4/6:</b> Введите ключевые слова через запятую\n\n"
            f"Примеры:\n"
            f"<code>airdrop, промо, campaign, listing</code>\n"
            f"<code>новый токен, листинг, бонус</code>\n\n"
            f"Бот уведомит вас, если найдет хотя бы одно из этих слов.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_keywords)

    elif strategy == 'all_keywords':
        # Для стратегии "все ключевые слова" запрашиваем ключевые слова
        await callback.message.edit_text(
            f"✅ Стратегия: <b>Поиск всех ключевых слов</b>\n\n"
            f"📚 <b>Шаг 4/6:</b> Введите ключевые слова через запятую\n\n"
            f"Примеры:\n"
            f"<code>airdrop, BTC, trading</code>\n"
            f"<code>новый, листинг, reward</code>\n\n"
            f"Бот уведомит вас только если найдет ВСЕ эти слова одновременно.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_keywords)

    elif strategy == 'regex':
        # Для стратегии "регулярное выражение" запрашиваем regex
        await callback.message.edit_text(
            f"✅ Стратегия: <b>Поиск по регулярному выражению</b>\n\n"
            f"⚡ <b>Шаг 4/6:</b> Введите регулярное выражение\n\n"
            f"Примеры:\n"
            f"<code>(airdrop|промо|campaign)</code>\n"
            f"<code>\\d+\\s*(USDT|BTC)</code>\n"
            f"<code>новый\\s+листинг</code>\n\n"
            f"Бот будет искать совпадения с вашим regex паттерном.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_regex)

    await callback.answer()

@router.message(AddLinkStates.waiting_for_announcement_selector)
async def process_announcement_selector_input(message: Message, state: FSMContext):
    """Обработка ввода CSS селектора"""
    css_selector = message.text.strip()

    if not css_selector:
        await message.answer("❌ CSS селектор не может быть пустым. Попробуйте снова:")
        return

    # Сохраняем CSS селектор
    await state.update_data(announcement_css_selector=css_selector)

    # Теперь запрашиваем HTML URL
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)

    await message.answer(
        f"✅ CSS селектор сохранен: <code>{css_selector}</code>\n\n"
        f"🌐 <b>Шаг 5/6:</b> Введите HTML ссылку на страницу анонсов\n\n"
        f"Пример:\n"
        f"<code>https://www.mexc.com/ru-RU/announcements/</code>\n\n"
        f"Бот будет отслеживать изменения в указанном элементе.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)

@router.message(AddLinkStates.waiting_for_announcement_keywords)
async def process_announcement_keywords_input(message: Message, state: FSMContext):
    """Обработка ввода ключевых слов для анонсов"""
    keywords_text = message.text.strip()

    if not keywords_text:
        await message.answer("❌ Ключевые слова не могут быть пустыми. Попробуйте снова:")
        return

    # Разбиваем по запятой и очищаем
    keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]

    if not keywords:
        await message.answer("❌ Не удалось распознать ключевые слова. Введите их через запятую:")
        return

    # Сохраняем ключевые слова
    await state.update_data(announcement_keywords=keywords)

    # Теперь запрашиваем HTML URL
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)

    keywords_display = ', '.join(keywords[:5])
    if len(keywords) > 5:
        keywords_display += f' (+{len(keywords) - 5} еще)'

    await message.answer(
        f"✅ Ключевые слова сохранены ({len(keywords)} шт.)\n"
        f"<code>{keywords_display}</code>\n\n"
        f"🌐 <b>Шаг 5/6:</b> Введите HTML ссылку на страницу анонсов\n\n"
        f"Пример:\n"
        f"<code>https://www.mexc.com/ru-RU/announcements/</code>\n\n"
        f"Бот будет искать эти слова на странице.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)

@router.message(AddLinkStates.waiting_for_announcement_regex)
async def process_announcement_regex_input(message: Message, state: FSMContext):
    """Обработка ввода регулярного выражения для анонсов"""
    import re

    regex_pattern = message.text.strip()

    if not regex_pattern:
        await message.answer("❌ Регулярное выражение не может быть пустым. Попробуйте снова:")
        return

    # Проверяем валидность regex
    try:
        re.compile(regex_pattern)
    except re.error as e:
        await message.answer(
            f"❌ Ошибка в регулярном выражении: {str(e)}\n\n"
            f"Проверьте синтаксис и попробуйте снова:"
        )
        return

    # Сохраняем regex
    await state.update_data(announcement_regex=regex_pattern)

    # Теперь запрашиваем HTML URL
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)

    # Обрезаем regex если слишком длинный
    regex_display = regex_pattern if len(regex_pattern) <= 50 else regex_pattern[:47] + "..."

    await message.answer(
        f"✅ Регулярное выражение сохранено\n"
        f"<code>{regex_display}</code>\n\n"
        f"🌐 <b>Шаг 5/6:</b> Введите HTML ссылку на страницу анонсов\n\n"
        f"Пример:\n"
        f"<code>https://www.mexc.com/ru-RU/announcements/</code>\n\n"
        f"Бот будет искать совпадения с вашим regex.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)

@router.message(AddLinkStates.waiting_for_api_url)
async def process_api_url_input(message: Message, state: FSMContext):
    """Обработка ввода API ссылки"""
    api_url = message.text.strip()

    if not api_url.startswith(('http://', 'https://')):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    # Сохраняем API URL
    await state.update_data(api_url=api_url)

    data = await state.get_data()
    parsing_type = data.get('parsing_type', 'combined')
    category = data.get('category', 'launches')
    custom_name = data.get('custom_name')
    
    # =========================================================================
    # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ СТЕЙКИНГА - переходим к выбору APR
    # =========================================================================
    if category == 'staking':
        builder = InlineKeyboardBuilder()
        # Кнопки выбора минимального APR
        builder.add(InlineKeyboardButton(text="0% (все)", callback_data="staking_apr_0"))
        builder.add(InlineKeyboardButton(text="5%", callback_data="staking_apr_5"))
        builder.add(InlineKeyboardButton(text="10%", callback_data="staking_apr_10"))
        builder.add(InlineKeyboardButton(text="20%", callback_data="staking_apr_20"))
        builder.add(InlineKeyboardButton(text="50%", callback_data="staking_apr_50"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url_staking"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(3, 2, 2)
        
        await message.answer(
            f"✅ API ссылка сохранена!\n\n"
            f"📊 <b>Шаг 3/4:</b> Минимальный APR для уведомлений\n\n"
            f"Бот будет уведомлять только о стейкингах с APR выше выбранного значения.\n\n"
            f"💡 <b>0% (все)</b> - показывать все стейкинги\n"
            f"💡 <b>5-10%</b> - только интересные предложения\n"
            f"💡 <b>20-50%</b> - только высокодоходные",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_min_apr)
        return
    
    # =========================================================================
    # СТАНДАРТНАЯ ОБРАБОТКА
    # =========================================================================
    # Для combined - сразу переходим к выбору парсера (пропускаем HTML)
    if parsing_type == 'combined':
        await state.update_data(html_url=None)
        # Переходим к выбору интервала (combined пропускает выбор парсера)
        await _show_interval_selection_msg(message, state, custom_name)
        return
    
    # Для api типа - предлагаем добавить HTML как fallback
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_url"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)

    await message.answer(
        f"✅ API ссылка сохранена!\n\n"
        f"🌐 <b>Шаг 4/6:</b> Введите HTML ссылку (опционально)\n\n"
        f"HTML используется как резервный метод, если API не сработает.\n\n"
        f"<b>Введите ссылку</b> или нажмите <b>Пропустить</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)

# =============================================================================
# ОБРАБОТЧИКИ ДЛЯ ЛАУЧЕЙ - упрощённый процесс добавления
# Обработчик waiting_for_page_url (process_airdrop_url_input) объединён 
# с airdrop и находится в секции ОБРАБОТЧИКИ ДЛЯ АИРДРОПА
# =============================================================================

@router.callback_query(AddLinkStates.waiting_for_parser_selection, F.data.startswith("launches_parser_"))
async def process_launches_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора парсера для лаучей"""
    parser_id = callback.data.replace("launches_parser_", "")
    
    # Сохраняем парсер
    await state.update_data(selected_parser=parser_id if parser_id != 'auto' else 'auto')
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'launchpool')
    
    # Получаем информацию о парсере
    parser_info = PARSERS_CONFIG.get(parser_id, {})
    parser_emoji = parser_info.get('emoji', '🤖')
    parser_name = parser_info.get('name', 'Автоматический')
    
    category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
    
    # Показываем выбор интервала
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]
    
    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parser_launches"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(3, 3, 3, 2)
    
    await callback.message.edit_text(
        f"✅ Парсер выбран: <b>{parser_emoji} {parser_name}</b>\n\n"
        f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> {category_display}\n"
        f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
        f"Как часто проверять на новые проекты?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


# Кнопки "Назад" для лаучей
@router.callback_query(F.data == "back_to_name_launches")
async def back_to_name_launches(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия для лаучей"""
    data = await state.get_data()
    category = data.get('category', 'launchpool')
    category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
    
    # Определяем куда возвращаться - к подкатегориям лаучей
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="add_category_launches"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> {category_display}\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название\n\n"
        f"Примеры:\n"
        f"• <i>Bybit Launchpool</i>\n"
        f"• <i>MEXC Launchpad</i>\n"
        f"• <i>Gate.io Startup</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data == "back_to_url_launches")
async def back_to_url_launches(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу URL для лаучей"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    category = data.get('category', 'launchpool')
    
    category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
    category_emoji = "🚀" if category == "launchpad" else "🌊"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_launches"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"✅ Название: <b>{custom_name}</b>\n\n"
        f"{category_emoji} <b>Шаг 2/3:</b> Введите ссылку на {category_display}\n\n"
        f"<b>Можете ввести:</b>\n"
        f"• API ссылку (например <code>https://api.bybit.com/...</code>)\n"
        f"• Ссылку на страницу (например <code>https://www.bybit.com/en/trade/spot/launchpool</code>)\n\n"
        f"💡 Бот автоматически определит подходящий парсер по URL.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_page_url)
    await callback.answer()


@router.callback_query(F.data == "back_to_parser_launches")
async def back_to_parser_launches(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору парсера для лаучей"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    category = data.get('category', 'launchpool')
    api_url = data.get('api_url')
    html_url = data.get('html_url')
    url = api_url or html_url or ''
    
    category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
    
    # Формируем клавиатуру с доступными парсерами
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🤖 Автоматический выбор", callback_data="launches_parser_auto"))
    
    if category == 'launchpool':
        builder.add(InlineKeyboardButton(text="🌊 Bybit Launchpool", callback_data="launches_parser_bybit_launchpool"))
        builder.add(InlineKeyboardButton(text="🌊 MEXC Launchpool", callback_data="launches_parser_mexc_launchpool"))
        builder.add(InlineKeyboardButton(text="🌊 Gate.io Launchpool", callback_data="launches_parser_gate_launchpool"))
        builder.add(InlineKeyboardButton(text="🌊 BingX Launchpool", callback_data="launches_parser_bingx_launchpool"))
        builder.add(InlineKeyboardButton(text="🌊 Bitget Launchpool", callback_data="launches_parser_bitget_launchpool"))
    elif category == 'launchpad':
        builder.add(InlineKeyboardButton(text="🚀 Gate.io Launchpad", callback_data="launches_parser_gate_launchpad"))
    
    builder.add(InlineKeyboardButton(text="🔧 WEEX Parser", callback_data="launches_parser_weex"))
    builder.add(InlineKeyboardButton(text="🚀 OKX Boost", callback_data="launches_parser_okx_boost"))
    builder.add(InlineKeyboardButton(text="🌐 Универсальный", callback_data="launches_parser_universal"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_launches"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🤖 <b>Выберите парсер:</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> {category_display}\n"
        f"<b>URL:</b> <code>{url[:50]}...</code>\n\n"
        f"Выберите подходящий парсер для обработки данных:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parser_selection)
    await callback.answer()


# =============================================================================
# ОБРАБОТЧИКИ ДЛЯ АИРДРОПА - упрощённый процесс добавления
# =============================================================================

def auto_detect_parser_for_airdrop(url: str) -> tuple:
    """
    Автоматически определяет парсер для аирдропа по URL.
    
    Returns:
        (parser_id, parser_name, parser_emoji) или (None, None, None) если не распознан
    """
    url_lower = url.lower()
    
    # Специальные парсеры для airdrop
    if 'weex.com' in url_lower:
        return ('weex', 'WEEX Parser', '🔧')
    elif 'okx.com' in url_lower:
        return ('okx_boost', 'OKX Boost', '🚀')
    elif 'bitget.com' in url_lower and ('candy-bomb' in url_lower or 'candybomb' in url_lower):
        return ('bitget_candybomb', 'Bitget CandyBomb', '🎁')
    elif 'phemex.com' in url_lower and ('candy-drop' in url_lower or 'candydrop' in url_lower or '/events/candy' in url_lower):
        return ('phemex_candydrop', 'Phemex Candy Drop', '🍬')
    
    return (None, None, None)


@router.callback_query(AddLinkStates.waiting_for_parsing_type, F.data.startswith("airdrop_source_"))
async def process_airdrop_source_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора источника данных для аирдропа"""
    source = callback.data.replace("airdrop_source_", "")
    
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    # Маппинг источника на тип парсинга
    source_to_parsing_type = {
        'api': 'api',
        'web': 'html',
        'telegram': 'telegram'
    }
    parsing_type = source_to_parsing_type.get(source, 'api')
    await state.update_data(parsing_type=parsing_type)
    
    builder = InlineKeyboardBuilder()
    
    if source == 'telegram':
        # Для Telegram - переходим к стандартной обработке Telegram
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_airdrop"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Источник: <b>📱 Telegram</b>\n\n"
            f"📱 <b>Шаг 3/5:</b> Введите username или ссылку на канал\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>@channel_name</code>\n"
            f"• <code>https://t.me/channel_name</code>\n\n"
            f"⚠️ Бот должен иметь доступ к каналу для мониторинга.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_telegram_channel)
    else:
        # Для API и Web - запрашиваем URL
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_airdrop"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        source_name = "API" if source == "api" else "веб-страницы"
        source_emoji = "📡" if source == "api" else "🌐"
        
        await callback.message.edit_text(
            f"✅ Источник: <b>{source_emoji} {source_name}</b>\n\n"
            f"🔗 <b>Шаг 3/4:</b> Введите ссылку\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>https://www.weex.com/api/airdrop/list</code>\n"
            f"• <code>https://www.okx.com/priapi/v1/earn/airdrop</code>\n\n"
            f"💡 Бот попробует автоматически определить парсер.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_page_url)  # Используем page_url
    
    await callback.answer()


@router.message(AddLinkStates.waiting_for_page_url)
async def process_airdrop_url_input(message: Message, state: FSMContext):
    """Обработка ввода URL для аирдропа (и лаучей)"""
    url = message.text.strip()
    
    if not url:
        await message.answer("❌ URL не может быть пустым. Попробуйте снова:")
        return
    
    # Базовая валидация URL
    if not url.startswith(('http://', 'https://')):
        await message.answer(
            "❌ Неверный формат URL. Ссылка должна начинаться с http:// или https://\n\n"
            "Попробуйте снова:"
        )
        return
    
    data = await state.get_data()
    category = data.get('category', 'airdrop')
    custom_name = data.get('custom_name', '')
    
    # Определяем, это API или HTML URL (для airdrop)
    if 'api' in url.lower() or '/v1/' in url.lower() or '/v5/' in url.lower() or 'priapi' in url.lower():
        await state.update_data(api_url=url, html_url=None, page_url=url)
    else:
        await state.update_data(html_url=url, api_url=None, page_url=url)
    
    # =========================================================================
    # ДЛЯ ЛАУЧЕЙ - используем auto_detect_parser_for_launches
    # =========================================================================
    if category in ['launchpad', 'launchpool']:
        # Пробуем автоопределение парсера
        parser_id, parser_name, parser_emoji = auto_detect_parser_for_launches(url, category)
        
        if parser_id:
            # Парсер распознан - сохраняем и переходим к интервалу
            await state.update_data(selected_parser=parser_id)
            
            category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
            
            builder = InlineKeyboardBuilder()
            presets = [
                ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
                ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
                ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
            ]
            
            for text, seconds in presets:
                builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_launches"))
            builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
            builder.adjust(3, 3, 3, 2)
            
            await message.answer(
                f"✅ URL сохранён\n"
                f"🤖 Парсер определён автоматически: <b>{parser_emoji} {parser_name}</b>\n\n"
                f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
                f"<b>Имя:</b> {custom_name}\n"
                f"<b>Категория:</b> {category_display}\n"
                f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
                f"Как часто проверять на новые проекты?",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_interval)
        else:
            # Парсер не распознан - показываем выбор
            category_display = "Лаунчпад" if category == "launchpad" else "Лаунчпул"
            
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🤖 Автоматический выбор", callback_data="launches_parser_auto"))
            
            if category == 'launchpool':
                builder.add(InlineKeyboardButton(text="🌊 Bybit Launchpool", callback_data="launches_parser_bybit_launchpool"))
                builder.add(InlineKeyboardButton(text="🌊 MEXC Launchpool", callback_data="launches_parser_mexc_launchpool"))
                builder.add(InlineKeyboardButton(text="🌊 Gate.io Launchpool", callback_data="launches_parser_gate_launchpool"))
                builder.add(InlineKeyboardButton(text="🌊 BingX Launchpool", callback_data="launches_parser_bingx_launchpool"))
                builder.add(InlineKeyboardButton(text="🌊 Bitget Launchpool", callback_data="launches_parser_bitget_launchpool"))
            elif category == 'launchpad':
                builder.add(InlineKeyboardButton(text="🚀 Gate.io Launchpad", callback_data="launches_parser_gate_launchpad"))
            
            builder.add(InlineKeyboardButton(text="🔧 WEEX Parser", callback_data="launches_parser_weex"))
            builder.add(InlineKeyboardButton(text="🚀 OKX Boost", callback_data="launches_parser_okx_boost"))
            builder.add(InlineKeyboardButton(text="🌐 Универсальный", callback_data="launches_parser_universal"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_launches"))
            builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
            builder.adjust(1)
            
            await message.answer(
                f"✅ URL сохранён\n"
                f"⚠️ Парсер не определён автоматически\n\n"
                f"🤖 <b>Шаг 3/3:</b> Выберите парсер вручную\n\n"
                f"<b>Имя:</b> {custom_name}\n"
                f"<b>Категория:</b> {category_display}\n"
                f"<b>URL:</b> <code>{url[:50]}...</code>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_parser_selection)
        return
    
    # =========================================================================
    # ДЛЯ АИРДРОПА - используем auto_detect_parser_for_airdrop
    # =========================================================================
    if category == 'airdrop':
        # Пробуем автоопределение парсера
        parser_id, parser_name, parser_emoji = auto_detect_parser_for_airdrop(url)
        
        if parser_id:
            # Парсер распознан - сохраняем и переходим к интервалу
            await state.update_data(selected_parser=parser_id)
            
            builder = InlineKeyboardBuilder()
            presets = [
                ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
                ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
                ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
            ]
            
            for text, seconds in presets:
                builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_airdrop"))
            builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
            builder.adjust(3, 3, 3, 2)
            
            await message.answer(
                f"✅ URL сохранён\n"
                f"🤖 Парсер определён автоматически: <b>{parser_emoji} {parser_name}</b>\n\n"
                f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
                f"<b>Имя:</b> {custom_name}\n"
                f"<b>Категория:</b> Аирдроп\n"
                f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
                f"Как часто проверять на новые аирдропы?",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_interval)
        else:
            # Парсер не распознан - показываем выбор
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🤖 Автоматический выбор", callback_data="airdrop_parser_auto"))
            builder.add(InlineKeyboardButton(text="🔧 WEEX Parser", callback_data="airdrop_parser_weex"))
            builder.add(InlineKeyboardButton(text="🚀 OKX Boost", callback_data="airdrop_parser_okx_boost"))
            builder.add(InlineKeyboardButton(text="🌐 Универсальный", callback_data="airdrop_parser_universal"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_airdrop"))
            builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
            builder.adjust(1)
            
            await message.answer(
                f"✅ URL сохранён\n"
                f"⚠️ Парсер не определён автоматически\n\n"
                f"🤖 <b>Шаг 4/4:</b> Выберите парсер вручную\n\n"
                f"<b>Имя:</b> {custom_name}\n"
                f"<b>Категория:</b> Аирдроп\n"
                f"<b>URL:</b> <code>{url[:50]}...</code>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(AddLinkStates.waiting_for_parser_selection)
        return


@router.callback_query(AddLinkStates.waiting_for_parser_selection, F.data.startswith("airdrop_parser_"))
async def process_airdrop_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора парсера для аирдропа"""
    parser_id = callback.data.replace("airdrop_parser_", "")
    
    # Сохраняем парсер
    await state.update_data(selected_parser=parser_id if parser_id != 'auto' else 'auto')
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    
    # Получаем информацию о парсере
    parser_info = PARSERS_CONFIG.get(parser_id, {})
    parser_emoji = parser_info.get('emoji', '🤖')
    parser_name = parser_info.get('name', 'Автоматический')
    
    # Показываем выбор интервала
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]
    
    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parser_airdrop"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(3, 3, 3, 2)
    
    await callback.message.edit_text(
        f"✅ Парсер выбран: <b>{parser_emoji} {parser_name}</b>\n\n"
        f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> Аирдроп\n"
        f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
        f"Как часто проверять на новые аирдропы?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


# Кнопки "Назад" для аирдропа
@router.callback_query(F.data == "back_to_name_airdrop")
async def back_to_name_airdrop(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия для аирдропа"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> Аирдроп\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название\n\n"
        f"Примеры:\n"
        f"• <i>WEEX Airdrop</i>\n"
        f"• <i>OKX Boost Events</i>\n"
        f"• <i>Binance Megadrop</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data == "back_to_source_airdrop")
async def back_to_source_airdrop(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору источника для аирдропа"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📡 API", callback_data="airdrop_source_api"))
    builder.add(InlineKeyboardButton(text="🌐 Веб-страница", callback_data="airdrop_source_web"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="airdrop_source_telegram"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_airdrop"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(3, 2)
    
    await callback.message.edit_text(
        f"✅ Название: <b>{custom_name}</b>\n\n"
        f"🪂 <b>Шаг 2/4:</b> Выберите источник данных\n\n"
        f"<b>📡 API</b> - прямой endpoint (быстро, надёжно)\n"
        f"<b>🌐 Веб-страница</b> - парсинг HTML страницы\n"
        f"<b>📱 Telegram</b> - мониторинг канала по ключевым словам",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parsing_type)
    await callback.answer()


@router.callback_query(F.data == "back_to_url_airdrop")
async def back_to_url_airdrop(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу URL для аирдропа"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    parsing_type = data.get('parsing_type', 'api')
    
    source_name = "API" if parsing_type == "api" else "веб-страницы"
    source_emoji = "📡" if parsing_type == "api" else "🌐"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_airdrop"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"✅ Источник: <b>{source_emoji} {source_name}</b>\n\n"
        f"🔗 <b>Шаг 3/4:</b> Введите ссылку\n\n"
        f"<b>Примеры:</b>\n"
        f"• <code>https://www.weex.com/api/airdrop/list</code>\n"
        f"• <code>https://www.okx.com/priapi/v1/earn/airdrop</code>\n\n"
        f"💡 Бот попробует автоматически определить парсер.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_page_url)
    await callback.answer()


@router.callback_query(F.data == "back_to_parser_airdrop")
async def back_to_parser_airdrop(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору парсера для аирдропа"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    api_url = data.get('api_url')
    html_url = data.get('html_url')
    url = api_url or html_url or ''
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🤖 Автоматический выбор", callback_data="airdrop_parser_auto"))
    builder.add(InlineKeyboardButton(text="🔧 WEEX Parser", callback_data="airdrop_parser_weex"))
    builder.add(InlineKeyboardButton(text="🚀 OKX Boost", callback_data="airdrop_parser_okx_boost"))
    builder.add(InlineKeyboardButton(text="🌐 Универсальный", callback_data="airdrop_parser_universal"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_airdrop"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🤖 <b>Выберите парсер:</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> Аирдроп\n"
        f"<b>URL:</b> <code>{url[:50]}...</code>\n\n"
        f"Выберите подходящий парсер для обработки данных:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parser_selection)
    await callback.answer()


# =============================================================================
# ОБРАБОТЧИКИ ДЛЯ АНОНСОВ - упрощённый процесс добавления
# =============================================================================

@router.callback_query(AddLinkStates.waiting_for_parsing_type, F.data.startswith("announcement_source_"))
async def process_announcement_source_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора источника данных для анонсов"""
    source = callback.data.replace("announcement_source_", "")
    
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    
    if source == 'telegram':
        # Для Telegram - запрашиваем канал
        await state.update_data(parsing_type='telegram')
        
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Источник: <b>📱 Telegram</b>\n\n"
            f"📱 <b>Шаг 3/6:</b> Введите username или ссылку на канал\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>@binance_announcements</code>\n"
            f"• <code>https://t.me/binance</code>\n\n"
            f"⚠️ Бот должен иметь доступ к каналу для мониторинга.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_telegram_channel)
    else:
        # Для веб-страницы - сначала запрашиваем URL
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Источник: <b>🌐 Веб-страница</b>\n\n"
            f"🔗 <b>Шаг 3/6:</b> Введите ссылку на страницу анонсов\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>https://www.binance.com/en/support/announcement</code>\n"
            f"• <code>https://www.okx.com/help/section/announcements-latest-announcements</code>\n\n"
            f"💡 Далее вы сможете выбрать тип страницы и стратегию отслеживания.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_url)
    
    await callback.answer()


@router.message(AddLinkStates.waiting_for_announcement_url)
async def process_announcement_url_input(message: Message, state: FSMContext):
    """Обработка ввода URL для анонсов"""
    url = message.text.strip()
    
    if not url:
        await message.answer("❌ URL не может быть пустым. Попробуйте снова:")
        return
    
    if not url.startswith(('http://', 'https://')):
        await message.answer(
            "❌ Неверный формат URL. Ссылка должна начинаться с http:// или https://\n\n"
            "Попробуйте снова:"
        )
        return
    
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    # Сохраняем URL
    await state.update_data(html_url=url, page_url=url)
    
    # Показываем выбор типа страницы
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📄 Статическая (HTML)", callback_data="announcement_page_html"))
    builder.add(InlineKeyboardButton(text="⚡ Динамическая (Browser)", callback_data="announcement_page_browser"))
    builder.add(InlineKeyboardButton(text="❓ Не знаю", callback_data="announcement_page_auto"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 2)
    
    await message.answer(
        f"✅ URL сохранён!\n\n"
        f"📄 <b>Шаг 4/6:</b> Выберите тип страницы\n\n"
        f"<b>📄 Статическая (HTML)</b>\n"
        f"Контент загружается сразу, быстрее работает\n\n"
        f"<b>⚡ Динамическая (Browser)</b>\n"
        f"Контент появляется после JavaScript, надёжнее\n\n"
        f"<b>❓ Не знаю</b>\n"
        f"Бот попробует определить автоматически",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_announcement_page_type)


@router.callback_query(AddLinkStates.waiting_for_announcement_page_type, F.data.startswith("announcement_page_"))
async def process_announcement_page_type(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа страницы для анонсов"""
    page_type = callback.data.replace("announcement_page_", "")
    
    # Маппинг на тип парсинга
    page_type_to_parsing = {
        'html': 'html',
        'browser': 'browser',
        'auto': 'combined'  # Автоматический = комбинированный
    }
    parsing_type = page_type_to_parsing.get(page_type, 'combined')
    await state.update_data(parsing_type=parsing_type, selected_parser='announcement')
    
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    # Показываем выбор стратегии
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔍 Любые изменения", callback_data="announcement_strategy_any_change"))
    builder.add(InlineKeyboardButton(text="🎯 Изменения в элементе", callback_data="announcement_strategy_element_change"))
    builder.add(InlineKeyboardButton(text="📝 Любое ключевое слово", callback_data="announcement_strategy_any_keyword"))
    builder.add(InlineKeyboardButton(text="📚 Все ключевые слова", callback_data="announcement_strategy_all_keywords"))
    builder.add(InlineKeyboardButton(text="⚡ Regex паттерн", callback_data="announcement_strategy_regex"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_page_type_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 1, 1, 2)
    
    page_type_display = {
        'html': '📄 Статическая',
        'browser': '⚡ Динамическая',
        'auto': '❓ Автоопределение'
    }.get(page_type, 'Неизвестно')
    
    await callback.message.edit_text(
        f"✅ Тип страницы: <b>{page_type_display}</b>\n\n"
        f"🎯 <b>Шаг 5/6:</b> Выберите стратегию отслеживания\n\n"
        f"<b>🔍 Любые изменения</b> - уведомления о любых изменениях\n"
        f"<b>🎯 Изменения в элементе</b> - отслеживание конкретного элемента\n"
        f"<b>📝 Любое ключевое слово</b> - поиск любого из заданных слов\n"
        f"<b>📚 Все ключевые слова</b> - все слова должны присутствовать\n"
        f"<b>⚡ Regex</b> - поиск по регулярному выражению",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_announcement_strategy)
    await callback.answer()


@router.callback_query(AddLinkStates.waiting_for_announcement_strategy, F.data.startswith("announcement_strategy_"))
async def process_announcement_strategy_new(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора стратегии для анонсов (новый flow)"""
    strategy = callback.data.replace("announcement_strategy_", "")
    
    await state.update_data(announcement_strategy=strategy)
    
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    
    # В зависимости от стратегии запрашиваем дополнительные данные или переходим к интервалу
    if strategy == 'any_change':
        # Для "любые изменения" - сразу к интервалу
        presets = [
            ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
            ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
            ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
        ]
        
        for text, seconds in presets:
            builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_strategy_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(3, 3, 3, 2)
        
        await callback.message.edit_text(
            f"✅ Стратегия: <b>🔍 Любые изменения</b>\n\n"
            f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
            f"<b>Имя:</b> {custom_name}\n"
            f"<b>Категория:</b> Анонсы\n"
            f"<b>Стратегия:</b> Любые изменения\n\n"
            f"Как часто проверять страницу?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_interval)
        
    elif strategy == 'element_change':
        # Запрашиваем CSS селектор
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_strategy_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Стратегия: <b>🎯 Изменения в элементе</b>\n\n"
            f"🎯 <b>Шаг 6/7:</b> Введите CSS селектор элемента\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>.announcement-list</code>\n"
            f"• <code>#news-container</code>\n"
            f"• <code>div.news-item:first-child</code>\n\n"
            f"Бот будет отслеживать изменения только в этом элементе.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_selector)
        
    elif strategy in ['any_keyword', 'all_keywords']:
        # Запрашиваем ключевые слова
        strategy_name = "Любое ключевое слово" if strategy == 'any_keyword' else "Все ключевые слова"
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_strategy_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Стратегия: <b>📝 {strategy_name}</b>\n\n"
            f"📝 <b>Шаг 6/7:</b> Введите ключевые слова\n\n"
            f"Введите слова через запятую:\n"
            f"<code>airdrop, launchpad, listing, token</code>\n\n"
            f"Бот будет искать эти слова в анонсах.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_keywords)
        
    elif strategy == 'regex':
        # Запрашиваем regex паттерн
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_strategy_announcement"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"✅ Стратегия: <b>⚡ Regex паттерн</b>\n\n"
            f"⚡ <b>Шаг 6/7:</b> Введите регулярное выражение\n\n"
            f"<b>Примеры:</b>\n"
            f"• <code>(?i)airdrop|launchpad</code>\n"
            f"• <code>\\b[A-Z]{{3,5}}\\b.*listing</code>\n\n"
            f"Бот будет искать совпадения с этим паттерном.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_announcement_regex)
    
    await callback.answer()


# Кнопки "Назад" для анонсов
@router.callback_query(F.data == "back_to_name_announcement")
async def back_to_name_announcement(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия для анонсов"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> Анонсы\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название\n\n"
        f"Примеры:\n"
        f"• <i>Binance Announcements</i>\n"
        f"• <i>OKX News</i>\n"
        f"• <i>Gate.io Updates</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data == "back_to_source_announcement")
async def back_to_source_announcement(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору источника для анонсов"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🌐 Веб-страница", callback_data="announcement_source_web"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="announcement_source_telegram"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2, 2)
    
    await callback.message.edit_text(
        f"✅ Название: <b>{custom_name}</b>\n\n"
        f"📢 <b>Шаг 2/5:</b> Выберите источник данных\n\n"
        f"<b>🌐 Веб-страница</b> - мониторинг страницы анонсов\n"
        f"<b>📱 Telegram</b> - мониторинг канала по ключевым словам",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parsing_type)
    await callback.answer()


@router.callback_query(F.data == "back_to_url_announcement")
async def back_to_url_announcement(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу URL для анонсов"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_source_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"✅ Источник: <b>🌐 Веб-страница</b>\n\n"
        f"🔗 <b>Шаг 3/6:</b> Введите ссылку на страницу анонсов\n\n"
        f"<b>Примеры:</b>\n"
        f"• <code>https://www.binance.com/en/support/announcement</code>\n"
        f"• <code>https://www.okx.com/help/section/announcements-latest-announcements</code>\n\n"
        f"💡 Далее вы сможете выбрать тип страницы и стратегию отслеживания.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_announcement_url)
    await callback.answer()


@router.callback_query(F.data == "back_to_page_type_announcement")
async def back_to_page_type_announcement(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору типа страницы для анонсов"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📄 Статическая (HTML)", callback_data="announcement_page_html"))
    builder.add(InlineKeyboardButton(text="⚡ Динамическая (Browser)", callback_data="announcement_page_browser"))
    builder.add(InlineKeyboardButton(text="❓ Не знаю", callback_data="announcement_page_auto"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 2)
    
    await callback.message.edit_text(
        f"📄 <b>Шаг 4/6:</b> Выберите тип страницы\n\n"
        f"<b>📄 Статическая (HTML)</b>\n"
        f"Контент загружается сразу, быстрее работает\n\n"
        f"<b>⚡ Динамическая (Browser)</b>\n"
        f"Контент появляется после JavaScript, надёжнее\n\n"
        f"<b>❓ Не знаю</b>\n"
        f"Бот попробует определить автоматически",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_announcement_page_type)
    await callback.answer()


@router.callback_query(F.data == "back_to_strategy_announcement")
async def back_to_strategy_announcement(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору стратегии для анонсов"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔍 Любые изменения", callback_data="announcement_strategy_any_change"))
    builder.add(InlineKeyboardButton(text="🎯 Изменения в элементе", callback_data="announcement_strategy_element_change"))
    builder.add(InlineKeyboardButton(text="📝 Любое ключевое слово", callback_data="announcement_strategy_any_keyword"))
    builder.add(InlineKeyboardButton(text="📚 Все ключевые слова", callback_data="announcement_strategy_all_keywords"))
    builder.add(InlineKeyboardButton(text="⚡ Regex паттерн", callback_data="announcement_strategy_regex"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_page_type_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 1, 1, 2)
    
    await callback.message.edit_text(
        f"🎯 <b>Шаг 5/6:</b> Выберите стратегию отслеживания\n\n"
        f"<b>🔍 Любые изменения</b> - уведомления о любых изменениях\n"
        f"<b>🎯 Изменения в элементе</b> - отслеживание конкретного элемента\n"
        f"<b>📝 Любое ключевое слово</b> - поиск любого из заданных слов\n"
        f"<b>📚 Все ключевые слова</b> - все слова должны присутствовать\n"
        f"<b>⚡ Regex</b> - поиск по регулярному выражению",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_announcement_strategy)
    await callback.answer()


# =============================================================================
# ОБРАБОТЧИКИ ДЛЯ СТЕЙКИНГА - упрощённый процесс добавления
# =============================================================================

@router.callback_query(AddLinkStates.waiting_for_min_apr, F.data.startswith("staking_apr_"))
async def process_staking_apr_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора минимального APR для стейкинга"""
    apr_value = int(callback.data.replace("staking_apr_", ""))
    
    # Сохраняем APR (0 означает без фильтра)
    await state.update_data(min_apr=apr_value if apr_value > 0 else None)
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    
    # Показываем выбор типов стейкинга
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📈 Flexible (гибкий)", callback_data="staking_type_flexible"))
    builder.add(InlineKeyboardButton(text="🔒 Fixed (фиксированный)", callback_data="staking_type_fixed"))
    builder.add(InlineKeyboardButton(text="✅ Оба типа", callback_data="staking_type_both"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_apr_staking"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 2)
    
    apr_display = f"{apr_value}%" if apr_value > 0 else "0% (все)"
    
    await callback.message.edit_text(
        f"✅ Минимальный APR: <b>{apr_display}</b>\n\n"
        f"📊 <b>Шаг 4/4:</b> Выберите типы стейкинга\n\n"
        f"<b>📈 Flexible</b> - можно вывести в любое время\n"
        f"<b>🔒 Fixed</b> - заблокирован на период\n"
        f"<b>✅ Оба типа</b> - показывать все (рекомендуется)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_statuses)
    await callback.answer()


@router.callback_query(AddLinkStates.waiting_for_statuses, F.data.startswith("staking_type_"))
async def process_staking_type_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа стейкинга - переход к интервалу"""
    staking_type = callback.data.replace("staking_type_", "")
    
    # Конвертируем в types_filter формат
    types_filter = None
    if staking_type == 'flexible':
        types_filter = '["Flexible"]'
    elif staking_type == 'fixed':
        types_filter = '["Fixed"]'
    # both = None (без фильтра)
    
    await state.update_data(types_filter=types_filter, staking_type_selected=staking_type)
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    min_apr = data.get('min_apr')
    
    # Показываем выбор интервала
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]
    
    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_type_staking"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(3, 3, 3, 2)
    
    # Формируем информацию о настройках
    apr_display = f"{min_apr}%" if min_apr else "0% (все)"
    type_display = {
        'flexible': '📈 Flexible',
        'fixed': '🔒 Fixed', 
        'both': '✅ Оба типа'
    }.get(staking_type, staking_type)
    
    await callback.message.edit_text(
        f"✅ Тип стейкинга: <b>{type_display}</b>\n\n"
        f"⏰ <b>Последний шаг:</b> Выберите интервал проверки\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Минимальный APR:</b> {apr_display}\n"
        f"<b>Типы:</b> {type_display}\n\n"
        f"Как часто проверять стейкинги?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


# Кнопки "Назад" для стейкинга
@router.callback_query(F.data == "back_to_name_staking")
async def back_to_name_staking(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия для стейкинга"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> Стейкинг\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название биржи\n\n"
        f"Примеры:\n"
        f"• <i>Bybit Staking</i>\n"
        f"• <i>Kucoin Earn</i>\n"
        f"• <i>OKX Savings</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data == "back_to_api_url_staking")
async def back_to_api_url_staking(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу API URL для стейкинга"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name_staking"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"✅ Название: <b>{custom_name}</b>\n\n"
        f"📡 <b>Шаг 2/4:</b> Введите API ссылку для стейкинга\n\n"
        f"<b>Примеры API ссылок:</b>\n"
        f"• <code>https://api.bybit.com/v5/earn/product?category=FlexibleSaving</code>\n"
        f"• <code>https://www.kucoin.com/_api/earn-saving/products</code>\n"
        f"• <code>https://www.okx.com/priapi/v1/earn/staking/products</code>\n\n"
        f"💡 Парсер автоматически определит биржу по URL.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_api_url)
    await callback.answer()


@router.callback_query(F.data == "back_to_apr_staking")
async def back_to_apr_staking(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору APR для стейкинга"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="0% (все)", callback_data="staking_apr_0"))
    builder.add(InlineKeyboardButton(text="5%", callback_data="staking_apr_5"))
    builder.add(InlineKeyboardButton(text="10%", callback_data="staking_apr_10"))
    builder.add(InlineKeyboardButton(text="20%", callback_data="staking_apr_20"))
    builder.add(InlineKeyboardButton(text="50%", callback_data="staking_apr_50"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url_staking"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(3, 2, 2)
    
    await callback.message.edit_text(
        f"✅ Название: <b>{custom_name}</b>\n\n"
        f"📊 <b>Шаг 3/4:</b> Минимальный APR для уведомлений\n\n"
        f"Бот будет уведомлять только о стейкингах с APR выше выбранного значения.\n\n"
        f"💡 <b>0% (все)</b> - показывать все стейкинги\n"
        f"💡 <b>5-10%</b> - только интересные предложения\n"
        f"💡 <b>20-50%</b> - только высокодоходные",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_min_apr)
    await callback.answer()


@router.callback_query(F.data == "back_to_type_staking")
async def back_to_type_staking(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору типа стейкинга"""
    data = await state.get_data()
    min_apr = data.get('min_apr')
    apr_display = f"{min_apr}%" if min_apr else "0% (все)"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📈 Flexible (гибкий)", callback_data="staking_type_flexible"))
    builder.add(InlineKeyboardButton(text="🔒 Fixed (фиксированный)", callback_data="staking_type_fixed"))
    builder.add(InlineKeyboardButton(text="✅ Оба типа", callback_data="staking_type_both"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_apr_staking"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 2)
    
    await callback.message.edit_text(
        f"✅ Минимальный APR: <b>{apr_display}</b>\n\n"
        f"📊 <b>Шаг 4/4:</b> Выберите типы стейкинга\n\n"
        f"<b>📈 Flexible</b> - можно вывести в любое время\n"
        f"<b>🔒 Fixed</b> - заблокирован на период\n"
        f"<b>✅ Оба типа</b> - показывать все (рекомендуется)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_statuses)
    await callback.answer()


# ОБРАБОТЧИКИ ДЛЯ ДОБАВЛЕНИЯ HTML ССЫЛКИ

@router.callback_query(F.data == "skip_html_url")
async def skip_html_url(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Пропустить' HTML - переходим к выбору парсера"""
    data = await state.get_data()
    parsing_type = data.get('parsing_type', 'combined')
    
    # Для combined и telegram - пропускаем выбор парсера
    if parsing_type in ['combined', 'telegram']:
        custom_name = data.get('custom_name')
        await _show_interval_selection(callback, state, custom_name)
        return
    
    # Для остальных (api, html, browser) - показываем выбор парсера
    await _show_parser_selection(callback, state)

@router.message(AddLinkStates.waiting_for_html_url)
async def process_html_url_input(message: Message, state: FSMContext):
    """Обработка ввода HTML ссылки - переходим к выбору парсера"""
    html_url = message.text.strip()

    if not html_url.startswith(('http://', 'https://')):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    # Сохраняем HTML URL
    await state.update_data(html_url=html_url)

    data = await state.get_data()
    parsing_type = data.get('parsing_type', 'combined')
    
    # Для combined и telegram - пропускаем выбор парсера
    if parsing_type in ['combined', 'telegram']:
        custom_name = data.get('custom_name')
        await _show_interval_selection_msg(message, state, custom_name)
        return
    
    # Для остальных (api, html, browser) - показываем выбор парсера
    await _show_parser_selection_msg(message, state)

# =============================================================================
# ОБРАБОТЧИКИ ДЛЯ TELEGRAM ПАРСИНГА
# =============================================================================

@router.message(AddLinkStates.waiting_for_telegram_channel)
async def process_telegram_channel_input(message: Message, state: FSMContext):
    """Обработка ввода Telegram-канала"""
    channel_input = message.text.strip()

    # Нормализуем ввод канала
    channel_username = channel_input

    # Убираем префикс https://
    if channel_username.startswith('https://t.me/'):
        channel_username = channel_username.replace('https://t.me/', '')
    elif channel_username.startswith('http://t.me/'):
        channel_username = channel_username.replace('http://t.me/', '')
    elif channel_username.startswith('t.me/'):
        channel_username = channel_username.replace('t.me/', '')

    # Добавляем @ если его нет
    if not channel_username.startswith('@'):
        channel_username = '@' + channel_username

    # Сохраняем канал
    await state.update_data(telegram_channel=channel_username)

    # Создаем кнопки
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)

    await message.answer(
        f"✅ Канал сохранен: <b>{channel_username}</b>\n\n"
        f"🔑 <b>Шаг 4/5:</b> Введите ключевые слова для поиска\n\n"
        f"Введите слова или фразы через запятую, по которым бот будет искать сообщения в канале.\n\n"
        f"<b>Примеры:</b>\n"
        f"<code>airdrop, промо, campaign, giveaway</code>\n"
        f"<code>listing, IEO, launchpad</code>\n"
        f"<code>staking, earn, APR</code>\n\n"
        f"Бот будет отправлять уведомления о сообщениях, содержащих эти слова.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_telegram_keywords)

@router.message(AddLinkStates.waiting_for_telegram_keywords)
async def process_telegram_keywords_input(message: Message, state: FSMContext):
    """Обработка ввода ключевых слов для Telegram"""
    keywords_input = message.text.strip()

    if not keywords_input:
        await message.answer("❌ Ключевые слова не могут быть пустыми. Попробуйте снова:")
        return

    # Разбиваем по запятой и очищаем
    keywords = [kw.strip() for kw in keywords_input.split(',') if kw.strip()]

    if not keywords:
        await message.answer("❌ Не удалось распознать ключевые слова. Введите их через запятую:")
        return

    # Сохраняем ключевые слова
    await state.update_data(telegram_keywords=keywords)

    data = await state.get_data()
    custom_name = data.get('custom_name')
    telegram_channel = data.get('telegram_channel')

    keywords_str = ", ".join([f"<code>{kw}</code>" for kw in keywords])

    # Теперь показываем выбор Telegram аккаунта
    from data.models import TelegramAccount

    with get_db_session() as db:
        accounts = db.query(TelegramAccount).filter(
            TelegramAccount.is_active == True,
            TelegramAccount.is_authorized == True,
            TelegramAccount.is_blocked == False
        ).all()

        if not accounts:
            await message.answer(
                "❌ <b>Нет доступных Telegram аккаунтов</b>\n\n"
                "Добавьте аккаунт через:\n"
                "🛡️ Обход блокировок → 📱 Telegram API",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Создаем кнопки выбора аккаунта
        builder = InlineKeyboardBuilder()
        
        for acc in accounts:
            # Статистика нагрузки
            from sqlalchemy import func
            load_count = db.query(func.count(ApiLink.id)).filter(
                ApiLink.telegram_account_id == acc.id,
                ApiLink.is_active == True,
                ApiLink.parsing_type == 'telegram'
            ).scalar()

            button_text = f"{acc.name} (+{acc.phone_number}) [{load_count} ссылок]"
            builder.add(InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_tg_acc_{acc.id}"
            ))

        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_telegram_channel"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(1, 2)

        await message.answer(
            f"✅ Ключевые слова сохранены!\n\n"
            f"📱 <b>Шаг 5/6: Выберите Telegram аккаунт</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n"
            f"<b>Канал:</b> {telegram_channel}\n"
            f"<b>Ключевые слова:</b> {keywords_str}\n\n"
            f"Выберите аккаунт для парсинга этого канала:\n"
            f"<i>[N ссылок] - количество уже назначенных ссылок на аккаунт</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_telegram_account)

# Обработчик выбора Telegram аккаунта
@router.callback_query(AddLinkStates.waiting_for_telegram_account, F.data.startswith("select_tg_acc_"))
async def process_telegram_account_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора Telegram аккаунта для новой ссылки"""
    try:
        account_id = int(callback.data.split("_")[-1])
        
        # Сохраняем выбранный аккаунт
        await state.update_data(telegram_account_id=account_id)
        
        data = await state.get_data()
        custom_name = data.get('custom_name')
        telegram_channel = data.get('telegram_channel')
        telegram_keywords = data.get('telegram_keywords', [])
        
        # Получаем информацию об аккаунте
        from data.models import TelegramAccount
        with get_db_session() as db:
            account = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
            if not account:
                await callback.answer("❌ Аккаунт не найден", show_alert=True)
                return
            
            account_name = f"{account.name} (+{account.phone_number})"
        
        keywords_str = ", ".join([f"<code>{kw}</code>" for kw in telegram_keywords])
        
        # Создаем кнопки выбора интервала
        builder = InlineKeyboardBuilder()
        presets = [
            ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
            ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
            ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
        ]

        for text, seconds in presets:
            builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_telegram_keywords"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(2, 2, 2, 2, 1, 2)

        await callback.message.edit_text(
            f"✅ Аккаунт выбран: <b>{account_name}</b>\n\n"
            f"⏰ <b>Шаг 6/6: Выберите интервал проверки</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n"
            f"<b>Канал:</b> {telegram_channel}\n"
            f"<b>Ключевые слова:</b> {keywords_str}\n"
            f"<b>Аккаунт парсера:</b> {account_name}\n\n"
            f"Как часто проверять этот канал на новые промоакции?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_interval)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при выборе Telegram аккаунта: {e}")
        await callback.answer("❌ Ошибка при выборе аккаунта", show_alert=True)

# Обработчик для кнопки "Назад" к выбору аккаунта
@router.callback_query(F.data == "back_to_telegram_keywords")
async def back_to_telegram_keywords(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору Telegram аккаунта"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    telegram_channel = data.get('telegram_channel')
    telegram_keywords = data.get('telegram_keywords', [])
    
    keywords_str = ", ".join([f"<code>{kw}</code>" for kw in telegram_keywords])
    
    from data.models import TelegramAccount
    with get_db_session() as db:
        accounts = db.query(TelegramAccount).filter(
            TelegramAccount.is_active == True,
            TelegramAccount.is_authorized == True,
            TelegramAccount.is_blocked == False
        ).all()

        if not accounts:
            await callback.message.edit_text(
                "❌ <b>Нет доступных Telegram аккаунтов</b>\n\n"
                "Добавьте аккаунт через:\n"
                "🛡️ Обход блокировок → 📱 Telegram API",
                parse_mode="HTML"
            )
            await state.clear()
            await callback.answer()
            return

        # Создаем кнопки выбора аккаунта
        builder = InlineKeyboardBuilder()
        
        for acc in accounts:
            from sqlalchemy import func
            load_count = db.query(func.count(ApiLink.id)).filter(
                ApiLink.telegram_account_id == acc.id,
                ApiLink.is_active == True,
                ApiLink.parsing_type == 'telegram'
            ).scalar()

            button_text = f"{acc.name} (+{acc.phone_number}) [{load_count} ссылок]"
            builder.add(InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_tg_acc_{acc.id}"
            ))

        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_telegram_channel"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
        builder.adjust(1, 2)

        await callback.message.edit_text(
            f"📱 <b>Шаг 5/6: Выберите Telegram аккаунт</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n"
            f"<b>Канал:</b> {telegram_channel}\n"
            f"<b>Ключевые слова:</b> {keywords_str}\n\n"
            f"Выберите аккаунт для парсинга этого канала:\n"
            f"<i>[N ссылок] - количество уже назначенных ссылок на аккаунт</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_telegram_account)
        await callback.answer()

# Обработчик для кнопки "Назад" от ввода ключевых слов
@router.callback_query(F.data == "back_to_telegram_channel")
async def back_to_telegram_channel(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу Telegram-канала"""
    # Создаем кнопки
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2)

    await callback.message.edit_text(
        f"📱 <b>Шаг 3/5:</b> Введите имя или ссылку Telegram-канала\n\n"
        f"Примеры:\n"
        f"<code>@binance</code>\n"
        f"<code>https://t.me/binance</code>\n"
        f"<code>t.me/binance</code>\n\n"
        f"Бот будет мониторить сообщения из этого канала по ключевым словам.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_telegram_channel)
    await callback.answer()

# =============================================================================
# ОБРАБОТЧИКИ "НАЗАД" ДЛЯ ДОБАВЛЕНИЯ ССЫЛКИ
# =============================================================================

@router.callback_query(F.data == "back_to_category")
async def back_to_category(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору категории"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⭐ Избранные", callback_data="add_category_favorite"))
    builder.add(InlineKeyboardButton(text="🚀 Лаучи", callback_data="add_category_launches"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1, 2, 2, 1)

    await callback.message.edit_text(
        "🔗 <b>Добавление новой ссылки</b>\n\n"
        "🗂️ <b>Шаг 1:</b> Выберите категорию ссылки:\n\n"
        "⭐ <b>Избранные</b> - важные ссылки для быстрого доступа",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_category)
    await callback.answer()


async def _show_interval_selection(callback: CallbackQuery, state: FSMContext, custom_name: str):
    """Вспомогательная функция для показа выбора интервала (через callback)"""
    data = await state.get_data()
    selected_parser = data.get('selected_parser', 'auto')
    parser_name = PARSERS_CONFIG.get(selected_parser, {}).get('name', 'Автоматический')
    parser_emoji = PARSERS_CONFIG.get(selected_parser, {}).get('emoji', '🤖')
    
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]

    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parser_selection"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 2, 2, 1, 2)

    await callback.message.edit_text(
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


async def _show_interval_selection_msg(message: Message, state: FSMContext, custom_name: str):
    """Вспомогательная функция для показа выбора интервала (через message)"""
    data = await state.get_data()
    selected_parser = data.get('selected_parser', 'auto')
    parser_name = PARSERS_CONFIG.get(selected_parser, {}).get('name', 'Автоматический')
    parser_emoji = PARSERS_CONFIG.get(selected_parser, {}).get('emoji', '🤖')
    
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]

    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 2, 2, 1, 2)

    await message.answer(
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Парсер:</b> {parser_emoji} {parser_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


async def _show_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Вспомогательная функция для показа выбора парсера"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'launches')
    html_url = data.get('html_url')
    api_url = data.get('api_url')
    
    # URL для определения доступных парсеров
    url_to_check = html_url or api_url or ''
    
    # Получаем список доступных парсеров
    parsers = get_available_parsers_for_context(category, url_to_check)
    
    # Формируем клавиатуру
    builder = InlineKeyboardBuilder()
    recommended_text = ""
    
    for parser_id, config, is_recommended in parsers:
        emoji = config['emoji']
        name = config['name']
        
        if is_recommended:
            btn_text = f"{emoji} {name} ⭐"
            recommended_text = f"\n\n⭐ <b>Рекомендуется:</b> {emoji} {name}"
        else:
            btn_text = f"{emoji} {name}"
        
        builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"select_parser_{parser_id}"))
    
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_url_input"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1)
    
    # Формируем текст категории
    category_names = {
        'launches': 'Лаучи',
        'launchpad': 'Лаунчпады',
        'launchpool': 'Лаунчпулы',
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'announcement': 'Анонс'
    }
    category_display = category_names.get(category, category)
    
    await callback.message.edit_text(
        f"🔧 <b>Шаг 4/5: Выберите парсер</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> {category_display}\n"
        f"<b>URL:</b> <code>{url_to_check[:50]}{'...' if len(url_to_check) > 50 else ''}</code>"
        f"{recommended_text}\n\n"
        f"Выберите парсер для обработки данных:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parser_selection)
    await callback.answer()


async def _show_parser_selection_msg(message: Message, state: FSMContext):
    """Вспомогательная функция для показа выбора парсера (через message)"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'launches')
    html_url = data.get('html_url')
    api_url = data.get('api_url')
    
    # URL для определения доступных парсеров
    url_to_check = html_url or api_url or ''
    
    # Получаем список доступных парсеров
    parsers = get_available_parsers_for_context(category, url_to_check)
    
    # Формируем клавиатуру
    builder = InlineKeyboardBuilder()
    recommended_text = ""
    
    for parser_id, config, is_recommended in parsers:
        emoji = config['emoji']
        name = config['name']
        
        if is_recommended:
            btn_text = f"{emoji} {name} ⭐"
            recommended_text = f"\n\n⭐ <b>Рекомендуется:</b> {emoji} {name}"
        else:
            btn_text = f"{emoji} {name}"
        
        builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"select_parser_{parser_id}"))
    
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(1)
    
    # Формируем текст категории
    category_names = {
        'launches': 'Лаучи',
        'launchpad': 'Лаунчпады',
        'launchpool': 'Лаунчпулы',
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'announcement': 'Анонс'
    }
    category_display = category_names.get(category, category)
    
    await message.answer(
        f"🔧 <b>Шаг 4/5: Выберите парсер</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Категория:</b> {category_display}\n"
        f"<b>URL:</b> <code>{url_to_check[:50]}{'...' if len(url_to_check) > 50 else ''}</code>"
        f"{recommended_text}\n\n"
        f"Выберите парсер для обработки данных:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parser_selection)


@router.callback_query(AddLinkStates.waiting_for_parser_selection, F.data.startswith("select_parser_"))
async def process_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора парсера"""
    parser_id = callback.data.replace("select_parser_", "")
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    
    # Сохраняем выбранный парсер
    await state.update_data(selected_parser=parser_id)
    
    # Для специальных парсеров также сохраняем в special_parser
    if parser_id in ['weex', 'okx_boost']:
        await state.update_data(special_parser=parser_id)
    elif parser_id == 'auto':
        await state.update_data(special_parser=None)
    else:
        # Для staking, announcement, universal - сохраняем в selected_parser
        await state.update_data(special_parser=None)
    
    parser_name = PARSERS_CONFIG.get(parser_id, {}).get('name', parser_id)
    logger.info(f"🔧 Выбран парсер '{parser_name}' для '{custom_name}'")
    
    # Переходим к выбору интервала
    await _show_interval_selection(callback, state, custom_name)


@router.callback_query(F.data == "back_to_parser_selection")
async def back_to_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору парсера"""
    data = await state.get_data()
    parsing_type = data.get('parsing_type', 'combined')
    
    # Если combined или telegram - возвращаемся к URL
    if parsing_type in ['combined', 'telegram']:
        await callback.answer("Выбор парсера недоступен для этого типа", show_alert=True)
        return
    
    await _show_parser_selection(callback, state)


@router.callback_query(F.data == "back_to_url_input")
async def back_to_url_input(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу HTML URL"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_url"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🌐 <b>Шаг 4/5:</b> Введите HTML ссылку (опционально)\n\n"
        f"HTML используется как резервный метод, если API не сработает.\n\n"
        f"<b>Введите ссылку</b> или нажмите <b>Пропустить</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)
    await callback.answer()


@router.callback_query(F.data.startswith("special_parser_"))
async def process_special_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора специального парсера (legacy)"""
    parser_id = callback.data.replace("special_parser_", "")
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    
    if parser_id == "none":
        # Стандартный парсер
        await state.update_data(special_parser=None, selected_parser='auto')
        logger.info(f"📋 Выбран стандартный парсер для '{custom_name}'")
    else:
        # Специальный парсер
        await state.update_data(special_parser=parser_id, selected_parser=parser_id)
        parser_name = SPECIAL_PARSERS_CONFIG.get(parser_id, {}).get('name', parser_id)
        logger.info(f"🔧 Выбран специальный парсер '{parser_name}' для '{custom_name}'")
    
    # Переходим к выбору интервала
    await _show_interval_selection(callback, state, custom_name)


@router.callback_query(F.data == "back_to_name")
async def back_to_name(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия биржи"""
    data = await state.get_data()
    category = data.get('category', 'launches')

    category_names = {
        'launches': 'Лаучи',
        'launchpad': 'Лаунчпады',
        'launchpool': 'Лаунчпулы',
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'announcement': 'Анонс'
    }
    category_display = category_names.get(category, category)

    # Добавляем кнопку "Назад"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_category"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2)

    await callback.message.edit_text(
        f"🔗 <b>Добавление новой ссылки</b>\n\n"
        f"✅ <b>Категория:</b> {category_display}\n\n"
        f"🏷️ <b>Шаг 2:</b> Введите название биржи\n\n"
        f"Примеры:\n"
        f"• <i>Bybit Promotions</i>\n"
        f"• <i>MEXC Launchpad</i>\n"
        f"• <i>OKX Earn</i>\n\n"
        f"Это название поможет вам легко находить ссылку в списке.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()

@router.callback_query(F.data == "back_to_parsing_type")
async def back_to_parsing_type(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору типа парсинга"""
    data = await state.get_data()
    custom_name = data.get('custom_name', '')

    # Создаем кнопки для выбора типа парсинга
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Комбинированный (API + HTML + Browser)", callback_data="parsing_type_combined"))
    builder.add(InlineKeyboardButton(text="📡 Только API", callback_data="parsing_type_api"))
    builder.add(InlineKeyboardButton(text="🌐 Только HTML", callback_data="parsing_type_html"))
    builder.add(InlineKeyboardButton(text="🌐 Только Browser", callback_data="parsing_type_browser"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data="parsing_type_telegram"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_name"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1, 1, 1, 1, 1, 2)

    await callback.message.edit_text(
        f"✅ Название сохранено: <b>{custom_name}</b>\n\n"
        f"🎯 <b>Шаг 2/5:</b> Выберите тип парсинга\n\n"
        f"<b>Типы парсинга:</b>\n"
        f"• <b>Комбинированный</b> - пробует все методы (Browser → API → HTML)\n"
        f"• <b>Только API</b> - быстрый, но может быть заблокирован\n"
        f"• <b>Только HTML</b> - стабильный для статических страниц\n"
        f"• <b>Только Browser</b> - обходит капчи и динамический контент\n"
        f"• <b>Telegram</b> - мониторинг Telegram-каналов по ключевым словам\n\n"
        f"Рекомендуется <b>Комбинированный</b> для лучшей надежности.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_parsing_type)
    await callback.answer()

@router.callback_query(F.data == "back_to_api_url")
async def back_to_api_url(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу API URL"""
    data = await state.get_data()
    parsing_type = data.get('parsing_type', 'combined')

    # Создаем клавиатуру с кнопками "Назад" и "Отмена"
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))
    cancel_builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    cancel_builder.adjust(2)

    if parsing_type == 'api':
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Только API</b>\n\n"
            f"📡 <b>Шаг 3/5:</b> Введите API ссылку\n\n"
            f"Пример:\n"
            f"<code>https://api.bybit.com/v5/promotion/list</code>\n\n"
            f"API ссылка используется для автоматического парсинга.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_api_url)
    else:  # combined
        await callback.message.edit_text(
            f"✅ Выбран тип: <b>Комбинированный</b>\n\n"
            f"📡 <b>Шаг 3/5:</b> Введите API ссылку\n\n"
            f"Пример:\n"
            f"<code>https://api.bybit.com/v5/promotion/list</code>\n\n"
            f"API ссылка используется для автоматического парсинга.\n"
            f"Далее вы сможете добавить HTML/Browser URL как fallback.",
            reply_markup=cancel_builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_api_url)

    await callback.answer()

@router.callback_query(F.data == "back_to_html_url")
async def back_to_html_url(callback: CallbackQuery, state: FSMContext):
    """Возврат к шагу ввода HTML ссылки"""
    data = await state.get_data()
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_url"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)

    await callback.message.edit_text(
        f"🌐 <b>Шаг 4/5:</b> Введите HTML ссылку (опционально)\n\n"
        f"HTML используется как резервный метод, если API не сработает.\n\n"
        f"<b>Введите ссылку</b> или нажмите <b>Пропустить</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)
    await callback.answer()
    await state.set_state(AddLinkStates.waiting_for_example_url)
    await callback.answer()

@router.callback_query(F.data == "cancel_add_link")
async def cancel_add_link(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления ссылки"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Добавление ссылки отменено\n\nЧто вы хотите сделать?",
        reply_markup=get_cancel_keyboard_with_navigation()
    )
    await callback.answer()

@router.message(AddLinkStates.waiting_for_example_url)
async def process_example_url_input(message: Message, state: FSMContext):
    """Обработка ввода примера ссылки на промоакцию"""
    example_url = message.text.strip()

    if not example_url.startswith(('http://', 'https://')):
        await message.answer("❌ URL должен начинаться с http:// или https://\nПопробуйте снова:")
        return

    # Сохраняем example URL
    await state.update_data(example_url=example_url)

    data = await state.get_data()
    custom_name = data.get('custom_name')
    api_url = data.get('api_url')

    # Показываем сообщение о процессе анализа
    analysis_msg = await message.answer(
        "🔍 <b>Анализирую ссылку...</b>\n\n"
        "1. Запрашиваю API...\n"
        "2. Ищу соответствующую промоакцию...\n"
        "3. Создаю шаблон...",
        parse_mode="HTML"
    )

    try:
        # Запрашиваем API и парсим промоакции
        from parsers.universal_parser import UniversalParser
        parser = UniversalParser(api_url)
        api_promotions = parser.get_promotions()

        if not api_promotions:
            await analysis_msg.edit_text(
                "⚠️ <b>Не удалось получить данные из API</b>\n\n"
                "Возможно, API временно недоступен или требует специальных заголовков.\n"
                "Шаблон не был создан, но ссылка будет добавлена.",
                parse_mode="HTML"
            )
        else:
            # Определяем exchange и тип ДО анализа
            from urllib.parse import urlparse
            parsed = urlparse(example_url)
            domain = parsed.netloc.replace('www.', '')
            # Берем предпоследнюю часть домена (для web3.okx.com берем okx, а не web3)
            exchange = domain.split('.')[-2] if len(domain.split('.')) >= 2 else domain.split('.')[0]

            # Определяем тип промоакции из path
            path_parts = [p for p in parsed.path.split('/') if p]
            template_type = path_parts[1] if len(path_parts) > 1 else 'default'

            # Проверяем, существует ли уже шаблон
            url_builder = get_url_builder()
            existing_templates = url_builder.get_template_info(exchange)

            if template_type in existing_templates:
                # Шаблон уже существует - используем его
                await analysis_msg.edit_text(
                    f"ℹ️ <b>Шаблон уже существует</b>\n\n"
                    f"<b>Биржа:</b> {exchange.upper()}\n"
                    f"<b>Тип:</b> {template_type}\n"
                    f"<b>Паттерн:</b> <code>{existing_templates[template_type]['pattern']}</code>\n\n"
                    f"Бот будет использовать существующий шаблон для генерации ссылок.",
                    parse_mode="HTML"
                )
            else:
                # Анализируем URL и создаем шаблон
                analyzer = URLTemplateAnalyzer(example_url, api_promotions)
                template = analyzer.analyze()

                if template:
                    # Сохраняем шаблон
                    url_builder.add_template(exchange, template_type, template)

                    await analysis_msg.edit_text(
                        f"✅ <b>Шаблон успешно создан!</b>\n\n"
                        f"<b>Биржа:</b> {exchange.upper()}\n"
                        f"<b>Тип:</b> {template_type}\n"
                        f"<b>Паттерн:</b> <code>{template['pattern']}</code>\n\n"
                        f"Теперь бот будет автоматически генерировать ссылки для всех промоакций этого типа!",
                        parse_mode="HTML"
                    )
                else:
                    await analysis_msg.edit_text(
                        "⚠️ <b>Не удалось создать шаблон</b>\n\n"
                        "Не найдено достаточно совпадений между URL и данными API.\n"
                        "Ссылка будет добавлена без шаблона.",
                        parse_mode="HTML"
                    )

    except Exception as e:
        logger.error(f"❌ Ошибка анализа примера URL: {e}", exc_info=True)
        await analysis_msg.edit_text(
            f"❌ <b>Ошибка анализа ссылки</b>\n\n"
            f"Детали: {str(e)}\n\n"
            f"Ссылка будет добавлена без шаблона.",
            parse_mode="HTML"
        )

    # Переходим к выбору интервала
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]

    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.adjust(2)

    await message.answer(
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)

# =============================================================================
# ЗАВЕРШЕНИЕ ДОБАВЛЕНИЯ ССЫЛКИ
# =============================================================================

@router.callback_query(AddLinkStates.waiting_for_interval, F.data.startswith("add_interval_"))
async def process_interval_selection(callback: CallbackQuery, state: FSMContext):
    try:
        interval_seconds = int(callback.data.split("_")[2])
        data = await state.get_data()
        api_url = data.get('api_url')
        html_url = data.get('html_url')  # Может быть None
        custom_name = data.get('custom_name')
        parsing_type = data.get('parsing_type', 'combined')  # По умолчанию combined

        # НОВЫЕ ПОЛЯ ФАЗЫ 2:
        category = data.get('category', 'launches')
        page_url = data.get('page_url')
        min_apr = data.get('min_apr')
        statuses_filter = data.get('statuses_filter')
        types_filter = data.get('types_filter')  # НОВОЕ: типы стейкинга (Flexible/Fixed)

        # ПОЛЯ ДЛЯ TELEGRAM:
        telegram_channel = data.get('telegram_channel')
        telegram_keywords = data.get('telegram_keywords', [])
        telegram_account_id = data.get('telegram_account_id')  # НОВОЕ: ID выбранного аккаунта

        # ПОЛЯ ДЛЯ АНОНСОВ:
        announcement_strategy = data.get('announcement_strategy')
        announcement_keywords = data.get('announcement_keywords', [])
        announcement_regex = data.get('announcement_regex')
        announcement_css_selector = data.get('announcement_css_selector')
        
        # СПЕЦИАЛЬНЫЙ ПАРСЕР (новая логика с selected_parser):
        selected_parser = data.get('selected_parser', 'auto')
        # Конвертируем selected_parser в special_parser для БД
        if selected_parser == 'auto':
            special_parser = None  # Автоматический выбор
        elif selected_parser == 'universal':
            special_parser = None  # Универсальный = стандартный
        else:
            special_parser = selected_parser  # staking, announcement, weex, okx_boost

        # ИЗБРАННЫЕ:
        is_favorite = data.get('is_favorite', False)

        def add_link_operation(session):
            # Проверяем дубликаты по URL
            url_to_check = api_url or html_url or telegram_channel
            existing_link = session.query(ApiLink).filter(
                ApiLink.url == url_to_check
            ).first()
            
            if existing_link:
                # Ссылка уже существует
                raise ValueError(f"Ссылка с URL '{url_to_check}' уже существует (ID: {existing_link.id}, Имя: '{existing_link.name}')")
            
            new_link = ApiLink(
                name=custom_name,
                url=api_url or html_url or telegram_channel,  # Для совместимости
                api_url=api_url,  # НОВОЕ
                html_url=html_url,  # НОВОЕ (может быть None)
                parsing_type=parsing_type,  # НОВОЕ: тип парсинга
                check_interval=interval_seconds,
                added_by=callback.from_user.id,
                # НОВЫЕ ПОЛЯ ФАЗЫ 2:
                category=category,
                page_url=page_url,
                min_apr=min_apr,
                statuses_filter=statuses_filter,
                types_filter=types_filter,  # НОВОЕ: типы стейкинга
                # ПОЛЯ ДЛЯ TELEGRAM:
                telegram_channel=telegram_channel,
                telegram_account_id=telegram_account_id,  # НОВОЕ: Назначаем аккаунт
                # ПОЛЯ ДЛЯ АНОНСОВ:
                announcement_strategy=announcement_strategy,
                announcement_regex=announcement_regex,
                announcement_css_selector=announcement_css_selector,
                # СПЕЦИАЛЬНЫЙ ПАРСЕР:
                special_parser=special_parser,
                # ИЗБРАННЫЕ:
                is_favorite=is_favorite
            )
            # Устанавливаем ключевые слова для Telegram
            if telegram_keywords:
                new_link.set_telegram_keywords(telegram_keywords)
            # Устанавливаем ключевые слова для анонсов
            if announcement_keywords:
                new_link.set_announcement_keywords(announcement_keywords)
            session.add(new_link)
            session.flush()
            return new_link

        new_link = atomic_operation(add_link_operation)

        # Для Telegram - автоматическая подписка на канал (в фоновом режиме)
        subscription_info = ""
        telegram_account_info = ""
        
        if parsing_type == 'telegram' and telegram_channel and telegram_account_id:
            # Получаем информацию об аккаунте
            from data.models import TelegramAccount
            with get_db_session() as db:
                account = db.query(TelegramAccount).filter(TelegramAccount.id == telegram_account_id).first()
                if account:
                    telegram_account_info = f"<b>📱 Аккаунт парсера:</b> {account.name} (+{account.phone_number})\n"

            subscription_info = "🔄 Подписка на канал выполняется...\n"

            # Запускаем подписку в фоновом режиме, чтобы не блокировать БД
            async def subscribe_to_channel():
                """Фоновая задача подписки на канал"""
                subscription_success = False
                account_info_str = ""
                
                try:
                    # Небольшая задержка для завершения транзакции БД
                    await asyncio.sleep(1)

                    from parsers.telegram_parser import TelegramParser
                    from data.models import TelegramAccount
                    
                    # Получаем аккаунт для подписки
                    with get_db_session() as db:
                        account = db.query(TelegramAccount).filter(TelegramAccount.id == telegram_account_id).first()
                        if not account:
                            logger.error(f"❌ Telegram аккаунт {telegram_account_id} не найден")
                            return
                        
                        account_info_str = f"{account.name} (+{account.phone_number})"
                    
                    parser = TelegramParser()

                    # Подключаемся к Telegram
                    connected = await parser.connect()

                    if connected:
                        # Подписываемся на канал
                        joined = await parser.join_channel(telegram_channel)

                        if joined:
                            subscription_success = True
                            logger.info(f"✅ Успешно подписан на канал {telegram_channel} через аккаунт {account_info_str}")
                        else:
                            logger.warning(f"⚠️ Не удалось подписаться на канал {telegram_channel}")

                        # Отключаемся
                        await parser.disconnect()
                    else:
                        logger.warning(f"⚠️ Не удалось подключиться к Telegram для подписки на {telegram_channel}")

                except Exception as e:
                    logger.error(f"❌ Ошибка фоновой подписки на Telegram канал: {e}")
                
                # Отправляем уведомление о результате подписки
                try:
                    if subscription_success:
                        await callback.message.answer(
                            f"✅ <b>Подписка выполнена успешно!</b>\n\n"
                            f"<b>Канал:</b> {telegram_channel}\n"
                            f"<b>Аккаунт:</b> {account_info_str}\n\n"
                            f"Парсинг канала начнется автоматически согласно установленному интервалу.",
                            parse_mode="HTML"
                        )
                    else:
                        await callback.message.answer(
                            f"⚠️ <b>Ошибка подписки на канал</b>\n\n"
                            f"<b>Канал:</b> {telegram_channel}\n"
                            f"<b>Аккаунт:</b> {account_info_str}\n\n"
                            f"Возможные причины:\n"
                            f"• Канал приватный\n"
                            f"• Требуется подтверждение администратора\n"
                            f"• Проблемы с Telegram аккаунтом\n\n"
                            f"Проверьте настройки канала и попробуйте снова.",
                            parse_mode="HTML"
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления о подписке: {e}")

            # Запускаем в фоновом режиме
            asyncio.create_task(subscribe_to_channel())

        interval_minutes = interval_seconds // 60

        # Определяем иконку и название типа парсинга
        parsing_type_names = {
            'combined': '🔄 Комбинированный',
            'api': '📡 Только API',
            'html': '🌐 Только HTML',
            'browser': '🌐 Только Browser',
            'telegram': '📱 Telegram'
        }
        parsing_type_display = parsing_type_names.get(parsing_type, parsing_type)

        category_names = {
            'launches': 'Лаучи',
            'launchpad': 'Лаунчпады',
            'launchpool': 'Лаунчпулы',
            'airdrop': 'Аирдроп',
            'staking': 'Стейкинг',
            'announcement': 'Анонс'
        }
        category_display = category_names.get(category, category)

        # Формируем детальное сообщение
        # Получаем информацию о выбранном парсере
        selected_parser = data.get('selected_parser', 'auto')
        parser_info = PARSERS_CONFIG.get(selected_parser, {})
        parser_emoji = parser_info.get('emoji', '🤖')
        parser_name = parser_info.get('name', 'Автоматический')
        
        message_parts = [
            "✅ <b>Ссылка успешно добавлена!</b>\n\n",
            f"<b>Имя:</b> {custom_name}\n",
            f"<b>Категория:</b> {category_display}\n",
            f"<b>Тип парсинга:</b> {parsing_type_display}\n",
            f"<b>Парсер:</b> {parser_emoji} {parser_name}\n",
            f"<b>Интервал проверки:</b> {interval_minutes} минут\n\n"
        ]

        if api_url:
            message_parts.append(f"<b>👾 API URL:</b>\n<code>{api_url}</code>\n")

        if html_url:
            message_parts.append(f"\n<b>🌐 HTML URL:</b>\n<code>{html_url}</code>\n")

        if page_url:
            message_parts.append(f"\n<b>🔗 Страница акций:</b>\n<code>{page_url}</code>\n")

        if telegram_channel:
            message_parts.append(f"\n<b>📱 Telegram канал:</b> {telegram_channel}\n")
            keywords_display = ", ".join([f"<code>{kw}</code>" for kw in telegram_keywords])
            message_parts.append(f"<b>🔑 Ключевые слова:</b> {keywords_display}\n")
            if telegram_account_info:
                message_parts.append(telegram_account_info)
            if subscription_info:
                message_parts.append(f"\n{subscription_info}")

        # Специальное форматирование для стейкинга
        if category == 'staking':
            apr_display = f"{min_apr}%" if min_apr else "0% (все)"
            message_parts.append(f"\n<b>📊 Минимальный APR:</b> {apr_display}\n")
            
            # Отображение типов стейкинга
            staking_type = data.get('staking_type_selected', 'both')
            type_display = {
                'flexible': '📈 Flexible',
                'fixed': '🔒 Fixed',
                'both': '✅ Оба типа'
            }.get(staking_type, '✅ Оба типа')
            message_parts.append(f"<b>📋 Типы стейкинга:</b> {type_display}\n")
        elif min_apr:
            message_parts.append(f"\n<b>📊 Минимальный APR:</b> {min_apr}%\n")

        await callback.message.edit_text(
            "".join(message_parts),
            parse_mode="HTML"
        )

        await state.clear()
        await callback.answer()

    except ValueError as e:
        # Обработка ошибки дубликата
        error_msg = str(e)
        logger.warning(f"⚠️ Попытка добавить дубликат ссылки: {error_msg}")
        await callback.message.edit_text(
            f"⚠️ <b>Ссылка уже существует!</b>\n\n"
            f"{error_msg}\n\n"
            f"Используйте другой URL или отредактируйте существующую ссылку.",
            parse_mode="HTML"
        )
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении ссылки: {e}")
        
        # Определяем тип ошибки для более понятного сообщения
        error_msg = "❌ Ошибка при сохранении ссылки"
        if "UNIQUE constraint failed" in str(e):
            error_msg = "⚠️ Ссылка с таким URL уже существует"
        elif "database is locked" in str(e).lower():
            error_msg = "⚠️ База данных заблокирована, попробуйте ещё раз"
        
        await callback.message.edit_text(error_msg)
        await state.clear()
        await callback.answer()

@router.message(F.text == "⚙️ Управление ссылками")
async def menu_manage_links(message: Message):
    """Показать подменю выбора категории для управления ссылками"""
    try:
        clear_navigation(message.from_user.id)
        push_navigation(message.from_user.id, NAV_MANAGEMENT)

        await message.answer(
            "🗂️ <b>Выберите раздел для управления:</b>",
            reply_markup=get_category_management_menu(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"❌ Ошибка при управлении ссылками: {e}")
        await message.answer("❌ Ошибка при управлении ссылками")

@router.callback_query(F.data.startswith("category_"))
async def handle_category_selection(callback: CallbackQuery):
    """Обработка выбора категории - показ ссылок этой категории"""
    try:
        category = callback.data.replace("category_", "")  # 'staking', 'airdrop', 'all' и т.д.
        user_id = callback.from_user.id

        # Если выбрали "Лаучи" - показываем подменю с Лаунчпады/Лаунчпулы
        if category == "launches":
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🚀 Лаунчпады", callback_data="category_launchpad"))
            builder.add(InlineKeyboardButton(text="🌊 Лаунчпулы", callback_data="category_launchpool"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_categories"))
            builder.adjust(2, 1)
            
            await callback.message.edit_text(
                "🚀 <b>Лаучи</b>\n\n"
                "Выберите подкатегорию:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Если выбрали "Дропы" - показываем подменю с Аирдропы/CandyBomb
        if category == "drops":
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="🪂 Аирдропы", callback_data="category_airdrop"))
            builder.add(InlineKeyboardButton(text="🍬 CandyBomb", callback_data="category_candybomb"))
            builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_categories"))
            builder.adjust(2, 1)
            
            await callback.message.edit_text(
                "🎁 <b>Дропы</b>\n\n"
                "Выберите подкатегорию:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Сохраняем категорию в navigation_stack
        current_nav = get_current_navigation(user_id)
        if current_nav:
            current_nav["data"]["category"] = category

        # Словарь названий категорий
        category_names = {
            'launches': 'Лаучи',
            'launchpad': 'Лаунчпады',
            'launchpool': 'Лаунчпулы',
            'drops': 'Дропы',
            'airdrop': 'Аирдропы',
            'candybomb': 'CandyBomb',
            'staking': 'Стейкинг',
            'announcement': 'Анонс',
            'all': 'Все ссылки'
        }
        category_display = category_names.get(category, category)

        # Определяем кнопку "Назад" в зависимости от категории
        back_callback = "back_to_categories"
        if category in ['launchpad', 'launchpool']:
            back_callback = "category_launches"
        elif category in ['airdrop', 'candybomb']:
            back_callback = "category_drops"

        # Получаем ссылки из БД
        with get_db_session() as db:
            if category == 'all':
                # Для "Все ссылки" получаем все записи
                links = db.query(ApiLink).all()
            else:
                # Для конкретной категории фильтруем
                links = db.query(ApiLink).filter(ApiLink.category == category).all()

            if not links:
                await callback.message.edit_text(
                    f"📭 <b>В разделе '{category_display}' пока нет ссылок</b>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="← Назад", callback_data=back_callback)]
                    ]),
                    parse_mode="HTML"
                )
                await callback.answer()
                return

            # Детач данных для передачи в клавиатуру
            links_data = []
            for link in links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval,
                    'parsing_type': link.parsing_type or 'combined',
                    'category': link.category or 'launches'
                })())

            # Показываем список ссылок для управления
            keyboard = get_links_keyboard(links_data, action_type="manage")

            # Разный текст для "Все ссылки" и конкретной категории
            if category == 'all':
                header_text = f"📋 <b>{category_display}:</b>\n\n"
            else:
                header_text = f"🗂️ <b>Ссылки в категории '{category_display}':</b>\n\n"

            await callback.message.edit_text(
                f"{header_text}Выберите ссылку для управления:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

            await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при выборе категории: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при загрузке ссылок")
        await callback.answer()

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """Возврат к выбору категории"""
    try:
        await callback.message.edit_text(
            "🗂️ <b>Выберите раздел для управления:</b>",
            reply_markup=get_category_management_menu(),
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка при возврате к категориям: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "back_to_link_list")
async def back_to_link_list(callback: CallbackQuery):
    """Возврат к списку ссылок в категории"""
    try:
        user_id = callback.from_user.id
        
        # Получаем сохраненную категорию
        current_nav = get_current_navigation(user_id)
        category = current_nav.get("data", {}).get("category", "all") if current_nav else "all"
        
        # Очищаем выбор ссылки
        if user_id in user_selections:
            del user_selections[user_id]
        
        # Создаем mock callback для повторного вызова handle_category_selection
        from unittest.mock import Mock
        category_callback = Mock()
        category_callback.data = f"category_{category}"
        category_callback.message = callback.message
        category_callback.answer = callback.answer
        category_callback.from_user = callback.from_user
        
        await handle_category_selection(category_callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при возврате к списку ссылок: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


async def _show_link_management_by_id(callback: CallbackQuery, link_id: int):
    """Вспомогательная функция для показа меню управления ссылкой по ID"""
    user_id = callback.from_user.id

    with get_db_session() as db:
        link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

        if not link:
            await callback.message.edit_text("❌ Ссылка не найдена")
            await callback.answer()
            return

        # Сохраняем link_id для использования в других обработчиках
        user_selections[user_id] = link_id

        # Используем унифицированную клавиатуру для всех категорий
        keyboard = get_unified_link_management_keyboard(link)

        # Информация о ссылке
        status_text = "✅ Активна" if link.is_active else "❌ Остановлена"
        parsing_type_text = {
            'api': 'API',
            'html': 'HTML',
            'browser': 'Browser',
            'combined': 'Комбинированный',
            'telegram': 'Telegram'
        }.get(link.parsing_type, 'Комбинированный')
        
        # Категория с иконкой
        category_icons = {
            'launches': '🚀',
            'launchpad': '🚀',
            'launchpool': '🌊',
            'drops': '🎁',
            'airdrop': '🪂',
            'candybomb': '🍬',
            'staking': '💰',
            'announcement': '📢'
        }
        category = link.category or 'launches'
        category_icon = category_icons.get(category, '📁')
        
        # НОВОЕ: URL ссылки (укороченный если слишком длинный)
        url_info = ""
        display_url = link.url or link.html_url or link.api_url or ""
        if display_url:
            # Укорачиваем URL если он длиннее 50 символов
            if len(display_url) > 50:
                display_url = display_url[:47] + "..."
            url_info = f"<b>🔗 URL:</b> <code>{display_url}</code>\n"

        # Информация о Telegram аккаунте
        telegram_info = ""
        if link.parsing_type == 'telegram':
            if link.telegram_account:
                account = link.telegram_account

                # Статус аккаунта
                if account.is_blocked:
                    account_status = "❌ Заблокирован"
                    if account.blocked_at:
                        from datetime import datetime
                        blocked_date = account.blocked_at.strftime('%d.%m.%Y %H:%M') if isinstance(account.blocked_at, datetime) else str(account.blocked_at)
                        account_status += f" (с {blocked_date})"
                elif not account.is_active:
                    account_status = "💤 Неактивен"
                else:
                    account_status = "✅ Активен"

                telegram_info = (
                    f"<b>📱 Telegram аккаунт:</b> {account.name}\n"
                    f"<b>   Номер:</b> +{account.phone_number}\n"
                    f"<b>   Статус:</b> {account_status}\n"
                )

                # Канал
                if link.telegram_channel:
                    telegram_info += f"<b>📡 Канал:</b> {link.telegram_channel}\n"
            else:
                telegram_info = "<b>📱 Telegram аккаунт:</b> ⚠️ Не назначен\n"

        await callback.message.edit_text(
            f"📊 <b>Управление ссылкой:</b> {link.name}\n\n"
            f"{url_info}"
            f"<b>{category_icon} Категория:</b> {category}\n"
            f"<b>⏱ Интервал:</b> {link.check_interval}с ({link.check_interval // 60} мин)\n"
            f"<b>📡 Тип парсинга:</b> {parsing_type_text}\n"
            f"<b>Статус:</b> {status_text}\n"
            f"{telegram_info}\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


@router.callback_query(F.data.startswith("manage_link_"))
async def show_link_management(callback: CallbackQuery):
    """Показать меню управления выбранной ссылкой (с учетом категории)"""
    try:
        link_id = int(callback.data.split("_")[2])
        await _show_link_management_by_id(callback, link_id)

    except Exception as e:
        logger.error(f"❌ Ошибка при показе меню управления ссылкой: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при загрузке меню")
        await callback.answer()

@router.callback_query(F.data == "manage_change_tg_account")
async def manage_change_tg_account(callback: CallbackQuery):
    """Смена Telegram аккаунта для ссылки"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        from data.models import TelegramAccount

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                await callback.answer()
                return

            if link.parsing_type != 'telegram':
                await callback.answer("❌ Эта функция только для Telegram ссылок", show_alert=True)
                return

            # Получить доступные аккаунты
            accounts = db.query(TelegramAccount).filter(
                TelegramAccount.is_active == True,
                TelegramAccount.is_authorized == True,
                TelegramAccount.is_blocked == False
            ).all()

            if not accounts:
                await callback.message.edit_text(
                    "❌ <b>Нет доступных Telegram аккаунтов</b>\n\n"
                    "Добавьте аккаунт через:\n"
                    "🛡️ Обход блокировок → 📱 Telegram API",
                    parse_mode="HTML"
                )
                await callback.answer()
                return

            # Создать клавиатуру выбора
            builder = InlineKeyboardBuilder()
            for acc in accounts:
                # Пометка текущего
                prefix = "✅ " if acc.id == link.telegram_account_id else ""

                # Статистика нагрузки
                from sqlalchemy import func
                load_count = db.query(func.count(ApiLink.id)).filter(
                    ApiLink.telegram_account_id == acc.id,
                    ApiLink.is_active == True,
                    ApiLink.parsing_type == 'telegram'
                ).scalar()

                button_text = f"{prefix}{acc.name} (+{acc.phone_number}) [{load_count} ссылок]"
                builder.add(InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"assign_tg_account_{acc.id}"
                ))

            builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"manage_link_{link_id}"))
            builder.adjust(1)

            await callback.message.edit_text(
                f"📱 <b>Выберите Telegram аккаунт для {link.name}:</b>\n\n"
                f"<i>✅ - текущий аккаунт\n"
                f"[N ссылок] - количество назначенных ссылок</i>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка смены аккаунта: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при смене аккаунта")
        await callback.answer()

@router.callback_query(F.data.startswith("assign_tg_account_"))
async def process_assign_tg_account(callback: CallbackQuery):
    """Обработка назначения Telegram аккаунта"""
    try:
        account_id = int(callback.data.split("_")[-1])
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        from data.models import TelegramAccount

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            account = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()

            if not link or not account:
                await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
                return

            old_account_name = link.telegram_account.name if link.telegram_account else "нет"

            # Назначить новый аккаунт
            link.telegram_account_id = account_id
            db.commit()

            await callback.message.edit_text(
                f"✅ <b>Telegram аккаунт изменен!</b>\n\n"
                f"<b>Ссылка:</b> {link.name}\n"
                f"<b>Старый аккаунт:</b> {old_account_name}\n"
                f"<b>Новый аккаунт:</b> {account.name} (+{account.phone_number})\n\n"
                f"<i>Парсер переподключится к каналу при следующей проверке</i>",
                parse_mode="HTML"
            )
            await callback.answer("✅ Аккаунт изменен")

            logger.info(f"✅ Аккаунт для ссылки {link.name} изменен: {old_account_name} → {account.name}")

    except Exception as e:
        logger.error(f"❌ Ошибка назначения аккаунта: {e}", exc_info=True)
        await callback.answer("❌ Ошибка назначения", show_alert=True)

@router.callback_query(F.data == "manage_check_pools")
async def check_staking_pools(callback: CallbackQuery):
    """Проверка заполненности пулов для выбранной ссылки стейкинга"""
    try:
        # Получаем ID ссылки из user_selections
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        # ВАЖНО: Отвечаем на callback СРАЗУ, чтобы избежать timeout
        await callback.answer()

        await callback.message.edit_text("⏳ <b>Проверяю заполненность пулов...</b>", parse_mode="HTML")

        try:
            # Получаем ссылку из БД и сохраняем нужные данные
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if not link:
                    await callback.message.edit_text("❌ Ссылка не найдена")
                    return

                if link.category not in ['staking', 'launchpool']:
                    await callback.message.edit_text("❌ Эта функция доступна только для стейкинг и launchpool ссылок")
                    return

                # ВАЖНО: Сохраняем все нужные данные из link пока сессия открыта
                link_api_url = link.api_url or link.url
                link_name = link.name
                link_page_url = link.page_url

            # Парсим стейкинги с текущей биржи
            from parsers.staking_parser import StakingParser
            from bot.notification_service import NotificationService

            parser = StakingParser(
                api_url=link_api_url,
                exchange_name=link_name
            )

            stakings = parser.parse()

            if not stakings:
                message_text = (
                    f"📊 <b>ОТЧЁТ: ЗАПОЛНЕННОСТЬ ПУЛОВ</b>\n\n"
                    f"🏦 <b>Биржа:</b> {link_name}\n\n"
                    f"ℹ️ Нет данных о стейкингах или заполненности пулов."
                )
            else:
                # Фильтруем только стейкинги с данными о заполненности И APR >= 100%
                # ИСКЛЮЧАЕМ: пулы с заполненностью >= 95% и со статусом "Sold Out"
                pools_with_fill = [
                    s for s in stakings
                    if s.get('fill_percentage') is not None
                    and s.get('apr', 0) >= 100
                    and s.get('fill_percentage', 0) < 95  # Не заполненные >= 95%
                    and s.get('status') != 'Sold Out'  # Не проданные
                ]

                if not pools_with_fill:
                    # Проверяем, есть ли вообще пулы с заполненностью (без учета APR и фильтров)
                    pools_all = [s for s in stakings if s.get('fill_percentage') is not None]
                    if pools_all:
                        # Проверяем причину отсутствия доступных пулов
                        pools_sold_out = [s for s in pools_all if s.get('status') == 'Sold Out' or s.get('fill_percentage', 0) >= 95]
                        pools_low_apr = [s for s in pools_all if s.get('apr', 0) < 100]

                        message_text = (
                            f"📊 <b>ОТЧЁТ: ЗАПОЛНЕННОСТЬ ПУЛОВ</b>\n\n"
                            f"🏦 <b>Биржа:</b> {link_name}\n\n"
                            f"ℹ️ Найдено {len(pools_all)} пулов с данными о заполненности.\n\n"
                        )

                        if pools_sold_out:
                            message_text += f"🔴 Заполненных/распроданных: {len(pools_sold_out)}\n"
                        if pools_low_apr:
                            message_text += f"📉 С APR < 100%: {len(pools_low_apr)}\n"

                        message_text += f"\n<i>Нет доступных пулов с APR ≥ 100%</i>"
                    else:
                        message_text = (
                            f"📊 <b>ОТЧЁТ: ЗАПОЛНЕННОСТЬ ПУЛОВ</b>\n\n"
                            f"🏦 <b>Биржа:</b> {link_name}\n\n"
                            f"ℹ️ Найдено {len(stakings)} стейкингов, но нет данных о заполненности."
                        )
                else:
                    # Показываем ВСЕ незаполненные пулы
                    # (Если сообщение превысит лимит Telegram 4096 символов,
                    # оно будет автоматически обрезано в format_pools_report)
                    pools_to_show = pools_with_fill

                    # Используем форматтер для создания отчета
                    notification_service = NotificationService(bot=None)
                    message_text = notification_service.format_pools_report(
                        pools_to_show,
                        exchange_name=link_name,
                        page_url=link_page_url
                    )
                    # Добавляем информацию о фильтрации
                    total_with_fill = len([s for s in stakings if s.get('fill_percentage') is not None])
                    total_sold_out = len([s for s in stakings if s.get('status') == 'Sold Out' or s.get('fill_percentage', 0) >= 95])
                    info_parts = []

                    # Показываем статистику
                    info_parts.append(f"Показано {len(pools_with_fill)} доступных пулов")

                    if total_sold_out > 0:
                        info_parts.append(f"Скрыто {total_sold_out} заполненных")

                    if info_parts:
                        message_text += f"\n\n<i>ℹ️ {' | '.join(info_parts)}</i>"
                        message_text += f"\n<i>Фильтр: APR ≥ 100%, заполненность &lt; 100%</i>"

            # Отправляем результат
            # Логируем сообщение для диагностики
            logger.info(f"📝 Длина сообщения: {len(message_text)} символов")

            # ДИАГНОСТИКА: Показываем контекст вокруг проблемной позиции 2466
            if len(message_text) > 2466:
                logger.warning(f"🔍 Контекст позиции 2466:")
                logger.warning(f"   Символы 2450-2480: '{message_text[2450:2480]}'")
                logger.warning(f"   Символ на 2466: '{message_text[2466]}' (код: {ord(message_text[2466])})")

            # Проверяем на проблемные символы
            for i, char in enumerate(message_text):
                if char == '<' and i < len(message_text) - 3:
                    # Проверяем, является ли это началом валидного тега
                    next_chars = message_text[i:i+10]
                    if not any(next_chars.startswith(tag) for tag in ['<b>', '</b>', '<i>', '</i>', '<code>', '</code>']):
                        logger.error(f"❌ Невалидный '<' на позиции {i}: {message_text[max(0,i-20):i+20]}")

            await callback.message.edit_text(message_text, parse_mode="HTML", disable_web_page_preview=True)

        except Exception as e:
            logger.error(f"❌ Ошибка при проверке заполненности пулов: {e}", exc_info=True)
            await callback.message.edit_text(f"❌ Ошибка при проверке: {str(e)}")

    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике check_staking_pools: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка")

@router.callback_query(F.data == "manage_view_current_stakings")
async def view_current_stakings(callback: CallbackQuery):
    """Показать текущие стейкинги из БД (без принудительного парсинга)"""
    logger.info(f"📋 ОТКРЫТИЕ ТЕКУЩИХ СТЕЙКИНГОВ (из БД)")
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        logger.info(f"   User ID: {user_id}, Link ID: {link_id}")

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        # Используем async получение данных ссылки с кэшированием (Фаза 4)
        link = await get_link_by_id_async(link_id)
        
        if not link:
            await callback.answer("❌ Ссылка не найдена", show_alert=True)
            return

        if link.category not in ['staking', 'launchpool']:
            await callback.answer("❌ Эта функция доступна только для стейкинг и launchpool ссылок", show_alert=True)
            return

        exchange_name = link.name
        min_apr = link.min_apr
        page_url = link.page_url
        api_url = link.api_url or link.url
        exchange = link.exchange
        last_checked = link.last_checked  # Время последней проверки

        # Закрываем callback сразу для отзывчивости UI
        await callback.answer()

        # Нормализуем exchange для правильного поиска в БД
        from utils.exchange_detector import detect_exchange_from_url
        
        # Автоопределение биржи если не указана
        if not exchange or exchange in ['Unknown', 'None', '', 'null']:
            exchange = detect_exchange_from_url(api_url) if api_url else exchange_name
            logger.info(f"🔍 Автоопределение биржи: {exchange}")

        exchange_filter = exchange or exchange_name
        
        # Нормализация специальных парсеров -> базовое имя биржи для поиска в БД
        # BitgetPoolx -> Bitget, т.к. стейкинги сохраняются с exchange='Bitget'
        exchange_name_mapping = {
            'bitgetpoolx': 'Bitget',
            'bitget poolx': 'Bitget', 
            'bitget_poolx': 'Bitget',
        }
        exchange_filter_lower = exchange_filter.lower().replace(' ', '')
        if exchange_filter_lower in exchange_name_mapping:
            exchange_filter = exchange_name_mapping[exchange_filter_lower]
            logger.info(f"🔄 Нормализация биржи: {exchange_name} -> {exchange_filter}")

        # Получить стейкинги с дельтами
        from services.staking_snapshot_service import StakingSnapshotService
        snapshot_service = StakingSnapshotService()

        stakings_with_deltas = snapshot_service.get_stakings_with_deltas(
            exchange=exchange_filter,  # Используем нормализованное имя биржи
            min_apr=min_apr
        )

        # Для OKX Flash Earn: группируем по проектам, пагинируем проекты
        is_okx_flash = 'okx' in exchange_name.lower() and 'flash' in exchange_name.lower()

        if is_okx_flash:
            # Группируем все стейкинги по проектам (reward_coin + start_time + end_time)
            projects = {}
            for item in stakings_with_deltas:
                staking = item['staking'] if isinstance(item, dict) and 'staking' in item else item
                if isinstance(staking, dict):
                    reward_coin = staking.get('reward_coin') or staking.get('coin')
                    start_time = staking.get('start_time')
                    end_time = staking.get('end_time')
                else:
                    reward_coin = getattr(staking, 'reward_coin', None) or getattr(staking, 'coin', None)
                    start_time = getattr(staking, 'start_time', None)
                    end_time = getattr(staking, 'end_time', None)
                project_key = (reward_coin, start_time, end_time)
                if project_key not in projects:
                    projects[project_key] = []
                projects[project_key].append(item)

            # Конвертируем в список проектов (каждый проект = список пулов)
            project_list = list(projects.values())

            # Пагинация по проектам (2 проекта на страницу для OKX)
            page = 1
            per_page = 2  # 2 проекта на страницу
            total_pages = max(1, (len(project_list) + per_page - 1) // per_page)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_projects = project_list[start_idx:end_idx]

            # Развернуть проекты обратно в список стейкингов для формата
            page_stakings = []
            for project_pools in page_projects:
                page_stakings.extend(project_pools)

            # Сохраняем сгруппированные проекты
            current_stakings_state[user_id] = {
                'page': page,
                'link_id': link_id,
                'total_pages': total_pages,
                'stakings': stakings_with_deltas,
                'projects': project_list,  # Сохраняем список проектов
                'exchange_name': exchange_name,
                'min_apr': min_apr,
                'page_url': page_url,
                'is_okx_flash': True,
                'last_checked': last_checked  # Время последней проверки
            }
        else:
            # Стандартная пагинация по стейкингам
            page = 1
            per_page = 5
            total_pages = max(1, (len(stakings_with_deltas) + per_page - 1) // per_page)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_stakings = stakings_with_deltas[start_idx:end_idx]

            # Сохранить состояние
            current_stakings_state[user_id] = {
                'page': page,
                'link_id': link_id,
                'total_pages': total_pages,
                'stakings': stakings_with_deltas,
                'exchange_name': exchange_name,
                'min_apr': min_apr,
                'page_url': page_url,
                'is_okx_flash': False,
                'last_checked': last_checked  # Время последней проверки
            }

        logger.info(f"   💾 Состояние сохранено: page={page}, link_id={link_id}, total_pages={total_pages}")
        logger.info(f"   🔑 Текущее состояние в памяти: {current_stakings_state}")
        logger.info(f"   📱 Всего стейкингов: {len(stakings_with_deltas)}, на странице: {len(page_stakings)}")

        # Форматировать сообщение (skip_price_fetch=True - данные уже в БД, не нужны внешние запросы)
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)

        # Для OKX Flash Earn используем специальный формат с группировкой по проектам
        if is_okx_flash:
            message_text = notif_service.format_okx_flash_earn_page(
                stakings_with_deltas=page_stakings,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url,
                last_checked=last_checked
            )
        else:
            message_text = notif_service.format_current_stakings_page(
                stakings_with_deltas=page_stakings,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url,
                last_checked=last_checked
            )

        # Отправить с кнопками
        keyboard = get_current_stakings_keyboard(page, total_pages)

        await callback.message.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка просмотра стейкингов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки данных", show_alert=True)

@router.callback_query(F.data.startswith("stakings_page_"))
async def navigate_stakings_page(callback: CallbackQuery):
    """Навигация по страницам текущих стейкингов"""
    try:
        user_id = callback.from_user.id
        action = callback.data.split("_")[2]  # "prev" или "next"

        state = current_stakings_state.get(user_id)
        if not state:
            await callback.answer("❌ Сессия истекла. Откройте раздел заново.", show_alert=True)
            return

        current_page = state['page']
        total_pages = state['total_pages']
        link_id = state['link_id']

        # Вычисляем новую страницу
        if action == "prev":
            new_page = max(1, current_page - 1)
        else:  # next
            new_page = min(total_pages, current_page + 1)

        if new_page == current_page:
            await callback.answer()
            return

        # Обновляем состояние
        state['page'] = new_page

        # Используем сохраненные данные вместо повторного запроса к БД
        stakings_with_deltas = state.get('stakings', [])
        exchange_name = state.get('exchange_name', 'Unknown')
        min_apr = state.get('min_apr')
        page_url = state.get('page_url')
        is_okx_flash = state.get('is_okx_flash', False)

        if not stakings_with_deltas:
            await callback.answer("❌ Данные потеряны. Откройте раздел заново.", show_alert=True)
            return

        # Для OKX Flash Earn пагинация по проектам
        if is_okx_flash:
            project_list = state.get('projects', [])
            per_page = 2  # 2 проекта на страницу
            start_idx = (new_page - 1) * per_page
            end_idx = start_idx + per_page
            page_projects = project_list[start_idx:end_idx]

            # Развернуть проекты в список стейкингов
            page_stakings = []
            for project_pools in page_projects:
                page_stakings.extend(project_pools)
        else:
            # Стандартная пагинация
            per_page = 5
            start_idx = (new_page - 1) * per_page
            end_idx = start_idx + per_page
            page_stakings = stakings_with_deltas[start_idx:end_idx]

        # Форматировать сообщение (skip_price_fetch=True - данные уже в БД)
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)

        # Для OKX Flash Earn используем специальный формат
        if is_okx_flash:
            message_text = notif_service.format_okx_flash_earn_page(
                stakings_with_deltas=page_stakings,
                page=new_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
            )
        else:
            message_text = notif_service.format_current_stakings_page(
                stakings_with_deltas=page_stakings,
                page=new_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
            )

        # Отправить с обновленными кнопками
        keyboard = get_current_stakings_keyboard(new_page, total_pages)

        await callback.message.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка навигации: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "stakings_force_parse")
async def force_parse_stakings(callback: CallbackQuery):
    """Принудительный парсинг стейкингов (с обновлением БД)"""
    logger.info("="*80)
    logger.info("🔍 ПРИНУДИТЕЛЬНЫЙ ПАРСИНГ СТЕЙКИНГОВ")
    logger.info("="*80)
    try:
        user_id = callback.from_user.id
        logger.info(f"👤 User ID: {user_id}")

        state = current_stakings_state.get(user_id)
        
        # Если сессия истекла, пытаемся восстановить из user_selections
        if not state:
            link_id = user_selections.get(user_id)
            if link_id:
                logger.info(f"🔄 Восстанавливаю сессию из user_selections: link_id={link_id}")
                state = {
                    'page': 1,
                    'link_id': link_id,
                    'total_pages': 1,
                    'stakings': [],
                    'is_okx_flash': False
                }
                current_stakings_state[user_id] = state
            else:
                await callback.answer("❌ Сессия истекла. Откройте раздел заново.", show_alert=True)
                return

        current_page = state['page']
        link_id = state['link_id']

        # Получить данные ссылки
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            exchange_name = link.name
            min_apr = link.min_apr
            page_url = link.page_url
            api_url = link.api_url or link.url
            exchange = link.exchange

        # ПРИНУДИТЕЛЬНО запускаем парсер
        from bot.parser_service import ParserService
        from utils.exchange_detector import detect_exchange_from_url
        import asyncio

        # Автоопределение биржи если не указана
        if not exchange or exchange in ['Unknown', 'None', '', 'null']:
            exchange = detect_exchange_from_url(api_url)
            logger.info(f"🔍 Автоопределение биржи: {exchange}")

        # Используем exchange для поиска стейкингов
        exchange_filter = exchange or exchange_name
        
        # Нормализация специальных парсеров -> базовое имя биржи для поиска в БД
        exchange_name_mapping = {
            'bitgetpoolx': 'Bitget',
            'bitget poolx': 'Bitget', 
            'bitget_poolx': 'Bitget',
        }
        exchange_filter_lower = exchange_filter.lower().replace(' ', '')
        if exchange_filter_lower in exchange_name_mapping:
            exchange_filter = exchange_name_mapping[exchange_filter_lower]
            logger.info(f"🔄 Нормализация биржи: {exchange_name} -> {exchange_filter}")

        # Закрываем callback
        await callback.answer()

        # Отправляем сообщение о начале обновления
        status_msg = await callback.message.answer(
            f"⏳ <b>Принудительный парсинг {exchange_name}...</b>\n"
            f"📊 Запуск парсера стейкинг-продуктов",
            parse_mode="HTML"
        )

        # Запускаем парсер и ЖДЕМ его завершения
        parser_service = ParserService()
        loop = asyncio.get_event_loop()

        try:
            logger.info(f"{'='*60}")
            logger.info(f"🔄 ПРИНУДИТЕЛЬНЫЙ ПАРСИНГ СТЕЙКИНГОВ: {exchange_name}")
            logger.info(f"   link_id={link_id}")
            logger.info(f"   api_url={api_url}")
            logger.info(f"   exchange={exchange}")
            logger.info(f"{'='*60}")

            # СИНХРОННО выполняем парсинг
            new_stakings = await loop.run_in_executor(
                get_executor(),
                parser_service.parse_staking_link,
                link_id,
                api_url,
                exchange,
                page_url
            )

            logger.info(f"✅ ПАРСЕР ЗАВЕРШИЛ РАБОТУ")
            logger.info(f"   Получено новых записей: {len(new_stakings) if new_stakings else 0}")
            logger.info(f"{'='*60}")

            # Обновляем last_checked для ApiLink
            with get_db_session() as db:
                link_record = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                if link_record:
                    link_record.last_checked = datetime.utcnow()
                    db.commit()

            # Удаляем сообщение о статусе
            await status_msg.delete()

        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при принудительном парсинге {exchange_name}: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Ошибка при парсинге {exchange_name}</b>\n"
                f"Показываю данные из кэша",
                parse_mode="HTML"
            )
            await asyncio.sleep(2)
            await status_msg.delete()

        # Получить стейкинги с дельтами (ПОСЛЕ парсинга)
        from services.staking_snapshot_service import StakingSnapshotService
        snapshot_service = StakingSnapshotService()

        stakings_with_deltas = snapshot_service.get_stakings_with_deltas(
            exchange=exchange_filter,
            min_apr=min_apr
        )

        # Для OKX Flash Earn пагинация по проектам
        is_okx_flash = 'okx' in exchange_name.lower() and 'flash' in exchange_name.lower()

        if is_okx_flash:
            # Группируем все стейкинги по проектам
            projects = {}
            for item in stakings_with_deltas:
                staking = item['staking'] if isinstance(item, dict) and 'staking' in item else item
                if isinstance(staking, dict):
                    reward_coin = staking.get('reward_coin') or staking.get('coin')
                    start_time = staking.get('start_time')
                    end_time = staking.get('end_time')
                else:
                    reward_coin = getattr(staking, 'reward_coin', None) or getattr(staking, 'coin', None)
                    start_time = getattr(staking, 'start_time', None)
                    end_time = getattr(staking, 'end_time', None)
                project_key = (reward_coin, start_time, end_time)
                if project_key not in projects:
                    projects[project_key] = []
                projects[project_key].append(item)

            project_list = list(projects.values())
            per_page = 2
            total_pages = max(1, (len(project_list) + per_page - 1) // per_page)

            if current_page > total_pages:
                current_page = total_pages

            start_idx = (current_page - 1) * per_page
            end_idx = start_idx + per_page
            page_projects = project_list[start_idx:end_idx]

            page_stakings = []
            for project_pools in page_projects:
                page_stakings.extend(project_pools)

            # Обновляем state
            state['page'] = current_page
            state['total_pages'] = total_pages
            state['stakings'] = stakings_with_deltas
            state['projects'] = project_list
            state['is_okx_flash'] = True
        else:
            # Стандартная пагинация
            per_page = 5
            total_pages = max(1, (len(stakings_with_deltas) + per_page - 1) // per_page)

            if current_page > total_pages:
                current_page = total_pages

            start_idx = (current_page - 1) * per_page
            end_idx = start_idx + per_page
            page_stakings = stakings_with_deltas[start_idx:end_idx]

            # Обновляем state
            state['page'] = current_page
            state['total_pages'] = total_pages
            state['stakings'] = stakings_with_deltas
            state['is_okx_flash'] = False

        state['exchange_name'] = exchange_name
        state['min_apr'] = min_apr
        state['page_url'] = page_url

        # Форматировать сообщение (skip_price_fetch=True - данные уже в БД)
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)

        # Для OKX Flash Earn используем специальный формат
        if is_okx_flash:
            message_text = notif_service.format_okx_flash_earn_page(
                stakings_with_deltas=page_stakings,
                page=current_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
            )
        else:
            message_text = notif_service.format_current_stakings_page(
                stakings_with_deltas=page_stakings,
                page=current_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
            )

        # Добавляем время парсинга
        from datetime import timedelta
        now_local = datetime.utcnow() + timedelta(hours=2)
        last_updated_str = now_local.strftime("%d.%m.%Y %H:%M")
        message_text += f"\n\n⏱ <i>Обновлено: {last_updated_str}</i>"

        # Отправляем НОВОЕ сообщение с обновленными данными
        keyboard = get_current_stakings_keyboard(current_page, total_pages)

        await callback.message.answer(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"❌ Ошибка принудительного парсинга стейкингов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка парсинга", show_alert=True)


# =============================================================================
# ОБРАБОТЧИКИ ТЕКУЩИХ ПРОМОАКЦИЙ (AIRDROP)
# =============================================================================

def get_promos_from_db(link_id: int, exchange_name: str = None) -> list:
    """
    Получить промоакции из БД для конкретной ссылки.
    
    Args:
        link_id: ID ссылки в БД
        exchange_name: Название биржи (для фильтрации)
    
    Returns:
        Список словарей с данными промоакций
    """
    from data.models import PromoHistory
    from sqlalchemy import or_
    
    try:
        now = datetime.utcnow()
        
        with get_db_session() as session:
            # Базовый запрос по link_id
            query = session.query(PromoHistory).filter(
                PromoHistory.api_link_id == link_id
            )
            
            # Фильтр по статусу - только активные (включая MEXC статусы и числовые коды Bybit)
            query = query.filter(
                or_(
                    PromoHistory.status.ilike('%ongoing%'),
                    PromoHistory.status.ilike('%active%'),
                    PromoHistory.status.ilike('%upcoming%'),
                    PromoHistory.status.ilike('%underway%'),  # MEXC Launchpad
                    PromoHistory.status == None,
                    PromoHistory.status == '0',  # Bybit: 0 = активный (сохраняется как строка)
                    PromoHistory.status == '1',  # Bybit: 1 = активный
                    PromoHistory.status == ''    # Пустая строка = активный
                )
            )
            
            # Фильтр по времени окончания
            query = query.filter(
                or_(
                    PromoHistory.end_time == None,
                    PromoHistory.end_time > now
                )
            )
            
            # Сортируем по дате создания (новые первые)
            query = query.order_by(PromoHistory.created_at.desc())
            
            promos = query.all()
            
            # Конвертируем в словари, фильтруем пустые промо
            result = []
            for promo in promos:
                # Пропускаем промо без данных (например "Gate.io Promo gate.io_200")
                # Но НЕ пропускаем если есть нормальный title (для WeexTS, Telegram и других)
                has_data = promo.total_prize_pool or promo.participants_count
                has_meaningful_title = promo.title and not promo.title.startswith('Gate.io Promo')
                if not has_data and not has_meaningful_title:
                    logger.debug(f"⏭️ Пропускаем пустую промоакцию: {promo.title}")
                    continue
                    
                promo_dict = {
                    'promo_id': promo.promo_id,
                    'title': promo.title or 'Без названия',
                    'description': promo.description,
                    'award_token': promo.award_token,
                    'total_prize_pool': promo.total_prize_pool,
                    'total_prize_pool_usd': promo.total_prize_pool_usd,
                    'reward_per_winner': promo.reward_per_winner,
                    'reward_per_winner_usd': promo.reward_per_winner_usd,
                    'participants_count': promo.participants_count,
                    'winners_count': promo.winners_count,
                    'conditions': promo.conditions,
                    'reward_type': promo.reward_type,
                    'status': promo.status or 'ongoing',
                    'start_time': promo.start_time,
                    'end_time': promo.end_time,
                    'link': promo.link,
                    'last_updated': promo.last_updated,
                    'exchange': promo.exchange,
                    # Gate.io специфичные поля
                    'user_max_rewards': promo.max_reward_per_user,
                    # MEXC Airdrop специфичные поля (раздельные пулы)
                    'token_pool': promo.token_pool,
                    'token_pool_currency': promo.token_pool_currency,
                    'bonus_usdt': promo.bonus_usdt,
                    'token_price': promo.token_price,
                    # Для специальных форматов (MEXC Launchpad, OKX Boost и т.д.)
                    'promo_type': promo.promo_type,
                    'raw_data': promo.raw_data
                }
                result.append(promo_dict)
            
            logger.info(f"📊 Получено {len(result)} промоакций из БД для link_id={link_id}")
            return result
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения промоакций из БД: {e}", exc_info=True)
        return []


@router.callback_query(F.data == "manage_view_current_promos")
async def view_current_promos(callback: CallbackQuery):
    """Показать текущие промоакции из БД (без принудительного парсинга)"""
    logger.info(f"📋 ОТКРЫТИЕ ТЕКУЩИХ ПРОМОАКЦИЙ (из БД)")
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        logger.info(f"   User ID: {user_id}, Link ID: {link_id}")

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        # Используем async получение данных ссылки с кэшированием (Фаза 4)
        link = await get_link_by_id_async(link_id)
        
        if not link:
            await callback.answer("❌ Ссылка не найдена", show_alert=True)
            return

        if link.category not in ('airdrop', 'candybomb', 'drops', 'launches', 'launchpool', 'launchpad', 'announcement'):
            await callback.answer("❌ Эта функция доступна только для drops/launches-ссылок", show_alert=True)
            return

        exchange_name = link.name
        page_url = link.page_url
        api_url = link.api_url or link.url
        html_url = link.html_url
        last_checked = link.last_checked  # Время последней проверки

        # Закрываем callback сразу для отзывчивости UI
        await callback.answer()

        # Получаем данные из БД (без парсинга)
        promos_data = get_promos_from_db(link_id, exchange_name)
        
        # Форматируем время последнего обновления
        last_updated_str = ""
        if last_checked:
            try:
                from datetime import timedelta
                if isinstance(last_checked, datetime):
                    local_time = last_checked + timedelta(hours=2)
                    last_updated_str = local_time.strftime("%d.%m.%Y %H:%M")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отформатировать last_checked: {e}")

        # Если данных нет в БД
        if not promos_data:
            message_text = (
                f"🎁 <b>ТЕКУЩИЕ ПРОМОАКЦИИ</b>\n\n"
                f"<b>🏦 Биржа:</b> {exchange_name}\n"
            )
            if last_updated_str:
                message_text += f"<b>⏱️ Обновлено:</b> {last_updated_str}\n"
            message_text += (
                f"\n📭 <i>Нет данных в базе.</i>\n"
                f"<i>Используйте \"🔍 Принудительная проверка\" для загрузки данных.</i>"
            )
            
            await callback.message.edit_text(
                message_text,
                parse_mode="HTML",
                reply_markup=get_current_promos_keyboard(1, 1)
            )
            return

        # Определяем тип биржи по URL для правильного форматирования
        def get_exchange_from_url(url: str) -> str:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                parts = domain.split('.')
                if len(parts) >= 2:
                    return parts[-2] if parts[-1] in ['com', 'io', 'org', 'net', 'ru'] else parts[-1]
                return domain
            except:
                return ''
        
        check_url = html_url or api_url or page_url or ''
        exchange = get_exchange_from_url(check_url)
        
        # Определяем тип биржи
        is_okx_boost = exchange == 'okx' and 'boost' in (page_url or '').lower()
        is_gate_candy = 'gatecandy' in exchange_name.lower().replace(' ', '').replace('.', '') or (api_url and 'candydrop' in api_url.lower() and 'gate' in (check_url or '').lower())
        is_bitget_candy = 'bitgetcandy' in exchange_name.lower().replace(' ', '').replace('.', '') or link.special_parser == 'bitget_candybomb' or ('bitget' in (check_url or '').lower() and 'candy-bomb' in (check_url or '').lower())
        is_phemex_candy = 'phemexcandy' in exchange_name.lower().replace(' ', '').replace('.', '') or link.special_parser == 'phemex_candydrop' or ('phemex' in (check_url or '').lower() and 'candy-drop' in (check_url or '').lower())
        is_mexc_airdrop = (api_url and 'eftd' in api_url.lower()) or (page_url and 'token-airdrop' in page_url.lower())
        is_mexc_launchpad = (api_url and 'launchpad/list' in api_url.lower()) or (page_url and '/launchpad' in page_url.lower() and 'mexc' in exchange.lower())
        is_weex = exchange == 'weex'
        is_weex_rewards_page = is_weex and '/rewards' in (html_url or page_url or '').lower()
        
        # Определяем launchpool/launchpad парсеры по special_parser
        is_launchpool = link.special_parser and (link.special_parser.endswith('_launchpool') or link.special_parser.endswith('_launchpad'))
        is_bybit_launchpool = link.special_parser == 'bybit_launchpool' or (exchange == 'bybit' and 'launchpool' in (page_url or '').lower())
        is_mexc_launchpool = link.special_parser == 'mexc_launchpool' or (exchange == 'mexc' and 'launchpool' in (page_url or '').lower())
        is_gate_launchpool = link.special_parser == 'gate_launchpool' or (exchange == 'gate' and 'launchpool' in (page_url or '').lower())
        is_gate_launchpad = link.special_parser == 'gate_launchpad' or (exchange == 'gate' and 'launchpad' in (page_url or '').lower())

        # Пагинация
        page = 1
        per_page = 5
        total_pages = max(1, (len(promos_data) + per_page - 1) // per_page)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_promos = promos_data[start_idx:end_idx]

        # Добавляем статистику участников для ВСЕХ бирж при первом открытии
        if page_promos:
            try:
                from services.participants_tracker_service import get_participants_tracker
                tracker = get_participants_tracker()
                
                for promo in page_promos:
                    promo_id = promo.get('promo_id')
                    if promo_id:
                        stats = tracker.get_participants_stats(exchange_name, promo_id)
                        promo['participants_stats'] = stats
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки статистики участников: {e}")

        # Сохранить состояние
        current_promos_state[user_id] = {
            'page': page,
            'link_id': link_id,
            'total_pages': total_pages,
            'promos': promos_data,
            'exchange_name': exchange_name,
            'page_url': page_url,
            'is_okx_boost': is_okx_boost,
            'is_gate_candy': is_gate_candy,
            'is_bitget_candy': is_bitget_candy,
            'is_phemex_candy': is_phemex_candy,
            'is_mexc_airdrop': is_mexc_airdrop,
            'is_mexc_launchpad': is_mexc_launchpad,
            'is_weex': is_weex,
            'is_weex_rewards': is_weex_rewards_page,
            'is_bybit_launchpool': is_bybit_launchpool,
            'is_mexc_launchpool': is_mexc_launchpool,
            'is_gate_launchpool': is_gate_launchpool,
            'is_gate_launchpad': is_gate_launchpad,
            'is_launchpool': is_launchpool,
            'special_parser': link.special_parser,
            'last_checked': last_checked,
            'last_updated_str': last_updated_str,
            'participants_snapshot': {}
        }
        logger.info(f"   💾 Состояние сохранено: page={page}, total_pages={total_pages}")

        # Форматировать сообщение (skip_price_fetch=True - данные уже в БД, не нужны внешние запросы)
        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)

        # Используем специальный форматтер для каждой биржи
        if is_gate_candy:
            message_text = notif_service.format_gate_candy_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants={}
            )
        elif is_bitget_candy:
            message_text = notif_service.format_bitget_candy_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants={}
            )
        elif is_phemex_candy:
            message_text = notif_service.format_phemex_candy_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants={}
            )
        elif is_weex:
            message_text = notif_service.format_weex_airdrop_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url
            )
        elif is_mexc_launchpad:
            message_text = notif_service.format_mexc_launchpad_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url
            )
        elif is_launchpool:
            # Для BingX и Bitget используем асинхронную версию (нужен браузер)
            if link.special_parser in ['bingx_launchpool', 'bitget_launchpool']:
                message_text = await notif_service.format_launchpool_page_async(
                    promos=page_promos,
                    page=page,
                    total_pages=total_pages,
                    page_url=page_url,
                    special_parser=link.special_parser,
                    exchange_name=exchange_name
                )
            else:
                # Универсальный форматтер для других launchpool парсеров
                message_text = notif_service.format_launchpool_page(
                    promos=page_promos,
                    page=page,
                    total_pages=total_pages,
                    page_url=page_url,
                    special_parser=link.special_parser,
                    exchange_name=exchange_name
                )
        else:
            message_text = notif_service.format_current_promos_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                page_url=page_url
            )

        # Добавляем информацию о времени последнего обновления сразу после "🏦 Биржа:"
        if last_updated_str:
            # Вставляем время обновления после строки с биржей
            if "<b>🏦 Биржа:</b>" in message_text:
                # Находим позицию после строки с биржей и вставляем время
                lines = message_text.split('\n')
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if "<b>🏦 Биржа:</b>" in line:
                        new_lines.append(f"<b>⏱️ Обновлено:</b> {last_updated_str}")
                message_text = '\n'.join(new_lines)

        # Отправить с кнопками
        keyboard = get_current_promos_keyboard(page, total_pages)

        await callback.message.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"❌ Ошибка просмотра промоакций: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки данных", show_alert=True)


@router.callback_query(F.data == "promos_force_parse")
async def force_parse_promos(callback: CallbackQuery):
    """Принудительный парсинг промоакций (с обновлением БД)"""
    logger.info("🔍 ПРИНУДИТЕЛЬНЫЙ ПАРСИНГ ПРОМОАКЦИЙ")
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        
        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return
        
        # Получаем данные ссылки
        link = await get_link_by_id_async(link_id)
        
        if not link:
            await callback.answer("❌ Ссылка не найдена", show_alert=True)
            return
        
        if link.category not in ('airdrop', 'candybomb', 'drops', 'launches', 'launchpool', 'launchpad', 'announcement'):
            await callback.answer("❌ Эта функция доступна только для drops/launches-ссылок", show_alert=True)
            return
        
        exchange_name = link.name
        page_url = link.page_url
        api_url = link.api_url or link.url
        html_url = link.html_url
        parsing_type = link.parsing_type or 'api'
        
        # Закрываем callback сразу
        await callback.answer()
        
        # Используем LoadingContext для индикации загрузки
        async with LoadingContext(
            callback,
            f"⏳ <b>Принудительный парсинг {exchange_name}...</b>\n\n🌐 Получаем актуальные данные из API...",
            delete_on_complete=True,
            edit_original=True
        ) as loading:
            # Получаем СВЕЖИЕ данные через парсер
            api_promos = []
            try:
                # Определяем биржу из URL
                def get_exchange_from_url(url: str) -> str:
                    try:
                        parsed = urlparse(url)
                        domain = parsed.netloc.lower()
                        parts = domain.split('.')
                        if len(parts) >= 2:
                            return parts[-2] if parts[-1] in ['com', 'io', 'org', 'net', 'ru'] else parts[-1]
                        return domain
                    except:
                        return ''
                
                check_url = html_url or api_url or page_url or ''
                exchange = get_exchange_from_url(check_url)
                logger.info(f"   🔍 Определена биржа: {exchange}")
                
                await loading.update(f"🔄 <b>Парсинг {exchange_name}...</b>\n📊 Обработка данных")
                
                # BINGX/BITGET/PHEMEX: используем асинхронный парсер напрямую
                if link.special_parser in ['bingx_launchpool', 'bitget_launchpool', 'bitget_candybomb', 'phemex_candydrop']:
                    logger.info(f"   🌊 Используем асинхронный парсер: {link.special_parser}")
                    
                    if link.special_parser == 'bingx_launchpool':
                        from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
                        parser = BingxLaunchpoolParser()
                    elif link.special_parser == 'bitget_candybomb':
                        from parsers.bitget_candybomb_parser import BitgetCandybombParser
                        parser = BitgetCandybombParser()
                    elif link.special_parser == 'phemex_candydrop':
                        from parsers.phemex_candydrop_parser import PhemexCandydropParser
                        parser = PhemexCandydropParser()
                    else:
                        from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
                        parser = BitgetLaunchpoolParser()
                    
                    # Получаем проекты асинхронно
                    projects = await parser.get_projects_async()
                    
                    # Конвертируем в формат промоакций
                    api_promos = []
                    for project in projects:
                        if project.status in ['active', 'upcoming']:
                            promo_id = f"{parser.EXCHANGE_NAME.lower()}_{parser.EXCHANGE_TYPE}_{project.id}"
                            formatted_text = parser.format_project(project)
                            
                            # Формируем список типов заданий из pools
                            task_types = []
                            biz_labels = set()
                            for pool in project.pools:
                                if pool.stake_coin and pool.stake_coin not in task_types:
                                    task_types.append(pool.stake_coin)
                                if pool.labels:
                                    biz_labels.update(pool.labels)
                            
                            # Определяем условия (SPOT/CONTRACT)
                            conditions = list(biz_labels) if biz_labels else []
                            
                            # Определяем тип промо-акции
                            is_candydrop = link.special_parser in ['bitget_candybomb', 'phemex_candydrop']
                            
                            api_promos.append({
                                'promo_id': promo_id,
                                'title': f"🌊 {project.token_name} ({project.token_symbol}) - {project.get_status_text()}",
                                'description': formatted_text,
                                'link': project.project_url or parser.BASE_URL,
                                'award_token': project.token_symbol,
                                'start_time': project.start_time,
                                'end_time': project.end_time,
                                'exchange': parser.EXCHANGE_NAME,
                                'type': parser.EXCHANGE_TYPE,
                                'status': project.status,
                                'total_pool_tokens': project.total_pool_tokens,
                                'total_pool_usd': project.total_pool_usd,
                                'total_prize_pool': project.total_pool_tokens,
                                'total_prize_pool_usd': project.total_pool_usd,
                                'total_participants': project.total_participants,
                                'participants_count': project.total_participants,
                                'conditions': conditions,
                                'task_types': task_types,
                                'pools': [{'name': p.stake_coin, 'reward': p.pool_reward, 'labels': p.labels, 'extra': p.extra_data} for p in project.pools],
                                'is_launchpool': not is_candydrop,
                                'is_candybomb': link.special_parser == 'bitget_candybomb',
                                'is_candydrop': link.special_parser == 'phemex_candydrop',
                                'formatted_message': formatted_text,
                            })
                    
                    logger.info(f"   📊 Найдено проектов: {len(api_promos)}")
                else:
                    # Обычные парсеры через executor
                    from bot.parser_service import ParserService
                    
                    def run_parser():
                        parser_service = ParserService()
                        parser = parser_service._select_parser(
                            url=page_url or api_url or html_url,
                            api_url=api_url,
                            html_url=html_url,
                            parsing_type=parsing_type,
                            special_parser=link.special_parser,
                            category=link.category
                        )
                        return parser.get_promotions()
                    
                    loop = asyncio.get_event_loop()
                    api_promos = await loop.run_in_executor(get_executor(), run_parser)
                
                logger.info(f"   📊 Получено через API: {len(api_promos)} промоакций")
            except Exception as e:
                logger.error(f"❌ Ошибка получения данных: {e}", exc_info=True)
                api_promos = []
        
        # После LoadingContext - используем ParserService для обогащения и сохранения уже полученных данных
        if api_promos:
            try:
                from bot.parser_service import ParserService
                
                # ParserService правильно обогащает данные USD и обновляет БД
                parser_service = ParserService()
                
                # Определяем биржу для обогащения ценами
                check_url = html_url or api_url or page_url or ''
                exchange = parser_service._extract_exchange_from_url(check_url)
                
                # Обогащаем уже полученные данные USD ценами
                enriched_promos = parser_service._enrich_promos_with_prices(api_promos, exchange)
                
                # Фильтруем и обновляем существующие записи (это также сохраняет USD)
                new_promos = parser_service._filter_new_promotions(link_id, enriched_promos)
                
                # Сохраняем новые промоакции если есть
                if new_promos:
                    parser_service._save_to_history(link_id, new_promos)
                    logger.info(f"💾 Сохранено {len(new_promos)} новых промоакций")
                
                # Записываем историю участников для отслеживания изменений
                try:
                    from services.participants_tracker_service import ParticipantsTrackerService
                    recorded = ParticipantsTrackerService.record_batch(exchange_name, api_promos)
                    if recorded > 0:
                        logger.info(f"📊 Записано {recorded} записей в историю участников")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка записи истории участников: {e}")
                
                logger.info(f"✅ Принудительный парсинг: обновлено {len(api_promos)} промоакций")
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения промоакций в БД: {e}", exc_info=True)
        
        # Теперь показываем данные из БД (уже обновлённые)
        try:
            await view_current_promos(callback)
        except TelegramBadRequest as e:
            # Callback устарел - отправляем результат в новом сообщении
            if "query is too old" in str(e):
                logger.warning(f"⚠️ Callback устарел, отправляем результат в новом сообщении")
                try:
                    # Получаем данные из БД для нового сообщения
                    promos_data = get_promos_from_db(link_id, exchange_name)
                    if promos_data:
                        # Форматируем сообщение
                        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)
                        
                        # Определяем тип биржи
                        check_url = html_url or api_url or page_url or ''
                        is_mexc_airdrop = (api_url and 'eftd' in api_url.lower()) or (page_url and 'token-airdrop' in page_url.lower())
                        is_mexc_launchpad = (api_url and 'launchpad/list' in api_url.lower()) or (page_url and '/launchpad' in page_url.lower())
                        is_gate_candy = 'gatecandy' in exchange_name.lower().replace(' ', '').replace('.', '') or (api_url and 'candydrop' in api_url.lower() and 'gate' in (check_url or '').lower())
                        is_bitget_candy = 'bitgetcandy' in exchange_name.lower().replace(' ', '').replace('.', '') or link.special_parser == 'bitget_candybomb' or ('bitget' in (check_url or '').lower() and 'candy-bomb' in (check_url or '').lower())
                        is_phemex_candy = 'phemexcandy' in exchange_name.lower().replace(' ', '').replace('.', '') or link.special_parser == 'phemex_candydrop' or ('phemex' in (check_url or '').lower() and 'candy-drop' in (check_url or '').lower())
                        is_weex = 'weex' in (check_url or '').lower()
                        
                        page = 1
                        per_page = 5
                        total_pages = max(1, (len(promos_data) + per_page - 1) // per_page)
                        page_promos = promos_data[:per_page]
                        
                        if is_gate_candy:
                            message_text = notif_service.format_gate_candy_page(promos=page_promos, page=page, total_pages=total_pages, page_url=page_url, prev_participants={})
                        elif is_bitget_candy:
                            message_text = notif_service.format_bitget_candy_page(promos=page_promos, page=page, total_pages=total_pages, page_url=page_url, prev_participants={})
                        elif is_phemex_candy:
                            message_text = notif_service.format_phemex_candy_page(promos=page_promos, page=page, total_pages=total_pages, page_url=page_url, prev_participants={})
                        elif is_weex:
                            message_text = notif_service.format_weex_airdrop_page(promos=page_promos, page=page, total_pages=total_pages, page_url=page_url)
                        elif is_mexc_launchpad:
                            message_text = notif_service.format_mexc_launchpad_page(promos=page_promos, page=page, total_pages=total_pages, page_url=page_url)
                        else:
                            message_text = notif_service.format_current_promos_page(promos=page_promos, page=page, total_pages=total_pages, exchange_name=exchange_name, page_url=page_url)
                        
                        # Добавляем информацию о том, что это результат долгой проверки
                        message_text = f"⏰ <i>Результат принудительной проверки (callback устарел):</i>\n\n" + message_text
                        
                        keyboard = get_current_promos_keyboard(page, total_pages)
                        await callback.message.answer(message_text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
                        logger.info(f"✅ Результат отправлен в новом сообщении")
                    else:
                        await callback.message.answer(f"✅ Принудительная проверка {exchange_name} завершена.\n📭 Активных промоакций не найдено.", parse_mode="HTML")
                except Exception as send_err:
                    logger.error(f"❌ Ошибка отправки нового сообщения: {send_err}")
            else:
                raise
        
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            logger.error(f"❌ Ошибка Telegram: {e}")
        else:
            # Callback устарел на уровне принудительного парсинга - тоже отправляем новое сообщение
            logger.warning(f"⚠️ Callback устарел на этапе парсинга")
            try:
                await callback.message.answer(f"⏰ <i>Принудительная проверка завершена, но callback устарел.</i>\n\n<b>Данные обновлены!</b> Используйте '📋 Текущие промоакции' чтобы увидеть результат.", parse_mode="HTML")
            except:
                pass
    except Exception as e:
        logger.error(f"❌ Ошибка принудительного парсинга промоакций: {e}", exc_info=True)
        try:
            await callback.answer("❌ Ошибка парсинга", show_alert=True)
        except TelegramBadRequest:
            # Callback устарел - отправляем ошибку в новом сообщении
            try:
                await callback.message.answer(f"❌ Ошибка принудительного парсинга: {str(e)[:100]}", parse_mode="HTML")
            except:
                pass


@router.callback_query(F.data.startswith("promos_page_"))
async def navigate_promos_page(callback: CallbackQuery):
    """Навигация по страницам текущих промоакций"""
    try:
        user_id = callback.from_user.id
        action = callback.data.split("_")[2]  # "prev", "next" или "info"

        # Игнорируем нажатие на индикатор страницы
        if action == "info":
            await callback.answer()
            return

        state = current_promos_state.get(user_id)
        if not state:
            await callback.answer("❌ Сессия истекла. Откройте раздел заново.", show_alert=True)
            return

        current_page = state['page']
        total_pages = state['total_pages']

        # Вычисляем новую страницу
        if action == "prev":
            new_page = max(1, current_page - 1)
        else:  # next
            new_page = min(total_pages, current_page + 1)

        if new_page == current_page:
            await callback.answer()
            return

        # Обновляем состояние
        state['page'] = new_page

        # Используем сохраненные данные
        promos_data = state.get('promos', [])
        exchange_name = state.get('exchange_name', 'Unknown')
        page_url = state.get('page_url')

        if not promos_data:
            await callback.answer("❌ Данные потеряны. Откройте раздел заново.", show_alert=True)
            return

        # Проверяем тип для правильной пагинации
        is_okx_boost = state.get('is_okx_boost', False)
        is_gate_candy = state.get('is_gate_candy', False)
        is_bitget_candy = state.get('is_bitget_candy', False)
        is_mexc_airdrop = state.get('is_mexc_airdrop', False)
        is_mexc_launchpad = state.get('is_mexc_launchpad', False)
        is_weex = state.get('is_weex', False)
        is_weex_rewards = state.get('is_weex_rewards', False)
        is_bybit_launchpool = state.get('is_bybit_launchpool', False)
        prev_participants = state.get('participants_snapshot', {})

        # Пагинация - по 5 на страницу
        per_page = 5
        start_idx = (new_page - 1) * per_page
        end_idx = start_idx + per_page
        page_promos = promos_data[start_idx:end_idx]

        # Обновляем статистику участников для ВСЕХ бирж при пагинации
        if page_promos:
            try:
                from services.participants_tracker_service import get_participants_tracker
                tracker = get_participants_tracker()
                
                for promo in page_promos:
                    promo_id = promo.get('promo_id')
                    if promo_id:
                        stats = tracker.get_participants_stats(exchange_name, promo_id)
                        promo['participants_stats'] = stats
            except Exception as e:
                logger.warning(f"⚠️ Ошибка обновления статистики при пагинации: {e}")

        # Форматировать сообщение (skip_price_fetch=True - данные уже в БД)
        notif_service = NotificationService(bot=callback.bot, skip_price_fetch=True)

        # Используем специальный форматтер для каждой биржи
        if is_gate_candy:
            message_text = notif_service.format_gate_candy_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants=prev_participants
            )
        elif is_bitget_candy:
            message_text = notif_service.format_bitget_candy_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants=prev_participants
            )
        elif state.get('is_phemex_candy'):
            message_text = notif_service.format_phemex_candy_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants=prev_participants
            )
        elif is_weex:
            message_text = notif_service.format_weex_airdrop_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url
            )
        elif is_mexc_launchpad:
            message_text = notif_service.format_mexc_launchpad_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url
            )
        elif state.get('is_launchpool'):
            # Для BingX и Bitget используем асинхронную версию
            special_parser = state.get('special_parser')
            if special_parser in ['bingx_launchpool', 'bitget_launchpool']:
                message_text = await notif_service.format_launchpool_page_async(
                    promos=page_promos,
                    page=new_page,
                    total_pages=total_pages,
                    page_url=page_url,
                    special_parser=special_parser,
                    exchange_name=exchange_name
                )
            else:
                # Универсальный форматтер для других launchpool парсеров
                message_text = notif_service.format_launchpool_page(
                    promos=page_promos,
                    page=new_page,
                    total_pages=total_pages,
                    page_url=page_url,
                    special_parser=special_parser,
                    exchange_name=exchange_name
                )
        else:
            message_text = notif_service.format_current_promos_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                page_url=page_url
            )

        # Добавляем время обновления сразу после "🏦 Биржа:"
        last_updated_str = state.get('last_updated_str', '')
        if last_updated_str:
            if "<b>🏦 Биржа:</b>" in message_text:
                lines = message_text.split('\n')
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if "<b>🏦 Биржа:</b>" in line:
                        new_lines.append(f"<b>⏱️ Обновлено:</b> {last_updated_str}")
                message_text = '\n'.join(new_lines)

        # Отправить с обновленными кнопками
        keyboard = get_current_promos_keyboard(new_page, total_pages)

        await callback.message.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка навигации промоакций: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "back_to_link_management")
async def back_to_link_management(callback: CallbackQuery):
    """Возврат к меню управления ссылкой"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        # Вызываем вспомогательную функцию напрямую с link_id
        await _show_link_management_by_id(callback, link_id)

    except Exception as e:
        logger.error(f"❌ Ошибка возврата: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "stakings_configure_apr")
async def configure_min_apr(callback: CallbackQuery):
    """Диалог настройки минимального APR"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            current_apr = link.min_apr or 0
            exchange_name = link.name

        # Клавиатура с пресетами
        builder = InlineKeyboardBuilder()

        presets = [1, 5, 10, 20, 50, 100, 200, 500]
        for apr in presets:
            builder.add(InlineKeyboardButton(
                text=f"{apr}%",
                callback_data=f"set_apr_{link_id}_{apr}"
            ))

        builder.adjust(4)  # 4 кнопки в ряд

        builder.row(InlineKeyboardButton(
            text="🗑️ Убрать фильтр",
            callback_data=f"set_apr_{link_id}_0"
        ))

        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="manage_view_current_stakings"))

        await callback.message.edit_text(
            f"<b>⚙️ НАСТРОЙКА ФИЛЬТРА APR</b>\n\n"
            f"🏦 <b>Биржа:</b> {exchange_name}\n"
            f"📌 <b>Текущий минимальный APR:</b> {current_apr}%\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Выберите новое значение:</b>\n\n"
            f"💡 <i>Будут показаны только стейкинги с APR ≥ выбранного значения</i>",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка настройки APR: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_settings_show")
async def notification_settings_show(callback: CallbackQuery):
    """Показать настройки умных уведомлений"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            # Форматирование настроек
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка показа настроек: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_settings_change_stability")
async def change_stability_hours(callback: CallbackQuery):
    """Показать пресеты времени стабилизации"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            current_hours = link.flexible_stability_hours
            link_name = link.name  # Сохранить перед закрытием сессии

        keyboard = get_stability_hours_keyboard()

        await callback.message.edit_text(
            f"⏱️ <b>НАСТРОЙКА ВРЕМЕНИ СТАБИЛИЗАЦИИ</b>\n\n"
            f"🏦 <b>Биржа:</b> {link_name}\n"
            f"📌 <b>Текущее значение:</b> {current_hours} часов\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <i>Flexible стейкинги будут уведомлять\n"
            f"только после X часов стабильного APR</i>\n\n"
            f"<b>Выберите новое значение:</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка изменения времени стабилизации: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("set_stability_"))
async def set_stability_hours(callback: CallbackQuery):
    """Установить время стабилизации из пресета"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        # Извлечь hours из callback.data
        hours = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.flexible_stability_hours = hours
            db.commit()

            # Показать обновленные настройки
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await callback.answer(f"✅ Время стабилизации изменено на {hours} часов")

    except Exception as e:
        logger.error(f"❌ Ошибка установки времени стабилизации: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_settings_change_apr_threshold")
async def change_apr_threshold(callback: CallbackQuery):
    """Показать пресеты порога APR"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            current_threshold = link.notify_min_apr_change
            link_name = link.name  # Сохранить перед закрытием сессии

        keyboard = get_apr_threshold_keyboard()

        await callback.message.edit_text(
            f"📊 <b>НАСТРОЙКА ПОРОГА ИЗМЕНЕНИЯ APR</b>\n\n"
            f"🏦 <b>Биржа:</b> {link_name}\n"
            f"📌 <b>Текущее значение:</b> {current_threshold}%\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <i>Уведомлять только если APR изменился\n"
            f"на X% или больше (абсолютное изменение)</i>\n\n"
            f"<b>Примеры:</b>\n"
            f"• 20% → 25% = изменение 5%\n"
            f"• 100% → 110% = изменение 10%\n\n"
            f"<b>Выберите новое значение:</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка изменения порога APR: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("set_apr_threshold_"))
async def set_apr_threshold(callback: CallbackQuery):
    """Установить порог APR из пресета"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        # Извлечь threshold из callback.data
        threshold = float(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.notify_min_apr_change = threshold
            db.commit()

            # Показать обновленные настройки
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await callback.answer(f"✅ Порог изменения APR установлен на {threshold}%")

    except Exception as e:
        logger.error(f"❌ Ошибка установки порога APR: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_toggle_new_stakings")
async def toggle_new_stakings(callback: CallbackQuery):
    """Переключить уведомления о новых стейкингах"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            # Инвертировать значение
            link.notify_new_stakings = not link.notify_new_stakings
            db.commit()

            # Показать обновленные настройки
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включены" if link.notify_new_stakings else "❌ Выключены"
            await callback.answer(f"Уведомления о новых стейкингах: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения новых стейкингов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_toggle_apr_changes")
async def toggle_apr_changes(callback: CallbackQuery):
    """Переключить уведомления об изменениях APR"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.notify_apr_changes = not link.notify_apr_changes
            db.commit()

            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включены" if link.notify_apr_changes else "❌ Выключены"
            await callback.answer(f"Уведомления об изменениях APR: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения изменений APR: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_toggle_fixed_immediately")
async def toggle_fixed_immediately(callback: CallbackQuery):
    """Переключить уведомления Fixed сразу"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.fixed_notify_immediately = not link.fixed_notify_immediately
            db.commit()

            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включено" if link.fixed_notify_immediately else "❌ Выключено"
            await callback.answer(f"Fixed стейкинги сразу: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения Fixed сразу: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_toggle_combined_as_fixed")
async def toggle_combined_as_fixed(callback: CallbackQuery):
    """Переключить Combined как Fixed"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.notify_combined_as_fixed = not link.notify_combined_as_fixed
            db.commit()

            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включено" if link.notify_combined_as_fixed else "❌ Выключено"
            await callback.answer(f"Combined как Fixed: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения Combined как Fixed: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "notification_toggle_only_stable")
async def toggle_only_stable(callback: CallbackQuery):
    """Переключить только стабильные Flexible"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.notify_only_stable_flexible = not link.notify_only_stable_flexible
            db.commit()

            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включено" if link.notify_only_stable_flexible else "❌ Выключено"
            await callback.answer(f"Только стабильные Flexible: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения стабильных Flexible: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("set_apr_"))
async def set_min_apr_preset(callback: CallbackQuery):
    """Установка APR из пресета"""
    try:
        parts = callback.data.split("_")
        link_id = int(parts[2])
        new_apr = float(parts[3])

        # Обновить БД
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.min_apr = new_apr if new_apr > 0 else None
            db.commit()

            exchange_name = link.name

        # Вернуться к списку стейкингов
        if new_apr > 0:
            await callback.answer(f"✅ APR фильтр установлен: {new_apr}%")
        else:
            await callback.answer("✅ APR фильтр убран")

        # Перезагрузить список стейкингов (вызываем view_current_stakings)
        await view_current_stakings(callback)

    except Exception as e:
        logger.error(f"❌ Ошибка установки APR: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "notification_toggle_fill_changes")
async def toggle_fill_changes(callback: CallbackQuery):
    """Переключить уведомления о заполненности пулов"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            link.notify_fill_changes = not link.notify_fill_changes
            db.commit()

            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            status = "✅ Включены" if link.notify_fill_changes else "❌ Выключены"
            await callback.answer(f"Уведомления о заполненности: {status}")

    except Exception as e:
        logger.error(f"❌ Ошибка переключения заполненности: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


# =============================================================================
# НАСТРОЙКИ LAUNCHPOOL УВЕДОМЛЕНИЙ
# =============================================================================

@router.callback_query(F.data == "notification_toggle_period_changes")
async def toggle_period_changes(callback: CallbackQuery):
    """Переключить уведомления об изменении периода лаунчпула"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return
            link.notify_period_changes = not getattr(link, 'notify_period_changes', True)
            db.commit()
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()
            await callback.message.edit_text(message, parse_mode="HTML", reply_markup=keyboard)
            status = "✅ Включены" if link.notify_period_changes else "❌ Выключены"
            await callback.answer(f"Уведомления об изменении периода: {status}")
    except Exception as e:
        logger.error(f"❌ Ошибка переключения уведомлений периода: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "notification_toggle_reward_pool_changes")
async def toggle_reward_pool_changes(callback: CallbackQuery):
    """Переключить уведомления об изменении общего пула наград лаунчпула"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return
            link.notify_reward_pool_changes = not getattr(link, 'notify_reward_pool_changes', True)
            db.commit()
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()
            await callback.message.edit_text(message, parse_mode="HTML", reply_markup=keyboard)
            status = "✅ Включены" if link.notify_reward_pool_changes else "❌ Выключены"
            await callback.answer(f"Уведомления об изменении пула наград: {status}")
    except Exception as e:
        logger.error(f"❌ Ошибка переключения уведомлений пула наград: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "notification_other_settings")
async def show_other_settings(callback: CallbackQuery):
    """Показать остальные настройки launchpool уведомлений"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return
            
            # Используем функцию для создания клавиатуры
            keyboard = get_other_notification_settings_keyboard(link)
        
        await callback.message.edit_text(
            "⚙️ <b>Другие настройки уведомлений</b>\n\n"
            "Выберите опцию для переключения:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка показа других настроек: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


# =============================================================================
# ПОДМЕНЮ НАСТРОЕК ССЫЛКИ (НОВЫЙ РЕФАКТОРИНГ)
# =============================================================================

@router.callback_query(F.data == "manage_settings_submenu")
async def manage_settings_submenu(callback: CallbackQuery):
    """Показывает подменю настроек для текущей ссылки"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        
        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return
        
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            
            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                await callback.answer()
                return
            
            # Информация о ссылке
            parsing_type_text = {
                'api': 'API',
                'html': 'HTML',
                'browser': 'Browser',
                'combined': 'Комбинированный',
                'telegram': 'Telegram'
            }.get(link.parsing_type, 'Комбинированный')
            
            # Клавиатура подменю настроек
            keyboard = get_link_settings_submenu_keyboard(link)
            
            await callback.message.edit_text(
                f"⚙️ <b>Настройки ссылки:</b> {link.name}\n\n"
                f"<b>⏱ Интервал:</b> {link.check_interval}с ({link.check_interval // 60} мин)\n"
                f"<b>📡 Тип парсинга:</b> {parsing_type_text}\n\n"
                f"Выберите что настроить:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()
            
    except Exception as e:
        logger.error(f"❌ Ошибка при открытии настроек: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при открытии настроек")
        await callback.answer()


@router.callback_query(F.data == "manage_change_category")
async def manage_change_category(callback: CallbackQuery):
    """Быстрая смена категории из главного меню управления"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        
        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return
        
        # Перенаправляем на существующий обработчик редактирования категории
        from unittest.mock import Mock
        edit_callback = Mock()
        edit_callback.data = f"edit_category_{link_id}"
        edit_callback.message = callback.message
        edit_callback.answer = callback.answer
        edit_callback.from_user = callback.from_user
        
        await edit_category(edit_callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при смене категории: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "manage_delete")
async def manage_delete(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id

        # ПРОВЕРЯЕМ: может link_id уже выбран?
        if user_id in user_selections:
            link_id = user_selections[user_id]

            # Получаем ссылку из БД
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if link:
                    # СРАЗУ показываем подтверждение удаления
                    keyboard = get_confirmation_keyboard(link_id, "delete")
                    await callback.message.edit_text(
                        f"⚠️ <b>Вы уверены что хотите удалить ссылку?</b>\n\n"
                        f"<b>Название:</b> {link.name}\n"
                        f"<b>URL:</b> <code>{link.url}</code>\n\n"
                        f"Это действие нельзя отменить!",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    await callback.answer()
                    return

        # Если link_id не выбран - показываем список (старое поведение)
        # Сохраняем контекст навигации
        push_navigation(user_id, NAV_DELETE)

        with get_db_session() as db:
            links = db.query(ApiLink).all()

            if not links:
                await callback.message.edit_text("❌ У вас нет ссылок для удаления")
                return

            # Детач данных
            links_data = []
            for link in links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval,
                    'parsing_type': link.parsing_type or 'combined'
                })())

            keyboard = get_links_keyboard(links_data, "delete")
            await callback.message.edit_text("🗑️ <b>Выберите ссылку для удаления:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при удалении: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении")
        await callback.answer()

@router.callback_query(F.data.startswith("delete_link_"))
async def process_link_selection(callback: CallbackQuery):
    try:
        link_id = int(callback.data.split("_")[2])
        
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            
            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return
            
            keyboard = get_confirmation_keyboard(link_id, "delete")
            await callback.message.edit_text(
                f"⚠️ <b>Вы уверены что хотите удалить ссылку?</b>\n\n"
                f"<b>Название:</b> {link.name}\n"
                f"<b>URL:</b> <code>{link.url}</code>\n\n"
                f"Это действие нельзя отменить!",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при выборе ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при выборе ссылки")
        await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_"))
async def process_confirmation(callback: CallbackQuery):
    try:
        link_id = int(callback.data.split("_")[2])
        
        def delete_link_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link_name = link.name
            session.delete(link)
            return link_name

        link_name = atomic_operation(delete_link_operation)

        if callback.from_user.id in user_selections:
            del user_selections[callback.from_user.id]

        # Проверяем, остались ли ещё ссылки
        with get_db_session() as db:
            remaining_links = db.query(ApiLink).all()

            if remaining_links:
                # Если остались ссылки - показываем обновленный список
                links_data = []
                for link in remaining_links:
                    links_data.append(type('Link', (), {
                        'id': link.id,
                        'name': link.name,
                        'is_active': link.is_active,
                        'check_interval': link.check_interval,
                        'parsing_type': link.parsing_type or 'combined'
                    })())

                keyboard = get_links_keyboard(links_data, "delete")
                await callback.message.edit_text(
                    f"✅ <b>Ссылка '{link_name}' успешно удалена!</b>\n\n"
                    f"🗑️ Выберите следующую ссылку для удаления:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                # Если ссылок больше нет
                navigation_keyboard = get_cancel_keyboard_with_navigation()
                await callback.message.edit_text(
                    f"✅ <b>Ссылка '{link_name}' успешно удалена!</b>\n\n"
                    f"📭 У вас больше нет ссылок.",
                    parse_mode="HTML",
                    reply_markup=navigation_keyboard
                )

        await callback.answer("✅ Ссылка удалена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении ссылки")
        await callback.answer()

@router.callback_query(F.data.in_(["cancel_action", "manage_cancel"]))
async def process_cancel(callback: CallbackQuery):
    """Улучшенный обработчик отмены с навигацией"""
    user_id = callback.from_user.id

    # Очищаем выбор пользователя
    if user_id in user_selections:
        del user_selections[user_id]

    # Проверяем текущий контекст навигации БЕЗ удаления
    current_context = get_current_navigation(user_id)

    if current_context and current_context["context"] == NAV_MANAGEMENT:
        # Возвращаемся к выбору категории для управления ссылками
        await callback.message.edit_text(
            "🗂️ <b>Выберите раздел для управления:</b>",
            reply_markup=get_category_management_menu(),
            parse_mode="HTML"
        )
    else:
        # Если нет контекста управления - возвращаемся в главное меню
        clear_navigation(user_id)
        await callback.message.edit_text(
            "🏠 <b>Меню</b>\n\n"
            "📌 <i>Выберите действие:</i>",
            reply_markup=get_main_menu_inline(),
            parse_mode="HTML"
        )

    await callback.answer()

# ОБРАБОТЧИКИ НАВИГАЦИИ
@router.callback_query(F.data == "nav_back")
async def nav_back_handler(callback: CallbackQuery):
    """Возврат к предыдущему шагу в стеке навигации"""
    user_id = callback.from_user.id

    # Удаляем текущий контекст
    pop_navigation(user_id)

    # Получаем предыдущий контекст
    prev_context = get_current_navigation(user_id)

    if prev_context:
        context = prev_context["context"]

        # Перенаправляем на соответствующий обработчик в зависимости от контекста
        if context == NAV_MANAGEMENT:
            await callback.message.edit_text(
                "⚙️ <b>Управление ссылками</b>\n\n"
                "Выберите действие:",
                reply_markup=get_management_keyboard(),
                parse_mode="HTML"
            )
        elif context == NAV_DELETE:
            # Возвращаемся к выбору ссылки для удаления
            callback.data = "manage_delete"
            await manage_delete(callback)
            return
        elif context == NAV_INTERVAL:
            callback.data = "manage_interval"
            await manage_interval(callback)
            return
        else:
            # Если контекст неизвестен, возвращаемся в главное меню
            clear_navigation(user_id)
            await callback.message.edit_text(
                "🏠 <b>Меню</b>\n\n"
                "📌 <i>Выберите действие:</i>",
                reply_markup=get_main_menu_inline(),
                parse_mode="HTML"
            )
            await callback.answer()
            return
    else:
        # Если стек пустой, возвращаемся в главное меню
        clear_navigation(user_id)
        await callback.message.edit_text(
            "🏠 <b>Меню</b>\n\n"
            "📌 <i>Выберите действие:</i>",
            reply_markup=get_main_menu_inline(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    await callback.answer()

@router.callback_query(F.data == "back_to_management")
async def back_to_management_handler(callback: CallbackQuery):
    """Возврат к меню управления ссылками"""
    clear_navigation(callback.from_user.id)
    push_navigation(callback.from_user.id, NAV_MANAGEMENT)

    await callback.message.edit_text(
        "⚙️ <b>Управление ссылками</b>\n\n"
        "Выберите действие:",
        reply_markup=get_management_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_handler(callback: CallbackQuery):
    """Возврат в главное меню"""
    clear_navigation(callback.from_user.id)

    # Редактируем текущее сообщение на главное меню
    await callback.message.edit_text(
        "🏠 <b>Меню</b>\n\n"
        "📌 <i>Выберите действие:</i>",
        reply_markup=get_main_menu_inline(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "manage_interval")
async def manage_interval(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id

        # ПРОВЕРЯЕМ: может link_id уже выбран?
        if user_id in user_selections:
            link_id = user_selections[user_id]

            # Получаем ссылку из БД
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if link:
                    # СРАЗУ показываем выбор интервала
                    keyboard = get_interval_presets_keyboard(link_id)
                    await callback.message.edit_text(
                        f"⏰ <b>Настройка интервала для:</b>\n\n"
                        f"<b>Название:</b> {link.name}\n"
                        f"<b>Текущий интервал:</b> {link.check_interval} сек ({link.check_interval // 60} мин)\n\n"
                        f"Выберите интервал проверки:",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    await callback.answer()
                    return

        # Если link_id не выбран - показываем список (старое поведение)
        # Сохраняем контекст навигации
        push_navigation(user_id, NAV_INTERVAL)

        with get_db_session() as db:
            links = db.query(ApiLink).all()

            if not links:
                await callback.message.edit_text("❌ У вас нет ссылок для изменения интервала")
                return

            # Детач данных
            links_data = []
            for link in links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval,
                    'parsing_type': link.parsing_type or 'combined'
                })())

            keyboard = get_links_keyboard(links_data, "interval")
            await callback.message.edit_text("⏰ <b>Выберите ссылку для изменения интервала:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при изменении интервала: {e}")
        await callback.message.edit_text("❌ Ошибка при изменении интервала")
        await callback.answer()

@router.callback_query(F.data == "manage_rename")
async def manage_rename(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id

        # ПРОВЕРЯЕМ: может link_id уже выбран?
        if user_id in user_selections:
            link_id = user_selections[user_id]

            # Получаем ссылку из БД
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if link:
                    # СРАЗУ запрашиваем новое имя
                    await state.update_data(link_id=link_id, current_name=link.name)
                    
                    # Клавиатура с кнопкой отмены
                    cancel_kb = InlineKeyboardBuilder()
                    cancel_kb.add(InlineKeyboardButton(
                        text="❌ Отмена", 
                        callback_data=f"cancel_rename_{link_id}"
                    ))
                    
                    await callback.message.edit_text(
                        f"✏️ <b>Переименование ссылки</b>\n\n"
                        f"<b>Текущее имя:</b> {link.name}\n\n"
                        f"Введите новое имя для ссылки:",
                        reply_markup=cancel_kb.as_markup(),
                        parse_mode="HTML"
                    )
                    await state.set_state(RenameLinkStates.waiting_for_new_name)
                    await callback.answer()
                    return

        # Если link_id не выбран - показываем список (старое поведение)
        with get_db_session() as db:
            links = db.query(ApiLink).all()

            if not links:
                await callback.message.edit_text("❌ У вас нет ссылок для переименования")
                return

            # Детач данных
            links_data = []
            for link in links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval,
                    'parsing_type': link.parsing_type or 'combined'
                })())

            keyboard = get_links_keyboard(links_data, "rename")
            await callback.message.edit_text("✏️ <b>Выберите ссылку для переименования:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при переименовании: {e}")
        await callback.message.edit_text("❌ Ошибка при переименовании")
        await callback.answer()

@router.callback_query(F.data.startswith("rename_link_"))
async def process_rename_selection(callback: CallbackQuery, state: FSMContext):
    try:
        link_id = int(callback.data.split("_")[2])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            await state.update_data(link_id=link_id, current_name=link.name)
            
            # Клавиатура с кнопкой отмены
            cancel_kb = InlineKeyboardBuilder()
            cancel_kb.add(InlineKeyboardButton(
                text="❌ Отмена", 
                callback_data=f"cancel_rename_{link_id}"
            ))
            
            await callback.message.edit_text(
                f"✏️ <b>Переименование ссылки</b>\n\n"
                f"<b>Текущее имя:</b> {link.name}\n\n"
                f"Введите новое имя для ссылки:",
                reply_markup=cancel_kb.as_markup(),
                parse_mode="HTML"
            )
            await state.set_state(RenameLinkStates.waiting_for_new_name)

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при выборе ссылки для переименования: {e}")
        await callback.message.edit_text("❌ Ошибка при выборе ссылки")
        await callback.answer()


@router.callback_query(F.data.startswith("cancel_rename_"))
async def cancel_rename(callback: CallbackQuery, state: FSMContext):
    """Отмена переименования ссылки"""
    try:
        link_id = int(callback.data.split("_")[2])
        
        # Очищаем состояние
        await state.clear()
        
        # Возвращаемся к управлению ссылкой
        await _show_link_management_by_id(callback, link_id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отмене переименования: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(RenameLinkStates.waiting_for_new_name)
async def process_new_name_input(message: Message, state: FSMContext):
    try:
        new_name = message.text.strip()

        if not new_name:
            await message.answer("❌ Имя не может быть пустым. Попробуйте снова:")
            return

        if len(new_name) > 100:
            await message.answer("❌ Имя слишком длинное (максимум 100 символов). Введите другое имя:")
            return

        data = await state.get_data()
        link_id = data.get('link_id')
        current_name = data.get('current_name')

        def rename_link_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.name = new_name
            return link.exchange

        exchange = atomic_operation(rename_link_operation)

        await state.clear()

        # Проверяем, был ли вызван из меню управления конкретной ссылкой
        user_id = message.from_user.id
        if user_id in user_selections:
            # Возвращаемся к настройкам ссылки
            keyboard = get_back_to_settings_keyboard(link_id)
            await message.answer(
                f"✅ <b>Ссылка переименована!</b>\n\n"
                f"<b>Было:</b> {current_name}\n"
                f"<b>Стало:</b> {new_name}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Старое поведение - показываем список для продолжения
            with get_db_session() as db:
                links = db.query(ApiLink).all()

                if links:
                    links_data = []
                    for link in links:
                        links_data.append(type('Link', (), {
                            'id': link.id,
                            'name': link.name,
                            'is_active': link.is_active,
                            'check_interval': link.check_interval,
                            'parsing_type': link.parsing_type or 'combined'
                        })())

                    keyboard = get_links_keyboard(links_data, "rename")
                    await message.answer(
                        f"✅ <b>Ссылка переименована!</b>\n"
                        f"'{current_name}' → '{new_name}'\n\n"
                        f"✏️ Выберите следующую ссылку для переименования:",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    navigation_keyboard = get_cancel_keyboard_with_navigation()
                    await message.answer(
                        f"✅ <b>Ссылка переименована!</b>\n\n"
                        f"<b>Старое имя:</b> {current_name}\n"
                        f"<b>Новое имя:</b> {new_name}",
                        parse_mode="HTML",
                        reply_markup=navigation_keyboard
                    )

    except Exception as e:
        logger.error(f"❌ Ошибка при переименовании ссылки: {e}")
        await message.answer("❌ Ошибка при переименовании ссылки")
        await state.clear()

@router.callback_query(F.data.startswith("interval_link_"))
async def process_interval_selection(callback: CallbackQuery):
    try:
        link_id = int(callback.data.split("_")[2])
        
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            
            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return
            
            user_selections[callback.from_user.id] = link
            keyboard = get_interval_presets_keyboard(link_id)
            await callback.message.edit_text(
                f"⏰ <b>Настройка интервала для:</b>\n\n"
                f"<b>Название:</b> {link.name}\n"
                f"<b>Текущий интервал:</b> {link.check_interval} сек ({link.check_interval // 60} мин)\n\n"
                f"Выберите интервал проверки:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при выборе интервала: {e}")
        await callback.message.edit_text("❌ Ошибка при выборе интервала")
        await callback.answer()

@router.callback_query(F.data.startswith("interval_preset_"))
async def process_interval_preset(callback: CallbackQuery):
    try:
        parts = callback.data.split("_")
        link_id = int(parts[2])
        interval_seconds = int(parts[3])
        
        def update_interval_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.check_interval = interval_seconds
            return link.name
        
        link_name = atomic_operation(update_interval_operation)

        interval_minutes = interval_seconds // 60
        
        # Проверяем, был ли вызван из меню управления конкретной ссылкой
        user_id = callback.from_user.id
        if user_id in user_selections:
            # Возвращаемся к настройкам ссылки
            keyboard = get_back_to_settings_keyboard(link_id)
            await callback.message.edit_text(
                f"✅ <b>Интервал обновлен!</b>\n\n"
                f"<b>Ссылка:</b> {link_name}\n"
                f"<b>Новый интервал:</b> {interval_seconds} сек ({interval_minutes} мин)",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Старое поведение - показываем список для продолжения
            with get_db_session() as db:
                links = db.query(ApiLink).all()

                if links:
                    links_data = []
                    for link in links:
                        links_data.append(type('Link', (), {
                            'id': link.id,
                            'name': link.name,
                            'is_active': link.is_active,
                            'check_interval': link.check_interval,
                            'parsing_type': link.parsing_type or 'combined'
                        })())

                    keyboard = get_links_keyboard(links_data, "interval")
                    await callback.message.edit_text(
                        f"✅ <b>Интервал обновлен для '{link_name}'!</b>\n"
                        f"<b>Новый интервал:</b> {interval_seconds} сек ({interval_minutes} мин)\n\n"
                        f"⏰ Выберите следующую ссылку для изменения интервала:",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    navigation_keyboard = get_cancel_keyboard_with_navigation()
                    await callback.message.edit_text(
                        f"✅ <b>Интервал обновлен!</b>\n\n"
                        f"<b>Ссылка:</b> {link_name}\n"
                        f"<b>Новый интервал:</b> {interval_seconds} сек ({interval_minutes} мин)",
                        parse_mode="HTML",
                        reply_markup=navigation_keyboard
                    )

        await callback.answer("✅ Интервал обновлен")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при установке интервала: {e}")
        await callback.message.edit_text("❌ Ошибка при установке интервала")
        await callback.answer()

@router.callback_query(F.data.startswith("interval_custom_"))
async def process_custom_interval(callback: CallbackQuery, state: FSMContext):
    try:
        link_id = int(callback.data.split("_")[2])
        await state.update_data(link_id=link_id)
        await callback.message.edit_text(
            "⏰ <b>Введите интервал в секундах:</b>\n\n"
            "Минимальный: 60 сек (1 минута)\n"
            "Максимальный: 86400 сек (24 часа)",
            parse_mode="HTML"
        )
        await state.set_state(IntervalStates.waiting_for_interval)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запросе кастомного интервала: {e}")
        await callback.message.edit_text("❌ Ошибка при запросе интервала")
        await callback.answer()

@router.message(IntervalStates.waiting_for_interval)
async def process_interval_input(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        link_id = data.get('link_id')
        
        try:
            interval_seconds = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Введите корректное число (только цифры):")
            return
        
        if interval_seconds < 60 or interval_seconds > 86400:
            await message.answer("❌ Интервал должен быть от 60 до 86400 секунд. Попробуйте снова:")
            return
        
        def update_interval_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.check_interval = interval_seconds
            return link.name

        link_name = atomic_operation(update_interval_operation)
        
        interval_minutes = interval_seconds // 60
        await message.answer(
            f"✅ <b>Интервал обновлен!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый интервал:</b> {interval_seconds} сек ({interval_minutes} мин)\n\n"
            f"Теперь проверка будет выполняться каждые {interval_minutes} минут.",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при установке интервала: {e}")
        await message.answer("❌ Ошибка при установке интервала")
        await state.clear()

@router.callback_query(F.data == "manage_pause")
async def manage_pause(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id

        # ПРОВЕРЯЕМ: может link_id уже выбран?
        if user_id in user_selections:
            link_id = user_selections[user_id]

            # СРАЗУ останавливаем парсинг для этой ссылки
            def pause_link_operation(session):
                link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
                if not link:
                    raise ValueError("Ссылка не найдена")
                link.is_active = False
                return link.name

            link_name = atomic_operation(pause_link_operation)

            # Возвращаемся к управлению ссылкой с обновленной клавиатурой
            keyboard = get_back_to_link_keyboard(link_id)
            await callback.message.edit_text(
                f"⏸️ <b>Парсинг остановлен!</b>\n\n"
                f"<b>Ссылка:</b> {link_name}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

            await callback.answer("⏸️ Парсинг остановлен")
            return

        # Если link_id не выбран - показываем список (старое поведение)
        with get_db_session() as db:
            active_links = db.query(ApiLink).filter(ApiLink.is_active == True).all()

            if not active_links:
                await callback.message.edit_text("❌ Нет активных ссылок для остановки")
                return

            # Детач данных
            links_data = []
            for link in active_links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval
                })())

            keyboard = get_toggle_parsing_keyboard(links_data, "pause")
            await callback.message.edit_text("⏸️ <b>Выберите ссылку для остановки парсинга:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при остановке парсинга: {e}")
        await callback.message.edit_text("❌ Ошибка при остановке парсинга")
        await callback.answer()

@router.callback_query(F.data == "manage_resume")
async def manage_resume(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id

        # ПРОВЕРЯЕМ: может link_id уже выбран?
        if user_id in user_selections:
            link_id = user_selections[user_id]

            # СРАЗУ возобновляем парсинг для этой ссылки
            def resume_link_operation(session):
                link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
                if not link:
                    raise ValueError("Ссылка не найдена")
                link.is_active = True
                return link.name

            link_name = atomic_operation(resume_link_operation)

            # Возвращаемся к управлению ссылкой с обновленной клавиатурой
            keyboard = get_back_to_link_keyboard(link_id)
            await callback.message.edit_text(
                f"▶️ <b>Парсинг включен!</b>\n\n"
                f"<b>Ссылка:</b> {link_name}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

            await callback.answer("▶️ Парсинг включен")
            return

        # Если link_id не выбран - показываем список (старое поведение)
        with get_db_session() as db:
            inactive_links = db.query(ApiLink).filter(ApiLink.is_active == False).all()

            if not inactive_links:
                await callback.message.edit_text("❌ Нет остановленных ссылок для возобновления")
                return

            # Детач данных
            links_data = []
            for link in inactive_links:
                links_data.append(type('Link', (), {
                    'id': link.id,
                    'name': link.name,
                    'is_active': link.is_active,
                    'check_interval': link.check_interval
                })())

            keyboard = get_toggle_parsing_keyboard(links_data, "resume")
            await callback.message.edit_text("▶️ <b>Выберите ссылку для возобновления парсинга:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при возобновлении парсинга: {e}")
        await callback.message.edit_text("❌ Ошибка при возобновлении парсинга")
        await callback.answer()

@router.callback_query(F.data.startswith("pause_link_"))
async def process_pause_link(callback: CallbackQuery):
    try:
        link_id = int(callback.data.split("_")[2])

        def pause_link_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.is_active = False
            return link.name

        link_name = atomic_operation(pause_link_operation)

        # Показываем обновленный список активных ссылок для продолжения остановки
        with get_db_session() as db:
            active_links = db.query(ApiLink).filter(ApiLink.is_active == True).all()

            if active_links:
                links_data = []
                for link in active_links:
                    links_data.append(type('Link', (), {
                        'id': link.id,
                        'name': link.name,
                        'is_active': link.is_active,
                        'check_interval': link.check_interval,
                        'parsing_type': link.parsing_type or 'combined'
                    })())

                keyboard = get_toggle_parsing_keyboard(links_data, "pause")
                await callback.message.edit_text(
                    f"⏸️ <b>Парсинг остановлен для '{link_name}'!</b>\n\n"
                    f"Выберите следующую ссылку для остановки:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                navigation_keyboard = get_cancel_keyboard_with_navigation()
                await callback.message.edit_text(
                    f"⏸️ <b>Парсинг остановлен для '{link_name}'!</b>\n\n"
                    f"Все ссылки остановлены.",
                    parse_mode="HTML",
                    reply_markup=navigation_keyboard
                )

        await callback.answer("⏸️ Парсинг остановлен")

    except Exception as e:
        logger.error(f"❌ Ошибка при остановке ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при остановке ссылки")
        await callback.answer()

@router.callback_query(F.data.startswith("resume_link_"))
async def process_resume_link(callback: CallbackQuery):
    try:
        link_id = int(callback.data.split("_")[2])

        def resume_link_operation(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            link.is_active = True
            return link.name

        link_name = atomic_operation(resume_link_operation)

        # Показываем обновленный список неактивных ссылок для продолжения возобновления
        with get_db_session() as db:
            inactive_links = db.query(ApiLink).filter(ApiLink.is_active == False).all()

            if inactive_links:
                links_data = []
                for link in inactive_links:
                    links_data.append(type('Link', (), {
                        'id': link.id,
                        'name': link.name,
                        'is_active': link.is_active,
                        'check_interval': link.check_interval,
                        'parsing_type': link.parsing_type or 'combined'
                    })())

                keyboard = get_toggle_parsing_keyboard(links_data, "resume")
                await callback.message.edit_text(
                    f"▶️ <b>Парсинг возобновлен для '{link_name}'!</b>\n\n"
                    f"Выберите следующую ссылку для возобновления:",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                navigation_keyboard = get_cancel_keyboard_with_navigation()
                await callback.message.edit_text(
                    f"▶️ <b>Парсинг возобновлен для '{link_name}'!</b>\n\n"
                    f"Все ссылки активны.",
                    parse_mode="HTML",
                    reply_markup=navigation_keyboard
                )

        await callback.answer("▶️ Парсинг возобновлен")

    except Exception as e:
        logger.error(f"❌ Ошибка при возобновлении ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при возобновлении ссылки")
        await callback.answer()

@router.callback_query(F.data == "manage_force_check")
async def manage_force_check(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                await callback.answer()
                return

            link_data = {
                'id': link.id,
                'name': link.name
            }

        await callback.message.edit_text(f"🔧 Запускаю принудительную проверку для <b>{link_data['name']}</b>...", parse_mode="HTML")
        await callback.answer()

        bot_instance = bot_manager.get_instance()
        if bot_instance:
            await bot_instance.force_check_specific_link(callback.from_user.id, link_data['id'])
        else:
            await callback.message.edit_text("❌ Бот не инициализирован")

    except Exception as e:
        logger.error(f"❌ Ошибка при принудительной проверке: {e}")
        await callback.message.edit_text("❌ Ошибка при принудительной проверке")
        await callback.answer()

@router.callback_query(F.data.startswith("force_check_link_"))
async def process_force_check_link(callback: CallbackQuery):
    # Отвечаем на callback сразу, чтобы избежать timeout
    try:
        await callback.answer()
    except:
        pass  # Игнорируем ошибки callback.answer()

    try:
        link_id = int(callback.data.split("_")[3])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            link_data = {
                'id': link.id,
                'name': link.name
            }

        await callback.message.edit_text(f"🔧 Запускаю принудительную проверку для <b>{link_data['name']}</b>...", parse_mode="HTML")

        bot_instance = bot_manager.get_instance()
        if bot_instance:
            await bot_instance.force_check_specific_link(callback.from_user.id, link_data['id'])
        else:
            await callback.message.edit_text("❌ Бот не инициализирован")

    except Exception as e:
        logger.error(f"❌ Ошибка при принудительной проверке ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при принудительной проверке ссылки")

# =============================================================================
# НАСТРОЙКА ПАРСИНГА
# =============================================================================

@router.callback_query(F.data == "manage_configure_parsing")
async def manage_configure_parsing(callback: CallbackQuery):
    """Показывает настройки парсинга для уже выбранной ссылки"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        # Используем существующую функцию для показа конфигурации
        # Создаем mock callback с правильными данными
        from unittest.mock import Mock
        config_callback = Mock()
        config_callback.data = f"configure_parsing_link_{link_id}"
        config_callback.message = callback.message
        config_callback.answer = callback.answer
        config_callback.from_user = callback.from_user
        
        await show_parsing_configuration(config_callback)

    except Exception as e:
        logger.error(f"❌ Ошибка при настройке парсинга: {e}")
        await callback.message.edit_text("❌ Ошибка при настройке парсинга")
        await callback.answer()

@router.callback_query(F.data.startswith("configure_parsing_link_"))
async def show_parsing_configuration(callback: CallbackQuery):
    """Показывает текущую конфигурацию парсинга и меню редактирования"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            # Детач данных
            link_data = {
                'id': link.id,
                'name': link.name,
                'category': link.category,
                'parsing_type': link.parsing_type or 'combined',
                'api_url': link.api_url,
                'html_url': link.html_url,
                'telegram_channel': link.telegram_channel,
                'telegram_keywords': link.get_telegram_keywords(),
                'announcement_strategy': link.announcement_strategy,
                'announcement_keywords': link.get_announcement_keywords(),
                'announcement_regex': link.announcement_regex,
                'announcement_css_selector': link.announcement_css_selector
            }

        # Словарь для отображения типа парсинга с описанием
        parsing_type_info = {
            'combined': {
                'name': '🔄 Комбинированный (API + HTML + Browser)',
                'description': 'Пробует все методы по очереди для максимальной надёжности'
            },
            'api': {
                'name': '📡 Только API',
                'description': 'Быстрый метод через API запросы, может быть заблокирован'
            },
            'html': {
                'name': '🌐 Только HTML',
                'description': 'Парсинг HTML страниц, стабильный для статического контента'
            },
            'browser': {
                'name': '🌐 Только Browser',
                'description': 'Браузерная автоматизация, обходит капчи и защиты'
            },
            'telegram': {
                'name': '📱 Telegram',
                'description': 'Мониторинг Telegram канала по ключевым словам'
            }
        }

        current_type = link_data['parsing_type']
        type_info = parsing_type_info.get(current_type, parsing_type_info['combined'])

        # Словарь для отображения категории
        category_names = {
            'launches': '🚀 Лаучи',
            'launchpad': '🚀 Лаунчпады',
            'launchpool': '🌊 Лаунчпулы',
            'airdrop': '🪂 Аирдроп',
            'staking': '💰 Стейкинг',
            'announcement': '📢 Анонс'
        }
        current_category = link_data['category'] or 'launches'
        category_display = category_names.get(current_category, '🚀 Лаучи')

        message_parts = [
            f"🎯 <b>Настройка парсинга для:</b> {link_data['name']}\n\n",
            f"<b>Текущая категория:</b> {category_display}\n\n",
            f"<b>Текущий тип парсинга:</b>\n{type_info['name']}\n",
            f"<i>{type_info['description']}</i>\n\n",
        ]

        # Отображение параметров в зависимости от типа парсинга
        if current_type == 'telegram':
            # Для Telegram показываем канал и ключевые слова
            if link_data['telegram_channel']:
                message_parts.append(f"<b>📱 Telegram канал:</b>\n<code>{link_data['telegram_channel']}</code>\n\n")
            else:
                message_parts.append(f"<b>📱 Telegram канал:</b> <i>Не указан</i>\n\n")

            if link_data['telegram_keywords']:
                keywords_str = ", ".join([f"<code>{kw}</code>" for kw in link_data['telegram_keywords']])
                message_parts.append(f"<b>🔑 Ключевые слова:</b>\n{keywords_str}\n\n")
            else:
                message_parts.append(f"<b>🔑 Ключевые слова:</b> <i>Не указаны</i>\n\n")
        elif link_data['category'] == 'announcement':
            # Для анонсов показываем специальные параметры
            if link_data['html_url']:
                message_parts.append(f"<b>🌐 HTML URL:</b>\n<code>{link_data['html_url']}</code>\n\n")
            else:
                message_parts.append(f"<b>🌐 HTML URL:</b> <i>Не указан</i>\n\n")
            
            # Стратегия парсинга
            strategy_names = {
                'any_change': '🔄 Любые изменения',
                'element_change': '🎯 Изменения в элементе',
                'any_keyword': '🔑 Любое ключевое слово',
                'all_keywords': '📚 Все ключевые слова',
                'regex': '⚡ Регулярное выражение'
            }
            strategy_name = strategy_names.get(link_data['announcement_strategy'], 'Не указана')
            message_parts.append(f"<b>📋 Стратегия парсинга:</b> {strategy_name}\n\n")
            
            # Ключевые слова (если есть)
            if link_data['announcement_keywords'] and link_data['announcement_strategy'] in ['any_keyword', 'all_keywords']:
                keywords_str = ", ".join([f"<code>{kw}</code>" for kw in link_data['announcement_keywords']])
                message_parts.append(f"<b>🔑 Ключевые слова:</b>\n{keywords_str}\n\n")
            
            # CSS селектор (если есть)
            if link_data['announcement_css_selector'] and link_data['announcement_strategy'] == 'element_change':
                message_parts.append(f"<b>🎯 CSS селектор:</b>\n<code>{link_data['announcement_css_selector']}</code>\n\n")
            
            # Регулярное выражение (если есть)
            if link_data['announcement_regex'] and link_data['announcement_strategy'] == 'regex':
                message_parts.append(f"<b>⚡ Регулярное выражение:</b>\n<code>{link_data['announcement_regex']}</code>\n\n")
        else:
            # Для остальных типов показываем API и HTML URL
            if link_data['api_url']:
                message_parts.append(f"<b>👾 API URL:</b>\n<code>{link_data['api_url']}</code>\n\n")
            else:
                message_parts.append(f"<b>👾 API URL:</b> <i>Не указан</i>\n\n")

            if link_data['html_url']:
                message_parts.append(f"<b>🌐 HTML URL:</b>\n<code>{link_data['html_url']}</code>\n\n")
            else:
                message_parts.append(f"<b>🌐 HTML URL:</b> <i>Не указан</i>\n\n")

        message_parts.append("Выберите параметр для изменения:")

        keyboard = get_configure_parsing_submenu(link_id, current_type, link_data['category'])
        await callback.message.edit_text(
            "".join(message_parts),
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при отображении конфигурации: {e}")
        await callback.message.edit_text("❌ Ошибка при отображении конфигурации")
        await callback.answer()

@router.callback_query(F.data.startswith("show_parsing_config_"))
async def show_parsing_config_callback(callback: CallbackQuery):
    """Возврат к настройкам конкретной ссылки"""
    link_id = int(callback.data.split("_")[-1])
    # Создаем новый callback с правильным data для повторного использования
    # Используем Mock объект для имитации callback с нужным data
    from unittest.mock import Mock
    new_callback = Mock()
    new_callback.data = f"configure_parsing_link_{link_id}"
    new_callback.message = callback.message
    new_callback.answer = callback.answer
    await show_parsing_configuration(new_callback)

@router.callback_query(F.data.startswith("edit_parsing_type_"))
async def edit_parsing_type(callback: CallbackQuery):
    """Показывает меню выбора типа парсинга"""
    try:
        link_id = int(callback.data.split("_")[-1])

        keyboard = get_parsing_type_keyboard(link_id)
        await callback.message.edit_text(
            "🎯 <b>Выберите тип парсинга:</b>\n\n"
            "• <b>Комбинированный</b> - пробует все методы по очереди\n"
            "• <b>Только API</b> - использует только API запросы\n"
            "• <b>Только HTML</b> - парсит HTML страницу\n"
            "• <b>Только Browser</b> - использует браузерную автоматизацию",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании типа парсинга: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании типа парсинга")
        await callback.answer()

@router.callback_query(F.data.startswith("edit_category_"))
async def edit_category(callback: CallbackQuery):
    """Показывает меню выбора категории для ссылки"""
    try:
        link_id = int(callback.data.split("_")[-1])
        
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
            
            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return
            
            link_name = link.name
            current_category = link.category or 'launches'
            is_favorite = link.is_favorite
        
        category_names = {
            'launches': '🚀 Лаучи',
            'launchpad': '🚀 Лаунчпады',
            'launchpool': '🌊 Лаунчпулы',
            'drops': '🎁 Дропы',
            'airdrop': '🪂 Аирдропы',
            'candybomb': '🍬 CandyBomb',
            'staking': '💰 Стейкинг',
            'announcement': '📢 Анонс'
        }
        current_category_display = category_names.get(current_category, '🚀 Лаучи')
        favorite_status = "⭐ В избранном" if is_favorite else ""
        
        keyboard = get_category_edit_keyboard(link_id)
        await callback.message.edit_text(
            f"🗂️ <b>Изменение категории</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущая категория:</b> {current_category_display}\n"
            f"{favorite_status}\n\n"
            f"Выберите новую категорию:\n"
            f"<i>⭐ Избранные - добавит в избранное, сохранив текущую категорию</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании категории: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании категории")
        await callback.answer()

@router.callback_query(F.data.startswith("set_category_"))
async def set_category(callback: CallbackQuery):
    """Сохраняет выбранную категорию или добавляет/убирает из избранного"""
    try:
        parts = callback.data.split("_")
        link_id = int(parts[2])
        new_category = parts[3]
        
        def update_category(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            
            old_category = link.category or 'launches'
            old_is_favorite = link.is_favorite
            
            # Если выбрали "favorite" - только меняем флаг, категория остаётся прежней
            if new_category == 'favorite':
                link.is_favorite = True
                return link.name, old_category, old_category, old_is_favorite, True
            else:
                # Иначе меняем категорию и убираем из избранного
                link.category = new_category
                link.is_favorite = False
                return link.name, old_category, new_category, old_is_favorite, False
        
        link_name, old_category, result_category, old_is_favorite, is_now_favorite = atomic_operation(update_category)
        
        category_names = {
            'launches': '🚀 Лаучи',
            'launchpad': '🚀 Лаунчпады',
            'launchpool': '🌊 Лаунчпулы',
            'airdrop': '🪂 Аирдроп',
            'candybomb': '🍬 CandyBomb',
            'staking': '💰 Стейкинг',
            'announcement': '📢 Анонс'
        }
        old_category_display = category_names.get(old_category, '🚀 Лаучи')
        new_category_display = category_names.get(result_category, '🚀 Лаучи')
        
        # Клавиатура возврата к ссылке
        keyboard = get_back_to_link_keyboard(link_id)
        
        if is_now_favorite:
            # Добавили в избранное
            favorite_text = "⭐ <b>Добавлено в избранное!</b>\n\n" if not old_is_favorite else ""
            await callback.message.edit_text(
                f"✅ {favorite_text}"
                f"<b>Ссылка:</b> {link_name}\n"
                f"<b>Категория:</b> {new_category_display}\n"
                f"<b>Статус:</b> ⭐ В избранном",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer("⭐ Добавлено в избранное")
        else:
            await callback.message.edit_text(
                f"✅ <b>Категория успешно изменена!</b>\n\n"
                f"<b>Ссылка:</b> {link_name}\n"
                f"<b>Было:</b> {old_category_display}\n"
                f"<b>Стало:</b> {new_category_display}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer("✅ Категория обновлена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении категории: {e}")
        await callback.message.edit_text("❌ Ошибка при сохранении категории")
        await callback.answer()

@router.callback_query(F.data.startswith("set_parsing_type_"))
async def set_parsing_type(callback: CallbackQuery, state: FSMContext):
    """Сохраняет выбранный тип парсинга"""
    try:
        parts = callback.data.split("_")
        link_id = int(parts[3])
        parsing_type = parts[4]

        def update_parsing_type(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.parsing_type = parsing_type
            return link.name, link.telegram_channel

        link_name, current_telegram_channel = atomic_operation(update_parsing_type)

        # Если выбран тип Telegram - запускаем процесс настройки канала и ключевых слов
        if parsing_type == 'telegram':
            await state.update_data(link_id=link_id, link_name=link_name)
            await state.set_state(ConfigureParsingStates.waiting_for_telegram_channel_edit)

            current_channel_text = f"\n\n<b>Текущий канал:</b> {current_telegram_channel}" if current_telegram_channel else ""

            await callback.message.edit_text(
                f"📱 <b>Настройка Telegram парсинга</b>\n\n"
                f"<b>Ссылка:</b> {link_name}\n"
                f"<b>Тип парсинга:</b> Telegram{current_channel_text}\n\n"
                f"📝 <b>Введите ссылку на Telegram канал:</b>\n\n"
                f"<i>Форматы:</i>\n"
                f"• @channelname\n"
                f"• https://t.me/channelname\n"
                f"• t.me/channelname",
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Для остальных типов - стандартное поведение
        parsing_type_display = {
            'combined': '🔄 Комбинированный',
            'api': '📡 Только API',
            'html': '🌐 Только HTML',
            'browser': '🌐 Только Browser'
        }.get(parsing_type, parsing_type)

        # Клавиатура возврата к настройкам
        keyboard = get_back_to_settings_keyboard(link_id)
        
        await callback.message.edit_text(
            f"✅ <b>Тип парсинга успешно изменён!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый тип:</b> {parsing_type_display}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await callback.answer("✅ Тип парсинга обновлён")

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении типа парсинга: {e}")
        await callback.message.edit_text("❌ Ошибка при сохранении типа парсинга")
        await callback.answer()

@router.callback_query(F.data.startswith("edit_api_url_"))
async def edit_api_url(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения API URL"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_api_url = link.api_url or "Не указан"
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_api_url_edit)

        await callback.message.edit_text(
            f"📡 <b>Изменение API URL</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущий API URL:</b>\n<code>{current_api_url}</code>\n\n"
            f"Отправьте новый API URL или отправьте \"-\" чтобы удалить:\n\n"
            f"<i>Или используйте /cancel для отмены</i>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании API URL: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании API URL")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_api_url_edit)
async def process_api_url_edit(message: Message, state: FSMContext):
    """Обрабатывает новый API URL"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']
        new_api_url = message.text.strip()

        # Если пользователь отправил "-", удаляем URL
        if new_api_url == "-":
            new_api_url = None

        def update_api_url(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.api_url = new_api_url
            return link.name

        atomic_operation(update_api_url)

        display_url = new_api_url if new_api_url else "<i>Удалён</i>"

        await message.answer(
            f"✅ <b>API URL успешно обновлён!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый API URL:</b>\n{display_url}",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении API URL: {e}")
        await message.answer("❌ Ошибка при сохранении API URL")
        await state.clear()

@router.callback_query(F.data.startswith("edit_html_url_"))
async def edit_html_url(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения HTML URL"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_html_url = link.html_url or "Не указан"
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_html_url_edit)

        await callback.message.edit_text(
            f"🌐 <b>Изменение HTML URL</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущий HTML URL:</b>\n<code>{current_html_url}</code>\n\n"
            f"Отправьте новый HTML URL или отправьте \"-\" чтобы удалить:\n\n"
            f"<i>Или используйте /cancel для отмены</i>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании HTML URL: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании HTML URL")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_html_url_edit)
async def process_html_url_edit(message: Message, state: FSMContext):
    """Обрабатывает новый HTML URL"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']
        new_html_url = message.text.strip()

        # Если пользователь отправил "-", удаляем URL
        if new_html_url == "-":
            new_html_url = None

        def update_html_url(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.html_url = new_html_url
            return link.name

        atomic_operation(update_html_url)

        display_url = new_html_url if new_html_url else "<i>Удалён</i>"

        await message.answer(
            f"✅ <b>HTML URL успешно обновлён!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый HTML URL:</b>\n{display_url}",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении HTML URL: {e}")
        await message.answer("❌ Ошибка при сохранении HTML URL")
        await state.clear()

@router.callback_query(F.data.startswith("edit_telegram_channel_"))
async def edit_telegram_channel(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения Telegram канала"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_channel = link.telegram_channel or "Не указан"
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name, direct_edit=True)
        await state.set_state(ConfigureParsingStates.waiting_for_telegram_channel_edit)

        await callback.message.edit_text(
            f"📱 <b>Изменение Telegram канала</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущий канал:</b> {current_channel}\n\n"
            f"📝 Введите новую ссылку на Telegram канал:\n\n"
            f"<i>Форматы:</i>\n"
            f"• @channelname\n"
            f"• https://t.me/channelname\n"
            f"• t.me/channelname",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании Telegram канала: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании Telegram канала")
        await callback.answer()

@router.callback_query(F.data.startswith("edit_telegram_keywords_"))
async def edit_telegram_keywords(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения Telegram ключевых слов"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_keywords = link.get_telegram_keywords()
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_telegram_keywords_edit)

        keywords_text = ", ".join([f"<code>{kw}</code>" for kw in current_keywords]) if current_keywords else "<i>Не указаны</i>"

        await callback.message.edit_text(
            f"🔑 <b>Изменение ключевых слов</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущие ключевые слова:</b> {keywords_text}\n\n"
            f"📝 Введите новые ключевые слова через запятую:\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>airdrop, промо, campaign, giveaway</code>\n"
            f"<code>listing, IEO, launchpad</code>\n"
            f"<code>staking, earn, APR</code>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании ключевых слов: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании ключевых слов")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_telegram_channel_edit)
async def process_telegram_channel_edit(message: Message, state: FSMContext):
    """Обрабатывает изменение Telegram канала"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']

        channel_input = message.text.strip()

        # Нормализуем ввод канала
        channel_username = channel_input

        # Убираем префикс https://
        if channel_username.startswith('https://t.me/'):
            channel_username = channel_username.replace('https://t.me/', '')
        elif channel_username.startswith('http://t.me/'):
            channel_username = channel_username.replace('http://t.me/', '')
        elif channel_username.startswith('t.me/'):
            channel_username = channel_username.replace('t.me/', '')

        # Добавляем @ если его нет
        if not channel_username.startswith('@'):
            channel_username = '@' + channel_username

        # Сохраняем канал в базу данных
        def update_telegram_channel(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.telegram_channel = channel_username
            return link.get_telegram_keywords()

        current_keywords = atomic_operation(update_telegram_channel)

        # Проверяем, это прямое редактирование или часть процесса изменения типа
        direct_edit = data.get('direct_edit', False)

        if direct_edit:
            # Прямое редактирование - завершаем
            await message.answer(
                f"✅ <b>Telegram канал успешно обновлён!</b>\n\n"
                f"<b>Ссылка:</b> {link_name}\n"
                f"<b>Новый канал:</b> {channel_username}",
                parse_mode="HTML"
            )
            await state.clear()
        else:
            # Часть процесса изменения типа - переходим к ключевым словам
            await state.set_state(ConfigureParsingStates.waiting_for_telegram_keywords_edit)

            current_keywords_text = ""
            if current_keywords:
                keywords_list = ", ".join([f"<code>{kw}</code>" for kw in current_keywords])
                current_keywords_text = f"\n\n<b>Текущие ключевые слова:</b> {keywords_list}"

            await message.answer(
                f"✅ <b>Канал сохранён:</b> {channel_username}\n\n"
                f"🔑 <b>Введите ключевые слова для поиска:</b>{current_keywords_text}\n\n"
                f"Введите слова или фразы через запятую, по которым бот будет искать сообщения в канале.\n\n"
                f"<b>Примеры:</b>\n"
                f"<code>airdrop, промо, campaign, giveaway</code>\n"
                f"<code>listing, IEO, launchpad</code>\n"
                f"<code>staking, earn, APR</code>\n\n"
                f"Бот будет отправлять уведомления о сообщениях, содержащих эти слова.",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении Telegram канала: {e}")
        await message.answer("❌ Ошибка при сохранении Telegram канала")
        await state.clear()

@router.message(ConfigureParsingStates.waiting_for_telegram_keywords_edit)
async def process_telegram_keywords_edit(message: Message, state: FSMContext):
    """Обрабатывает изменение Telegram ключевых слов"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']

        keywords_input = message.text.strip()

        if not keywords_input:
            await message.answer("❌ Ключевые слова не могут быть пустыми. Попробуйте снова:")
            return

        # Разбиваем по запятой и очищаем
        keywords = [kw.strip() for kw in keywords_input.split(',') if kw.strip()]

        if not keywords:
            await message.answer("❌ Не удалось распознать ключевые слова. Введите их через запятую:")
            return

        # Сохраняем ключевые слова в базу данных
        def update_telegram_keywords(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.set_telegram_keywords(keywords)

        atomic_operation(update_telegram_keywords)

        keywords_str = ", ".join([f"<code>{kw}</code>" for kw in keywords])

        await message.answer(
            f"✅ <b>Настройка Telegram парсинга завершена!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Тип парсинга:</b> Telegram\n"
            f"<b>Ключевые слова:</b> {keywords_str}",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении ключевых слов: {e}")
        await message.answer("❌ Ошибка при сохранении ключевых слов")
        await state.clear()

# ========================================
# ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ АНОНСОВ
# ========================================

@router.callback_query(F.data.startswith("edit_announcement_strategy_"))
async def edit_announcement_strategy(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения стратегии парсинга анонсов"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_strategy = link.announcement_strategy
            link_name = link.name

        strategy_names = {
            'any_change': '🔄 Любые изменения',
            'element_change': '🎯 Изменения в элементе',
            'any_keyword': '🔑 Любое ключевое слово',
            'all_keywords': '📚 Все ключевые слова',
            'regex': '⚡ Регулярное выражение'
        }
        current_strategy_name = strategy_names.get(current_strategy, 'Не указана')

        # Создаем клавиатуру с выбором стратегии
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔄 Любые изменения", callback_data=f"set_ann_strategy_{link_id}_any_change"))
        builder.add(InlineKeyboardButton(text="🎯 Изменения в элементе", callback_data=f"set_ann_strategy_{link_id}_element_change"))
        builder.add(InlineKeyboardButton(text="🔑 Любое ключевое слово", callback_data=f"set_ann_strategy_{link_id}_any_keyword"))
        builder.add(InlineKeyboardButton(text="📚 Все ключевые слова", callback_data=f"set_ann_strategy_{link_id}_all_keywords"))
        builder.add(InlineKeyboardButton(text="⚡ Регулярное выражение", callback_data=f"set_ann_strategy_{link_id}_regex"))
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"configure_parsing_link_{link_id}"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
        builder.adjust(1)

        await callback.message.edit_text(
            f"📋 <b>Изменение стратегии парсинга анонсов</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущая стратегия:</b> {current_strategy_name}\n\n"
            f"<b>Стратегии:</b>\n\n"
            f"🔄 <b>Любые изменения</b> - отслеживание любых изменений на странице\n"
            f"🎯 <b>Изменения в элементе</b> - отслеживание конкретного элемента (CSS Selector)\n"
            f"🔑 <b>Любое ключевое слово</b> - поиск любого из заданных слов\n"
            f"📚 <b>Все ключевые слова</b> - все слова должны присутствовать\n"
            f"⚡ <b>Регулярное выражение</b> - поиск по regex паттерну\n\n"
            f"Выберите подходящую стратегию:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании стратегии анонсов: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании стратегии")
        await callback.answer()

@router.callback_query(F.data.startswith("set_ann_strategy_"))
async def set_announcement_strategy(callback: CallbackQuery):
    """Сохраняет выбранную стратегию анонсов"""
    try:
        parts = callback.data.split("_")
        link_id = int(parts[3])
        strategy = "_".join(parts[4:])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            link.announcement_strategy = strategy
            db.commit()
            link_name = link.name

        strategy_names = {
            'any_change': '🔄 Любые изменения',
            'element_change': '🎯 Изменения в элементе',
            'any_keyword': '🔑 Любое ключевое слово',
            'all_keywords': '📚 Все ключевые слова',
            'regex': '⚡ Регулярное выражение'
        }
        strategy_name = strategy_names.get(strategy, strategy)

        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ К настройкам ссылки", callback_data=f"configure_parsing_link_{link_id}"))
        builder.add(InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action"))
        builder.adjust(1)

        await callback.message.edit_text(
            f"✅ <b>Стратегия успешно изменена!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новая стратегия:</b> {strategy_name}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении стратегии: {e}")
        await callback.message.edit_text("❌ Ошибка при сохранении стратегии")
        await callback.answer()

@router.callback_query(F.data.startswith("edit_announcement_keywords_"))
async def edit_announcement_keywords(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения ключевых слов анонсов"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_keywords = link.get_announcement_keywords()
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_announcement_keywords_edit)

        keywords_text = ", ".join([f"<code>{kw}</code>" for kw in current_keywords]) if current_keywords else "<i>Не указаны</i>"

        await callback.message.edit_text(
            f"🔑 <b>Изменение ключевых слов анонсов</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущие ключевые слова:</b> {keywords_text}\n\n"
            f"📝 Введите новые ключевые слова через запятую:\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>airdrop, промо, campaign, listing</code>\n"
            f"<code>новый токен, листинг, бонус</code>\n"
            f"<code>staking, earn, 0% fee</code>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании ключевых слов: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании ключевых слов")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_announcement_keywords_edit)
async def process_announcement_keywords_edit(message: Message, state: FSMContext):
    """Обрабатывает изменение ключевых слов анонсов"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']

        keywords_input = message.text.strip()

        if not keywords_input:
            await message.answer("❌ Ключевые слова не могут быть пустыми. Попробуйте снова:")
            return

        # Разбиваем по запятой и очищаем
        keywords = [kw.strip() for kw in keywords_input.split(',') if kw.strip()]

        if not keywords:
            await message.answer("❌ Не удалось распознать ключевые слова. Введите их через запятую:")
            return

        # Сохраняем ключевые слова в базу данных
        def update_announcement_keywords(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.set_announcement_keywords(keywords)

        atomic_operation(update_announcement_keywords)

        keywords_str = ", ".join([f"<code>{kw}</code>" for kw in keywords])

        await message.answer(
            f"✅ <b>Ключевые слова успешно обновлены!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Ключевые слова:</b> {keywords_str}",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении ключевых слов: {e}")
        await message.answer("❌ Ошибка при сохранении ключевых слов")
        await state.clear()

@router.callback_query(F.data.startswith("edit_announcement_css_"))
async def edit_announcement_css(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения CSS селектора анонсов"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_css = link.announcement_css_selector
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_announcement_css_edit)

        css_text = f"<code>{current_css}</code>" if current_css else "<i>Не указан</i>"

        await callback.message.edit_text(
            f"🎯 <b>Изменение CSS селектора</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущий селектор:</b> {css_text}\n\n"
            f"📝 Введите новый CSS селектор:\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>div.announcement-item</code>\n"
            f"<code>#latest-news</code>\n"
            f"<code>.news-container > article</code>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании CSS селектора: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании CSS селектора")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_announcement_css_edit)
async def process_announcement_css_edit(message: Message, state: FSMContext):
    """Обрабатывает изменение CSS селектора анонсов"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']

        css_selector = message.text.strip()

        if not css_selector:
            await message.answer("❌ CSS селектор не может быть пустым. Попробуйте снова:")
            return

        # Сохраняем CSS селектор в базу данных
        def update_announcement_css(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.announcement_css_selector = css_selector

        atomic_operation(update_announcement_css)

        await message.answer(
            f"✅ <b>CSS селектор успешно обновлён!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>CSS селектор:</b> <code>{css_selector}</code>",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении CSS селектора: {e}")
        await message.answer("❌ Ошибка при сохранении CSS селектора")
        await state.clear()

@router.callback_query(F.data.startswith("edit_announcement_regex_"))
async def edit_announcement_regex(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения регулярного выражения анонсов"""
    try:
        link_id = int(callback.data.split("_")[-1])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

            current_regex = link.announcement_regex
            link_name = link.name

        await state.update_data(link_id=link_id, link_name=link_name)
        await state.set_state(ConfigureParsingStates.waiting_for_announcement_regex_edit)

        regex_text = f"<code>{current_regex}</code>" if current_regex else "<i>Не указано</i>"

        await callback.message.edit_text(
            f"⚡ <b>Изменение регулярного выражения</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущее выражение:</b> {regex_text}\n\n"
            f"📝 Введите новое регулярное выражение:\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>airdrop.*listing</code>\n"
            f"<code>\\d+% (APR|APY)</code>\n"
            f"<code>new.*token.*launch</code>",
            parse_mode="HTML"
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при редактировании regex: {e}")
        await callback.message.edit_text("❌ Ошибка при редактировании regex")
        await callback.answer()

@router.message(ConfigureParsingStates.waiting_for_announcement_regex_edit)
async def process_announcement_regex_edit(message: Message, state: FSMContext):
    """Обрабатывает изменение регулярного выражения анонсов"""
    try:
        data = await state.get_data()
        link_id = data['link_id']
        link_name = data['link_name']

        regex_pattern = message.text.strip()

        if not regex_pattern:
            await message.answer("❌ Регулярное выражение не может быть пустым. Попробуйте снова:")
            return

        # Проверяем валидность regex
        try:
            import re
            re.compile(regex_pattern)
        except re.error as e:
            await message.answer(f"❌ Некорректное регулярное выражение: {e}\n\nПопробуйте снова:")
            return

        # Сохраняем regex в базу данных
        def update_announcement_regex(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")

            link.announcement_regex = regex_pattern

        atomic_operation(update_announcement_regex)

        await message.answer(
            f"✅ <b>Регулярное выражение успешно обновлено!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Regex:</b> <code>{regex_pattern}</code>",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении regex: {e}")
        await message.answer("❌ Ошибка при сохранении regex")
        await state.clear()

@router.message(F.text == "🔄 Проверить всё")
async def menu_check_all(message: Message):
    await message.answer("🔄 Начинаю проверку АКТИВНЫХ ссылок...")

    bot_instance = bot_manager.get_instance()
    if bot_instance:
        await bot_instance.manual_check_all_links(message.chat.id)
    else:
        await message.answer("❌ Бот не инициализирован")


@router.message(F.text == "🏠 Меню")
async def menu_show_main(message: Message):
    """Показать главное меню с inline-кнопками"""
    clear_navigation(message.from_user.id)

    await message.answer(
        "🏠 <b>Меню</b>\n\n"
        "📌 <i>Выберите действие:</i>",
        reply_markup=get_main_menu_inline(),
        parse_mode="HTML"
    )

@router.message(F.text == "🛡️ Обход блокировок")
async def menu_bypass(message: Message):
    """Показать подменю обхода блокировок"""
    keyboard = get_bypass_keyboard()
    await message.answer(
        "🛡️ <b>Обход блокировок</b>\n\n"
        "Выберите нужную функцию:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "bypass_proxy")
async def bypass_proxy_handler(callback: CallbackQuery):
    """Открыть управление прокси из подменю обхода блокировок"""
    keyboard = get_proxy_management_keyboard()
    await callback.message.edit_text(
        "🔧 <b>Управление прокси-серверами</b>\n\n"
        "Выберите действие для управления прокси:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "bypass_ua")
async def bypass_ua_handler(callback: CallbackQuery):
    """Открыть управление User-Agent из подменю обхода блокировок"""
    keyboard = get_user_agent_management_keyboard()
    await callback.message.edit_text(
        "👤 <b>Управление User-Agent</b>\n\n"
        "Выберите действие для управления User-Agent:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "bypass_rotation")
async def bypass_rotation_handler(callback: CallbackQuery):
    """Открыть настройки ротации из подменю обхода блокировок"""
    keyboard = get_rotation_settings_keyboard()
    await callback.message.edit_text(
        "⚙️ <b>Настройки ротации</b>\n\n"
        "Управление параметрами ротации прокси и User-Agent:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# СТАРЫЙ ОБРАБОТЧИК bypass_telegram УДАЛЕН - используется новый из telegram_account_handlers.py

@router.callback_query(F.data == "back_to_bypass")
async def back_to_bypass_menu(callback: CallbackQuery):
    """Возврат к меню обхода блокировок"""
    keyboard = get_bypass_keyboard()
    await callback.message.edit_text(
        "🛡️ <b>Обход блокировок</b>\n\n"
        "Выберите нужную функцию:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# СТАРЫЕ ОБРАБОТЧИКИ telegram_api_* УДАЛЕНЫ - используется новая система из telegram_account_handlers.py

@router.callback_query(F.data == "bypass_stats")
async def bypass_stats_handler(callback: CallbackQuery):
    """Открыть статистику системы из подменю обхода блокировок"""
    keyboard = get_statistics_keyboard()
    await callback.message.edit_text(
        "📈 <b>Статистика системы</b>\n\n"
        "Выберите раздел статистики:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.text == "📋 История промоакций")
async def menu_history(message: Message):
    await message.answer("📋 История промоакций будет доступна после нахождения первых промоакций")

@router.message(F.text.startswith("http"))
async def handle_direct_url_input(message: Message):
    await message.answer(
        "🔗 Для добавления ссылки используйте кнопку <b>\"➕ Добавить ссылку\"</b> в меню.\n\n"
        "Это позволит задать кастомное имя для ссылки.",
        parse_mode="HTML"
    )

# НОВЫЕ ОБРАБОТЧИКИ ДЛЯ РАСШИРЕННЫХ СИСТЕМ

# =============================================================================
# УПРАВЛЕНИЕ ПРОКСИ
# =============================================================================

@router.message(F.text == "🔧 Управление прокси")
async def menu_proxy_management(message: Message):
    keyboard = get_proxy_management_keyboard()
    await message.answer(
        "🔧 <b>Управление прокси-серверами</b>\n\n"
        "Выберите действие для управления прокси:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "proxy_list")
async def proxy_list(callback: CallbackQuery):
    try:
        logger.info("📋 Получение списка прокси-серверов")
        proxy_manager = get_proxy_manager()
        proxies = proxy_manager.get_all_proxies(active_only=False)

        if not proxies:
            logger.warning("⚠️ Нет добавленных прокси-серверов")
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
            await callback.message.edit_text("❌ Нет добавленных прокси-серверов", reply_markup=builder.as_markup())
            return

        # Детачим данные из объектов SQLAlchemy в словари
        proxy_data_list = []
        for proxy in proxies:
            total_requests = proxy.success_count + proxy.fail_count
            success_rate = (proxy.success_count / total_requests * 100) if total_requests > 0 else 0

            proxy_data_list.append({
                'address': proxy.address,
                'protocol': proxy.protocol,
                'status': proxy.status,
                'speed_ms': proxy.speed_ms,
                'success_rate': success_rate,
                'priority': proxy.priority
            })

        response = "📋 <b>Список прокси-серверов:</b>\n\n"
        for proxy_data in proxy_data_list:
            status_icon = "🟢" if proxy_data['status'] == "active" else "🔴"
            speed_info = f"{proxy_data['speed_ms']:.0f}мс" if proxy_data['speed_ms'] > 0 else "не тестирован"

            response += f"{status_icon} <b>{proxy_data['address']}</b>\n"
            response += f"   Протокол: {proxy_data['protocol']}\n"
            response += f"   Статус: {proxy_data['status']}\n"
            response += f"   Скорость: {speed_info}\n"
            response += f"   Успешность: {proxy_data['success_rate']:.1f}%\n"
            response += f"   Приоритет: {proxy_data['priority']}\n\n"

        logger.info(f"✅ Отображено {len(proxy_data_list)} прокси-серверов")
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"❌ Ошибка при получении списка прокси: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при получении списка прокси")

@router.callback_query(F.data == "proxy_add")
async def proxy_add_start(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
    builder.adjust(2)
    await callback.message.edit_text(
        "➕ <b>Добавление нового прокси</b>\n\n"
        "Введите адрес прокси в формате:\n"
        "<code>ip:port</code> или <code>user:pass@ip:port</code>\n\n"
        "Примеры:\n"
        "• <code>192.168.1.1:8080</code>\n"
        "• <code>user:password@proxy.example.com:3128</code>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(ProxyManagementStates.waiting_for_proxy_address)
    await callback.answer()

@router.message(ProxyManagementStates.waiting_for_proxy_address)
async def process_proxy_address(message: Message, state: FSMContext):
    proxy_address = message.text.strip()
    
    if ':' not in proxy_address:
        await message.answer("❌ Неверный формат адреса. Должен быть ip:port\nПопробуйте снова:")
        return
    
    await state.update_data(proxy_address=proxy_address)
    
    builder = InlineKeyboardBuilder()
    protocols = ["http", "https", "socks4", "socks5"]
    for protocol in protocols:
        builder.add(InlineKeyboardButton(text=protocol.upper(), callback_data=f"proxy_protocol_{protocol}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="proxy_add"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
    builder.adjust(2)
    await message.answer(
        f"🔌 <b>Выберите протокол для прокси:</b>\n\n"
        f"Адрес: <code>{proxy_address}</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("proxy_protocol_"))
async def process_proxy_protocol(callback: CallbackQuery, state: FSMContext):
    try:
        protocol = callback.data.split("_")[2]
        data = await state.get_data()
        proxy_address = data.get('proxy_address')
        
        proxy_manager = get_proxy_manager()
        
        success = proxy_manager.add_proxy(proxy_address, protocol)
        
        if success:
            await callback.message.edit_text("🧪 Тестируем новый прокси...")
            proxy = proxy_manager.get_proxy_by_address(proxy_address)
            if proxy:
                test_result = proxy_manager.test_proxy(proxy.id)
                
                if test_result:
                    status_msg = "✅ Прокси успешно добавлен и протестирован!"
                else:
                    status_msg = "⚠️ Прокси добавлен, но не прошел тестирование"
                    
                await callback.message.edit_text(
                    f"{status_msg}\n\n"
                    f"<b>Адрес:</b> <code>{proxy_address}</code>\n"
                    f"<b>Протокол:</b> {protocol.upper()}",
                    parse_mode="HTML"
                )
            else:
                await callback.message.edit_text("❌ Ошибка: прокси не найден после добавления")
        else:
            await callback.message.edit_text("❌ Не удалось добавить прокси. Возможно, он уже существует.")
        
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при добавлении прокси")
        await state.clear()
        await callback.answer()

@router.callback_query(F.data == "proxy_test_all")
async def proxy_test_all(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🧪 Запускаю тестирование всех прокси...")
        
        proxy_manager = get_proxy_manager()
        proxy_manager.periodic_proxy_test()
        
        proxies = proxy_manager.get_all_proxies(active_only=False)
        active_proxies = [p for p in proxies if p.status == "active"]
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
        await callback.message.edit_text(
            f"✅ <b>Тестирование завершено!</b>\n\n"
            f"Активных прокси: {len(active_proxies)}/{len(proxies)}\n"
            f"Используйте <b>\"📋 Список прокси\"</b> для просмотра детальной информации.",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при тестировании прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при тестировании прокси")

@router.callback_query(F.data == "proxy_stats")
async def proxy_stats(callback: CallbackQuery):
    try:
        proxy_manager = get_proxy_manager()
        proxies = proxy_manager.get_all_proxies()
        
        if not proxies:
            await callback.message.edit_text("❌ Нет прокси для отображения статистики")
            return
        
        active_proxies = [p for p in proxies if p.status == "active"]
        total_requests = sum(p.success_count + p.fail_count for p in proxies)
        successful_requests = sum(p.success_count for p in proxies)
        success_rate = (successful_requests / max(total_requests, 1)) * 100
        
        active_speeds = [p.speed_ms for p in active_proxies if p.speed_ms > 0]
        avg_speed = sum(active_speeds) / len(active_speeds) if active_speeds else 0
        
        response = (
            "📊 <b>Статистика прокси:</b>\n\n"
            f"• Всего прокси: {len(proxies)}\n"
            f"• Активных: {len(active_proxies)}\n"
            f"• Общее количество запросов: {total_requests}\n"
            f"• Успешных запросов: {successful_requests}\n"
            f"• Общая успешность: {success_rate:.1f}%\n"
            f"• Средняя скорость: {avg_speed:.0f}мс\n\n"
            f"<i>Детальная статистика по каждому прокси в списке</i>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики прокси")

@router.callback_query(F.data == "proxy_delete")
async def proxy_delete_start(callback: CallbackQuery):
    await safe_answer_callback(callback)
    try:
        proxy_manager = get_proxy_manager()
        proxies = proxy_manager.get_all_proxies()
        
        if not proxies:
            await callback.message.edit_text("❌ Нет прокси для удаления")
            return
        
        builder = InlineKeyboardBuilder()
        for proxy in proxies:
            status_icon = "🟢" if proxy.status == "active" else "🔴"
            builder.add(InlineKeyboardButton(
                text=f"{status_icon} {proxy.address}",
                callback_data=f"proxy_delete_{proxy.id}"
            ))
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
        builder.adjust(1)
        await callback.message.edit_text(
            "🗑️ <b>Выберите прокси для удаления:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при удалении прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении прокси")

@router.callback_query(F.data.startswith("proxy_delete_"))
async def process_proxy_delete(callback: CallbackQuery):
    await safe_answer_callback(callback)
    try:
        # Игнорируем proxy_delete_dead
        if callback.data == "proxy_delete_dead":
            return
            
        proxy_id_str = callback.data.split("_")[2]
        if not proxy_id_str.isdigit():
            await callback.message.edit_text("❌ Некорректный идентификатор прокси")
            return
        proxy_id = int(proxy_id_str)
        proxy_manager = get_proxy_manager()
        proxy = proxy_manager.get_proxy_by_id(proxy_id)
        
        if not proxy:
            await callback.message.edit_text("❌ Прокси не найден")
            return
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"proxy_confirm_delete_{proxy_id}"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"⚠️ <b>Вы уверены что хотите удалить прокси?</b>\n\n"
            f"<b>Адрес:</b> <code>{proxy.address}</code>\n"
            f"<b>Протокол:</b> {proxy.protocol}\n"
            f"<b>Статус:</b> {proxy.status}\n\n"
            f"Это действие нельзя отменить!",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при удалении прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении прокси")

@router.callback_query(F.data.startswith("proxy_confirm_delete_"))
async def process_proxy_confirm_delete(callback: CallbackQuery):
    await safe_answer_callback(callback)
    try:
        proxy_id = int(callback.data.split("_")[3])
        proxy_manager = get_proxy_manager()
        
        success = proxy_manager.delete_proxy(proxy_id)
        
        proxy_manager = get_proxy_manager()
        proxies_left = proxy_manager.get_all_proxies()
        if success:
            if proxies_left:
                # Показываем обновленный список для повторного удаления
                builder = InlineKeyboardBuilder()
                for proxy in proxies_left:
                    status_icon = "🟢" if proxy.status == "active" else "🔴"
                    builder.add(InlineKeyboardButton(
                        text=f"{status_icon} {proxy.address}",
                        callback_data=f"proxy_delete_{proxy.id}"
                    ))
                builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
                builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
                builder.adjust(1)
                await callback.message.edit_text(
                    "✅ <b>Прокси успешно удален!</b>\n\n"
                    "Выберите следующий прокси для удаления:",
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            else:
                builder = InlineKeyboardBuilder()
                builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
                await callback.message.edit_text(
                    "✅ <b>Прокси успешно удален!</b>\n\n"
                    "Прокси-сервер больше не будет использоваться в ротации.",
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
        else:
            await callback.message.edit_text("❌ Не удалось удалить прокси")
    except Exception as e:
        logger.error(f"Ошибка при подтверждении удаления прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при подтверждении удаления прокси")

# =============================================================================
# УДАЛЕНИЕ НЕРАБОЧИХ ПРОКСИ
# =============================================================================

@router.callback_query(F.data == "proxy_delete_dead")
async def proxy_delete_dead(callback: CallbackQuery):
    try:
        proxy_manager = get_proxy_manager()
        proxies = proxy_manager.get_all_proxies(active_only=False)
        dead_proxies = [p for p in proxies if p.status != "active"]
        if not dead_proxies:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
            await callback.message.edit_text("❌ Нет нерабочих прокси для удаления.", reply_markup=builder.as_markup())
            return
        deleted = 0
        for proxy in dead_proxies:
            if proxy_manager.delete_proxy(proxy.id):
                deleted += 1
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_proxy"))
        await callback.message.edit_text(
            f"✅ Удалено нерабочих прокси: {deleted}",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении нерабочих прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении нерабочих прокси")

# =============================================================================
# УПРАВЛЕНИЕ USER-AGENT
# =============================================================================

@router.message(F.text == "👤 Управление User-Agent")
async def menu_ua_management(message: Message):
    keyboard = get_user_agent_management_keyboard()
    await message.answer(
        "👤 <b>Управление User-Agent</b>\n\n"
        "Выберите действие для управления User-Agent:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "ua_list")
async def ua_list(callback: CallbackQuery):
    try:
        logger.info("📋 Получение списка User-Agent")
        ua_manager = get_user_agent_manager()
        user_agents = ua_manager.get_all_user_agents()

        if not user_agents:
            logger.warning("⚠️ Нет добавленных User-Agent")
            await callback.message.edit_text("❌ Нет добавленных User-Agent")
            return

        # Берем первые 10 User-Agent для отображения
        ua_data_list = user_agents[:10]

        response = "📋 <b>Список User-Agent:</b>\n\n"
        for ua_data in ua_data_list:
            status_icon = "🟢" if ua_data['status'] == "active" else "🔴"
            response += f"{status_icon} <b>{ua_data['browser_type']} {ua_data['browser_version']}</b>\n"
            response += f"   Платформа: {ua_data['platform']} ({ua_data['device_type']})\n"
            response += f"   Использований: {ua_data['usage_count']}\n"
            response += f"   Успешность: {ua_data['success_rate']*100:.1f}%\n\n"

        if len(user_agents) > 10:
            response += f"<i>... и еще {len(user_agents) - 10} User-Agent</i>"

        logger.info(f"✅ Отображено {len(ua_data_list)} User-Agent")
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_ua"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"❌ Ошибка при получении списка User-Agent: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при получении списка User-Agent")

@router.callback_query(F.data == "ua_stats")
async def ua_stats(callback: CallbackQuery):
    try:
        logger.info("📊 Получение статистики User-Agent")
        ua_manager = get_user_agent_manager()
        stats = ua_manager.get_user_agent_stats()

        response = (
            "📊 <b>Статистика User-Agent:</b>\n\n"
            f"• Всего User-Agent: {stats['total']}\n"
            f"• Активных: {stats['active']}\n"
            f"• Неактивных: {stats['inactive']}\n"
            f"• Средняя успешность: {stats['avg_success_rate']*100:.1f}%\n"
            f"• Среднее использование: {stats['avg_usage_count']:.1f}\n\n"
            f"<i>Система автоматически выбирает оптимальные User-Agent</i>"
        )

        logger.info(f"✅ Статистика User-Agent получена: {stats['total']} всего, {stats['active']} активных")
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_ua"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"❌ Ошибка при получении статистики User-Agent: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при получении статистики User-Agent")

@router.callback_query(F.data == "ua_add")
async def ua_add_start(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_ua"))
    await callback.message.edit_text(
        "➕ <b>Добавление нового User-Agent</b>\n\n"
        "Введите User-Agent строку:\n\n"
        "Пример:\n"
        "<code>Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36</code>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(UserAgentStates.waiting_for_user_agent)
    await callback.answer()

@router.message(UserAgentStates.waiting_for_user_agent)
async def process_user_agent_input(message: Message, state: FSMContext):
    user_agent_string = message.text.strip()
    
    if not user_agent_string:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_ua"))
        await message.answer("❌ User-Agent не может быть пустым. Попробуйте снова:", reply_markup=builder.as_markup())
        return
    # === Обработчики отмены и возврата для User-Agent ===
    
    try:
        ua_manager = get_user_agent_manager()
        
        browser_type = "chrome"
        browser_version = "91.0"
        platform = "windows"
        device_type = "desktop"
        
        if "Firefox" in user_agent_string:
            browser_type = "firefox"
        elif "Safari" in user_agent_string and "Chrome" not in user_agent_string:
            browser_type = "safari"
        elif "Edg" in user_agent_string:
            browser_type = "edge"
        
        if "Mobile" in user_agent_string or "Android" in user_agent_string:
            device_type = "mobile"
        if "Mac" in user_agent_string:
            platform = "macos"
        elif "Linux" in user_agent_string:
            platform = "linux"
        elif "Android" in user_agent_string:
            platform = "android"
        
        success = ua_manager.add_user_agent(
            user_agent_string, browser_type, browser_version, platform, device_type
        )
        
        if success:
            await message.answer(
                f"✅ <b>User-Agent успешно добавлен!</b>\n\n"
                f"<b>Тип браузера:</b> {browser_type}\n"
                f"<b>Платформа:</b> {platform}\n"
                f"<b>Тип устройства:</b> {device_type}\n\n"
                f"User-Agent теперь доступен для использования в ротации.",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Не удалось добавить User-Agent. Возможно, он уже существует.")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении User-Agent: {e}")
        await message.answer("❌ Ошибка при добавлении User-Agent")
        await state.clear()

@router.callback_query(F.data == "ua_generate")
async def ua_generate(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🔄 Генерация новых User-Agent...")
        
        ua_manager = get_user_agent_manager()

        current_ua = ua_manager.get_all_user_agents()
        current_count = len(current_ua)

        # Получаем список User-Agent для генерации
        new_user_agents = ua_manager.get_user_agents_to_generate()

        added_count = 0
        for ua in new_user_agents:
            success = ua_manager.add_user_agent(*ua)
            if success:
                added_count += 1
        
        await callback.message.edit_text(
            f"✅ <b>Генерация завершена!</b>\n\n"
            f"Добавлено новых User-Agent: {added_count}\n"
            f"Всего User-Agent в системе: {current_count + added_count}\n\n"
            f"Новые User-Agent теперь доступны для использования.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации User-Agent: {e}")
        await callback.message.edit_text("❌ Ошибка при генерации User-Agent")

# =============================================================================
# СТАТИСТИКА СИСТЕМЫ
# =============================================================================

@router.message(F.text == "📈 Статистика системы")
async def menu_statistics(message: Message):
    keyboard = get_statistics_keyboard()
    await message.answer(
        "📈 <b>Статистика системы</b>\n\n"
        "Выберите раздел статистики:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "stats_overall")
async def stats_overall(callback: CallbackQuery):
    try:
        stats_manager = get_statistics_manager()
        overall_stats = stats_manager.get_overall_stats()
        
        response = (
            "📈 <b>Общая статистика системы</b>\n\n"
            f"• Запросов за 24ч: {overall_stats['last_24h_requests']}\n"
            f"• Успешных запросов: {overall_stats['last_24h_success']}\n"
            f"• Заблокированных запросов: {overall_stats['last_24h_blocked']}\n"
            f"• Успешность: {overall_stats['last_24h_success_rate']}%\n"
            f"• Протестировано комбинаций: {overall_stats['total_combinations_tested']}\n\n"
            f"<i>Статистика обновляется в реальном времени</i>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка при получении общей статистики: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики")

@router.callback_query(F.data == "stats_by_exchange")
async def stats_by_exchange(callback: CallbackQuery):
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                builder = InlineKeyboardBuilder()
                builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
                await callback.message.edit_text("❌ Нет добавленных бирж для статистики", reply_markup=builder.as_markup())
                return
            
            exchanges = list(set(link.exchange for link in links))
            stats_manager = get_statistics_manager()
            
            response = "🏢 <b>Статистика по биржам (за 24ч):</b>\n\n"
            
            for exchange in exchanges:
                stats = stats_manager.get_exchange_stats(exchange, 24)
                if stats:
                    response += f"<b>{exchange}</b>\n"
                    response += f"• Запросов: {stats['total_requests']}\n"
                    response += f"• Успешность: {stats['success_rate']}%\n"
                    response += f"• Среднее время: {stats['average_response_time']}мс\n\n"
            
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
            await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
            
    except Exception as e:
        logger.error(f"Ошибка при получении статистики по биржам: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики по биржам")

@router.callback_query(F.data == "stats_best_combinations")
async def stats_best_combinations(callback: CallbackQuery):
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                builder = InlineKeyboardBuilder()
                builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
                await callback.message.edit_text("❌ Нет добавленных бирж", reply_markup=builder.as_markup())
                return
            
            exchanges = list(set(link.exchange for link in links))
            stats_manager = get_statistics_manager()
            
            response = "🔗 <b>Лучшие комбинации (за 24ч):</b>\n\n"
            
            for exchange in exchanges[:3]:
                combinations = stats_manager.get_best_combinations(exchange, 3)
                if combinations:
                    response += f"<b>{exchange}</b>\n"
                    for i, combo in enumerate(combinations, 1):
                        response += f"{i}. Proxy#{combo['proxy_id']} + UA#{combo['user_agent_id']}\n"
                        response += f"   Успешность: {combo['success_rate']}% | Время: {combo['avg_response_time']}мс\n"
                    response += "\n"
            
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
            await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
            
    except Exception as e:
        logger.error(f"Ошибка при получении лучших комбинаций: {e}")
        await callback.message.edit_text("❌ Ошибка при получении лучших комбинаций")

@router.callback_query(F.data == "stats_rotation_status")
async def stats_rotation_status(callback: CallbackQuery):
    try:
        rotation_manager = get_rotation_manager()
        status = rotation_manager.get_rotation_status()
        
        time_until_rotation = status['time_until_next_rotation']
        minutes = int(time_until_rotation // 60)
        seconds = int(time_until_rotation % 60)
        
        response = (
            "🔄 <b>Статус ротации</b>\n\n"
            f"• Активных бирж: {status['total_active_combinations']}\n"
            f"• Интервал ротации: {status['rotation_interval']} сек\n"
            f"• Автооптимизация: {'ВКЛ' if status['auto_optimize'] else 'ВЫКЛ'}\n"
            f"• До следующей ротации: {minutes:02d}:{seconds:02d}\n\n"
        )
        
        if status['combinations']:
            response += "<b>Активные комбинации:</b>\n"
            for exchange, combo in list(status['combinations'].items())[:5]:
                response += f"• {exchange}: proxy#{combo['proxy_id']} + ua#{combo['user_agent_id']} (score: {combo['score']})\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="bypass_stats"))
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса ротации: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статуса ротации")

# =============================================================================
# НАСТРОЙКИ РОТАЦИИ
# =============================================================================

@router.message(F.text == "⚙️ Настройки ротации")
async def menu_rotation_settings(message: Message):
    keyboard = get_rotation_settings_keyboard()
    await message.answer(
        "⚙️ <b>Настройки ротации</b>\n\n"
        "Управление параметрами ротации прокси и User-Agent:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "rotation_current")
async def rotation_current(callback: CallbackQuery):
    try:
        rotation_manager = get_rotation_manager()
        settings = rotation_manager.settings
        
        response = (
            "⚙️ <b>Текущие настройки ротации</b>\n\n"
            f"• Интервал ротации: {settings.rotation_interval} сек\n"
            f"• Автооптимизация: {'ВКЛ' if settings.auto_optimize else 'ВЫКЛ'}\n"
            f"• Хранение статистики: {settings.stats_retention_days} дней\n"
            f"• Архивация неактивных: {settings.archive_inactive_days} дней\n"
            f"• Последняя ротация: {_format_timestamp(settings.last_rotation)}\n"
            f"• Последняя очистка: {_format_timestamp(settings.last_cleanup)}\n\n"
            f"<i>Используйте кнопки ниже для изменения настроек</i>"
        )
        
        keyboard = get_rotation_management_keyboard()
        await callback.message.edit_text(response, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Ошибка при получении настроек ротации: {e}")
        await callback.message.edit_text("❌ Ошибка при получении настроек ротации")

@router.callback_query(F.data == "rotation_interval")
async def rotation_interval_start(callback: CallbackQuery, state: FSMContext):
    keyboard = get_rotation_interval_keyboard()
    await callback.message.edit_text(
        "⏰ <b>Настройка интервала ротации</b>\n\n"
        "Выберите интервал из предложенных вариантов или введите свое значение:\n\n"
        "• Рекомендуется: 15-60 минут\n"
        "• Минимальный: 10 минут (600 сек)\n"
        "• Максимальный: 24 часа (86400 сек)\n\n"
        "<i>Выберите подходящий вариант:</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@router.message(RotationSettingsStates.waiting_for_rotation_interval)
async def process_rotation_interval(message: Message, state: FSMContext):
    try:
        interval_seconds = int(message.text.strip())
        
        if interval_seconds < 300 or interval_seconds > 86400:
            await message.answer("❌ Интервал должен быть от 300 до 86400 секунд. Попробуйте снова:")
            return
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(rotation_interval=interval_seconds)
        
        minutes = interval_seconds // 60
        await message.answer(
            f"✅ <b>Интервал ротации обновлен!</b>\n\n"
            f"Новый интервал: {interval_seconds} сек ({minutes} минут)\n"
            f"Ротация будет выполняться каждые {minutes} минут.",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число (только цифры):")
    except Exception as e:
        logger.error(f"Ошибка при установке интервала ротации: {e}")
        await message.answer("❌ Ошибка при установке интервала ротации")
        await state.clear()

# Обработчики preset кнопок для интервала ротации
@router.callback_query(F.data.startswith("set_rotation_interval_"))
async def set_rotation_interval_preset(callback: CallbackQuery):
    try:
        interval_seconds = int(callback.data.split("_")[-1])
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(rotation_interval=interval_seconds)
        
        # Форматируем время в читаемый вид
        if interval_seconds < 3600:
            time_str = f"{interval_seconds // 60} минут"
        else:
            hours = interval_seconds // 3600
            time_str = f"{hours} час{'а' if hours < 5 else 'ов'}"
        
        await callback.message.edit_text(
            f"✅ <b>Интервал ротации обновлен!</b>\n\n"
            f"Новый интервал: {time_str} ({interval_seconds} сек)\n"
            f"Ротация будет выполняться с заданным интервалом.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Интервал установлен!")
        
    except Exception as e:
        logger.error(f"Ошибка при установке интервала ротации: {e}")
        await callback.message.edit_text("❌ Ошибка при установке интервала ротации")
        await callback.answer("❌ Ошибка!")

@router.callback_query(F.data == "rotation_interval_custom")
async def rotation_interval_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⏰ <b>Ввод своего значения интервала</b>\n\n"
        "Введите интервал в секундах:\n"
        "• Минимальный: 300 сек (5 минут)\n"
        "• Максимальный: 86400 сек (24 часа)\n\n"
        "<i>Например: 1800 (для 30 минут)</i>",
        parse_mode="HTML"
    )
    await state.set_state(RotationSettingsStates.waiting_for_rotation_interval)
    await callback.answer()

# =============================================================================
# НАСТРОЙКА ХРАНЕНИЯ СТАТИСТИКИ
# =============================================================================

@router.callback_query(F.data == "rotation_stats_retention")
async def rotation_stats_retention_start(callback: CallbackQuery):
    keyboard = get_stats_retention_keyboard()
    rotation_manager = get_rotation_manager()
    current_days = rotation_manager.settings.stats_retention_days
    
    await callback.message.edit_text(
        "📊 <b>Настройка срока хранения статистики</b>\n\n"
        f"Текущее значение: {current_days} дней\n\n"
        "Выберите новый срок хранения статистики или введите свое значение:\n\n"
        "• Рекомендуется: 30-90 дней\n"
        "• Минимальный: 1 день\n"
        "• Максимальный: 365 дней\n\n"
        "<i>Старые записи будут автоматически удаляться</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_stats_retention_"))
async def set_stats_retention_preset(callback: CallbackQuery):
    try:
        days = int(callback.data.split("_")[-1])
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(stats_retention_days=days)
        
        await callback.message.edit_text(
            f"✅ <b>Срок хранения статистики обновлен!</b>\n\n"
            f"Новое значение: {days} дней\n"
            f"Записи старше {days} дней будут автоматически удаляться.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Настройка сохранена!")
        
    except Exception as e:
        logger.error(f"Ошибка при установке срока хранения статистики: {e}")
        await callback.message.edit_text("❌ Ошибка при установке срока хранения")
        await callback.answer("❌ Ошибка!")

@router.callback_query(F.data == "stats_retention_custom")
async def stats_retention_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📊 <b>Ввод своего значения</b>\n\n"
        "Введите количество дней для хранения статистики:\n"
        "• Минимальный: 1 день\n"
        "• Максимальный: 365 дней\n\n"
        "<i>Например: 45 (для 45 дней)</i>",
        parse_mode="HTML"
    )
    await state.set_state(RotationSettingsStates.waiting_for_stats_retention)
    await callback.answer()

@router.message(RotationSettingsStates.waiting_for_stats_retention)
async def process_stats_retention(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        
        if days < 1 or days > 365:
            await message.answer("❌ Срок должен быть от 1 до 365 дней. Попробуйте снова:")
            return
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(stats_retention_days=days)
        
        await message.answer(
            f"✅ <b>Срок хранения статистики обновлен!</b>\n\n"
            f"Новое значение: {days} дней\n"
            f"Записи старше {days} дней будут автоматически удаляться.",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число (только цифры):")
    except Exception as e:
        logger.error(f"Ошибка при установке срока хранения статистики: {e}")
        await message.answer("❌ Ошибка при установке срока хранения")
        await state.clear()

# =============================================================================
# НАСТРОЙКА АРХИВАЦИИ НЕАКТИВНЫХ
# =============================================================================

@router.callback_query(F.data == "rotation_archive_inactive")
async def rotation_archive_inactive_start(callback: CallbackQuery):
    keyboard = get_archive_inactive_keyboard()
    rotation_manager = get_rotation_manager()
    current_days = rotation_manager.settings.archive_inactive_days
    
    await callback.message.edit_text(
        "📦 <b>Настройка срока архивации неактивных записей</b>\n\n"
        f"Текущее значение: {current_days} дней\n\n"
        "Выберите новый срок архивации или введите свое значение:\n\n"
        "• Рекомендуется: 7-30 дней\n"
        "• Минимальный: 1 день\n"
        "• Максимальный: 90 дней\n\n"
        "<i>Неактивные записи будут архивироваться через указанный период</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_archive_inactive_"))
async def set_archive_inactive_preset(callback: CallbackQuery):
    try:
        days = int(callback.data.split("_")[-1])
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(archive_inactive_days=days)
        
        await callback.message.edit_text(
            f"✅ <b>Срок архивации обновлен!</b>\n\n"
            f"Новое значение: {days} дней\n"
            f"Неактивные записи будут архивироваться через {days} дней.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Настройка сохранена!")
        
    except Exception as e:
        logger.error(f"Ошибка при установке срока архивации: {e}")
        await callback.message.edit_text("❌ Ошибка при установке срока архивации")
        await callback.answer("❌ Ошибка!")

@router.callback_query(F.data == "archive_inactive_custom")
async def archive_inactive_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📦 <b>Ввод своего значения</b>\n\n"
        "Введите количество дней для архивации неактивных записей:\n"
        "• Минимальный: 1 день\n"
        "• Максимальный: 90 дней\n\n"
        "<i>Например: 14 (для 14 дней)</i>",
        parse_mode="HTML"
    )
    await state.set_state(RotationSettingsStates.waiting_for_archive_inactive)
    await callback.answer()

@router.message(RotationSettingsStates.waiting_for_archive_inactive)
async def process_archive_inactive(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        
        if days < 1 or days > 90:
            await message.answer("❌ Срок должен быть от 1 до 90 дней. Попробуйте снова:")
            return
        
        rotation_manager = get_rotation_manager()
        rotation_manager.update_settings(archive_inactive_days=days)
        
        await message.answer(
            f"✅ <b>Срок архивации обновлен!</b>\n\n"
            f"Новое значение: {days} дней\n"
            f"Неактивные записи будут архивироваться через {days} дней.",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число (только цифры):")
    except Exception as e:
        logger.error(f"Ошибка при установке срока архивации: {e}")
        await message.answer("❌ Ошибка при установке срока архивации")
        await state.clear()

@router.callback_query(F.data == "rotation_auto_optimize")
async def rotation_auto_optimize(callback: CallbackQuery):
    try:
        rotation_manager = get_rotation_manager()
        current_setting = rotation_manager.settings.auto_optimize
        new_setting = not current_setting
        
        rotation_manager.update_settings(auto_optimize=new_setting)
        
        status = "ВКЛ" if new_setting else "ВЫКЛ"
        await callback.message.edit_text(
            f"✅ <b>Автооптимизация {status}</b>\n\n"
            f"Система автоматического подбора оптимальных комбинаций {'включена' if new_setting else 'выключена'}.\n\n"
            f"<i>При включении система будет автоматически выбирать лучшие комбинации прокси и User-Agent</i>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при изменении автооптимизации: {e}")
        await callback.message.edit_text("❌ Ошибка при изменении автооптимизации")

@router.callback_query(F.data == "rotation_force")
async def rotation_force(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🔄 Запуск принудительной ротации...")
        
        rotation_manager = get_rotation_manager()
        rotation_manager.rotate_all_combinations()
        
        await callback.message.edit_text(
            "✅ <b>Принудительная ротация завершена!</b>\n\n"
            "Все активные комбинации прокси и User-Agent были сброшены.\n"
            "Новые комбинации будут подобраны при следующем запросе.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при принудительной ротации: {e}")
        await callback.message.edit_text("❌ Ошибка при принудительной ротации")

@router.callback_query(F.data == "rotation_cleanup")
async def rotation_cleanup(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🗑️ Запуск очистки старых данных...")
        
        stats_manager = get_statistics_manager()
        stats_manager._cleanup_old_data()
        
        await callback.message.edit_text(
            "✅ <b>Очистка данных завершена!</b>\n\n"
            "Старые записи статистики были удалены в соответствии с настройками хранения.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при очистке данных: {e}")
        await callback.message.edit_text("❌ Ошибка при очистке данных")

# =============================================================================
# ОБРАБОТЧИКИ ОТМЕНЫ ДЛЯ НОВЫХ СИСТЕМ
# =============================================================================

@router.callback_query(F.data.in_(["proxy_cancel", "stats_cancel", "rotation_cancel"]))
async def process_new_systems_cancel(callback: CallbackQuery, state: FSMContext):
    # Очищаем выбор пользователя и состояние
    global user_selections
    if callback.from_user.id in user_selections:
        del user_selections[callback.from_user.id]
    await state.clear()

    # Возвращаемся к меню "Обход блокировок"
    keyboard = get_bypass_keyboard()
    await callback.message.edit_text(
        "🛡️ <b>Обход блокировок</b>\n\n"
        "Выберите нужную функцию:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def format_notification_settings_message(link) -> str:
    """Форматирует сообщение с настройками умных уведомлений"""

    # Преобразование bool в эмодзи
    def bool_emoji(value):
        return "✅ Включено" if value else "❌ Выключено"

    # Определяем категорию для правильного отображения
    category = getattr(link, 'category', 'staking')
    category_names = {
        'staking': 'Стейкинг',
        'launchpool': 'Launchpool',
        'launchpad': 'Launchpad',
        'launches': 'Запуски',
        'airdrop': 'Airdrop',
        'candybomb': 'CandyBomb',
        'announcement': 'Анонсы'
    }
    category_display = category_names.get(category, category.title())
    
    # Получаем значения настроек launchpool
    notify_period = getattr(link, 'notify_period_changes', True)
    notify_reward_pool = getattr(link, 'notify_reward_pool_changes', True)

    message = (
        f"⚙️ <b>НАСТРОЙКИ УМНЫХ УВЕДОМЛЕНИЙ</b>\n\n"
        f"🏦 <b>Биржа:</b> {link.name}\n"
        f"📌 <b>Категория:</b> {category_display}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>ТЕКУЩИЕ НАСТРОЙКИ:</b>\n\n"
        f"🔔 <b>Новые стейкинги:</b> {bool_emoji(link.notify_new_stakings)}\n"
        f"📈 <b>Изменения APR:</b> {bool_emoji(link.notify_apr_changes)}\n"
        f"📊 <b>Заполненность:</b> {bool_emoji(link.notify_fill_changes)}\n"
        f"📅 <b>Изменения периода:</b> {bool_emoji(notify_period)}\n"
        f"🎁 <b>Изменения пула наград:</b> {bool_emoji(notify_reward_pool)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ <b>FLEXIBLE СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Время стабилизации:</b> {link.flexible_stability_hours} часов\n"
        f"└─ <b>Только стабильные:</b> {bool_emoji(link.notify_only_stable_flexible)}\n\n"
        f"⚡ <b>FIXED СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Уведомлять сразу:</b> {bool_emoji(link.fixed_notify_immediately)}\n"
        f"└─ <b>Combined как Fixed:</b> {bool_emoji(link.notify_combined_as_fixed)}\n\n"
        f"📊 <b>ИЗМЕНЕНИЯ APR:</b>\n"
        f"└─ <b>Минимальный порог:</b> {link.notify_min_apr_change}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <i>Combined стейкинги содержат Fixed И Flexible опции.\n"
        f"При включенной настройке \"Combined как Fixed\" они уведомляют сразу.</i>\n\n"
        f"Выберите действие:"
    )

    return message

def _format_timestamp(timestamp: float) -> str:
    if timestamp == 0:
        return "никогда"
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%d.%m.%Y %H:%M:%S")


# =============================================================================
# ТОП АКТИВНОСТИ - ОБРАБОТЧИКИ
# =============================================================================

# Состояние пагинации для ТОП АКТИВНОСТИ
top_activity_state = {}

@router.callback_query(F.data == "top_activity_menu")
async def show_top_activity_menu(callback: CallbackQuery):
    """Показать главное меню ТОП АКТИВНОСТИ"""
    try:
        from services.top_activity_service import get_top_activity_service
        from bot.keyboards import get_top_activity_menu_keyboard
        from aiogram.exceptions import TelegramBadRequest
        
        service = get_top_activity_service()
        stats = service.get_statistics()
        
        # Добавляем секунды для уникальности при обновлении
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
        
        message = (
            f"📊 <b>ТОП АКТИВНОСТИ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🕐 <b>Обновлено:</b> {now} UTC\n\n"
            f"📈 <b>Статистика:</b>\n"
            f"├─ 🔥 Стейкингов: {stats.get('active_stakings', 0)} активных\n"
            f"├─ 🎁 Промоакций: {stats.get('active_promos', 0)} активных\n"
            f"├─ 🏦 Бирж (стейкинг): {stats.get('staking_exchanges', 0)}\n"
            f"└─ 🏦 Бирж (промо): {stats.get('promo_exchanges', 0)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Выберите раздел:"
        )
        
        try:
            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=get_top_activity_menu_keyboard()
            )
        except TelegramBadRequest as e:
            # Игнорируем ошибку "message is not modified"
            if "message is not modified" not in str(e):
                raise
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка открытия ТОП АКТИВНОСТИ: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки", show_alert=True)


@router.callback_query(F.data == "top_activity_refresh")
async def refresh_top_activity(callback: CallbackQuery):
    """Обновить данные ТОП АКТИВНОСТИ"""
    await show_top_activity_menu(callback)


@router.callback_query(F.data == "top_activity_stakings")
async def show_top_stakings(callback: CallbackQuery):
    """Показать ТОП стейкингов со всех бирж"""
    try:
        from services.top_activity_service import get_top_activity_service
        from bot.keyboards import get_top_stakings_keyboard
        
        user_id = callback.from_user.id
        
        # Используем LoadingContext для отзывчивого UI
        async with LoadingContext(
            callback,
            "⏳ <b>Загрузка ТОП стейкингов...</b>\n\n🔄 Агрегируем данные со всех бирж...",
            delete_on_complete=True,
            edit_original=True
        ) as loading:
            service = get_top_activity_service()
            stakings = service.get_top_stakings(limit=50)  # Получаем больше для пагинации
        
        if not stakings:
            await callback.message.edit_text(
                "📊 <b>ТОП СТЕЙКИНГОВ</b>\n\n"
                "📭 <i>Нет активных стейкингов в базе данных.\n"
                "Убедитесь что добавлены ссылки на биржи с категорией 'staking'.</i>",
                parse_mode="HTML",
                reply_markup=get_top_stakings_keyboard(1, 1)
            )
            return
        
        # Сохраняем состояние пагинации
        items_per_page = 5
        total_pages = max(1, (len(stakings) + items_per_page - 1) // items_per_page)
        
        top_activity_state[user_id] = {
            'stakings': stakings,
            'page': 1,
            'items_per_page': items_per_page,
            'total_pages': total_pages
        }
        
        # Форматируем первую страницу
        message = format_top_stakings_page(stakings, 1, total_pages, items_per_page)
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_top_stakings_keyboard(1, total_pages)
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки ТОП стейкингов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки", show_alert=True)


@router.callback_query(F.data.in_(["top_stakings_prev", "top_stakings_next"]))
async def navigate_top_stakings(callback: CallbackQuery):
    """Навигация по страницам ТОП стейкингов"""
    try:
        from bot.keyboards import get_top_stakings_keyboard
        
        user_id = callback.from_user.id
        state = top_activity_state.get(user_id)
        
        if not state or 'stakings' not in state:
            await callback.answer("❌ Данные устарели, обновите список", show_alert=True)
            return
        
        # Изменяем страницу
        current_page = state['page']
        total_pages = state['total_pages']
        
        if callback.data == "top_stakings_prev" and current_page > 1:
            current_page -= 1
        elif callback.data == "top_stakings_next" and current_page < total_pages:
            current_page += 1
        
        state['page'] = current_page
        
        # Форматируем страницу
        message = format_top_stakings_page(
            state['stakings'], 
            current_page, 
            total_pages, 
            state['items_per_page']
        )
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_top_stakings_keyboard(current_page, total_pages)
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка навигации ТОП стейкингов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "top_activity_promos")
async def show_promo_categories(callback: CallbackQuery):
    """Показати меню категорій промоакцій"""
    try:
        from services.top_activity_service import get_top_activity_service
        from bot.keyboards import get_promo_categories_keyboard
        
        # Отримуємо кількість по категоріях
        service = get_top_activity_service()
        counts = service.get_promo_counts_by_category()
        
        # Загальна кількість
        total = sum(counts.values())
        
        # Формуємо повідомлення
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
        message = (
            f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 <b>ПРОМОАКЦІЇ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 Всього активних: <b>{total}</b>\n\n"
        )
        
        # Показуємо кількість по категоріях
        category_info = [
            ("🪂", "Аірдропи", counts.get('airdrop', 0)),
            ("🍬", "Кендибомби", counts.get('candybomb', 0)),
            ("🚀", "Лаунчпади", counts.get('launchpad', 0)),
            ("🌊", "Лаунчпули", counts.get('launchpool', 0)),
            ("🗂️", "Інші", counts.get('other', 0)),
        ]
        
        for icon, name, count in category_info:
            message += f"{icon} {name}: {count}\n"
        
        message += "\n<i>Оберіть категорію для перегляду:</i>"
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_promo_categories_keyboard(counts),
            disable_web_page_preview=True
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Помилка завантаження категорій промо: {e}", exc_info=True)
        await callback.answer("❌ Помилка завантаження", show_alert=True)


# Альас для назад до категорій
@router.callback_query(F.data.in_(["top_promos_categories_menu", "top_promos_categories_refresh"]))
async def back_to_promo_categories(callback: CallbackQuery):
    """Повернутися до меню категорій промоакцій"""
    await show_promo_categories(callback)


@router.callback_query(F.data.regexp(r"^top_promos_(airdrop|candybomb|launchpad|launchpool|other)$"))
async def show_category_promos(callback: CallbackQuery):
    """Показати промоакції конкретної категорії"""
    try:
        from services.top_activity_service import get_top_activity_service
        from bot.keyboards import get_category_promos_keyboard
        
        # Визначаємо категорію з callback_data
        category = callback.data.replace("top_promos_", "")
        user_id = callback.from_user.id
        
        # Отримуємо конфіг категорії
        CATEGORY_CONFIG = {
            'airdrop': {'icon': '🪂', 'name': 'Аірдропи'},
            'candybomb': {'icon': '🍬', 'name': 'Кендибомби'},
            'launchpad': {'icon': '🚀', 'name': 'Лаунчпади'},
            'launchpool': {'icon': '🌊', 'name': 'Лаунчпули'},
            'other': {'icon': '🗂️', 'name': 'Інші'},
        }
        
        config = CATEGORY_CONFIG.get(category, {'icon': '📋', 'name': category.title()})
        
        # Використовуємо LoadingContext
        async with LoadingContext(
            callback,
            f"⏳ <b>Завантаження {config['name']}...</b>",
            delete_on_complete=True,
            edit_original=True
        ) as loading:
            service = get_top_activity_service()
            promos = service.get_top_promos_by_category(category, limit=50)
        
        items_per_page = 5
        total_pages = max(1, (len(promos) + items_per_page - 1) // items_per_page)
        
        # Зберігаємо стан
        top_activity_state[user_id] = {
            'category_promos': promos,
            'category': category,
            'page': 1,
            'items_per_page': items_per_page,
            'total_pages': total_pages,
            'type': 'category_promos'
        }
        
        # Форматуємо сторінку
        message = format_category_page(
            promos, 1, total_pages, items_per_page, 
            category, config['icon'], config['name']
        )
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_category_promos_keyboard(category, 1, total_pages),
            disable_web_page_preview=True
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Помилка завантаження категорії {callback.data}: {e}", exc_info=True)
        await callback.answer("❌ Помилка завантаження", show_alert=True)


@router.callback_query(F.data.regexp(r"^top_promos_(airdrop|candybomb|launchpad|launchpool|other)_(prev|next)$"))
async def navigate_category_promos(callback: CallbackQuery):
    """Навігація по сторінках категорії промо"""
    try:
        from bot.keyboards import get_category_promos_keyboard
        
        user_id = callback.from_user.id
        state = top_activity_state.get(user_id)
        
        if not state or state.get('type') != 'category_promos':
            await callback.answer("❌ Дані застаріли, оновіть список", show_alert=True)
            return
        
        # Парсимо callback
        parts = callback.data.replace("top_promos_", "").rsplit("_", 1)
        category = parts[0]  # airdrop, candybomb, etc.
        action = parts[1]    # prev or next
        
        # Перевіряємо що категорія співпадає
        if category != state.get('category'):
            await callback.answer("❌ Дані застаріли", show_alert=True)
            return
        
        current_page = state['page']
        total_pages = state['total_pages']
        
        if action == "prev" and current_page > 1:
            current_page -= 1
        elif action == "next" and current_page < total_pages:
            current_page += 1
        
        state['page'] = current_page
        
        # Отримуємо конфіг категорії
        CATEGORY_CONFIG = {
            'airdrop': {'icon': '🪂', 'name': 'Аірдропи'},
            'candybomb': {'icon': '🍬', 'name': 'Кендибомби'},
            'launchpad': {'icon': '🚀', 'name': 'Лаунчпади'},
            'launchpool': {'icon': '🌊', 'name': 'Лаунчпули'},
            'other': {'icon': '🗂️', 'name': 'Інші'},
        }
        config = CATEGORY_CONFIG.get(category, {'icon': '📋', 'name': category.title()})
        
        # Форматуємо сторінку
        message = format_category_page(
            state['category_promos'], 
            current_page, 
            total_pages, 
            state['items_per_page'],
            category, config['icon'], config['name']
        )
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_category_promos_keyboard(category, current_page, total_pages),
            disable_web_page_preview=True
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Помилка навігації категорії: {e}", exc_info=True)
        await callback.answer("❌ Помилка", show_alert=True)


@router.callback_query(F.data.regexp(r"^top_promos_(airdrop|candybomb|launchpad|launchpool|other)_info$"))
async def category_page_info(callback: CallbackQuery):
    """Інформація про поточну сторінку категорії"""
    await callback.answer("📄 Поточна сторінка")


# Legacy handler - перенаправляємо на категорії
@router.callback_query(F.data.in_(["top_promos_prev", "top_promos_next"]))
async def navigate_top_promos(callback: CallbackQuery):
    """Навигация по страницам ТОП промоакций"""
    try:
        from bot.keyboards import get_top_promos_keyboard
        
        user_id = callback.from_user.id
        state = top_activity_state.get(user_id)
        
        if not state or 'promos' not in state:
            await callback.answer("❌ Данные устарели, обновите список", show_alert=True)
            return
        
        # Изменяем страницу
        current_page = state['page']
        total_pages = state['total_pages']
        
        if callback.data == "top_promos_prev" and current_page > 1:
            current_page -= 1
        elif callback.data == "top_promos_next" and current_page < total_pages:
            current_page += 1
        
        state['page'] = current_page
        
        # Форматируем страницу
        message = format_top_promos_page(
            state['promos'], 
            current_page, 
            total_pages, 
            state['items_per_page']
        )
        
        await callback.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=get_top_promos_keyboard(current_page, total_pages),
            disable_web_page_preview=True
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"❌ Ошибка навигации ТОП промоакций: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.in_(["top_stakings_info", "top_promos_info"]))
async def top_activity_page_info(callback: CallbackQuery):
    """Информация о текущей странице"""
    await callback.answer("📄 Текущая страница")


def format_top_stakings_page(stakings: list, page: int, total_pages: int, items_per_page: int) -> str:
    """Форматирует страницу ТОП стейкингов"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТИ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>СТЕЙКИНГИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    # Вычисляем срез для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_stakings = stakings[start_idx:end_idx]
    
    # Номера для рейтинга
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, staking in enumerate(page_stakings):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        coin = staking.get('coin', 'N/A')
        exchange = staking.get('exchange', 'N/A')
        apr = staking.get('apr', 0) or 0
        
        # Определяем тип (Fixed/Flexible)
        staking_type = staking.get('type', '') or ''
        is_flexible = staking.get('is_flexible', False)
        term_days = staking.get('term_days')
        
        if is_flexible or 'flex' in staking_type.lower():
            type_str = "Flexible"
        elif term_days:
            type_str = f"Fixed {term_days}д"
        else:
            type_str = staking_type[:20] if staking_type else "N/A"
        
        # Заработок
        profit_display = staking.get('profit_display', 'N/A')
        
        # Макс сумма и заполненность
        user_limit = staking.get('user_limit_usd', 0)
        fill_pct = staking.get('fill_percentage')
        
        if user_limit:
            limit_str = f"${user_limit:,.0f}"
        else:
            limit_str = "нет данных"
        
        if fill_pct is not None:
            fill_str = f"({fill_pct:.0f}% заполнено)"
        else:
            fill_str = ""
        
        # Оставшееся время
        time_remaining = staking.get('time_remaining', 'нет данных')
        
        # Формируем карточку
        message += f"{number} <b>{coin}</b> ({exchange}) • {type_str}\n"
        message += f"🚀 APR: {apr:.1f}%\n"
        message += f"💸 Заработок: {profit_display}\n"
        message += f"🏦 Макс: {limit_str} {fill_str}\n"
        message += f"⏰ Осталось: {time_remaining}\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


def format_top_promos_page(promos: list, page: int, total_pages: int, items_per_page: int) -> str:
    """Форматирует страницу ТОП промоакций"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТИ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎁 <b>ПРОМОАКЦИИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    # Вычисляем срез для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    # Номера для рейтинга
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        title = promo.get('title', 'N/A')
        exchange = promo.get('exchange', 'N/A')
        
        # Токен награды
        award_token = promo.get('award_token', '')
        if award_token:
            title_display = f"{title[:35]} ({award_token})"
        else:
            title_display = title[:40]
        
        # Заработок (награда)
        reward_display = promo.get('reward_display')
        reward_usd_display = promo.get('reward_usd_display')  # USD эквивалент
        
        # Места / участники
        winners = promo.get('winners', 0) or 0
        participants = promo.get('participants', 0) or 0
        
        if winners and participants:
            places_str = f"{winners:,} ({participants:,})"
        elif participants:
            places_str = f"{participants:,}"
        elif winners:
            places_str = f"{winners:,} мест"
        else:
            places_str = None
        
        # Даты
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            start_str = time_data.get('start_str', '')
            end_str = time_data.get('end_str', '')
            remaining_str = time_data.get('remaining_str', '')
            
            if start_str and end_str:
                dates_str = f"{start_str} → {end_str}"
            elif end_str:
                dates_str = f"До {end_str}"
            else:
                dates_str = None
        else:
            dates_str = None
            remaining_str = str(time_data) if time_data else None
        
        # Статус
        status = promo.get('status', '')
        status_emoji = ""
        if status:
            if 'ongoing' in status.lower() or 'active' in status.lower():
                status_emoji = "🟢 "
            elif 'upcoming' in status.lower():
                status_emoji = "🟡 "
        
        # Ссылка
        link = promo.get('link', '')
        
        # Формируем карточку
        message += f"{number} {status_emoji}<b>{title_display}</b> ({exchange})\n"
        
        if reward_display:
            if reward_usd_display:
                message += f"💰 Награда: {reward_display} ({reward_usd_display})\n"
            else:
                message += f"💰 Награда: {reward_display}\n"
        
        if places_str:
            message += f"👥 Участники: {places_str}\n"
        
        if dates_str:
            if remaining_str:
                message += f"📅 {dates_str} ({remaining_str})\n"
            else:
                message += f"📅 {dates_str}\n"
        elif remaining_str:
            message += f"⏳ {remaining_str}\n"
        
        if link:
            message += f"🔗 <a href=\"{link}\">Открыть</a>\n"
        
        message += "\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


# =============================================================================
# ФОРМАТУВАННЯ ДЛЯ КАТЕГОРІЙ ПРОМОАКЦІЙ
# =============================================================================

def format_category_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category: str,
    category_icon: str,
    category_name: str
) -> str:
    """
    Універсальний форматувальник для категорій промоакцій.
    Викликає специфічний форматер в залежності від категорії.
    """
    formatters = {
        'airdrop': format_airdrop_page,
        'candybomb': format_candybomb_page,
        'launchpad': format_launchpad_page,
        'launchpool': format_launchpool_page,
        'other': format_other_page,
    }
    
    formatter = formatters.get(category, format_other_page)
    return formatter(promos, page, total_pages, items_per_page, category_icon, category_name)


def format_airdrop_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category_icon: str = "🪂",
    category_name: str = "Аірдропи"
) -> str:
    """Форматує сторінку аірдропів"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{category_icon} <b>{category_name.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        exchange = promo.get('exchange', 'N/A')
        award_token = promo.get('award_token', '')
        title = promo.get('title', 'N/A')
        
        # Формуємо назву
        if award_token and award_token not in title:
            title_display = f"{exchange} | {award_token}"
        else:
            title_display = f"{exchange} | {title[:25]}"
        
        # Нагорода
        reward_display = promo.get('reward_per_user_display') or promo.get('reward_display')
        reward_usd = promo.get('reward_usd_display')
        expected_reward = promo.get('expected_reward', 0)
        
        # Умови
        conditions = promo.get('conditions', '')
        
        # Учасники / переможці
        participants = promo.get('participants_count') or promo.get('participants', 0)
        winners = promo.get('winners_count') or promo.get('winners', 0)
        
        # Час
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            remaining_str = time_data.get('remaining_str', '')
        else:
            remaining_str = str(time_data) if time_data else ''
        
        link = promo.get('link', '')
        
        # Формуємо картку
        message += f"{number} <b>{title_display}</b>\n"
        
        # 💰 Нагорода
        if reward_display:
            if reward_usd:
                message += f"   💰 Нагорода: {reward_display} ({reward_usd})\n"
            elif expected_reward > 0:
                message += f"   💰 Нагорода: {reward_display} (~${expected_reward:,.2f})\n"
            else:
                message += f"   💰 Нагорода: {reward_display}\n"
        elif expected_reward > 0:
            message += f"   💰 Нагорода: ~${expected_reward:,.2f}\n"
        
        # 📋 Умови
        if conditions:
            message += f"   📋 Умови: {conditions[:50]}\n"
        
        # 👥 Учасники
        if participants and winners:
            message += f"   👥 Учасників: {participants:,} | 🏆 Місць: {winners:,}\n"
        elif participants:
            message += f"   👥 Учасників: {participants:,}\n"
        
        # ⏰ Час
        if remaining_str:
            message += f"   ⏰ {remaining_str}\n"
        
        # 🔗 Посилання
        if link:
            message += f"   🔗 <a href=\"{link}\">Участвувати</a>\n"
        
        message += "\n"
    
    if not page_promos:
        message += "📭 <i>Немає активних аірдропів</i>\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


def format_candybomb_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category_icon: str = "🍬",
    category_name: str = "Кендибомби"
) -> str:
    """Форматує сторінку кендибомбів"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{category_icon} <b>{category_name.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        exchange = promo.get('exchange', 'N/A')
        award_token = promo.get('award_token', '')
        
        title_display = f"{exchange} | {award_token}" if award_token else f"{exchange}"
        
        # Пул
        total_pool = promo.get('total_prize_pool')
        total_pool_usd = promo.get('total_prize_pool_usd', 0) or 0
        
        # Нагорода на переможця
        participants = promo.get('participants_count') or promo.get('participants', 0) or 0
        winners = promo.get('winners_count') or promo.get('winners', 0) or 0
        
        reward_per_winner = None
        reward_per_winner_usd = None
        
        if participants > 0 and total_pool:
            try:
                pool_value = float(str(total_pool).replace(',', ''))
                reward_per_winner = pool_value / participants
                if total_pool_usd > 0:
                    reward_per_winner_usd = total_pool_usd / participants
            except:
                pass
        
        # Шанс
        win_chance = 0
        if winners and participants:
            win_chance = min((winners / participants) * 100, 100)
        
        # Час
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            remaining_str = time_data.get('remaining_str', '')
        else:
            remaining_str = str(time_data) if time_data else ''
        
        link = promo.get('link', '')
        
        # Формуємо картку
        message += f"{number} <b>{title_display}</b>\n"
        
        # 🎁 Пул
        if total_pool:
            if total_pool_usd > 0:
                message += f"   🎁 Пул: {total_pool} {award_token} (~${total_pool_usd:,.0f})\n"
            else:
                message += f"   🎁 Пул: {total_pool} {award_token}\n"
        
        # 🎯 На переможця
        if reward_per_winner:
            if reward_per_winner_usd:
                message += f"   🎯 На переможця: ~{reward_per_winner:,.0f} {award_token} (~${reward_per_winner_usd:,.2f})\n"
            else:
                message += f"   🎯 На переможця: ~{reward_per_winner:,.0f} {award_token}\n"
        
        # 🎲 Шанс
        if win_chance > 0:
            message += f"   🎲 Шанс: {win_chance:.1f}% ({winners:,} місць з {participants:,})\n"
        elif participants:
            message += f"   👥 Учасників: {participants:,}\n"
        
        # ⏰ Час
        if remaining_str:
            message += f"   ⏰ {remaining_str}\n"
        
        # 🔗 Посилання
        if link:
            message += f"   🔗 <a href=\"{link}\">Участвувати</a>\n"
        
        message += "\n"
    
    if not page_promos:
        message += "📭 <i>Немає активних кендибомбів</i>\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


def format_launchpad_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category_icon: str = "🚀",
    category_name: str = "Лаунчпади"
) -> str:
    """Форматує сторінку лаунчпадів"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{category_icon} <b>{category_name.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        exchange = promo.get('exchange', 'N/A')
        award_token = promo.get('award_token', '')
        title = promo.get('title', '')
        
        title_display = f"{exchange} | {award_token}" if award_token else f"{exchange} | {title[:20]}"
        
        # Дані з raw_data
        taking_price = promo.get('taking_price', 0)
        market_price = promo.get('market_price', 0)
        max_allocation = promo.get('max_allocation', 0)
        expected_reward = promo.get('expected_reward', 0)
        profit_display = promo.get('profit_display')
        
        # Час
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            remaining_str = time_data.get('remaining_str', '')
        else:
            remaining_str = str(time_data) if time_data else ''
        
        link = promo.get('link', '')
        
        # Формуємо картку
        message += f"{number} <b>{title_display}</b>\n"
        
        # 💵 Ціна
        if taking_price:
            if market_price:
                price_change = ((market_price - taking_price) / taking_price) * 100 if taking_price > 0 else 0
                sign = "+" if price_change > 0 else ""
                message += f"   💵 Ціна: ${taking_price:.4f} за токен\n"
                message += f"   📈 Ринкова: ${market_price:.4f} ({sign}{price_change:.1f}%)\n"
            else:
                message += f"   💵 Ціна: ${taking_price:.4f} за токен\n"
        
        # 📊 Аллокація
        if max_allocation:
            message += f"   📊 Аллокація: до {max_allocation:,.0f} USDT\n"
        
        # 💰 Потенційний профіт
        if expected_reward > 0:
            message += f"   💰 Потенц. профіт: {profit_display or f'~${expected_reward:,.2f}'}\n"
        
        # ⏰ Час
        if remaining_str:
            message += f"   ⏰ {remaining_str}\n"
        
        # 🔗 Посилання
        if link:
            message += f"   🔗 <a href=\"{link}\">Участвувати</a>\n"
        
        message += "\n"
    
    if not page_promos:
        message += "📭 <i>Немає активних лаунчпадів</i>\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


def format_launchpool_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category_icon: str = "🌊",
    category_name: str = "Лаунчпули"
) -> str:
    """Форматує сторінку лаунчпулів"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{category_icon} <b>{category_name.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        exchange = promo.get('exchange', 'N/A')
        award_token = promo.get('award_token', '')
        title = promo.get('title', '')
        
        title_display = f"{exchange} | {award_token}" if award_token else f"{exchange} | {title[:20]}"
        
        # Дані з raw_data
        raw_data = promo.get('raw_data', {})
        pools = raw_data.get('pools', []) if raw_data else []
        max_apr = promo.get('max_apr', 0)
        days_left = promo.get('days_left', 0)
        earnings_display = promo.get('earnings_display')
        expected_reward = promo.get('expected_reward', 0)
        total_participants = promo.get('participants_count', 0)
        
        # Формуємо список пулів
        pools_str = ""
        if pools:
            pool_parts = []
            for pool in pools[:3]:  # Максимум 3 пули
                stake_coin = pool.get('stake_coin', '')
                apr = pool.get('apr', 0)
                if stake_coin and apr:
                    pool_parts.append(f"{stake_coin} ({apr:.0f}%)")
            pools_str = ", ".join(pool_parts)
        
        # Час
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            remaining_str = time_data.get('remaining_str', '')
        else:
            remaining_str = str(time_data) if time_data else ''
        
        link = promo.get('link', '')
        
        # Формуємо картку
        message += f"{number} <b>{title_display}</b>\n"
        
        # 🪙 Стейк пули
        if pools_str:
            message += f"   🪙 Стейк: {pools_str}\n"
        elif max_apr:
            message += f"   📈 APR: {max_apr:.0f}%\n"
        
        # 🎁 Пул нагород
        total_pool = promo.get('total_prize_pool')
        if total_pool:
            message += f"   🎁 Пул нагород: {total_pool} {award_token}\n"
        
        # 💰 Заробіток
        if expected_reward > 0:
            message += f"   💰 Заробіток: {earnings_display or f'~${expected_reward:,.2f}'}\n"
        elif earnings_display:
            message += f"   💰 Заробіток: {earnings_display}\n"
        
        # 👥 Учасники
        if total_participants:
            message += f"   👥 Учасників: {total_participants:,}\n"
        
        # ⏰ Час
        if remaining_str:
            message += f"   ⏰ Фармінг: {remaining_str}\n"
        elif days_left:
            message += f"   ⏰ Фармінг: {days_left}д залишилось\n"
        
        # 🔗 Посилання
        if link:
            message += f"   🔗 <a href=\"{link}\">Участвувати</a>\n"
        
        message += "\n"
    
    if not page_promos:
        message += "📭 <i>Немає активних лаунчпулів</i>\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message


def format_other_page(
    promos: list, 
    page: int, 
    total_pages: int, 
    items_per_page: int,
    category_icon: str = "🗂️",
    category_name: str = "Інші"
) -> str:
    """Форматує сторінку інших промоакцій"""
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    
    message = (
        f"📊 <b>ТОП АКТИВНОСТІ</b> | {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{category_icon} <b>{category_name.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_promos = promos[start_idx:end_idx]
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, promo in enumerate(page_promos):
        global_idx = start_idx + idx
        number = number_emojis[global_idx] if global_idx < 10 else f"{global_idx + 1}."
        
        exchange = promo.get('exchange', 'N/A')
        award_token = promo.get('award_token', '')
        title = promo.get('title', 'N/A')
        promo_type = promo.get('promo_type', '')
        
        title_display = f"{exchange} | {title[:30]}"
        
        # Нагорода
        expected_reward = promo.get('expected_reward', 0)
        reward_display = promo.get('reward_display') or promo.get('reward_per_user_display')
        
        # Час
        time_data = promo.get('time_remaining', {})
        if isinstance(time_data, dict):
            remaining_str = time_data.get('remaining_str', '')
        else:
            remaining_str = str(time_data) if time_data else ''
        
        link = promo.get('link', '')
        
        # Формуємо картку
        message += f"{number} <b>{title_display}</b>\n"
        
        # 📌 Тип
        if promo_type and promo_type != 'other':
            message += f"   📌 Тип: {promo_type.replace('_', ' ').title()}\n"
        
        # 💰 Нагорода
        if expected_reward > 0:
            message += f"   💰 Нагорода: ~${expected_reward:,.2f}\n"
        elif reward_display:
            message += f"   💰 Нагорода: {reward_display}\n"
        
        # ⏰ Час
        if remaining_str:
            message += f"   ⏰ {remaining_str}\n"
        
        # 🔗 Посилання
        if link:
            message += f"   🔗 <a href=\"{link}\">Участвувати</a>\n"
        
        message += "\n"
    
    if not page_promos:
        message += "📭 <i>Немає інших промоакцій</i>\n\n"
    
    message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📄 {page}/{total_pages}"
    
    return message
