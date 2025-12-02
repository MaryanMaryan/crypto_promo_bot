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
from urllib.parse import urlparse
from datetime import datetime

# ИМПОРТЫ ДЛЯ НОВЫХ СИСТЕМ
from utils.proxy_manager import get_proxy_manager
from utils.user_agent_manager import get_user_agent_manager  
from utils.statistics_manager import get_statistics_manager
from utils.rotation_manager import get_rotation_manager

router = Router()
logger = logging.getLogger(__name__)
parser_service = ParserService()

# Хранилище для временных данных
user_selections = {}

# СУЩЕСТВУЮЩИЕ СОСТОЯНИЯ FSM
class AddLinkStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_api_urls = State()
    waiting_for_html_urls = State()
    waiting_for_name = State()
    waiting_for_interval = State()

class IntervalStates(StatesGroup):
    waiting_for_interval = State()

class RenameLinkStates(StatesGroup):
    waiting_for_new_name = State()

# НОВЫЕ FSM СОСТОЯНИЯ
class ProxyManagementStates(StatesGroup):
    waiting_for_proxy_address = State()
    waiting_for_proxy_protocol = State()

class UserAgentStates(StatesGroup):
    waiting_for_user_agent = State()

class RotationSettingsStates(StatesGroup):
    waiting_for_rotation_interval = State()

# РАСШИРЕННОЕ ГЛАВНОЕ МЕНЮ
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Список ссылок"))
    builder.add(KeyboardButton(text="➕ Добавить ссылку"))
    builder.add(KeyboardButton(text="⚙️ Управление ссылками"))
    builder.add(KeyboardButton(text="🔧 Управление прокси"))
    builder.add(KeyboardButton(text="👤 Управление User-Agent"))
    builder.add(KeyboardButton(text="📈 Статистика системы"))
    builder.add(KeyboardButton(text="⚙️ Настройки ротации"))
    builder.add(KeyboardButton(text="🔄 Проверить все"))
    builder.add(KeyboardButton(text="📋 История промоакций"))
    builder.add(KeyboardButton(text="❓ Помощь"))
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

# СУЩЕСТВУЮЩИЕ КЛАВИАТУРЫ
def get_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data="manage_delete"))
    builder.add(InlineKeyboardButton(text="⏰ Изменить интервал", callback_data="manage_interval"))
    builder.add(InlineKeyboardButton(text="✏️ Переименовать ссылку", callback_data="manage_rename"))
    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="manage_cancel"))
    builder.adjust(1)
    return builder.as_markup()

