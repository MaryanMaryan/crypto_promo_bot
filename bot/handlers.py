from aiogram import Router, F

# Константы для навигации
NAV_MANAGEMENT = "NAV_MANAGEMENT"
NAV_DELETE = "NAV_DELETE"
NAV_INTERVAL = "NAV_INTERVAL"
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from data.database import get_db_session, atomic_operation
from data.models import ApiLink
from bot.parser_service import ParserService
from bot.notification_service import NotificationService
from bot.bot_manager import bot_manager
import logging
import asyncio
from urllib.parse import urlparse
from datetime import datetime

# ИМПОРТЫ ДЛЯ НОВЫХ СИСТЕМ
from utils.proxy_manager import get_proxy_manager
from utils.user_agent_manager import get_user_agent_manager
from utils.statistics_manager import get_statistics_manager
from bot.keyboards import get_airdrop_management_keyboard, get_current_promos_keyboard
from utils.rotation_manager import get_rotation_manager
from utils.url_template_builder import URLTemplateAnalyzer, get_url_builder


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
    waiting_for_announcement_strategy = State()  # НОВОЕ: Выбор стратегии парсинга анонсов
    waiting_for_announcement_keywords = State()  # НОВОЕ: Ввод ключевых слов для анонсов
    waiting_for_announcement_regex = State()  # НОВОЕ: Ввод regex для анонсов
    waiting_for_announcement_selector = State()  # НОВОЕ: Ввод CSS селектора для анонсов
    # Специальный парсер:
    waiting_for_special_parser = State()  # НОВОЕ: Выбор специального парсера

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

# РАСШИРЕННОЕ ГЛАВНОЕ МЕНЮ
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Список ссылок"))
    builder.add(KeyboardButton(text="➕ Добавить ссылку"))
    builder.add(KeyboardButton(text="⚙️ Управление ссылками"))
    builder.add(KeyboardButton(text="🔄 Проверить всё"))
    builder.add(KeyboardButton(text="🛡️ Обход блокировок"))

    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

# СУЩЕСТВУЮЩИЕ КЛАВИАТУРЫ
def get_management_keyboard(link=None):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data="manage_delete"))
    builder.add(InlineKeyboardButton(text="⏰ Изменить интервал", callback_data="manage_interval"))
    builder.add(InlineKeyboardButton(text="✏️ Переименовать ссылку", callback_data="manage_rename"))
    builder.add(InlineKeyboardButton(text="🎯 Настроить парсинг", callback_data="manage_configure_parsing"))

    # НОВОЕ: Кнопка смены Telegram аккаунта (только для telegram ссылок)
    if link and link.parsing_type == 'telegram':
        builder.add(InlineKeyboardButton(text="📱 Сменить Telegram аккаунт", callback_data="manage_change_tg_account"))

    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_link_list"))
    builder.adjust(1)
    return builder.as_markup()

def get_category_management_menu():
    """Подменю выбора категории для управления ссылками"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Все ссылки", callback_data="category_all"))
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data="category_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main_menu"))
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()

def get_staking_management_keyboard():
    """Меню управления для ссылок категории 'staking' с дополнительной кнопкой"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data="manage_delete"))
    builder.add(InlineKeyboardButton(text="⏰ Изменить интервал", callback_data="manage_interval"))
    builder.add(InlineKeyboardButton(text="✏️ Переименовать ссылку", callback_data="manage_rename"))
    builder.add(InlineKeyboardButton(text="🎯 Настроить парсинг", callback_data="manage_configure_parsing"))
    builder.add(InlineKeyboardButton(text="📈 Текущие стейкинги", callback_data="manage_view_current_stakings"))
    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_link_list"))
    builder.adjust(1)
    return builder.as_markup()

def get_current_stakings_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Клавиатура навигации для текущих стейкингов"""
    builder = InlineKeyboardBuilder()

    # Кнопки навигации
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="stakings_page_prev"))
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data="stakings_page_next"))

    if nav_buttons:
        builder.row(*nav_buttons)

    # Управление
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="stakings_refresh"),
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

    builder.add(InlineKeyboardButton(
        text="⏱️ Изменить время стабилизации",
        callback_data="notification_settings_change_stability"
    ))
    builder.add(InlineKeyboardButton(
        text="📊 Изменить порог изменения APR",
        callback_data="notification_settings_change_apr_threshold"
    ))
    builder.add(InlineKeyboardButton(
        text="🔔 Новые стейкинги (вкл/выкл)",
        callback_data="notification_toggle_new_stakings"
    ))
    builder.add(InlineKeyboardButton(
        text="📈 Изменения APR (вкл/выкл)",
        callback_data="notification_toggle_apr_changes"
    ))
    builder.add(InlineKeyboardButton(
        text="⚡ Fixed сразу (вкл/выкл)",
        callback_data="notification_toggle_fixed_immediately"
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Combined как Fixed (вкл/выкл)",
        callback_data="notification_toggle_combined_as_fixed"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 Только стабильные Flexible (вкл/выкл)",
        callback_data="notification_toggle_only_stable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Назад",
        callback_data="manage_view_current_stakings"
    ))

    builder.adjust(1)  # По одной кнопке в ряд
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
        'airdrop': '🪂',
        'staking': '💰',
        'launchpool': '🚀',
        'announcement': '📢',
        'general': '📁'
    }

    for link in links:
        status_icon = "✅" if link.is_active else "❌"

        # Добавляем иконку типа парсинга, если поле существует
        parsing_icon = ""
        if hasattr(link, 'parsing_type'):
            parsing_type = link.parsing_type or 'combined'
            parsing_icon = parsing_icons.get(parsing_type, '🔄') + " "

        # Добавляем иконку категории, если поле существует
        category_icon = ""
        if hasattr(link, 'category'):
            category = link.category or 'general'
            category_icon = category_icons.get(category, '📁') + " "

        builder.add(InlineKeyboardButton(
            text=f"{status_icon} {category_icon}{parsing_icon}{link.name} ({link.check_interval}с)",
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
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(2)
    return builder.as_markup()

def get_confirmation_keyboard(link_id, action_type="delete"):
    builder = InlineKeyboardBuilder()
    if action_type == "delete":
        builder.add(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{link_id}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
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

    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_configure_parsing"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(1)
    return builder.as_markup()

def get_category_edit_keyboard(link_id):
    """Клавиатура для выбора категории при редактировании ссылки"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data=f"set_category_{link_id}_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data=f"set_category_{link_id}_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data=f"set_category_{link_id}_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data=f"set_category_{link_id}_announcement"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"show_parsing_config_{link_id}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

