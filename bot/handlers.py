from aiogram import Router, F
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
from utils.rotation_manager import get_rotation_manager
from utils.url_template_builder import URLTemplateAnalyzer, get_url_builder

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
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback: {e}")

# Хранилище для временных данных
user_selections = {}

# Система контекстной навигации - хранит историю навигации пользователя
navigation_stack = {}

# Контексты навигации
NAV_MAIN = "main"
NAV_LINKS_LIST = "links_list"
NAV_MANAGEMENT = "management"
NAV_DELETE = "delete"
NAV_INTERVAL = "interval"
NAV_RENAME = "rename"
NAV_PARSING = "parsing"
NAV_PROXY = "proxy"
NAV_USER_AGENT = "user_agent"

def push_navigation(user_id: int, context: str, data: dict = None):
    """Добавить контекст в стек навигации пользователя"""
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

class IntervalStates(StatesGroup):
    waiting_for_interval = State()

class RenameLinkStates(StatesGroup):
    waiting_for_new_name = State()

class ConfigureParsingStates(StatesGroup):
    waiting_for_link_selection = State()  # Выбор ссылки для настройки
    waiting_for_parsing_type_edit = State()  # Изменение типа парсинга
    waiting_for_api_url_edit = State()  # Изменение API URL
    waiting_for_html_url_edit = State()  # Изменение HTML URL

# НОВЫЕ FSM СОСТОЯНИЯ
class ProxyManagementStates(StatesGroup):
    waiting_for_proxy_address = State()
    waiting_for_proxy_protocol = State()

class UserAgentStates(StatesGroup):
    waiting_for_user_agent = State()

class RotationSettingsStates(StatesGroup):
    waiting_for_rotation_interval = State()

class TelegramAPIStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()

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
def get_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data="manage_delete"))
    builder.add(InlineKeyboardButton(text="⏰ Изменить интервал", callback_data="manage_interval"))
    builder.add(InlineKeyboardButton(text="✏️ Переименовать ссылку", callback_data="manage_rename"))
    builder.add(InlineKeyboardButton(text="🎯 Настроить парсинг", callback_data="manage_configure_parsing"))
    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="manage_cancel"))
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
    # НОВАЯ КНОПКА ДЛЯ СТЕЙКИНГА:
    builder.add(InlineKeyboardButton(text="📊 Проверить заполненность пулов", callback_data="manage_check_pools"))
    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="manage_cancel"))
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

