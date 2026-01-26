from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_keyboard():
    """Основная клавиатура бота"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Список ссылок"), KeyboardButton(text="➕ Добавить ссылку")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🔄 Проверить все")],
            [KeyboardButton(text="📋 История промоакций"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard

def get_links_keyboard(links):
    """Клавиатура для управления ссылками"""
    builder = InlineKeyboardBuilder()
    
    for link in links:
        status = "✅" if link.is_active else "❌"
        builder.add(InlineKeyboardButton(
            text=f"{status} {link.name} ({link.check_interval}с)",
            callback_data=f"link_{link.id}"
        ))
    
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu"))
    builder.adjust(1)
    return builder.as_markup()

def get_link_actions_keyboard(link_id):
    """Клавиатура действий для конкретной ссылки"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="⚡ Тестировать", callback_data=f"test_{link_id}"))
    builder.add(InlineKeyboardButton(text="⏱ Интервал", callback_data=f"interval_{link_id}"))
    builder.add(InlineKeyboardButton(text="🔍 Фильтр", callback_data=f"filter_{link_id}"))
    builder.add(InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{link_id}"))
    
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_links"))
    builder.adjust(2)
    return builder.as_markup()

def get_interval_keyboard(link_id):
    """Клавиатура для выбора интервала"""
    builder = InlineKeyboardBuilder()
    
    intervals = [
        ("1 мин", 60),
        ("5 мин", 300),
        ("15 мин", 900),
        ("30 мин", 1800),
        ("1 час", 3600),
        ("6 часов", 21600)
    ]
    
    for text, seconds in intervals:
        builder.add(InlineKeyboardButton(
            text=text,
            callback_data=f"set_interval_{link_id}_{seconds}"
        ))
    
    builder.add(InlineKeyboardButton(text="✏️ Ввести вручную", callback_data=f"custom_interval_{link_id}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_link_{link_id}"))
    builder.adjust(2)
    return builder.as_markup()

def get_back_keyboard(target: str = "main"):
    """Простая кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_{target}"))
    return builder.as_markup()

def get_confirmation_keyboard(action: str, item_id: int):
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}_{item_id}"))
    builder.add(InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_{action}_{item_id}"))
    
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


# =============================================================================
# EXCHANGE CREDENTIALS KEYBOARDS
# =============================================================================

def get_exchange_credentials_menu_keyboard():
    """Главное меню управления API ключами бирж"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="➕ Добавить ключи", callback_data="exchange_cred_add"))
    builder.add(InlineKeyboardButton(text="📋 Список ключей", callback_data="exchange_cred_list"))
    builder.add(InlineKeyboardButton(text="✅ Проверить все", callback_data="exchange_cred_verify_all"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="exchange_cred_stats"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="settings_menu"))
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_exchange_select_keyboard():
    """Клавиатура выбора биржи для добавления ключей"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="🟡 Bybit",
        callback_data="exchange_select_bybit"
    ))
    builder.add(InlineKeyboardButton(
        text="🟢 Kucoin",
        callback_data="exchange_select_kucoin"
    ))
    builder.add(InlineKeyboardButton(
        text="⚫ OKX",
        callback_data="exchange_select_okx"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="exchange_cred_menu"
    ))
    
    builder.adjust(3, 1)
    return builder.as_markup()


def get_exchange_credentials_list_keyboard(credentials: list):
    """
    Клавиатура со списком API ключей
    
    Args:
        credentials: Список словарей с данными о ключах
    """
    builder = InlineKeyboardBuilder()
    
    for cred in credentials:
        status = "✅" if cred['is_verified'] else "❓"
        active = "🟢" if cred['is_active'] else "🔴"
        exchange_icon = {
            'bybit': '🟡',
            'kucoin': '🟢',
            'okx': '⚫'
        }.get(cred['exchange'], '⚪')
        
        builder.add(InlineKeyboardButton(
            text=f"{active}{status} {exchange_icon} {cred['name']}",
            callback_data=f"exchange_cred_view_{cred['id']}"
        ))
    
    if not credentials:
        builder.add(InlineKeyboardButton(
            text="📝 Ключи не добавлены",
            callback_data="exchange_cred_add"
        ))
    
    builder.add(InlineKeyboardButton(text="➕ Добавить", callback_data="exchange_cred_add"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="exchange_cred_menu"))
    
    builder.adjust(1)
    return builder.as_markup()


def get_exchange_credential_actions_keyboard(credential_id: int, is_verified: bool = False):
    """Клавиатура действий для конкретных API ключей"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="✅ Проверить" if not is_verified else "🔄 Перепроверить",
        callback_data=f"exchange_cred_verify_{credential_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="📊 Статистика",
        callback_data=f"exchange_cred_stats_{credential_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔴 Деактивировать",
        callback_data=f"exchange_cred_toggle_{credential_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🗑️ Удалить",
        callback_data=f"exchange_cred_delete_{credential_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 К списку",
        callback_data="exchange_cred_list"
    ))
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_exchange_delete_confirm_keyboard(credential_id: int):
    """Подтверждение удаления API ключей"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="✅ Да, удалить",
        callback_data=f"exchange_cred_confirm_delete_{credential_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"exchange_cred_view_{credential_id}"
    ))
    
    builder.adjust(2)
    return builder.as_markup()


def get_cancel_exchange_keyboard():
    """Кнопка отмены при добавлении ключей"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="exchange_cred_menu"))
    return builder.as_markup()