def get_parsing_type_keyboard(link_id):
    """Клавиатура для выбора типа парсинга"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Комбинированный (API + HTML + Browser)", callback_data=f"set_parsing_type_{link_id}_combined"))
    builder.add(InlineKeyboardButton(text="📡 Только API", callback_data=f"set_parsing_type_{link_id}_api"))
    builder.add(InlineKeyboardButton(text="🌐 Только HTML", callback_data=f"set_parsing_type_{link_id}_html"))
    builder.add(InlineKeyboardButton(text="🌐 Только Browser", callback_data=f"set_parsing_type_{link_id}_browser"))
    builder.add(InlineKeyboardButton(text="📱 Telegram", callback_data=f"set_parsing_type_{link_id}_telegram"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"show_parsing_config_{link_id}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
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
    }
}

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

    menu = get_main_menu()
    await message.answer(
        "🤖 Добро пожаловать в Crypto Promo Bot!\n\n"
        "Я помогу отслеживать промоакции криптобирж.\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=menu
    )

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
        "• 📋 История промоакций - история\n\n"
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
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                await message.answer("📊 У вас пока нет добавленных ссылок")
                return
            
            response = "📊 Ваши API ссылки:\n\n"
            for link in links:
                status = "✅ Активна" if link.is_active else "❌ Остановлена"
                interval_minutes = link.check_interval // 60

                # Определяем отображение категории
                category = link.category or 'general'
                category_icons = {
                    'airdrop': '🪂 Аирдроп',
                    'staking': '💰 Стейкинг',
                    'launchpool': '🚀 Лаунчпул',
                    'announcement': '📢 Анонс',
                    'general': '📁 Общее'
                }
                category_display = category_icons.get(category, '📁 Общее')

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
                response += f"Интервал: {interval_minutes} мин\n"

                # НОВОЕ: Отображение Telegram аккаунта
                if link.parsing_type == 'telegram' and link.telegram_account:
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
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data="add_category_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 1)

    await message.answer(
        "🔗 <b>Добавление новой ссылки</b>\n\n"
        "🗂️ <b>Шаг 1:</b> Выберите категорию ссылки:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_category)

@router.callback_query(F.data.startswith("add_category_"), StateFilter(AddLinkStates.waiting_for_category))
async def handle_category_choice(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории при добавлении ссылки"""
    category = callback.data.replace("add_category_", "")

    # Сохраняем категорию в state
    await state.update_data(category=category)

    category_names = {
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'launchpool': 'Лаунчпул',
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
        category = data.get('category', 'general')

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

    # Создаем кнопки для выбора
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить HTML ссылку", callback_data="add_html_url"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)

    await message.answer(
        f"✅ API ссылка сохранена!\n\n"
        f"🌐 <b>Шаг 4/5:</b> Добавить HTML ссылку?\n\n"
        f"HTML ссылка используется как резервный метод парсинга, если API не сработает.\n\n"
        f"Выберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ОБРАБОТЧИКИ ДЛЯ ДОБАВЛЕНИЯ HTML ССЫЛКИ

@router.callback_query(F.data == "add_html_url")
async def add_html_url(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Добавить HTML ссылку'"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_url"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)

    await callback.message.edit_text(
        "🌐 <b>Введите HTML ссылку:</b>\n\n"
        "Пример:\n"
        "<code>https://www.bybit.com/en/trade/spot/token-splash</code>\n\n"
        "HTML используется как резервный метод парсинга.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_url)
    await callback.answer()

@router.callback_query(F.data == "skip_html_url")
async def skip_html_url(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Пропустить' HTML"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'general')

    # Создаем кнопки для выбора: добавить пример или пропустить
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить пример ссылки", callback_data="add_example_url"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_example_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить добавление", callback_data="cancel_add_link"))
    builder.adjust(1)

    # Разный текст для стейкинга и остальных категорий
    if category == 'staking':
        message_text = (
            f"⏭️ HTML ссылка пропущена\n\n"
            f"🔗 <b>Шаг 4/5: Добавить ссылку на страницу стейкинга?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите ссылку на страницу стейкинга, бот сможет автоматически мониторить новые стейкинг предложения.\n\n"
            f"<b>Примеры:</b>\n"
            f"• KuCoin Earn: <code>https://www.kucoin.com/ru/earn</code>\n"
            f"• Bybit Earn: <code>https://www.bybit.com/en/earn/home</code>\n\n"
            f"Это опционально, но очень полезно!"
        )
    else:
        message_text = (
            f"⏭️ HTML ссылка пропущена\n\n"
            f"🔗 <b>Шаг 4/5: Добавить пример ссылки на промоакцию?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите пример ссылки на промоакцию, бот автоматически научится генерировать правильные ссылки для всех будущих промоакций этой биржи.\n\n"
            f"<b>Пример:</b>\n"
            f"<code>https://www.mexc.com/ru-RU/launchpad/monad/6912adb5e4b0e60c0ec02d2c</code>\n\n"
            f"Это опционально, но очень полезно!"
        )

    await callback.message.edit_text(
        message_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    # ИСПРАВЛЕНИЕ: устанавливаем состояние, чтобы принимать текстовый ввод
    await state.set_state(AddLinkStates.waiting_for_example_url)
    await callback.answer()

@router.message(AddLinkStates.waiting_for_html_url)
async def process_html_url_input(message: Message, state: FSMContext):
    """Обработка ввода HTML ссылки"""
    html_url = message.text.strip()

    if not html_url.startswith(('http://', 'https://')):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    # Сохраняем HTML URL
    await state.update_data(html_url=html_url)

    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'general')

    # Создаем кнопки для выбора: добавить пример или пропустить
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить пример ссылки", callback_data="add_example_url"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_example_url"))
    builder.adjust(1)

    # Разный текст для стейкинга и остальных категорий
    if category == 'staking':
        message_text = (
            f"✅ HTML ссылка сохранена!\n\n"
            f"🔗 <b>Шаг 4/5: Добавить ссылку на страницу стейкинга?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите ссылку на страницу стейкинга, бот сможет автоматически мониторить новые стейкинг предложения.\n\n"
            f"<b>Примеры:</b>\n"
            f"• KuCoin Earn: <code>https://www.kucoin.com/ru/earn</code>\n"
            f"• Bybit Earn: <code>https://www.bybit.com/en/earn/home</code>\n\n"
            f"Это опционально, но очень полезно!"
        )
    else:
        message_text = (
            f"✅ HTML ссылка сохранена!\n\n"
            f"🔗 <b>Шаг 4/5: Добавить пример ссылки на промоакцию?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите пример ссылки на промоакцию, бот автоматически научится генерировать правильные ссылки для всех будущих промоакций этой биржи.\n\n"
            f"<b>Пример:</b>\n"
            f"<code>https://www.mexc.com/ru-RU/launchpad/monad/6912adb5e4b0e60c0ec02d2c</code>\n\n"
            f"Это опционально, но очень полезно!"
        )

    await message.answer(
        message_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

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
# НОВЫЕ ОБРАБОТЧИКИ ДЛЯ ПРИМЕРА ССЫЛКИ
# =============================================================================

@router.callback_query(F.data == "add_example_url")
async def add_example_url(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Добавить пример ссылки'"""
    data = await state.get_data()
    category = data.get('category', 'general')

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_example_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(1)

    # Разный текст для стейкинга и остальных категорий
    if category == 'staking':
        message_text = (
            "🔗 <b>Введите ссылку на страницу стейкинга:</b>\n\n"
            "Примеры:\n"
            "• KuCoin Earn:\n"
            "<code>https://www.kucoin.com/ru/earn</code>\n\n"
            "• Bybit Earn:\n"
            "<code>https://www.bybit.com/en/earn/home</code>\n\n"
            "Бот будет мониторить эту страницу на новые стейкинг предложения."
        )
    else:
        message_text = (
            "🔗 <b>Введите пример ссылки на промоакцию:</b>\n\n"
            "Примеры:\n"
            "• MEXC Launchpad:\n"
            "<code>https://www.mexc.com/ru-RU/launchpad/monad/6912adb5e4b0e60c0ec02d2c</code>\n\n"
            "• Bybit Token Splash:\n"
            "<code>https://www.bybit.com/en/trade/spot/token-splash/detail?code=20251201080514</code>\n\n"
            "Бот автоматически проанализирует ссылку и создаст шаблон для генерации ссылок."
        )

    await callback.message.edit_text(
        message_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_example_url)
    await callback.answer()

@router.callback_query(F.data == "skip_example_url")
async def skip_example_url(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Пропустить' пример ссылки"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    html_url = data.get('html_url')
    api_url = data.get('api_url')
    
    # Проверяем, есть ли специальные парсеры для этого URL
    url_to_check = html_url or api_url or ''
    available_parsers = detect_special_parser_for_url(url_to_check)
    
    if available_parsers:
        # Есть специальные парсеры - предлагаем выбор
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⚙️ Стандартный парсер", callback_data="special_parser_none"))
        
        for parser_id in available_parsers:
            if parser_id in SPECIAL_PARSERS_CONFIG:
                config = SPECIAL_PARSERS_CONFIG[parser_id]
                btn_text = f"{config['emoji']} {config['name']}"
                builder.add(InlineKeyboardButton(text=btn_text, callback_data=f"special_parser_{parser_id}"))
        
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_html_url"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
        builder.adjust(1)
        
        # Формируем описание парсеров
        parser_descriptions = []
        for parser_id in available_parsers:
            if parser_id in SPECIAL_PARSERS_CONFIG:
                config = SPECIAL_PARSERS_CONFIG[parser_id]
                parser_descriptions.append(f"{config['emoji']} <b>{config['name']}</b> - {config['description']}")
        
        await callback.message.edit_text(
            f"🔧 <b>Выбор метода парсинга</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Для этого URL доступны специальные парсеры:\n\n"
            + "\n".join(parser_descriptions) + "\n\n"
            f"⚙️ <b>Стандартный парсер</b> - обычный метод парсинга\n\n"
            f"<i>Специальные парсеры используют продвинутые методы (перехват API, Playwright) "
            f"для более надежного получения данных.</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_special_parser)
        await callback.answer()
        return

    # Нет специальных парсеров - переходим к интервалу
    await _show_interval_selection(callback, state, custom_name)

# =============================================================================
# ОБРАБОТЧИКИ "НАЗАД" ДЛЯ ДОБАВЛЕНИЯ ССЫЛКИ
# =============================================================================

@router.callback_query(F.data == "back_to_category")
async def back_to_category(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору категории"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data="add_category_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 1)

    await callback.message.edit_text(
        "🔗 <b>Добавление новой ссылки</b>\n\n"
        "🗂️ <b>Шаг 1:</b> Выберите категорию ссылки:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_category)
    await callback.answer()


async def _show_interval_selection(callback: CallbackQuery, state: FSMContext, custom_name: str):
    """Вспомогательная функция для показа выбора интервала"""
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]

    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_html_url"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 2, 2, 1, 2)

    await callback.message.edit_text(
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()


@router.callback_query(F.data.startswith("special_parser_"))
async def process_special_parser_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора специального парсера"""
    parser_id = callback.data.replace("special_parser_", "")
    
    data = await state.get_data()
    custom_name = data.get('custom_name')
    
    if parser_id == "none":
        # Стандартный парсер
        await state.update_data(special_parser=None)
        logger.info(f"📋 Выбран стандартный парсер для '{custom_name}'")
    else:
        # Специальный парсер
        await state.update_data(special_parser=parser_id)
        parser_name = SPECIAL_PARSERS_CONFIG.get(parser_id, {}).get('name', parser_id)
        logger.info(f"🔧 Выбран специальный парсер '{parser_name}' для '{custom_name}'")
    
    # Переходим к выбору интервала
    await _show_interval_selection(callback, state, custom_name)


@router.callback_query(F.data == "back_to_name")
async def back_to_name(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу названия биржи"""
    data = await state.get_data()
    category = data.get('category', 'general')

    category_names = {
        'airdrop': 'Аирдроп',
        'staking': 'Стейкинг',
        'launchpool': 'Лаунчпул',
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
    """Возврат к шагу добавления/пропуска HTML ссылки"""
    data = await state.get_data()
    custom_name = data.get('custom_name')
    category = data.get('category', 'general')
    api_url = data.get('api_url')
    parsing_type = data.get('parsing_type', 'combined')

    # Создаем кнопки для выбора: добавить пример или пропустить
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить пример ссылки", callback_data="add_example_url"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_example_url"))

    # Кнопка "Назад" зависит от наличия API URL
    if api_url:
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="add_html_url"))
    else:
        builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_parsing_type"))

    builder.add(InlineKeyboardButton(text="❌ Отменить добавление", callback_data="cancel_add_link"))
    builder.adjust(1)

    # Разный текст для стейкинга и остальных категорий
    if category == 'staking':
        message_text = (
            f"🔗 <b>Шаг 4/5: Добавить ссылку на страницу стейкинга?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите ссылку на страницу стейкинга, бот сможет автоматически мониторить новые стейкинг предложения.\n\n"
            f"<b>Примеры:</b>\n"
            f"• KuCoin Earn: <code>https://www.kucoin.com/ru/earn</code>\n"
            f"• Bybit Earn: <code>https://www.bybit.com/en/earn/home</code>\n\n"
            f"Это опционально, но очень полезно!"
        )
    else:
        message_text = (
            f"🔗 <b>Шаг 4/5: Добавить пример ссылки на промоакцию?</b>\n\n"
            f"<b>Имя:</b> {custom_name}\n\n"
            f"Если вы предоставите пример ссылки на промоакцию, бот автоматически научится генерировать правильные ссылки для всех будущих промоакций этой биржи.\n\n"
            f"<b>Пример:</b>\n"
            f"<code>https://www.mexc.com/ru-RU/launchpad/monad/6912adb5e4b0e60c0ec02d2c</code>\n\n"
            f"Это опционально, но очень полезно!"
        )

    await callback.message.edit_text(
        message_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
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
        category = data.get('category', 'general')
        page_url = data.get('page_url')
        min_apr = data.get('min_apr')
        statuses_filter = data.get('statuses_filter')

        # ПОЛЯ ДЛЯ TELEGRAM:
        telegram_channel = data.get('telegram_channel')
        telegram_keywords = data.get('telegram_keywords', [])
        telegram_account_id = data.get('telegram_account_id')  # НОВОЕ: ID выбранного аккаунта

        # ПОЛЯ ДЛЯ АНОНСОВ:
        announcement_strategy = data.get('announcement_strategy')
        announcement_keywords = data.get('announcement_keywords', [])
        announcement_regex = data.get('announcement_regex')
        announcement_css_selector = data.get('announcement_css_selector')
        
        # СПЕЦИАЛЬНЫЙ ПАРСЕР:
        special_parser = data.get('special_parser')

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
                # ПОЛЯ ДЛЯ TELEGRAM:
                telegram_channel=telegram_channel,
                telegram_account_id=telegram_account_id,  # НОВОЕ: Назначаем аккаунт
                # ПОЛЯ ДЛЯ АНОНСОВ:
                announcement_strategy=announcement_strategy,
                announcement_regex=announcement_regex,
                announcement_css_selector=announcement_css_selector,
                # СПЕЦИАЛЬНЫЙ ПАРСЕР:
                special_parser=special_parser
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
            'airdrop': 'Аирдроп',
            'staking': 'Стейкинг',
            'launchpool': 'Лаунчпул',
            'announcement': 'Анонс',
            'general': 'Общее'
        }
        category_display = category_names.get(category, category)

        # Формируем детальное сообщение
        message_parts = [
            "✅ <b>Ссылка успешно добавлена!</b>\n\n",
            f"<b>Имя:</b> {custom_name}\n",
            f"<b>Категория:</b> {category_display}\n",
            f"<b>Тип парсинга:</b> {parsing_type_display}\n",
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

        if min_apr:
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

        # Сохраняем категорию в navigation_stack
        current_nav = get_current_navigation(user_id)
        if current_nav:
            current_nav["data"]["category"] = category

        # Словарь названий категорий
        category_names = {
            'airdrop': 'Аирдроп',
            'staking': 'Стейкинг',
            'launchpool': 'Лаунчпул',
            'announcement': 'Анонс',
            'all': 'Все ссылки'
        }
        category_display = category_names.get(category, category)

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
                        [InlineKeyboardButton(text="❌ Назад", callback_data="back_to_categories")]
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
                    'category': link.category or 'general'
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

        # Выбираем правильную клавиатуру в зависимости от категории
        if link.category == 'staking':
            keyboard = get_staking_management_keyboard()
        elif link.category == 'airdrop':
            keyboard = get_airdrop_management_keyboard()
        else:
            keyboard = get_management_keyboard(link=link)  # Передаем link для условной кнопки

        # Информация о ссылке
        status_text = "✅ Активна" if link.is_active else "❌ Остановлена"
        parsing_type_text = {
            'api': 'API',
            'html': 'HTML',
            'browser': 'Browser',
            'combined': 'Комбинированный',
            'telegram': 'Telegram'
        }.get(link.parsing_type, 'Комбинированный')

        # НОВОЕ: Информация о Telegram аккаунте
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
                    telegram_info += f"<b>🔗 Канал:</b> {link.telegram_channel}\n"
            else:
                telegram_info = "<b>📱 Telegram аккаунт:</b> ⚠️ Не назначен\n"

        await callback.message.edit_text(
            f"⚙️ <b>Управление ссылкой:</b> {link.name}\n\n"
            f"<b>Статус:</b> {status_text}\n"
            f"<b>Категория:</b> {link.category or 'general'}\n"
            f"<b>Интервал:</b> {link.check_interval}с ({link.check_interval // 60} мин)\n"
            f"<b>Тип парсинга:</b> {parsing_type_text}\n"
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

                if link.category != 'staking':
                    await callback.message.edit_text("❌ Эта функция доступна только для ссылок категории 'Стейкинг'")
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
                # ИСКЛЮЧАЕМ: полностью заполненные пулы и со статусом "Sold Out"
                pools_with_fill = [
                    s for s in stakings
                    if s.get('fill_percentage') is not None
                    and s.get('apr', 0) >= 100
                    and s.get('fill_percentage', 0) < 100  # Не полностью заполненные
                    and s.get('status') != 'Sold Out'  # Не проданные
                ]

                if not pools_with_fill:
                    # Проверяем, есть ли вообще пулы с заполненностью (без учета APR и фильтров)
                    pools_all = [s for s in stakings if s.get('fill_percentage') is not None]
                    if pools_all:
                        # Проверяем причину отсутствия доступных пулов
                        pools_sold_out = [s for s in pools_all if s.get('status') == 'Sold Out' or s.get('fill_percentage', 0) >= 100]
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
                    total_sold_out = len([s for s in stakings if s.get('status') == 'Sold Out' or s.get('fill_percentage', 0) >= 100])
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
    """Показать текущие стейкинги (страница 1)"""
    logger.info(f"📋 ОТКРЫТИЕ ТЕКУЩИХ СТЕЙКИНГОВ")
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        logger.info(f"   User ID: {user_id}, Link ID: {link_id}")

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        # Получить данные ссылки
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            if link.category != 'staking':
                await callback.answer("❌ Эта функция доступна только для стейкинг-ссылок", show_alert=True)
                return

            exchange_name = link.name
            min_apr = link.min_apr
            page_url = link.page_url
            api_url = link.api_url or link.url

        # Нормализуем exchange для правильного поиска в БД
        from utils.exchange_detector import detect_exchange_from_url
        exchange_filter = detect_exchange_from_url(api_url) if api_url else (link.exchange or link.name)

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
                'is_okx_flash': True
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
                'is_okx_flash': False
            }

        logger.info(f"   💾 Состояние сохранено: page={page}, link_id={link_id}, total_pages={total_pages}")
        logger.info(f"   🔑 Текущее состояние в памяти: {current_stakings_state}")
        logger.info(f"   📱 Всего стейкингов: {len(stakings_with_deltas)}, на странице: {len(page_stakings)}")

        # Форматировать сообщение
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot)

        # Для OKX Flash Earn используем специальный формат с группировкой по проектам
        if is_okx_flash:
            message_text = notif_service.format_okx_flash_earn_page(
                stakings_with_deltas=page_stakings,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
            )
        else:
            message_text = notif_service.format_current_stakings_page(
                stakings_with_deltas=page_stakings,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                min_apr=min_apr,
                page_url=page_url
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

        # Форматировать сообщение
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot)

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

@router.callback_query(F.data == "stakings_refresh")
async def refresh_current_stakings(callback: CallbackQuery):
    """Обновить данные текущих стейкингов"""
    logger.info("="*80)
    logger.info("🔔 CALLBACK ВЫЗВАН: stakings_refresh")
    logger.info("="*80)
    try:
        user_id = callback.from_user.id
        logger.info(f"👤 User ID: {user_id}")

        state = current_stakings_state.get(user_id)
        if not state:
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

        # ПРИНУДИТЕЛЬНО запускаем парсер в фоне (НЕ блокируем callback)
        from bot.parser_service import ParserService
        from utils.exchange_detector import detect_exchange_from_url
        import asyncio

        # Автоопределение биржи если не указана
        if not exchange or exchange in ['Unknown', 'None', '', 'null']:
            exchange = detect_exchange_from_url(api_url)
            logger.info(f"🔍 Автоопределение биржи: {exchange}")

        # Используем exchange для поиска стейкингов (не link.name!)
        exchange_filter = exchange or exchange_name

        # Закрываем callback
        await callback.answer()

        # Отправляем сообщение о начале обновления
        status_msg = await callback.message.answer(
            f"⏳ <b>Обновление данных {exchange_name}...</b>\n"
            f"📊 Запуск парсера стейкинг-продуктов",
            parse_mode="HTML"
        )

        # Запускаем парсер и ЖДЕМ его завершения
        parser_service = ParserService()
        loop = asyncio.get_event_loop()

        try:
            logger.info(f"{'='*60}")
            logger.info(f"🔄 ОБНОВЛЕНИЕ СТЕЙКИНГОВ: {exchange_name}")
            logger.info(f"   link_id={link_id}")
            logger.info(f"   api_url={api_url}")
            logger.info(f"   exchange={exchange}")
            logger.info(f"{'='*60}")

            # СИНХРОННО выполняем парсинг (ждем результата)
            new_stakings = await loop.run_in_executor(
                None,
                parser_service.parse_staking_link,
                link_id,
                api_url,
                exchange,
                page_url
            )

            logger.info(f"✅ ПАРСЕР ЗАВЕРШИЛ РАБОТУ")
            logger.info(f"   Получено новых записей: {len(new_stakings) if new_stakings else 0}")
            logger.info(f"{'='*60}")

            # Удаляем сообщение о статусе
            await status_msg.delete()

        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при обновлении {exchange_name}: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Ошибка при обновлении {exchange_name}</b>\n"
                f"Показываю данные из кэша",
                parse_mode="HTML"
            )
            await asyncio.sleep(2)
            await status_msg.delete()

        # Получить стейкинги с дельтами (ПОСЛЕ парсинга)
        from services.staking_snapshot_service import StakingSnapshotService
        snapshot_service = StakingSnapshotService()

        stakings_with_deltas = snapshot_service.get_stakings_with_deltas(
            exchange=exchange_filter,  # Используем правильное название биржи
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
            per_page = 2  # 2 проекта на страницу
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

        # Форматировать сообщение
        from bot.notification_service import NotificationService
        notif_service = NotificationService(bot=callback.bot)

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

        # Отправляем НОВОЕ сообщение с обновленными данными
        keyboard = get_current_stakings_keyboard(current_page, total_pages)

        await callback.message.answer(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"❌ Ошибка обновления: {e}", exc_info=True)
        await callback.answer("❌ Ошибка обновления", show_alert=True)


# =============================================================================
# ОБРАБОТЧИКИ ТЕКУЩИХ ПРОМОАКЦИЙ (AIRDROP)
# =============================================================================

@router.callback_query(F.data == "manage_view_current_promos")
async def view_current_promos(callback: CallbackQuery):
    """Показать текущие промоакции (свежие данные из API)"""
    logger.info(f"📋 ОТКРЫТИЕ ТЕКУЩИХ ПРОМОАКЦИЙ")
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)
        logger.info(f"   User ID: {user_id}, Link ID: {link_id}")

        if not link_id:
            await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
            return

        # Получить данные ссылки
        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            if link.category != 'airdrop':
                await callback.answer("❌ Эта функция доступна только для airdrop-ссылок", show_alert=True)
                return

            exchange_name = link.name
            page_url = link.page_url
            api_url = link.api_url or link.url
            html_url = link.html_url
            parsing_type = link.parsing_type or 'api'

        # Закрываем callback сразу
        await callback.answer("🔄 Загрузка данных...")

        # Отправляем сообщение о загрузке
        loading_msg = await callback.message.edit_text(
            f"⏳ <b>Загрузка промоакций {exchange_name}...</b>\n\n"
            f"🌐 Получаем актуальные данные из API...",
            parse_mode="HTML"
        )

        # Получаем СВЕЖИЕ данные через парсер в зависимости от типа
        from datetime import datetime
        import asyncio
        
        api_promos = []
        try:
            # Определяем биржу из URL для выбора специального парсера
            def get_exchange_from_url(url: str) -> str:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    domain = parsed.netloc.lower()
                    parts = domain.split('.')
                    if len(parts) >= 2:
                        return parts[-2] if parts[-1] in ['com', 'io', 'org', 'net', 'ru'] else parts[-1]
                    return domain
                except:
                    return ''
            
            # Проверяем все URL для определения биржи
            check_url = html_url or api_url or page_url or ''
            exchange = get_exchange_from_url(check_url)
            logger.info(f"   🔍 Определена биржа: {exchange}")
            
            # Специальные парсеры для конкретных бирж
            if exchange == 'weex':
                from parsers.weex_parser import WeexParser
                
                def run_weex_parser():
                    parser = WeexParser(html_url or api_url)
                    return parser.get_promotions()
                
                loop = asyncio.get_event_loop()
                api_promos = await loop.run_in_executor(None, run_weex_parser)
                logger.info(f"   📊 Получено через WeexParser: {len(api_promos) if api_promos else 0} промоакций")
            elif parsing_type == 'browser':
                # Browser парсер - используем в отдельном потоке чтобы избежать конфликта с asyncio
                from parsers.browser_parser import BrowserParser
                
                def run_browser_parser():
                    parser = BrowserParser(api_url)
                    return parser.get_promotions()
                
                # Запускаем синхронный код в executor
                loop = asyncio.get_event_loop()
                api_promos = await loop.run_in_executor(None, run_browser_parser)
                logger.info(f"   📊 Получено через Browser: {len(api_promos)} промоакций")
            else:
                # API/combined парсер - используем UniversalParser (обычный HTTP)
                from parsers.universal_parser import UniversalParser
                parser = UniversalParser(api_url)
                api_promos = parser.get_promotions()
                logger.info(f"   📊 Получено через API: {len(api_promos)} промоакций")
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных: {e}", exc_info=True)
            api_promos = []

        if not api_promos:
            await loading_msg.edit_text(
                f"🎁 <b>ТЕКУЩИЕ ПРОМОАКЦИИ</b>\n\n"
                f"<b>🏦 Биржа:</b> {exchange_name}\n\n"
                f"📭 <i>Не удалось получить данные из API.\n"
                f"Попробуйте позже или проверьте подключение.</i>",
                parse_mode="HTML",
                reply_markup=get_current_promos_keyboard(1, 1)
            )
            return

        # Для Weex - WeexParser уже возвращает готовые данные с правильной структурой
        # Пропускаем стандартную фильтрацию и используем данные напрямую
        if exchange == 'weex':
            promos_data = api_promos  # WeexParser уже фильтрует активные
            # Определяем тип страницы Weex (airdrop или rewards)
            url_to_check = (html_url or page_url or '').lower()
            is_weex_rewards = '/rewards' in url_to_check
            if is_weex_rewards:
                logger.info(f"   ✅ Weex rewards: {len(promos_data)} промоакций")
            else:
                logger.info(f"   ✅ Weex airdrop: {len(promos_data)} промоакций")
            is_okx_boost = False
            is_gate_candy = False
            is_weex = True
            is_weex_rewards_page = is_weex_rewards
        else:
            # Фильтруем только активные промоакции (end_time > now)
            now = datetime.utcnow()
            promos_data = []
            
            for promo in api_promos:
                # Конвертируем время если нужно
                start_time = promo.get('start_time')
                end_time = promo.get('end_time')
                
                # Конвертируем timestamp в datetime
                if isinstance(start_time, (int, float)) and start_time > 0:
                    if start_time > 10**10:
                        start_time = datetime.fromtimestamp(start_time / 1000)
                    else:
                        start_time = datetime.fromtimestamp(start_time)
                
                if isinstance(end_time, (int, float)) and end_time > 0:
                    if end_time > 10**10:
                        end_time = datetime.fromtimestamp(end_time / 1000)
                    else:
                        end_time = datetime.fromtimestamp(end_time)
                
                # Проверяем активность (end_time > now или end_time = None)
                is_active = True
                if end_time and isinstance(end_time, datetime):
                    is_active = end_time > now
                
                # Также проверяем статус из API (для GateCandy activity_status)
                api_status = str(promo.get('status', '')).lower()
                if api_status == 'ended':
                    is_active = False
                
                if not is_active:
                    logger.debug(f"   ⏭️ Пропускаем завершенную: {promo.get('title')}")
                    continue
                
                # Проверяем что промо не пустое (есть хотя бы награды или участники)
                has_data = (
                    promo.get('total_prize_pool') or 
                    promo.get('participants_count') or 
                    promo.get('user_max_rewards') or
                    promo.get('conditions')
                )
                if not has_data:
                    logger.debug(f"   ⏭️ Пропускаем пустое промо: {promo.get('title')}")
                    continue
                
                promo_id = promo.get('promo_id') or f"{exchange_name}_{promo.get('id', len(promos_data))}"
                
                promo_dict = {
                    'promo_id': promo_id,
                    'title': promo.get('title', 'Без названия'),
                    'award_token': promo.get('award_token'),
                    'total_prize_pool': promo.get('total_prize_pool'),
                    'total_prize_pool_usd': promo.get('total_prize_pool_usd'),
                    'start_time': start_time,
                    'end_time': end_time,
                    'participants_count': promo.get('participants_count'),
                    'winners_count': promo.get('winners_count'),
                    'reward_per_winner': promo.get('reward_per_winner'),
                    'reward_per_winner_usd': promo.get('reward_per_winner_usd'),
                    'conditions': promo.get('conditions'),
                    'reward_type': promo.get('reward_type'),
                    'status': 'ongoing' if is_active else 'ended',
                    'link': promo.get('link'),
                    # GateCandy специфичные поля
                    'user_max_rewards': promo.get('user_max_rewards'),
                    'user_max_rewards_usd': promo.get('user_max_rewards_usd'),
                    'exchange_rate': promo.get('exchange_rate'),
                    'phase': promo.get('phase')
                }
                promos_data.append(promo_dict)

            logger.info(f"   ✅ Активных промоакций: {len(promos_data)}")

            # Проверяем, является ли это OKX Boost
            is_okx_boost = False
            is_gate_candy = False
            if api_promos and len(api_promos) > 0:
                first_promo = api_promos[0]
                is_okx_boost = first_promo.get('promo_type') == 'okx_boost'
            
            # Проверяем GateCandy по имени биржи или URL
            if 'gatecandy' in exchange_name.lower().replace(' ', '').replace('.', ''):
                is_gate_candy = True
            elif api_url and 'candydrop' in api_url.lower():
                is_gate_candy = True
            
            # Weex уже обработан выше
            is_weex = False
            is_weex_rewards_page = False
            
            # Для OKX Boost фильтруем только активные (ongoing + upcoming)
            if is_okx_boost:
                # Фильтруем только активные и upcoming
                active_promos = [p for p in api_promos if p.get('status') in ['ongoing', 'upcoming']]
                promos_data = active_promos
                logger.info(f"   🚀 Режим OKX Boost: {len(promos_data)} активных launchpool'ов (отфильтровано из {len(api_promos)})")

        # Записываем участников в историю и получаем статистику (для ВСЕХ бирж)
        if promos_data:
            try:
                from services.participants_tracker_service import get_participants_tracker
                tracker = get_participants_tracker()
                
                # Записываем текущие данные
                tracker.record_batch(exchange_name, promos_data)
                
                # Получаем статистику для каждого промо
                for promo in promos_data:
                    promo_id = promo.get('promo_id')
                    if promo_id:
                        stats = tracker.get_participants_stats(exchange_name, promo_id)
                        promo['participants_stats'] = stats
                
                logger.info(f"   📊 Статистика участников обновлена для {len(promos_data)} промо ({exchange_name})")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось обновить статистику участников: {e}")

        # Пагинация - для OKX Boost показываем по 5
        page = 1
        per_page = 5  # По 5 на страницу
        total_pages = max(1, (len(promos_data) + per_page - 1) // per_page)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_promos = promos_data[start_idx:end_idx]

        # Получаем предыдущие данные о участниках из состояния
        prev_state = current_promos_state.get(user_id, {})
        prev_participants = prev_state.get('participants_snapshot', {})
        
        # Создаём снимок текущих участников
        current_participants = {}
        for p in promos_data:
            pid = p.get('promo_id')
            # Поддерживаем оба варианта названия поля (participants_count и participants)
            pcount = p.get('participants_count') or p.get('participants')
            if pid and pcount:
                try:
                    current_participants[pid] = int(float(str(pcount).replace(',', '').replace(' ', '')))
                except:
                    pass

        # Сохранить состояние
        current_promos_state[user_id] = {
            'page': page,
            'link_id': link_id,
            'total_pages': total_pages,
            'promos': promos_data,
            'exchange_name': exchange_name,
            'page_url': page_url,
            'is_okx_boost': is_okx_boost,  # Сохраняем тип для пагинации
            'is_gate_candy': is_gate_candy,  # Сохраняем тип для GateCandy
            'is_weex': is_weex,  # Сохраняем тип для Weex
            'is_weex_rewards': is_weex_rewards_page if is_weex else False,  # Тип страницы Weex (rewards или airdrop)
            'participants_snapshot': current_participants  # Сохраняем снимок участников
        }
        logger.info(f"   💾 Состояние сохранено: page={page}, total_pages={total_pages}, is_okx_boost={is_okx_boost}, is_gate_candy={is_gate_candy}, is_weex={is_weex}")

        # Форматировать сообщение
        notif_service = NotificationService(bot=callback.bot)

        # Используем специальный форматтер в зависимости от типа биржи
        if is_okx_boost:
            message_text = notif_service.format_okx_boost_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url="https://web3.okx.com/ua/boost"
            )
        elif is_gate_candy:
            message_text = notif_service.format_gate_candy_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants=prev_participants
            )
        elif is_weex:
            # Используем разные форматтеры для airdrop и rewards
            if is_weex_rewards_page:
                message_text = notif_service.format_weex_rewards_page(
                    promos=page_promos,
                    page=page,
                    total_pages=total_pages,
                    page_url=page_url or 'https://www.weex.com/rewards'
                )
            else:
                message_text = notif_service.format_weex_airdrop_page(
                    promos=page_promos,
                    page=page,
                    total_pages=total_pages,
                    page_url=page_url or 'https://www.weex.com/token-airdrop'
                )
        else:
            message_text = notif_service.format_current_promos_page(
                promos=page_promos,
                page=page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                page_url=page_url
            )

        # Отправить с кнопками
        keyboard = get_current_promos_keyboard(page, total_pages)

        await loading_msg.edit_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"❌ Ошибка просмотра промоакций: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки данных", show_alert=True)


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
        is_weex = state.get('is_weex', False)
        is_weex_rewards = state.get('is_weex_rewards', False)
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

        # Форматировать сообщение
        notif_service = NotificationService(bot=callback.bot)

        # Используем специальный форматтер в зависимости от типа биржи
        if is_okx_boost:
            message_text = notif_service.format_okx_boost_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url="https://web3.okx.com/ua/boost"
            )
        elif is_gate_candy:
            message_text = notif_service.format_gate_candy_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                page_url=page_url,
                prev_participants=prev_participants
            )
        elif is_weex:
            # Используем разные форматтеры для airdrop и rewards
            if is_weex_rewards:
                message_text = notif_service.format_weex_rewards_page(
                    promos=page_promos,
                    page=new_page,
                    total_pages=total_pages,
                    page_url=page_url or 'https://www.weex.com/rewards'
                )
            else:
                message_text = notif_service.format_weex_airdrop_page(
                    promos=page_promos,
                    page=new_page,
                    total_pages=total_pages,
                    page_url=page_url or 'https://www.weex.com/token-airdrop'
                )
        else:
            message_text = notif_service.format_current_promos_page(
                promos=page_promos,
                page=new_page,
                total_pages=total_pages,
                exchange_name=exchange_name,
                page_url=page_url
            )

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
        await callback.message.delete()
        await callback.message.answer(
            "🏠 Главное меню\n\n"
            "Используйте кнопки меню ниже для выбора действия",
            reply_markup=get_main_menu()
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
            await callback.message.delete()
            await callback.message.answer(
                "🏠 Главное меню\n\n"
                "Используйте кнопки меню ниже для выбора действия",
                reply_markup=get_main_menu()
            )
            await callback.answer()
            return
    else:
        # Если стек пустой, возвращаемся в главное меню
        clear_navigation(user_id)
        await callback.message.delete()
        await callback.message.answer(
            "🏠 Главное меню\n\n"
            "Используйте кнопки меню ниже для выбора действия",
            reply_markup=get_main_menu()
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

    # Удаляем inline сообщение
    await callback.message.delete()

    # Отправляем новое сообщение с ReplyKeyboard
    await callback.message.answer(
        "🏠 Главное меню\n\n"
        "Используйте кнопки меню ниже для выбора действия",
        reply_markup=get_main_menu()
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
                    await callback.message.edit_text(
                        f"✏️ <b>Переименование ссылки</b>\n\n"
                        f"<b>Текущее имя:</b> {link.name}\n\n"
                        f"Введите новое имя для ссылки:",
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
            await callback.message.edit_text(
                f"✏️ <b>Переименование ссылки</b>\n\n"
                f"<b>Текущее имя:</b> {link.name}\n\n"
                f"Введите новое имя для ссылки:",
                parse_mode="HTML"
            )
            await state.set_state(RenameLinkStates.waiting_for_new_name)

        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при выборе ссылки для переименования: {e}")
        await callback.message.edit_text("❌ Ошибка при выборе ссылки")
        await callback.answer()

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

        # Показываем обновленный список ссылок для продолжения переименования
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

        # Показываем обновленный список ссылок для продолжения изменения интервалов
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
            'airdrop': '🪂 Аирдроп',
            'staking': '💰 Стейкинг',
            'launchpool': '🚀 Лаунчпул',
            'announcement': '📢 Анонс',
            'general': '📁 Общее'
        }
        current_category = link_data['category'] or 'general'
        category_display = category_names.get(current_category, '📁 Общее')

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
            current_category = link.category or 'general'
        
        category_names = {
            'airdrop': '🪂 Аирдроп',
            'staking': '💰 Стейкинг',
            'launchpool': '🚀 Лаунчпул',
            'announcement': '📢 Анонс',
            'general': '📁 Общее'
        }
        current_category_display = category_names.get(current_category, '📁 Общее')
        
        keyboard = get_category_edit_keyboard(link_id)
        await callback.message.edit_text(
            f"🗂️ <b>Изменение категории</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Текущая категория:</b> {current_category_display}\n\n"
            f"Выберите новую категорию:",
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
    """Сохраняет выбранную категорию"""
    try:
        parts = callback.data.split("_")
        link_id = int(parts[2])
        new_category = parts[3]
        
        def update_category(session):
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()
            if not link:
                raise ValueError("Ссылка не найдена")
            
            old_category = link.category or 'general'
            link.category = new_category
            return link.name, old_category
        
        link_name, old_category = atomic_operation(update_category)
        
        category_names = {
            'airdrop': '🪂 Аирдроп',
            'staking': '💰 Стейкинг',
            'launchpool': '🚀 Лаунчпул',
            'announcement': '📢 Анонс',
            'general': '📁 Общее'
        }
        old_category_display = category_names.get(old_category, '📁 Общее')
        new_category_display = category_names.get(new_category, '📁 Общее')
        
        await callback.message.edit_text(
            f"✅ <b>Категория успешно изменена!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Было:</b> {old_category_display}\n"
            f"<b>Стало:</b> {new_category_display}",
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

        await callback.message.edit_text(
            f"✅ <b>Тип парсинга успешно изменён!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый тип:</b> {parsing_type_display}",
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

    message = (
        f"⚙️ <b>НАСТРОЙКИ УМНЫХ УВЕДОМЛЕНИЙ</b>\n\n"
        f"🏦 <b>Биржа:</b> {link.name}\n"
        f"📌 <b>Категория:</b> Стейкинг\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>ТЕКУЩИЕ НАСТРОЙКИ:</b>\n\n"
        f"🔔 <b>Новые стейкинги:</b> {bool_emoji(link.notify_new_stakings)}\n"
        f"📈 <b>Изменения APR:</b> {bool_emoji(link.notify_apr_changes)}\n"
        f"📊 <b>Заполненность:</b> {bool_emoji(link.notify_fill_changes)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ <b>FLEXIBLE СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Время стабилизации:</b> {link.flexible_stability_hours} часов\n"
        f"└─ <b>Только стабильные:</b> {bool_emoji(link.notify_only_stable_flexible)}\n\n"
        f"⚡ <b>FIXED СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Уведомлять сразу:</b> {bool_emoji(link.fixed_notify_immediately)}\n"
        f"└─ <b>Combined как Fixed:</b> {bool_emoji(link.notify_combined_as_fixed)}\n\n"
        f"📊 <b>ИЗМЕНЕНИЯ APR:</b>\n"
        f"└─ <b>Минимальное изменение:</b> {link.notify_min_apr_change}%\n\n"
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