def get_configure_parsing_submenu(link_id):
    """Подменю для настройки парсинга конкретной ссылки"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🎯 Изменить тип парсинга", callback_data=f"edit_parsing_type_{link_id}"))
    builder.add(InlineKeyboardButton(text="📡 Изменить API URL", callback_data=f"edit_api_url_{link_id}"))
    builder.add(InlineKeyboardButton(text="🌐 Изменить HTML URL", callback_data=f"edit_html_url_{link_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_configure_parsing"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    builder.adjust(1)
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

# НОВЫЕ ИНЛАЙН-КЛАВИАТУРЫ ДЛЯ РАСШИРЕННЫХ СИСТЕМ
def get_proxy_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список прокси", callback_data="proxy_list"))
    builder.add(InlineKeyboardButton(text="➕ Добавить прокси", callback_data="proxy_add"))
    builder.add(InlineKeyboardButton(text="🧪 Тестировать все", callback_data="proxy_test_all"))
    builder.add(InlineKeyboardButton(text="🗑️ Удалить прокси", callback_data="proxy_delete"))
    builder.add(InlineKeyboardButton(text="📊 Статистика прокси", callback_data="proxy_stats"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="proxy_cancel"))
    builder.adjust(2)
    return builder.as_markup()

def get_user_agent_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список User-Agent", callback_data="ua_list"))
    builder.add(InlineKeyboardButton(text="➕ Добавить User-Agent", callback_data="ua_add"))
    builder.add(InlineKeyboardButton(text="🔄 Сгенерировать новые", callback_data="ua_generate"))
    builder.add(InlineKeyboardButton(text="📊 Статистика UA", callback_data="ua_stats"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="ua_cancel"))
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

def get_bypass_keyboard():
    """Клавиатура для подменю Обход блокировок"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔧 Управление прокси", callback_data="bypass_proxy"))
    builder.add(InlineKeyboardButton(text="👤 Управление User-Agent", callback_data="bypass_ua"))
    builder.add(InlineKeyboardButton(text="📱 Telegram API", callback_data="bypass_telegram"))
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
                    'api': '📡 API',
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
        # Для HTML парсинга нужен только HTML URL
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

    # Создаем кнопки выбора интервала
    builder = InlineKeyboardBuilder()
    presets = [
        ("1 минута", 60), ("5 минут", 300), ("10 минут", 600),
        ("30 минут", 1800), ("1 час", 3600), ("2 часа", 7200),
        ("6 часов", 21600), ("12 часов", 43200), ("24 часа", 86400)
    ]

    for text, seconds in presets:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"add_interval_{seconds}"))
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_telegram_channel"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_link"))
    builder.adjust(2, 2, 2, 2, 1, 2)

    await message.answer(
        f"✅ Ключевые слова сохранены!\n\n"
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n"
        f"<b>Канал:</b> {telegram_channel}\n"
        f"<b>Ключевые слова:</b> {keywords_str}\n\n"
        f"Как часто проверять этот канал на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)

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

    # Создаем кнопки выбора интервала
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
        f"⏭️ Пример ссылки пропущен\n\n"
        f"⏰ <b>Шаг 5/5: Выберите интервал проверки</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)
    await callback.answer()

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
        "❌ Добавление ссылки отменено"
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

        def add_link_operation(session):
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
                telegram_channel=telegram_channel
            )
            # Устанавливаем ключевые слова для Telegram
            if telegram_keywords:
                new_link.set_telegram_keywords(telegram_keywords)
            session.add(new_link)
            session.flush()
            return new_link

        new_link = atomic_operation(add_link_operation)

        # Для Telegram - автоматическая подписка на канал (в фоновом режиме)
        subscription_status = ""
        if parsing_type == 'telegram' and telegram_channel:
            subscription_status = "🔄 Подписка на канал выполняется в фоновом режиме...\n"

            # Запускаем подписку в фоновом режиме, чтобы не блокировать БД
            async def subscribe_to_channel():
                """Фоновая задача подписки на канал"""
                try:
                    # Небольшая задержка для завершения транзакции БД
                    await asyncio.sleep(1)

                    from parsers.telegram_parser import TelegramParser
                    parser = TelegramParser()

                    # Подключаемся к Telegram
                    connected = await parser.connect()

                    if connected:
                        # Подписываемся на канал
                        joined = await parser.join_channel(telegram_channel)

                        if joined:
                            logger.info(f"✅ Успешно подписан на канал {telegram_channel}")
                        else:
                            logger.warning(f"⚠️ Не удалось подписаться на канал {telegram_channel}")

                        # Отключаемся
                        await parser.disconnect()
                    else:
                        logger.warning(f"⚠️ Не удалось подключиться к Telegram для подписки на {telegram_channel}")

                except Exception as e:
                    logger.error(f"❌ Ошибка фоновой подписки на Telegram канал: {e}")

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
            message_parts.append(f"<b>📡 API URL:</b>\n<code>{api_url}</code>\n")

        if html_url:
            message_parts.append(f"\n<b>🌐 HTML URL:</b>\n<code>{html_url}</code>\n")

        if page_url:
            message_parts.append(f"\n<b>🔗 Страница акций:</b>\n<code>{page_url}</code>\n")

        if telegram_channel:
            message_parts.append(f"\n<b>📱 Telegram канал:</b> {telegram_channel}\n")
            keywords_display = ", ".join([f"<code>{kw}</code>" for kw in telegram_keywords])
            message_parts.append(f"<b>🔑 Ключевые слова:</b> {keywords_display}\n")
            if subscription_status:
                message_parts.append(f"\n{subscription_status}")

        if min_apr:
            message_parts.append(f"\n<b>📊 Минимальный APR:</b> {min_apr}%\n")

        await callback.message.edit_text(
            "".join(message_parts),
            parse_mode="HTML"
        )

        await state.clear()
        await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при сохранении ссылки")
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

