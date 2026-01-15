"""
Хэндлеры для управления Telegram аккаунтами через интерфейс бота
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from bot.states import TelegramAccountStates
from utils.telegram_auth_manager import telegram_auth_manager
from data.models import TelegramAccount
from data.database import get_db_session
from datetime import datetime

logger = logging.getLogger(__name__)
router = Router()


def get_telegram_accounts_keyboard():
    """Клавиатура управления Telegram аккаунтами"""
    builder = InlineKeyboardBuilder()

    # Проверяем настройку API
    api_id, api_hash = telegram_auth_manager.get_api_credentials()

    if not api_id or not api_hash:
        # Если API не настроено - сначала настроить
        builder.add(InlineKeyboardButton(text="⚙️ Настроить API", callback_data="tg_setup_api"))
    else:
        # Если API настроено - показываем все опции
        builder.add(InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="tg_add_account"))
        builder.add(InlineKeyboardButton(text="📋 Мои аккаунты", callback_data="tg_list_accounts"))
        builder.add(InlineKeyboardButton(text="⚙️ Изменить API", callback_data="tg_setup_api"))

    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_bypass"))
    builder.adjust(2, 1)
    return builder.as_markup()


def get_account_list_keyboard(user_id: int):
    """Клавиатура со списком аккаунтов"""
    builder = InlineKeyboardBuilder()
    accounts = telegram_auth_manager.get_all_accounts(user_id)

    if accounts:
        for account in accounts:
            status_icon = "✅" if account['is_active'] else "❌"
            auth_icon = "🔓" if account['is_authorized'] else "🔒"
            text = f"{status_icon} {auth_icon} {account['name']} ({account['phone_number']})"
            builder.add(InlineKeyboardButton(
                text=text,
                callback_data=f"tg_acc_{account['id']}"
            ))

    builder.add(InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="tg_add_account"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="tg_main"))
    builder.adjust(1)
    return builder.as_markup()


def get_account_manage_keyboard(account_id: int, is_active: bool):
    """Клавиатура управления конкретным аккаунтом"""
    builder = InlineKeyboardBuilder()

    toggle_text = "⏸ Деактивировать" if is_active else "▶️ Активировать"
    builder.add(InlineKeyboardButton(text="🧪 Тест подключения", callback_data=f"tg_test_{account_id}"))
    builder.add(InlineKeyboardButton(text=toggle_text, callback_data=f"tg_toggle_{account_id}"))
    builder.add(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"tg_delete_{account_id}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="tg_list_accounts"))

    builder.adjust(1, 2, 1)
    return builder.as_markup()


@router.callback_query(F.data == "bypass_telegram")
async def bypass_telegram_handler(callback: CallbackQuery):
    """Главное меню управления Telegram аккаунтами (ЗАМЕНА старого bypass_telegram)"""
    try:
        keyboard = get_telegram_accounts_keyboard()

        # Проверяем настройку API
        api_id, api_hash = telegram_auth_manager.get_api_credentials()

        if not api_id or not api_hash:
            message = (
                "📱 <b>Управление Telegram аккаунтами</b>\n\n"
                "❌ <b>API не настроено</b>\n\n"
                "Для работы с Telegram необходимо:\n"
                "1. Создать приложение на https://my.telegram.org\n"
                "2. Получить API ID и API Hash\n"
                "3. Настроить их через кнопку ниже\n\n"
                "После настройки API вы сможете добавлять аккаунты."
            )
        else:
            # Получаем статистику
            accounts = telegram_auth_manager.get_all_accounts(callback.from_user.id)
            total = len(accounts)
            active = sum(1 for acc in accounts if acc['is_active'])
            authorized = sum(1 for acc in accounts if acc['is_authorized'])

            message = (
                "📱 <b>Управление Telegram аккаунтами</b>\n\n"
                "✅ <b>API настроено</b>\n\n"
                f"<b>Статистика:</b>\n"
                f"• Всего аккаунтов: {total}\n"
                f"• Активных: {active}\n"
                f"• Авторизованных: {authorized}\n\n"
                f"<b>API ID:</b> <code>{api_id}</code>\n\n"
                "Выберите действие:"
            )

        await callback.message.edit_text(
            message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка показа меню Telegram аккаунтов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки меню")


@router.callback_query(F.data == "tg_main")
async def tg_main_menu(callback: CallbackQuery):
    """Возврат в главное меню Telegram аккаунтов"""
    await bypass_telegram_handler(callback)


@router.callback_query(F.data == "tg_setup_api")
async def tg_setup_api(callback: CallbackQuery, state: FSMContext):
    """Начать настройку API"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))

    await callback.message.edit_text(
        "⚙️ <b>Настройка Telegram API</b>\n\n"
        "Для получения API ID и API Hash:\n\n"
        "1. Перейдите на https://my.telegram.org\n"
        "2. Войдите с вашим номером телефона\n"
        "3. Перейдите в 'API development tools'\n"
        "4. Создайте приложение (любые название и описание)\n"
        "5. Скопируйте <b>api_id</b> (число)\n\n"
        "Введите ваш <b>API ID</b>:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAccountStates.waiting_for_api_id)
    await callback.answer()


@router.message(TelegramAccountStates.waiting_for_api_id)
async def process_api_id(message: Message, state: FSMContext):
    """Обработка API ID"""
    api_id = message.text.strip()

    # Проверяем что это число
    if not api_id.isdigit():
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))
        await message.answer(
            "❌ API ID должен быть числом. Попробуйте еще раз:",
            reply_markup=builder.as_markup()
        )
        return

    # Сохраняем в FSM
    await state.update_data(api_id=api_id)

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))

    await message.answer(
        "✅ API ID сохранен\n\n"
        "Теперь введите <b>API Hash</b>:\n"
        "(длинная строка символов)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAccountStates.waiting_for_api_hash)


@router.message(TelegramAccountStates.waiting_for_api_hash)
async def process_api_hash(message: Message, state: FSMContext):
    """Обработка API Hash"""
    api_hash = message.text.strip()

    # Получаем API ID из FSM
    data = await state.get_data()
    api_id = data.get('api_id')

    # Сохраняем в БД
    success = telegram_auth_manager.save_api_credentials(api_id, api_hash)

    if success:
        keyboard = get_telegram_accounts_keyboard()
        await message.answer(
            "✅ <b>API успешно настроено!</b>\n\n"
            f"API ID: <code>{api_id}</code>\n"
            f"API Hash: <code>{api_hash[:8]}...</code>\n\n"
            "Теперь вы можете добавлять аккаунты для парсинга.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))
        await message.answer(
            "❌ Ошибка сохранения API. Попробуйте еще раз:",
            reply_markup=builder.as_markup()
        )
        return

    await state.clear()


@router.callback_query(F.data == "tg_cancel_setup")
async def tg_cancel_setup(callback: CallbackQuery, state: FSMContext):
    """Отмена настройки API или добавления аккаунта"""
    await state.clear()
    await callback.answer("❌ Действие отменено")
    # Возвращаемся в главное меню Telegram аккаунтов
    await bypass_telegram_handler(callback)


@router.callback_query(F.data == "tg_add_account")
async def tg_add_account(callback: CallbackQuery, state: FSMContext):
    """Начать добавление аккаунта"""
    # Проверяем настройку API
    api_id, api_hash = telegram_auth_manager.get_api_credentials()

    if not api_id or not api_hash:
        await callback.answer("❌ Сначала настройте API!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))

    await callback.message.edit_text(
        "➕ <b>Добавление Telegram аккаунта</b>\n\n"
        "Введите название для аккаунта:\n"
        "(например: 'Основной', 'Рабочий', 'Парсер 1')",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAccountStates.waiting_for_account_name)
    await callback.answer()


@router.message(TelegramAccountStates.waiting_for_account_name)
async def process_account_name(message: Message, state: FSMContext):
    """Обработка названия аккаунта"""
    account_name = message.text.strip()

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))

    if len(account_name) < 2:
        await message.answer(
            "❌ Название слишком короткое. Введите минимум 2 символа:",
            reply_markup=builder.as_markup()
        )
        return

    await state.update_data(account_name=account_name)

    await message.answer(
        f"✅ Название: <b>{account_name}</b>\n\n"
        "Теперь введите <b>номер телефона</b> в международном формате:\n"
        "(например: +1234567890)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(TelegramAccountStates.waiting_for_phone_number)


@router.message(TelegramAccountStates.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext):
    """Обработка номера телефона и отправка кода"""
    phone_number = message.text.strip()

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="tg_cancel_setup"))

    # Проверяем формат
    if not phone_number.startswith('+') or not phone_number[1:].replace(' ', '').isdigit():
        await message.answer(
            "❌ Неверный формат номера.\n"
            "Используйте международный формат: +1234567890",
            reply_markup=builder.as_markup()
        )
        return

    # Получаем данные из FSM
    data = await state.get_data()
    account_name = data.get('account_name')

    # Показываем процесс
    status_msg = await message.answer("⏳ Отправка кода...")

    # Начинаем процесс авторизации
    success, msg = await telegram_auth_manager.start_auth(
        user_id=message.from_user.id,
        account_name=account_name,
        phone_number=phone_number
    )

    if success:
        await state.update_data(phone_number=phone_number)
        await status_msg.edit_text(
            f"✅ {msg}\n\n"
            f"Проверьте Telegram на номере <code>{phone_number}</code>\n\n"
            f"<b>Важно:</b> У вас 3 попытки ввода кода!",
            parse_mode="HTML"
        )
        await state.set_state(TelegramAccountStates.waiting_for_verification_code)
    else:
        await status_msg.edit_text(f"❌ {msg}")
        await state.clear()