def get_links_keyboard(links, action_type="delete"):
    builder = InlineKeyboardBuilder()
    for link in links:
        status_icon = "✅" if link.is_active else "❌"
        builder.add(InlineKeyboardButton(
            text=f"{status_icon} {link.name} ({link.check_interval}с)",
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

# ОСНОВНЫЕ КОМАНДЫ БОТА
@router.message(Command("start"))
async def cmd_start(message: Message):
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
        "• 🔄 Проверить все - ручная проверка ТОЛЬКО АКТИВНЫХ ссылок\n"
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
                response += f"<b>{link.name}</b>\n"
                response += f"Биржа: {link.exchange}\n"
                response += f"Статус: {status}\n"
                response += f"Интервал: {interval_minutes} мин\n"
                response += f"URL: <code>{link.url}</code>\n\n"
            
            await message.answer(response, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка ссылок: {e}")
        await message.answer("❌ Ошибка при получении списка ссылок")

@router.message(F.text == "➕ Добавить ссылку")
async def menu_add_link(message: Message, state: FSMContext):
    await message.answer(
        "🔗 <b>Добавление новой ссылки для парсинга</b>\n\n"
        "📌 Вы можете добавить несколько URL для одной биржи:\n"
        "• API ссылки (для API парсинга)\n"
        "• HTML ссылки (для HTML парсинга)\n\n"
        "Система FALLBACK будет использовать эти ссылки автоматически!\n\n"
        "Отправьте основной URL биржи (API или HTML):",
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_url)

@router.message(AddLinkStates.waiting_for_url)
async def process_url_input(message: Message, state: FSMContext):
    url = message.text.strip()

    if not url.startswith(('http://', 'https://')):
        await message.answer("❌ URL должен начинаться с http:// или https://. Попробуйте снова:")
        return

    await state.update_data(url=url, api_urls_list=[], html_urls_list=[])

    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()

    exchange_name = "Unknown"
    if 'bybit' in domain:
        exchange_name = "Bybit"
    elif 'binance' in domain:
        exchange_name = "Binance"
    elif 'gate' in domain:
        exchange_name = "Gate.io"
    elif 'mexc' in domain:
        exchange_name = "MEXC"
    elif 'okx' in domain:
        exchange_name = "OKX"
    else:
        parts = domain.split('.')
        if len(parts) >= 2:
            exchange_name = parts[-2].title()

    await state.update_data(exchange_name=exchange_name)

    # Спрашиваем про дополнительные API URL
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Добавить API ссылки", callback_data="add_more_api_urls"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_api_urls"))
    builder.adjust(1)

    await message.answer(
        f"📡 <b>Дополнительные API ссылки для FALLBACK</b>\n\n"
        f"<b>Биржа:</b> {exchange_name}\n"
        f"<b>Основной URL:</b> <code>{url}</code>\n\n"
        f"Хотите добавить дополнительные API ссылки для этой биржи?\n"
        f"(Для мульти-стратегического парсинга)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ОБРАБОТЧИКИ ДЛЯ ДОБАВЛЕНИЯ API ССЫЛОК
@router.callback_query(F.data == "add_more_api_urls")
async def add_more_api_urls(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📡 <b>Добавление API ссылок</b>\n\n"
        "Отправьте API ссылки (по одной или несколько через запятую):\n\n"
        "Пример:\n"
        "<code>https://api.bybit.com/v5/promotion/list</code>\n"
        "или\n"
        "<code>https://api1.com, https://api2.com</code>\n\n"
        "Отправьте <b>\"готово\"</b> когда закончите или <b>\"пропустить\"</b> чтобы пропустить.",
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_api_urls)
    await callback.answer()

@router.callback_query(F.data == "skip_api_urls")
async def skip_api_urls(callback: CallbackQuery, state: FSMContext):
    # Переходим к HTML ссылкам
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Добавить HTML ссылки", callback_data="add_more_html_urls"))
    builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_urls"))
    builder.adjust(1)

    await callback.message.edit_text(
        "🌐 <b>Дополнительные HTML ссылки для FALLBACK</b>\n\n"
        "Хотите добавить HTML ссылки для этой биржи?\n"
        "(Система будет использовать HTML парсинг если API не сработает)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AddLinkStates.waiting_for_api_urls)
async def process_api_urls_input(message: Message, state: FSMContext):
    text = message.text.strip().lower()

    if text in ["готово", "done", "skip", "пропустить"]:
        # Переходим к HTML ссылкам
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅ Добавить HTML ссылки", callback_data="add_more_html_urls"))
        builder.add(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_html_urls"))
        builder.adjust(1)

        data = await state.get_data()
        api_urls = data.get('api_urls_list', [])

        await message.answer(
            f"✅ <b>API ссылки добавлены: {len(api_urls)}</b>\n\n"
            "🌐 Теперь добавим HTML ссылки?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return

    # Парсим ссылки (разделенные запятыми или пробелами)
    urls = [url.strip() for url in message.text.replace(',', ' ').split() if url.strip().startswith('http')]

    if not urls:
        await message.answer("❌ Не найдено валидных URL. Попробуйте снова или отправьте 'готово':")
        return

    data = await state.get_data()
    api_urls_list = data.get('api_urls_list', [])
    api_urls_list.extend(urls)
    await state.update_data(api_urls_list=api_urls_list)

    await message.answer(
        f"✅ <b>Добавлено {len(urls)} API ссылок</b>\n"
        f"Всего API ссылок: {len(api_urls_list)}\n\n"
        f"Отправьте еще ссылки или <b>\"готово\"</b> для продолжения.",
        parse_mode="HTML"
    )

# ОБРАБОТЧИКИ ДЛЯ ДОБАВЛЕНИЯ HTML ССЫЛОК
@router.callback_query(F.data == "add_more_html_urls")
async def add_more_html_urls(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🌐 <b>Добавление HTML ссылок</b>\n\n"
        "Отправьте HTML ссылки (по одной или несколько через запятую):\n\n"
        "Пример:\n"
        "<code>https://www.bybit.com/en/trade/spot/token-splash</code>\n"
        "или\n"
        "<code>https://site1.com, https://site2.com</code>\n\n"
        "Отправьте <b>\"готово\"</b> когда закончите или <b>\"пропустить\"</b> чтобы пропустить.",
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_html_urls)
    await callback.answer()

@router.callback_query(F.data == "skip_html_urls")
async def skip_html_urls(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exchange_name = data.get('exchange_name')
    url = data.get('url')

    # Переходим к вводу имени
    await callback.message.edit_text(
        f"🏷️ <b>Введите имя для этой ссылки:</b>\n\n"
        f"<b>Биржа:</b> {exchange_name}\n"
        f"<b>Основной URL:</b> <code>{url}</code>\n\n"
        f"Например: <i>\"Bybit Promotions\"</i> или <i>\"MEXC Launchpad\"</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
    await callback.answer()

@router.message(AddLinkStates.waiting_for_html_urls)
async def process_html_urls_input(message: Message, state: FSMContext):
    text = message.text.strip().lower()

    if text in ["готово", "done", "skip", "пропустить"]:
        # Переходим к вводу имени
        data = await state.get_data()
        exchange_name = data.get('exchange_name')
        url = data.get('url')
        html_urls = data.get('html_urls_list', [])

        await message.answer(
            f"✅ <b>HTML ссылки добавлены: {len(html_urls)}</b>\n\n"
            f"🏷️ <b>Введите имя для этой ссылки:</b>\n\n"
            f"<b>Биржа:</b> {exchange_name}\n"
            f"<b>Основной URL:</b> <code>{url}</code>\n\n"
            f"Например: <i>\"Bybit Promotions\"</i> или <i>\"MEXC Launchpad\"</i>",
            parse_mode="HTML"
        )
        await state.set_state(AddLinkStates.waiting_for_name)
        return

    # Парсим ссылки
    urls = [url.strip() for url in message.text.replace(',', ' ').split() if url.strip().startswith('http')]

    if not urls:
        await message.answer("❌ Не найдено валидных URL. Попробуйте снова или отправьте 'готово':")
        return

    data = await state.get_data()
    html_urls_list = data.get('html_urls_list', [])
    html_urls_list.extend(urls)
    await state.update_data(html_urls_list=html_urls_list)

    await message.answer(
        f"✅ <b>Добавлено {len(urls)} HTML ссылок</b>\n"
        f"Всего HTML ссылок: {len(html_urls_list)}\n\n"
        f"Отправьте еще ссылки или <b>\"готово\"</b> для продолжения.",
        parse_mode="HTML"
    )

@router.message(AddLinkStates.waiting_for_name)
async def process_name_input(message: Message, state: FSMContext):
    custom_name = message.text.strip()

    if not custom_name:
        await message.answer("❌ Имя не может быть пустым. Пожалуйста, введите имя:")
        return

    if len(custom_name) > 100:
        await message.answer("❌ Имя слишком длинное (максимум 100 символов). Введите другое имя:")
        return

    await state.update_data(custom_name=custom_name)

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
        f"⏰ <b>Выберите интервал проверки для ссылки:</b>\n\n"
        f"<b>Имя:</b> {custom_name}\n\n"
        f"Как часто проверять эту ссылку на новые промоакции?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AddLinkStates.waiting_for_interval)

@router.callback_query(AddLinkStates.waiting_for_interval, F.data.startswith("add_interval_"))
async def process_interval_selection(callback: CallbackQuery, state: FSMContext):
    try:
        interval_seconds = int(callback.data.split("_")[2])
        data = await state.get_data()
        url = data.get('url')
        custom_name = data.get('custom_name')
        exchange_name = data.get('exchange_name')
        api_urls_list = data.get('api_urls_list', [])
        html_urls_list = data.get('html_urls_list', [])

        def add_link_operation(session):
            new_link = ApiLink(
                name=custom_name,
                url=url,
                exchange=exchange_name,
                check_interval=interval_seconds,
                added_by=callback.from_user.id
            )
            # Сохраняем множественные URL
            new_link.set_api_urls(api_urls_list)
            new_link.set_html_urls(html_urls_list)
            session.add(new_link)
            session.flush()
            return new_link

        new_link = atomic_operation(add_link_operation)

        interval_minutes = interval_seconds // 60

        # Формируем детальное сообщение
        message_parts = [
            "✅ <b>Ссылка успешно добавлена!</b>\n",
            f"<b>Имя:</b> {custom_name}\n",
            f"<b>Биржа:</b> {exchange_name}\n",
            f"<b>Интервал проверки:</b> {interval_minutes} минут\n",
            f"<b>Основной URL:</b> <code>{url}</code>\n"
        ]

        if api_urls_list:
            message_parts.append(f"\n<b>📡 API URLs ({len(api_urls_list)}):</b>\n")
            for i, api_url in enumerate(api_urls_list[:3], 1):
                message_parts.append(f"{i}. <code>{api_url}</code>\n")
            if len(api_urls_list) > 3:
                message_parts.append(f"... и еще {len(api_urls_list) - 3} URL\n")

        if html_urls_list:
            message_parts.append(f"\n<b>🌐 HTML URLs ({len(html_urls_list)}):</b>\n")
            for i, html_url in enumerate(html_urls_list[:3], 1):
                message_parts.append(f"{i}. <code>{html_url}</code>\n")
            if len(html_urls_list) > 3:
                message_parts.append(f"... и еще {len(html_urls_list) - 3} URL\n")

        message_parts.append(f"\n<b>Система FALLBACK активирована!</b>\n")
        message_parts.append(f"Бот автоматически выберет лучший метод парсинга.")

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
    try:
        with get_db_session() as db:
            links = db.query(ApiLink).all()
            
            if not links:
                await message.answer("❌ У вас нет ссылок для управления")
                return
            
            user_selections[message.from_user.id] = links
            keyboard = get_management_keyboard()
            
            await message.answer(
                "⚙️ <b>Управление ссылками:</b>\n\n"
                "Выберите действие для управления вашими ссылками:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка при управлении ссылками: {e}")
        await message.answer("❌ Ошибка при управлении ссылками")

@router.callback_query(F.data == "manage_delete")
async def manage_delete(callback: CallbackQuery):
    try:
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
                    'check_interval': link.check_interval
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
                f"<b>Биржа:</b> {link.exchange}\n"
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
            link_exchange = link.exchange
            session.delete(link)
            return link_name, link_exchange

        link_name, link_exchange = atomic_operation(delete_link_operation)
        
        await callback.message.edit_text(
            f"✅ <b>Ссылка успешно удалена!</b>\n\n"
            f"<b>Название:</b> {link_name}\n"
            f"<b>Биржа:</b> {link_exchange}\n\n"
            f"Ссылка больше не будет проверяться.",
            parse_mode="HTML"
        )
        
        if callback.from_user.id in user_selections:
            del user_selections[callback.from_user.id]
        
        await callback.answer("✅ Ссылка удалена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении ссылки")
        await callback.answer()

@router.callback_query(F.data.in_(["cancel_action", "manage_cancel"]))
async def process_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Действие отменено")
    if callback.from_user.id in user_selections:
        del user_selections[callback.from_user.id]
    await callback.answer()

@router.callback_query(F.data == "manage_interval")
async def manage_interval(callback: CallbackQuery):
    try:
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
                    'check_interval': link.check_interval
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
                    'check_interval': link.check_interval
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

        await message.answer(
            f"✅ <b>Ссылка успешно переименована!</b>\n\n"
            f"<b>Старое имя:</b> {current_name}\n"
            f"<b>Новое имя:</b> {new_name}\n"
            f"<b>Биржа:</b> {exchange}",
            parse_mode="HTML"
        )

        await state.clear()

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
        await callback.message.edit_text(
            f"✅ <b>Интервал обновлен!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n"
            f"<b>Новый интервал:</b> {interval_seconds} сек ({interval_minutes} мин)\n\n"
            f"Теперь проверка будет выполняться каждые {interval_minutes} минут.",
            parse_mode="HTML"
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

        await callback.message.edit_text(
            f"⏸️ <b>Парсинг остановлен!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n\n"
            f"Эта ссылка больше не будет проверяться автоматически.\n"
            f"Используйте <b>\"▶️ Возобновить парсинг\"</b> для активации.",
            parse_mode="HTML"
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

        await callback.message.edit_text(
            f"▶️ <b>Парсинг возобновлен!</b>\n\n"
            f"<b>Ссылка:</b> {link_name}\n\n"
            f"Эта ссылка снова будет проверяться автоматически.",
            parse_mode="HTML"
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
                    'check_interval': link.check_interval
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

        await callback.answer("✅ Проверка завершена")

    except Exception as e:
        logger.error(f"❌ Ошибка при принудительной проверке ссылки: {e}")
        await callback.message.edit_text("❌ Ошибка при принудительной проверке ссылки")
        await callback.answer()

@router.message(F.text == "🔄 Проверить все")
async def menu_check_all(message: Message):
    await message.answer("🔄 Начинаю проверку АКТИВНЫХ ссылок...")
    
    bot_instance = bot_manager.get_instance()
    if bot_instance:
        await bot_instance.manual_check_all_links(message.chat.id)
    else:
        await message.answer("❌ Бот не инициализирован")

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