@router.callback_query(F.data.startswith("manage_link_"))
async def show_link_management(callback: CallbackQuery):
    """Показать меню управления выбранной ссылкой (с учетом категории)"""
    try:
        link_id = int(callback.data.split("_")[2])

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                await callback.answer()
                return

            # Сохраняем link_id для использования в других обработчиках
            user_selections[callback.from_user.id] = link_id

            # Выбираем правильную клавиатуру в зависимости от категории
            if link.category == 'staking':
                keyboard = get_staking_management_keyboard()
            else:
                keyboard = get_management_keyboard()

            # Информация о ссылке
            status_text = "✅ Активна" if link.is_active else "❌ Остановлена"
            parsing_type_text = {
                'api': 'API',
                'html': 'HTML',
                'browser': 'Browser',
                'combined': 'Комбинированный'
            }.get(link.parsing_type, 'Комбинированный')

            await callback.message.edit_text(
                f"⚙️ <b>Управление ссылкой:</b> {link.name}\n\n"
                f"<b>Статус:</b> {status_text}\n"
                f"<b>Категория:</b> {link.category or 'general'}\n"
                f"<b>Интервал:</b> {link.check_interval}с ({link.check_interval // 60} мин)\n"
                f"<b>Тип парсинга:</b> {parsing_type_text}\n\n"
                f"Выберите действие:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка при показе меню управления ссылкой: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при загрузке меню")
        await callback.answer()

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

@router.callback_query(F.data == "manage_delete")
async def manage_delete(callback: CallbackQuery):
    try:
        # Сохраняем контекст навигации
        push_navigation(callback.from_user.id, NAV_DELETE)

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
    await callback.message.edit_text(
        "❌ Действие отменено\n\nЧто вы хотите сделать?",
        reply_markup=get_cancel_keyboard_with_navigation()
    )
    if callback.from_user.id in user_selections:
        del user_selections[callback.from_user.id]
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
            await callback.message.edit_text("🏠 Возврат в главное меню", reply_markup=get_cancel_keyboard_with_navigation())
    else:
        # Если стек пустой, предлагаем вернуться в главное меню
        await callback.message.edit_text("🏠 Возврат в главное меню", reply_markup=get_cancel_keyboard_with_navigation())

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

    await callback.message.edit_text(
        "🏠 Главное меню\n\n"
        "Используйте кнопки меню ниже для выбора действия"
    )
    await callback.answer()

@router.callback_query(F.data == "manage_interval")
async def manage_interval(callback: CallbackQuery):
    try:
        # Сохраняем контекст навигации
        push_navigation(callback.from_user.id, NAV_INTERVAL)

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
async def manage_rename(callback: CallbackQuery):
    try:
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
        if user_id not in user_selections:
            await callback.message.edit_text("❌ Данные устарели, начните заново")
            return

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
        if user_id not in user_selections:
            await callback.message.edit_text("❌ Данные устарели, начните заново")
            return

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
        with get_db_session() as db:
            links = db.query(ApiLink).all()

            if not links:
                await callback.message.edit_text("❌ У вас нет ссылок для принудительной проверки")
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

            keyboard = get_links_keyboard(links_data, "force_check")
            await callback.message.edit_text("🔧 <b>Выберите ссылку для принудительной проверки:</b>", reply_markup=keyboard, parse_mode="HTML")

        await callback.answer()

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
    """Показывает список ссылок для настройки парсинга"""
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()

            if not links:
                await callback.message.edit_text("❌ У вас нет ссылок для настройки")
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

            keyboard = get_links_keyboard(links_data, "configure_parsing")
            await callback.message.edit_text(
                "🎯 <b>Настройка парсинга:</b>\n\n"
                "Выберите ссылку для настройки:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        await callback.answer()

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
                'parsing_type': link.parsing_type or 'combined',
                'api_url': link.api_url,
                'html_url': link.html_url
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
            }
        }

        current_type = link_data['parsing_type']
        type_info = parsing_type_info.get(current_type, parsing_type_info['combined'])

        message_parts = [
            f"🎯 <b>Настройка парсинга для:</b> {link_data['name']}\n\n",
            f"<b>Текущий тип парсинга:</b>\n{type_info['name']}\n",
            f"<i>{type_info['description']}</i>\n\n",
        ]

        if link_data['api_url']:
            message_parts.append(f"<b>📡 API URL:</b>\n<code>{link_data['api_url']}</code>\n\n")
        else:
            message_parts.append(f"<b>📡 API URL:</b> <i>Не указан</i>\n\n")

        if link_data['html_url']:
            message_parts.append(f"<b>🌐 HTML URL:</b>\n<code>{link_data['html_url']}</code>\n\n")
        else:
            message_parts.append(f"<b>🌐 HTML URL:</b> <i>Не указан</i>\n\n")

        message_parts.append("Выберите параметр для изменения:")

        keyboard = get_configure_parsing_submenu(link_id)
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
    # Повторно используем функцию показа конфигурации
    callback.data = f"configure_parsing_link_{link_id}"
    await show_parsing_configuration(callback)

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

