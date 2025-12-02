from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_keyboard():
    \"\"\"Основная клавиатура бота\"\"\"
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=\"📊 Список ссылок\"), KeyboardButton(text=\"➕ Добавить ссылку\")],
            [KeyboardButton(text=\"⚙️ Настройки\"), KeyboardButton(text=\"🔄 Проверить все\")],
            [KeyboardButton(text=\"📋 История промоакций\"), KeyboardButton(text=\"❓ Помощь\")]
        ],
        resize_keyboard=True,
        input_field_placeholder=\"Выберите действие...\"
    )
    return keyboard

def get_links_keyboard(links):
    \"\"\"Клавиатура для управления ссылками\"\"\"
    builder = InlineKeyboardBuilder()
    
    for link in links:
        status = \"✅\" if link.is_active else \"❌\"
        builder.add(InlineKeyboardButton(
            text=f\"{status} {link.name} ({link.check_interval}с)\",
            callback_data=f\"link_{link.id}\"
        ))
    
    builder.add(InlineKeyboardButton(text=\"🔙 Назад\", callback_data=\"back_to_main\"))
    builder.adjust(1)
    return builder.as_markup()

def get_link_actions_keyboard(link_id):
    \"\"\"Клавиатура действий для конкретной ссылки\"\"\"
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text=\"⚡ Тестировать\", callback_data=f\"test_{link_id}\"))
    builder.add(InlineKeyboardButton(text=\"⏱ Интервал\", callback_data=f\"interval_{link_id}\"))
    builder.add(InlineKeyboardButton(text=\"🔍 Фильтр\", callback_data=f\"filter_{link_id}\"))
    builder.add(InlineKeyboardButton(text=\"❌ Удалить\", callback_data=f\"delete_{link_id}\"))
    
    builder.add(InlineKeyboardButton(text=\"🔙 Назад\", callback_data=\"back_to_links\"))
    builder.adjust(2)
    return builder.as_markup()

def get_interval_keyboard(link_id):
    \"\"\"Клавиатура для выбора интервала\"\"\"
    builder = InlineKeyboardBuilder()
    
    intervals = [
        (\"1 мин\", 60),
        (\"5 мин\", 300),
        (\"15 мин\", 900),
        (\"30 мин\", 1800),
        (\"1 час\", 3600),
        (\"6 часов\", 21600)
    ]
    
    for text, seconds in intervals:
        builder.add(InlineKeyboardButton(
            text=text,
            callback_data=f\"set_interval_{link_id}_{seconds}\"
        ))
    
    builder.add(InlineKeyboardButton(text=\"✏️ Ввести вручную\", callback_data=f\"custom_interval_{link_id}\"))
    builder.add(InlineKeyboardButton(text=\"🔙 Назад\", callback_data=f\"back_to_link_{link_id}\"))
    builder.adjust(2)
    return builder.as_markup()

def get_back_keyboard(target: str = \"main\"):
    \"\"\"Простая кнопка назад\"\"\"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=\"🔙 Назад\", callback_data=f\"back_to_{target}\"))
    return builder.as_markup()

def get_confirmation_keyboard(action: str, item_id: int):
    \"\"\"Клавиатура подтверждения действия\"\"\"
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(text=\"✅ Да\", callback_data=f\"confirm_{action}_{item_id}\"))
    builder.add(InlineKeyboardButton(text=\"❌ Нет\", callback_data=f\"cancel_{action}_{item_id}\"))
    
    return builder.as_markup()