# =============================================================================
# ТОП АКТИВНОСТИ KEYBOARDS
# =============================================================================

def get_top_activity_menu_keyboard():
    """Главное меню раздела ТОП АКТИВНОСТИ"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text="🔥 Стейкинги", callback_data="top_activity_stakings"))
    builder.add(InlineKeyboardButton(text="🎁 Промоакции", callback_data="top_activity_promos"))
    builder.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_activity_refresh"))
    builder.add(InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_main_menu"))
    
    builder.adjust(2, 2)
    return builder.as_markup()


def get_top_stakings_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Клавиатура для просмотра ТОП стейкингов"""
    builder = InlineKeyboardBuilder()
    
    # Навигация по страницам
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="top_stakings_prev"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="top_stakings_info"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="top_stakings_next"))
    
    for btn in nav_buttons:
        builder.add(btn)
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_activity_stakings"))
    builder.add(InlineKeyboardButton(text="🔙 ТОП Меню", callback_data="top_activity_menu"))
    
    # Расположение: навигация в одну строку, остальное по 2
    if len(nav_buttons) == 3:
        builder.adjust(3, 2)
    elif len(nav_buttons) == 2:
        builder.adjust(2, 2)
    else:
        builder.adjust(1, 2)
    
    return builder.as_markup()


def get_top_promos_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Клавиатура для просмотра ТОП промоакций"""
    builder = InlineKeyboardBuilder()
    
    # Навигация по страницам
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="top_promos_prev"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="top_promos_info"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="top_promos_next"))
    
    for btn in nav_buttons:
        builder.add(btn)
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_activity_promos"))
    builder.add(InlineKeyboardButton(text="🔙 ТОП Меню", callback_data="top_activity_menu"))
    
    # Расположение
    if len(nav_buttons) == 3:
        builder.adjust(3, 2)
    elif len(nav_buttons) == 2:
        builder.adjust(2, 2)
    else:
        builder.adjust(1, 2)
    
    return builder.as_markup()


# =============================================================================
# PROMO CATEGORIES KEYBOARDS
# =============================================================================

def get_promo_categories_keyboard(counts: dict) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора категории промоакций.
    
    Args:
        counts: dict с количеством промо в каждой категории
                {'airdrop': 5, 'candybomb': 3, 'launchpad': 2, 'launchpool': 1, 'other': 10}
    """
    builder = InlineKeyboardBuilder()
    
    # Категории с иконками
    categories = [
        ("airdrop", "🪂", "Аирдропы"),
        ("candybomb", "🍬", "Кендибомбы"),
        ("launchpad", "🚀", "Лаунчпады"),
        ("launchpool", "🌊", "Лаунчпулы"),
        ("other", "🗂️", "Другие"),
    ]
    
    # Создаём кнопки в сетке 2x2 + 1
    for cat_key, icon, name in categories:
        count = counts.get(cat_key, 0)
        builder.add(InlineKeyboardButton(
            text=f"{icon} {name} ({count})",
            callback_data=f"top_promos_{cat_key}"
        ))
    
    # Кнопки навигации
    builder.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_promos_categories_refresh"))
    builder.add(InlineKeyboardButton(text="🔙 ТОП Меню", callback_data="top_activity_menu"))
    
    # Расположение: 2-2-1-2
    builder.adjust(2, 2, 1, 2)
    
    return builder.as_markup()