@router.message(TelegramAccountStates.waiting_for_verification_code)
async def process_verification_code(message: Message, state: FSMContext):
    """Обработка кода подтверждения"""
    code = message.text.strip().replace(' ', '').replace('-', '')

    # Показываем процесс
    status_msg = await message.answer("⏳ Проверка кода...")

    # Проверяем код
    success, msg, needs_password = await telegram_auth_manager.verify_code(
        user_id=message.from_user.id,
        code=code
    )

    if success:
        # Успешная авторизация
        keyboard = get_telegram_accounts_keyboard()
        await status_msg.edit_text(
            f"✅ {msg}\n\n"
            "Аккаунт успешно добавлен и готов к использованию!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()

    elif needs_password:
        # Требуется 2FA пароль
        await status_msg.edit_text(
            f"🔐 {msg}",
            parse_mode="HTML"
        )
        await state.set_state(TelegramAccountStates.waiting_for_password)

    else:
        # Ошибка
        await status_msg.edit_text(f"❌ {msg}", parse_mode="HTML")
        # Не очищаем state - даем еще попытки


@router.message(TelegramAccountStates.waiting_for_password)
async def process_2fa_password(message: Message, state: FSMContext):
    """Обработка пароля 2FA"""
    password = message.text.strip()

    # Показываем процесс
    status_msg = await message.answer("⏳ Проверка пароля...")

    # Проверяем пароль
    success, msg = await telegram_auth_manager.verify_password(
        user_id=message.from_user.id,
        password=password
    )

    if success:
        keyboard = get_telegram_accounts_keyboard()
        await status_msg.edit_text(
            f"✅ {msg}\n\n"
            "Аккаунт успешно добавлен и готов к использованию!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
    else:
        await status_msg.edit_text(f"❌ {msg}", parse_mode="HTML")


@router.callback_query(F.data == "tg_list_accounts")
async def tg_list_accounts(callback: CallbackQuery):
    """Показать список аккаунтов"""
    try:
        accounts = telegram_auth_manager.get_all_accounts(callback.from_user.id)
        keyboard = get_account_list_keyboard(callback.from_user.id)

        if accounts:
            accounts_text = []
            for acc in accounts:
                status = "✅ Активен" if acc['is_active'] else "❌ Неактивен"
                auth = "🔓 Авторизован" if acc['is_authorized'] else "🔒 Не авторизован"
                last_used = acc['last_used'].strftime("%d.%m.%Y %H:%M") if acc['last_used'] else "Никогда"

                accounts_text.append(
                    f"<b>{acc['name']}</b>\n"
                    f"📱 {acc['phone_number']}\n"
                    f"{status} | {auth}\n"
                    f"📊 Сообщений: {acc['messages_parsed']}\n"
                    f"🕐 Последнее использование: {last_used}"
                )

            message = (
                "📋 <b>Ваши Telegram аккаунты</b>\n\n"
                + "\n\n".join(accounts_text) +
                "\n\nВыберите аккаунт для управления:"
            )
        else:
            message = (
                "📋 <b>Ваши Telegram аккаунты</b>\n\n"
                "❌ У вас пока нет добавленных аккаунтов.\n\n"
                "Добавьте аккаунт для начала работы."
            )

        await callback.message.edit_text(
            message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка показа списка аккаунтов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки списка")


@router.callback_query(F.data.startswith("tg_acc_"))
async def tg_manage_account(callback: CallbackQuery):
    """Управление конкретным аккаунтом"""
    try:
        account_id = int(callback.data.split("_")[2])

        # Получаем данные аккаунта
        with get_db_session() as db:
            from data.models import ApiLink
            from sqlalchemy import func
            
            account = db.query(TelegramAccount).filter_by(
                id=account_id,
                added_by=callback.from_user.id
            ).first()

            if not account:
                await callback.answer("❌ Аккаунт не найден", show_alert=True)
                return

            # Подсчет назначенных ссылок
            assigned_links_count = db.query(func.count(ApiLink.id)).filter(
                ApiLink.telegram_account_id == account_id,
                ApiLink.parsing_type == 'telegram'
            ).scalar() or 0
            
            # Подсчет активных ссылок
            active_links_count = db.query(func.count(ApiLink.id)).filter(
                ApiLink.telegram_account_id == account_id,
                ApiLink.parsing_type == 'telegram',
                ApiLink.is_active == True
            ).scalar() or 0

            status = "✅ Активен" if account.is_active else "❌ Неактивен"
            auth = "🔓 Авторизован" if account.is_authorized else "🔒 Не авторизован"
            last_used = account.last_used.strftime("%d.%m.%Y %H:%M") if account.last_used else "Никогда"
            error = f"\n\n⚠️ <b>Последняя ошибка:</b>\n{account.last_error}" if account.last_error else ""

            keyboard = get_account_manage_keyboard(account_id, account.is_active)

            await callback.message.edit_text(
                f"📱 <b>Аккаунт: {account.name}</b>\n\n"
                f"<b>Номер:</b> <code>{account.phone_number}</code>\n"
                f"<b>Статус:</b> {status}\n"
                f"<b>Авторизация:</b> {auth}\n\n"
                f"<b>Статистика:</b>\n"
                f"• Назначено ссылок: {assigned_links_count} (активных: {active_links_count})\n"
                f"• Сообщений обработано: {account.messages_parsed}\n"
                f"• Последнее использование: {last_used}\n"
                f"• Создан: {account.created_at.strftime('%d.%m.%Y %H:%M')}"
                f"{error}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка управления аккаунтом: {e}", exc_info=True)
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("tg_toggle_"))
async def tg_toggle_account(callback: CallbackQuery):
    """Активировать/деактивировать аккаунт"""
    try:
        account_id = int(callback.data.split("_")[2])

        success, msg, new_state = telegram_auth_manager.toggle_account(
            account_id=account_id,
            user_id=callback.from_user.id
        )

        if success:
            await callback.answer(msg, show_alert=True)
            # Обновляем отображение
            await tg_manage_account(callback)
        else:
            await callback.answer(f"❌ {msg}", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка переключения аккаунта: {e}", exc_info=True)
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("tg_delete_"))
async def tg_delete_account(callback: CallbackQuery):
    """Удалить аккаунт"""
    try:
        account_id = int(callback.data.split("_")[2])

        # Спрашиваем подтверждение
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"tg_confirm_del_{account_id}"))
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"tg_acc_{account_id}"))
        builder.adjust(1)

        await callback.message.edit_text(
            "⚠️ <b>Подтвердите удаление</b>\n\n"
            "Вы уверены, что хотите удалить этот аккаунт?\n"
            "Файл сессии также будет удален.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка удаления аккаунта: {e}", exc_info=True)
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("tg_confirm_del_"))
async def tg_confirm_delete(callback: CallbackQuery):
    """Подтверждение удаления аккаунта"""
    try:
        account_id = int(callback.data.split("_")[3])

        success, msg = telegram_auth_manager.delete_account(
            account_id=account_id,
            user_id=callback.from_user.id
        )

        if success:
            await callback.answer(msg, show_alert=True)
            # Возвращаемся к списку
            await tg_list_accounts(callback)
        else:
            await callback.answer(f"❌ {msg}", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка подтверждения удаления: {e}", exc_info=True)
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("tg_test_"))
async def tg_test_account(callback: CallbackQuery):
    """Тестирование аккаунта"""
    try:
        account_id = int(callback.data.split("_")[2])

        # Показываем процесс
        await callback.answer("⏳ Подключение к Telegram...", show_alert=False)

        # Тестируем аккаунт
        success, message = await telegram_auth_manager.test_account(
            account_id=account_id,
            user_id=callback.from_user.id
        )

        # Показываем результат
        if success:
            await callback.message.answer(message, parse_mode="HTML")
            await callback.answer("✅ Тест завершен!")
        else:
            await callback.message.answer(f"❌ {message}", parse_mode="HTML")
            await callback.answer("❌ Тест не пройден")

    except Exception as e:
        logger.error(f"Ошибка теста аккаунта: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)
