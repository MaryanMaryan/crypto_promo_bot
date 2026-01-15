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
    
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
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