def get_category_promos_keyboard(
    category: str,
    current_page: int, 
    total_pages: int
) -> InlineKeyboardMarkup:
    """
    Клавиатура для просмотра промоакций конкретной категории.
    
    Args:
        category: ключ категории (airdrop, candybomb, launchpad, launchpool, other)
        current_page: текущая страница
        total_pages: всего страниц
    """
    builder = InlineKeyboardBuilder()
    
    # Навигация по страницам
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️", 
            callback_data=f"top_promos_{category}_prev"
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text=f"📄 {current_page}/{total_pages}", 
        callback_data=f"top_promos_{category}_info"
    ))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(
            text="▶️", 
            callback_data=f"top_promos_{category}_next"
        ))
    
    for btn in nav_buttons:
        builder.add(btn)
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(
        text="🔄 Обновить", 
        callback_data=f"top_promos_{category}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Категории", 
        callback_data="top_promos_categories_menu"
    ))
    
    # Расположение
    if len(nav_buttons) == 3:
        builder.adjust(3, 2)
    elif len(nav_buttons) == 2:
        builder.adjust(2, 2)
    else:
        builder.adjust(1, 2)
    
    return builder.as_markup()


# =============================================================================
# AIRDROP MANAGEMENT KEYBOARDS (LEGACY - использует унифицированную клавиатуру из handlers.py)
# =============================================================================

def get_airdrop_management_keyboard(link=None):
    """
    Legacy функция для airdrop - перенаправляет на унифицированную клавиатуру.
    Если link не передан, создаёт fallback клавиатуру.
    """
    if link:
        # Импортируем из handlers для избежания циклического импорта
        from bot.handlers import get_unified_link_management_keyboard
        return get_unified_link_management_keyboard(link)
    
    # Fallback без link объекта
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🎁 Текущие промоакции", callback_data="manage_view_current_promos"))
    builder.add(InlineKeyboardButton(text="🔄 Сменить категорию", callback_data="manage_change_category"))
    builder.add(InlineKeyboardButton(text="⚙️ Настройки", callback_data="manage_settings_submenu"))
    builder.add(InlineKeyboardButton(text="⏸ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_link_list"))
    builder.adjust(1)
    return builder.as_markup()

def get_current_promos_keyboard(current_page: int, total_pages: int, last_updated: str = None) -> InlineKeyboardMarkup:
    """Клавиатура пагинации для текущих промоакций
    
    Args:
        current_page: Текущая страница
        total_pages: Всего страниц
        last_updated: Время последнего обновления (для отображения)
    """
    builder = InlineKeyboardBuilder()
    
    # Навигация
    if current_page > 1:
        builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data="promos_page_prev"))
    
    builder.add(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="promos_page_info"))
    
    if current_page < total_pages:
        builder.add(InlineKeyboardButton(text="Вперед ▶️", callback_data="promos_page_next"))
    
    # Принудительная проверка (запуск парсера)
    builder.add(InlineKeyboardButton(text="🔍 Принудительная проверка", callback_data="promos_force_parse"))
    
    # Настройки уведомлений
    builder.add(InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="notification_settings_show"))
    
    builder.add(InlineKeyboardButton(text="⬅️ К ссылке", callback_data="back_to_link_management"))
    
    builder.adjust(3, 1, 1, 1)
    return builder.as_markup()