@router.callback_query(F.data.startswith("set_parsing_type_"))
async def set_parsing_type(callback: CallbackQuery):
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
            return link.name

        link_name = atomic_operation(update_parsing_type)

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

@router.callback_query(F.data == "bypass_telegram")
async def bypass_telegram_handler(callback: CallbackQuery):
    """Открыть настройки Telegram API из подменю обхода блокировок"""
    try:
        # Импортируем TelegramSettings
        from data.models import TelegramSettings

        # Получаем текущие настройки
        with get_db_session() as db:
            settings = db.query(TelegramSettings).first()

            if settings and settings.is_configured:
                status = "✅ Настроено"
                api_id_display = settings.api_id if settings.api_id else "Не установлено"
                api_hash_display = settings.api_hash[:10] + "..." if settings.api_hash else "Не установлено"
                phone_display = settings.phone_number if settings.phone_number else "Не установлен"
                last_auth = settings.last_auth.strftime("%d.%m.%Y %H:%M") if settings.last_auth else "Никогда"
            else:
                status = "❌ Не настроено"
                api_id_display = "Не установлено"
                api_hash_display = "Не установлено"
                phone_display = "Не установлен"
                last_auth = "Никогда"

        # Создаем клавиатуру
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="⚙️ Настроить API", callback_data="telegram_api_configure"))
        builder.add(InlineKeyboardButton(text="🔄 Пересоздать сессию", callback_data="telegram_api_reset"))
        builder.add(InlineKeyboardButton(text="📖 Инструкция", callback_data="telegram_api_help"))
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_bypass"))
        builder.adjust(2, 1, 1)

        await callback.message.edit_text(
            f"📱 <b>Настройки Telegram API</b>\n\n"
            f"<b>Статус:</b> {status}\n\n"
            f"<b>API ID:</b> <code>{api_id_display}</code>\n"
            f"<b>API Hash:</b> <code>{api_hash_display}</code>\n"
            f"<b>Номер телефона:</b> <code>{phone_display}</code>\n"
            f"<b>Последняя авторизация:</b> {last_auth}\n\n"
            f"Для использования Telegram парсинга необходимо настроить API.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка показа настроек Telegram API: {e}")
        await callback.answer("❌ Ошибка загрузки настроек")

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

@router.callback_query(F.data == "telegram_api_help")
async def telegram_api_help_handler(callback: CallbackQuery):
    """Показать инструкцию по получению Telegram API"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="bypass_telegram"))

    await callback.message.edit_text(
        "📖 <b>Как получить Telegram API</b>\n\n"
        "<b>Шаг 1:</b> Перейдите на сайт\n"
        "https://my.telegram.org/apps\n\n"
        "<b>Шаг 2:</b> Войдите с помощью номера телефона\n\n"
        "<b>Шаг 3:</b> Создайте новое приложение:\n"
        "• <b>App title:</b> любое название (например 'My Parser Bot')\n"
        "• <b>Short name:</b> короткое имя (например 'parser')\n"
        "• <b>Platform:</b> выберите 'Other'\n\n"
        "<b>Шаг 4:</b> Скопируйте <code>App api_id</code> и <code>App api_hash</code>\n\n"
        "<b>Шаг 5:</b> Нажмите '⚙️ Настроить API' и введите данные\n\n"
        "⚠️ <b>Важно:</b> Не делитесь API Hash с посторонними!",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "telegram_api_configure")
async def telegram_api_configure_start(callback: CallbackQuery, state: FSMContext):
    """Начало настройки Telegram API"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="bypass_telegram"))

    await callback.message.edit_text(
        "📱 <b>Настройка Telegram API</b>\n\n"
        "🔢 <b>Шаг 1/3:</b> Введите <b>API ID</b>\n\n"
        "Получите на https://my.telegram.org/apps\n\n"
        "Пример: <code>12345678</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAPIStates.waiting_for_api_id)
    await callback.answer()

@router.message(TelegramAPIStates.waiting_for_api_id)
async def process_telegram_api_id(message: Message, state: FSMContext):
    """Обработка ввода API ID"""
    api_id = message.text.strip()

    # Проверяем, что это число
    if not api_id.isdigit():
        await message.answer("❌ API ID должен быть числом. Попробуйте снова:")
        return

    # Сохраняем
    await state.update_data(telegram_api_id=api_id)

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_id"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="bypass_telegram"))
    builder.adjust(2)

    await message.answer(
        f"✅ API ID сохранен: <code>{api_id}</code>\n\n"
        f"🔑 <b>Шаг 2/3:</b> Введите <b>API Hash</b>\n\n"
        f"Получите на https://my.telegram.org/apps\n\n"
        f"Пример: <code>1234567890abcdef1234567890abcdef</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAPIStates.waiting_for_api_hash)

@router.message(TelegramAPIStates.waiting_for_api_hash)
async def process_telegram_api_hash(message: Message, state: FSMContext):
    """Обработка ввода API Hash"""
    api_hash = message.text.strip()

    if len(api_hash) < 16:
        await message.answer("❌ API Hash слишком короткий. Проверьте и введите снова:")
        return

    # Сохраняем
    await state.update_data(telegram_api_hash=api_hash)

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="← Назад", callback_data="back_to_api_hash"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="bypass_telegram"))
    builder.adjust(2)

    await message.answer(
        f"✅ API Hash сохранен\n\n"
        f"📞 <b>Шаг 3/3:</b> Введите <b>номер телефона</b>\n\n"
        f"Формат: <code>+79001234567</code>\n\n"
        f"⚠️ Этот номер будет использоваться для авторизации в Telegram",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAPIStates.waiting_for_phone)

@router.message(TelegramAPIStates.waiting_for_phone)
async def process_telegram_phone(message: Message, state: FSMContext):
    """Обработка ввода номера телефона"""
    phone = message.text.strip()

    # Базовая валидация номера
    if not phone.startswith('+'):
        await message.answer("❌ Номер должен начинаться с '+'. Попробуйте снова:")
        return

    if len(phone) < 10:
        await message.answer("❌ Номер слишком короткий. Попробуйте снова:")
        return

    # Получаем сохраненные данные
    data = await state.get_data()
    api_id = data.get('telegram_api_id')
    api_hash = data.get('telegram_api_hash')

    # Сохраняем в БД
    try:
        from data.models import TelegramSettings

        with get_db_session() as db:
            settings = db.query(TelegramSettings).first()

            if not settings:
                settings = TelegramSettings()
                db.add(settings)

            settings.api_id = api_id
            settings.api_hash = api_hash
            settings.phone_number = phone
            settings.is_configured = True
            db.commit()

        await message.answer(
            "✅ <b>Настройки Telegram API сохранены!</b>\n\n"
            f"<b>API ID:</b> <code>{api_id}</code>\n"
            f"<b>API Hash:</b> <code>{api_hash[:10]}...</code>\n"
            f"<b>Номер:</b> <code>{phone}</code>\n\n"
            "Теперь вы можете добавлять Telegram-ссылки для парсинга!",
            parse_mode="HTML"
        )

        # Очищаем состояние
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка сохранения настроек Telegram API: {e}")
        await message.answer("❌ Ошибка сохранения настроек. Попробуйте снова.")

@router.callback_query(F.data == "telegram_api_reset")
async def telegram_api_reset_handler(callback: CallbackQuery):
    """Сброс сессии Telegram"""
    try:
        import os
        session_file = 'telegram_parser_session.session'

        if os.path.exists(session_file):
            os.remove(session_file)
            await callback.answer("✅ Сессия удалена. При следующем запуске потребуется повторная авторизация")
        else:
            await callback.answer("ℹ️ Файл сессии не найден")

    except Exception as e:
        logger.error(f"Ошибка удаления сессии: {e}")
        await callback.answer("❌ Ошибка удаления сессии")

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
            await callback.message.edit_text("❌ Нет добавленных прокси-серверов")
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
        await callback.message.edit_text(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"❌ Ошибка при получении списка прокси: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при получении списка прокси")

@router.callback_query(F.data == "proxy_add")
async def proxy_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ <b>Добавление нового прокси</b>\n\n"
        "Введите адрес прокси в формате:\n"
        "<code>ip:port</code> или <code>user:pass@ip:port</code>\n\n"
        "Примеры:\n"
        "• <code>192.168.1.1:8080</code>\n"
        "• <code>user:password@proxy.example.com:3128</code>",
        parse_mode="HTML"
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
        
        await callback.message.edit_text(
            f"✅ <b>Тестирование завершено!</b>\n\n"
            f"Активных прокси: {len(active_proxies)}/{len(proxies)}\n"
            f"Используйте <b>\"📋 Список прокси\"</b> для просмотра детальной информации.",
            parse_mode="HTML"
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
        
        await callback.message.edit_text(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики прокси")

@router.callback_query(F.data == "proxy_delete")
async def proxy_delete_start(callback: CallbackQuery):
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
    try:
        proxy_id = int(callback.data.split("_")[2])
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
    try:
        proxy_id = int(callback.data.split("_")[3])
        proxy_manager = get_proxy_manager()
        
        success = proxy_manager.delete_proxy(proxy_id)
        
        if success:
            await callback.message.edit_text(
                "✅ <b>Прокси успешно удален!</b>\n\n"
                "Прокси-сервер больше не будет использоваться в ротации.",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text("❌ Не удалось удалить прокси")
            
    except Exception as e:
        logger.error(f"Ошибка при удалении прокси: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении прокси")

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
        await callback.message.edit_text(response, parse_mode="HTML")

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
        await callback.message.edit_text(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"❌ Ошибка при получении статистики User-Agent: {e}", exc_info=True)
        await callback.message.edit_text("❌ Ошибка при получении статистики User-Agent")

@router.callback_query(F.data == "ua_add")
async def ua_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ <b>Добавление нового User-Agent</b>\n\n"
        "Введите User-Agent строку:\n\n"
        "Пример:\n"
        "<code>Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36</code>",
        parse_mode="HTML"
    )
    await state.set_state(UserAgentStates.waiting_for_user_agent)
    await callback.answer()

@router.message(UserAgentStates.waiting_for_user_agent)
async def process_user_agent_input(message: Message, state: FSMContext):
    user_agent_string = message.text.strip()
    
    if not user_agent_string:
        await message.answer("❌ User-Agent не может быть пустым. Попробуйте снова:")
        return
    
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
        
        await callback.message.edit_text(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при получении общей статистики: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики")

@router.callback_query(F.data == "stats_by_exchange")
async def stats_by_exchange(callback: CallbackQuery):
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                await callback.message.edit_text("❌ Нет добавленных бирж для статистики")
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
            
            await callback.message.edit_text(response, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при получении статистики по биржам: {e}")
        await callback.message.edit_text("❌ Ошибка при получении статистики по биржам")

@router.callback_query(F.data == "stats_best_combinations")
async def stats_best_combinations(callback: CallbackQuery):
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                await callback.message.edit_text("❌ Нет добавленных бирж")
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
            
            await callback.message.edit_text(response, parse_mode="HTML")
            
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
        
        await callback.message.edit_text(response, parse_mode="HTML")
        
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
        
        await callback.message.edit_text(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при получении настроек ротации: {e}")
        await callback.message.edit_text("❌ Ошибка при получении настроек ротации")

@router.callback_query(F.data == "rotation_interval")
async def rotation_interval_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⏰ <b>Настройка интервала ротации</b>\n\n"
        "Введите интервал в секундах:\n"
        "• Рекомендуется: 900-3600 сек (15-60 минут)\n"
        "• Минимальный: 300 сек (5 минут)\n"
        "• Максимальный: 86400 сек (24 часа)\n\n"
        "Текущее значение: 900 сек",
        parse_mode="HTML"
    )
    await state.set_state(RotationSettingsStates.waiting_for_rotation_interval)
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

@router.callback_query(F.data.in_(["proxy_cancel", "ua_cancel", "stats_cancel", "rotation_cancel"]))
async def process_new_systems_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Действие отменено")
    if callback.from_user.id in user_selections:
        del user_selections[callback.from_user.id]
    await state.clear()
    await callback.answer()

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def _format_timestamp(timestamp: float) -> str:
    if timestamp == 0:
        return "никогда"
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%d.%m.%Y %H:%M:%S")

