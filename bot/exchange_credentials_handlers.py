"""
bot/exchange_credentials_handlers.py
Хендлеры для управления API ключами бирж (Bybit, Kucoin, OKX)
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime

from data.database import get_db_session
from data.models import ExchangeCredentials
from bot.states import ExchangeCredentialsStates
from bot.keyboards import (
    get_exchange_credentials_menu_keyboard,
    get_exchange_select_keyboard,
    get_exchange_credentials_list_keyboard,
    get_exchange_credential_actions_keyboard,
    get_exchange_delete_confirm_keyboard,
    get_cancel_exchange_keyboard,
)
from utils.exchange_auth_manager import get_exchange_auth_manager

router = Router()
logger = logging.getLogger(__name__)

# Временное хранилище для данных при добавлении ключей
_temp_credentials = {}

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный вызов callback.answer()"""
    try:
        from aiogram.exceptions import TelegramBadRequest
        if text:
            await callback.answer(text, show_alert=show_alert)
        else:
            await callback.answer()
    except Exception as e:
        if "query is too old" in str(e):
            pass
        else:
            logger.warning(f"Callback answer error: {e}")


def get_exchange_icon(exchange: str) -> str:
    """Получить иконку биржи"""
    return {
        'bybit': '🟡',
        'kucoin': '🟢',
        'okx': '⚫'
    }.get(exchange.lower(), '⚪')


def get_exchange_name(exchange: str) -> str:
    """Получить человекочитаемое название биржи"""
    return {
        'bybit': 'Bybit',
        'kucoin': 'Kucoin', 
        'okx': 'OKX'
    }.get(exchange.lower(), exchange.capitalize())


# =============================================================================
# ГЛАВНОЕ МЕНЮ API КЛЮЧЕЙ
# =============================================================================

@router.callback_query(F.data == "exchange_cred_menu")
async def show_exchange_credentials_menu(callback: CallbackQuery, state: FSMContext):
    """Показать главное меню управления API ключами"""
    await state.clear()
    
    auth_manager = get_exchange_auth_manager()
    configured = auth_manager.get_configured_exchanges()
    
    if configured:
        status_text = f"✅ Настроено: {', '.join([get_exchange_name(e) for e in configured])}"
    else:
        status_text = "⚠️ API ключи не настроены"
    
    message = (
        "🔑 <b>API КЛЮЧИ БИРЖ</b>\n\n"
        f"{status_text}\n\n"
        "API ключи позволяют получить расширенные данные о стейкингах:\n"
        "• Лимиты на пользователя\n"
        "• Доступные квоты\n"
        "• Дополнительные детали продуктов\n\n"
        "⚠️ <b>Важно:</b> Создавайте ключи только с правами на <b>чтение (Read-Only)</b>!\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        message,
        reply_markup=get_exchange_credentials_menu_keyboard(),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


# =============================================================================
# ДОБАВЛЕНИЕ КЛЮЧЕЙ
# =============================================================================

@router.callback_query(F.data == "exchange_cred_add")
async def start_add_credentials(callback: CallbackQuery, state: FSMContext):
    """Начать добавление API ключей - выбор биржи"""
    message = (
        "➕ <b>ДОБАВЛЕНИЕ API КЛЮЧЕЙ</b>\n\n"
        "Выберите биржу:\n\n"
        "🟡 <b>Bybit</b>\n"
        "   └ https://www.bybit.com/app/user/api-management\n\n"
        "🟢 <b>Kucoin</b>\n"
        "   └ https://www.kucoin.com/account/api\n\n"
        "⚫ <b>OKX</b>\n"
        "   └ https://www.okx.com/account/my-api\n\n"
        "⚠️ При создании ключей выбирайте <b>только права на чтение</b>!"
    )
    
    await callback.message.edit_text(
        message,
        reply_markup=get_exchange_select_keyboard(),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("exchange_select_"))
async def select_exchange_for_add(callback: CallbackQuery, state: FSMContext):
    """Выбрана биржа - запрос названия"""
    exchange = callback.data.replace("exchange_select_", "")
    
    # Сохраняем выбранную биржу
    user_id = callback.from_user.id
    _temp_credentials[user_id] = {'exchange': exchange}
    
    exchange_name = get_exchange_name(exchange)
    exchange_icon = get_exchange_icon(exchange)
    
    message = (
        f"{exchange_icon} <b>ДОБАВЛЕНИЕ КЛЮЧЕЙ {exchange_name.upper()}</b>\n\n"
        f"<b>Шаг 1/4:</b> Введите название для этих ключей\n\n"
        f"Например: <code>Основной {exchange_name}</code> или <code>Рабочий аккаунт</code>\n\n"
        f"Это поможет различать несколько ключей для одной биржи."
    )
    
    await callback.message.edit_text(
        message,
        reply_markup=get_cancel_exchange_keyboard(),
        parse_mode="HTML"
    )
    
    await state.set_state(ExchangeCredentialsStates.waiting_for_name)
    await safe_answer_callback(callback)


@router.message(ExchangeCredentialsStates.waiting_for_name)
async def process_credential_name(message: Message, state: FSMContext):
    """Получено название - запрос API ключа"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    if len(name) < 2 or len(name) > 50:
        await message.answer(
            "❌ Название должно быть от 2 до 50 символов.\n\nВведите название ещё раз:",
            reply_markup=get_cancel_exchange_keyboard(),
            parse_mode="HTML"
        )
        return
    
    _temp_credentials[user_id]['name'] = name
    exchange = _temp_credentials[user_id]['exchange']
    exchange_name = get_exchange_name(exchange)
    
    message_text = (
        f"✅ Название: <b>{name}</b>\n\n"
        f"<b>Шаг 2/4:</b> Введите <b>API Key</b>\n\n"
        f"Скопируйте API Key из настроек {exchange_name} и отправьте его сюда.\n\n"
        f"⚠️ Сообщение с ключом будет удалено после обработки."
    )
    
    await message.answer(
        message_text,
        reply_markup=get_cancel_exchange_keyboard(),
        parse_mode="HTML"
    )
    
    await state.set_state(ExchangeCredentialsStates.waiting_for_api_key)


@router.message(ExchangeCredentialsStates.waiting_for_api_key)
async def process_api_key(message: Message, state: FSMContext):
    """Получен API Key - запрос API Secret"""
    user_id = message.from_user.id
    api_key = message.text.strip()
    
    # Удаляем сообщение с ключом для безопасности
    try:
        await message.delete()
    except:
        pass
    
    if len(api_key) < 10:
        await message.answer(
            "❌ API Key слишком короткий. Проверьте и введите ещё раз:",
            reply_markup=get_cancel_exchange_keyboard(),
            parse_mode="HTML"
        )
        return
    
    _temp_credentials[user_id]['api_key'] = api_key
    
    message_text = (
        f"✅ API Key получен: <code>{api_key[:6]}...{api_key[-4:]}</code>\n\n"
        f"<b>Шаг 3/4:</b> Введите <b>API Secret</b>\n\n"
        f"⚠️ Сообщение с секретом будет удалено после обработки."
    )
    
    await message.answer(
        message_text,
        reply_markup=get_cancel_exchange_keyboard(),
        parse_mode="HTML"
    )
    
    await state.set_state(ExchangeCredentialsStates.waiting_for_api_secret)


@router.message(ExchangeCredentialsStates.waiting_for_api_secret)
async def process_api_secret(message: Message, state: FSMContext):
    """Получен API Secret - запрос passphrase или завершение"""
    user_id = message.from_user.id
    api_secret = message.text.strip()
    
    # Удаляем сообщение с секретом
    try:
        await message.delete()
    except:
        pass
    
    if len(api_secret) < 10:
        await message.answer(
            "❌ API Secret слишком короткий. Проверьте и введите ещё раз:",
            reply_markup=get_cancel_exchange_keyboard(),
            parse_mode="HTML"
        )
        return
    
    _temp_credentials[user_id]['api_secret'] = api_secret
    exchange = _temp_credentials[user_id]['exchange']
    
    # Для Kucoin и OKX нужен passphrase
    if exchange in ['kucoin', 'okx']:
        message_text = (
            f"✅ API Secret получен\n\n"
            f"<b>Шаг 4/4:</b> Введите <b>Passphrase</b>\n\n"
            f"Passphrase - это секретная фраза, которую вы указали при создании API ключа.\n\n"
            f"⚠️ Сообщение будет удалено после обработки."
        )
        
        await message.answer(
            message_text,
            reply_markup=get_cancel_exchange_keyboard(),
            parse_mode="HTML"
        )
        
        await state.set_state(ExchangeCredentialsStates.waiting_for_passphrase)
    else:
        # Для Bybit passphrase не нужен - сразу сохраняем
        await save_credentials(message, state, user_id)


@router.message(ExchangeCredentialsStates.waiting_for_passphrase)
async def process_passphrase(message: Message, state: FSMContext):
    """Получен Passphrase - сохранение"""
    user_id = message.from_user.id
    passphrase = message.text.strip()
    
    # Удаляем сообщение
    try:
        await message.delete()
    except:
        pass
    
    _temp_credentials[user_id]['passphrase'] = passphrase
    
    await save_credentials(message, state, user_id)


async def save_credentials(message: Message, state: FSMContext, user_id: int):
    """Сохранить credentials в БД"""
    cred_data = _temp_credentials.get(user_id, {})
    
    if not cred_data:
        await message.answer("❌ Ошибка: данные не найдены. Начните заново.")
        await state.clear()
        return
    
    exchange = cred_data.get('exchange')
    name = cred_data.get('name')
    api_key = cred_data.get('api_key')
    api_secret = cred_data.get('api_secret')
    passphrase = cred_data.get('passphrase')
    
    # Отправляем сообщение о проверке
    status_msg = await message.answer("⏳ Проверяю API ключи...")
    
    # Проверяем ключи
    auth_manager = get_exchange_auth_manager()
    verify_result = auth_manager.verify_credentials(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase
    )
    
    # Сохраняем в БД
    with get_db_session() as session:
        result = auth_manager.add_credentials_to_db(
            db_session=session,
            exchange=exchange,
            name=name,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            added_by=user_id,
            verify=False  # Уже проверили выше
        )
        
        if result['success']:
            # Обновляем статус верификации
            cred = session.query(ExchangeCredentials).filter(
                ExchangeCredentials.id == result['data']['id']
            ).first()
            if cred:
                cred.is_verified = verify_result['success']
                cred.last_verified = datetime.utcnow() if verify_result['success'] else None
                session.commit()
    
    # Удаляем временные данные
    if user_id in _temp_credentials:
        del _temp_credentials[user_id]
    
    # Формируем ответ
    exchange_icon = get_exchange_icon(exchange)
    exchange_name = get_exchange_name(exchange)
    
    if verify_result['success']:
        message_text = (
            f"✅ <b>API КЛЮЧИ ДОБАВЛЕНЫ</b>\n\n"
            f"{exchange_icon} <b>Биржа:</b> {exchange_name}\n"
            f"📝 <b>Название:</b> {name}\n"
            f"🔑 <b>API Key:</b> <code>{api_key[:6]}...{api_key[-4:]}</code>\n"
            f"✅ <b>Статус:</b> Проверен и работает\n\n"
            f"{verify_result['message']}"
        )
    else:
        message_text = (
            f"⚠️ <b>API КЛЮЧИ ДОБАВЛЕНЫ, НО НЕ ВЕРИФИЦИРОВАНЫ</b>\n\n"
            f"{exchange_icon} <b>Биржа:</b> {exchange_name}\n"
            f"📝 <b>Название:</b> {name}\n"
            f"🔑 <b>API Key:</b> <code>{api_key[:6]}...{api_key[-4:]}</code>\n"
            f"❓ <b>Статус:</b> Не удалось проверить\n\n"
            f"{verify_result['message']}\n\n"
            f"Ключи сохранены. Вы можете попробовать проверить их позже."
        )
    
    await status_msg.edit_text(
        message_text,
        reply_markup=get_exchange_credentials_menu_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()


# =============================================================================
# СПИСОК КЛЮЧЕЙ
# =============================================================================

@router.callback_query(F.data == "exchange_cred_list")
async def show_credentials_list(callback: CallbackQuery, state: FSMContext):
    """Показать список API ключей"""
    auth_manager = get_exchange_auth_manager()
    
    with get_db_session() as session:
        credentials = auth_manager.get_all_credentials_from_db(session)
    
    if not credentials:
        message = (
            "📋 <b>СПИСОК API КЛЮЧЕЙ</b>\n\n"
            "У вас пока нет добавленных API ключей.\n\n"
            "Нажмите <b>➕ Добавить</b> чтобы добавить ключи."
        )
    else:
        message = (
            f"📋 <b>СПИСОК API КЛЮЧЕЙ</b>\n\n"
            f"Всего ключей: {len(credentials)}\n\n"
            f"Нажмите на ключи для просмотра деталей:"
        )
    
    await callback.message.edit_text(
        message,
        reply_markup=get_exchange_credentials_list_keyboard(credentials),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


# =============================================================================
# ПРОСМОТР ДЕТАЛЕЙ КЛЮЧА
# =============================================================================

@router.callback_query(F.data.startswith("exchange_cred_view_"))
async def view_credential_details(callback: CallbackQuery):
    """Просмотр деталей API ключа"""
    credential_id = int(callback.data.replace("exchange_cred_view_", ""))
    
    with get_db_session() as session:
        cred = session.query(ExchangeCredentials).filter(
            ExchangeCredentials.id == credential_id
        ).first()
        
        if not cred:
            await callback.message.edit_text(
                "❌ Ключи не найдены",
                reply_markup=get_exchange_credentials_menu_keyboard(),
                parse_mode="HTML"
            )
            await safe_answer_callback(callback)
            return
        
        exchange_icon = get_exchange_icon(cred.exchange)
        exchange_name = get_exchange_name(cred.exchange)
        
        status = "✅ Верифицирован" if cred.is_verified else "❓ Не проверен"
        active = "🟢 Активен" if cred.is_active else "🔴 Неактивен"
        
        last_used = "Никогда"
        if cred.last_used:
            last_used = cred.last_used.strftime("%d.%m.%Y %H:%M")
        
        last_verified = "Никогда"
        if cred.last_verified:
            last_verified = cred.last_verified.strftime("%d.%m.%Y %H:%M")
        
        success_rate = 0
        if cred.requests_count > 0:
            success_rate = round((cred.success_count / cred.requests_count) * 100, 1)
        
        message = (
            f"🔑 <b>ДЕТАЛИ API КЛЮЧА</b>\n\n"
            f"{exchange_icon} <b>Биржа:</b> {exchange_name}\n"
            f"📝 <b>Название:</b> {cred.name}\n"
            f"🔑 <b>API Key:</b> <code>{cred.mask_api_key()}</code>\n\n"
            f"<b>Статус:</b>\n"
            f"├─ {status}\n"
            f"└─ {active}\n\n"
            f"<b>Статистика:</b>\n"
            f"├─ Запросов: {cred.requests_count}\n"
            f"├─ Успешных: {cred.success_count}\n"
            f"├─ Ошибок: {cred.error_count}\n"
            f"└─ Успешность: {success_rate}%\n\n"
            f"<b>Даты:</b>\n"
            f"├─ Добавлен: {cred.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"├─ Проверен: {last_verified}\n"
            f"└─ Использован: {last_used}\n"
        )
        
        if cred.last_error:
            message += f"\n⚠️ <b>Последняя ошибка:</b>\n<code>{cred.last_error[:100]}</code>"
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_credential_actions_keyboard(credential_id, cred.is_verified),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)


# =============================================================================
# ПРОВЕРКА КЛЮЧЕЙ
# =============================================================================

@router.callback_query(F.data.startswith("exchange_cred_verify_"))
async def verify_single_credential(callback: CallbackQuery):
    """Проверить один набор ключей"""
    credential_id = int(callback.data.replace("exchange_cred_verify_", ""))
    
    await callback.message.edit_text("⏳ Проверяю API ключи...")
    
    auth_manager = get_exchange_auth_manager()
    
    with get_db_session() as session:
        cred = session.query(ExchangeCredentials).filter(
            ExchangeCredentials.id == credential_id
        ).first()
        
        if not cred:
            await callback.message.edit_text(
                "❌ Ключи не найдены",
                reply_markup=get_exchange_credentials_menu_keyboard(),
                parse_mode="HTML"
            )
            return
        
        result = auth_manager.verify_credentials(
            exchange=cred.exchange,
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            passphrase=cred.passphrase
        )
        
        cred.is_verified = result['success']
        cred.last_verified = datetime.utcnow()
        if not result['success']:
            cred.last_error = result['message']
        session.commit()
        
        exchange_icon = get_exchange_icon(cred.exchange)
        
        if result['success']:
            message = (
                f"✅ <b>ПРОВЕРКА УСПЕШНА</b>\n\n"
                f"{exchange_icon} <b>{cred.name}</b>\n\n"
                f"{result['message']}"
            )
        else:
            message = (
                f"❌ <b>ПРОВЕРКА НЕ ПРОЙДЕНА</b>\n\n"
                f"{exchange_icon} <b>{cred.name}</b>\n\n"
                f"{result['message']}"
            )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_credential_actions_keyboard(credential_id, result['success']),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data == "exchange_cred_verify_all")
async def verify_all_credentials(callback: CallbackQuery):
    """Проверить все ключи"""
    auth_manager = get_exchange_auth_manager()
    
    with get_db_session() as session:
        credentials = session.query(ExchangeCredentials).filter(
            ExchangeCredentials.is_active == True
        ).all()
        
        if not credentials:
            await callback.message.edit_text(
                "📋 Нет активных API ключей для проверки.",
                reply_markup=get_exchange_credentials_menu_keyboard(),
                parse_mode="HTML"
            )
            await safe_answer_callback(callback)
            return
        
        await callback.message.edit_text(f"⏳ Проверяю {len(credentials)} ключей...")
        
        results = []
        for cred in credentials:
            result = auth_manager.verify_credentials(
                exchange=cred.exchange,
                api_key=cred.api_key,
                api_secret=cred.api_secret,
                passphrase=cred.passphrase
            )
            
            cred.is_verified = result['success']
            cred.last_verified = datetime.utcnow()
            if not result['success']:
                cred.last_error = result['message']
            
            icon = get_exchange_icon(cred.exchange)
            status = "✅" if result['success'] else "❌"
            results.append(f"{status} {icon} {cred.name}")
        
        session.commit()
        
        message = (
            "🔍 <b>РЕЗУЛЬТАТЫ ПРОВЕРКИ</b>\n\n" +
            "\n".join(results)
        )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_credentials_menu_keyboard(),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)


# =============================================================================
# УДАЛЕНИЕ КЛЮЧЕЙ
# =============================================================================

@router.callback_query(F.data.startswith("exchange_cred_delete_"))
async def confirm_delete_credential(callback: CallbackQuery):
    """Подтверждение удаления"""
    credential_id = int(callback.data.replace("exchange_cred_delete_", ""))
    
    with get_db_session() as session:
        cred = session.query(ExchangeCredentials).filter(
            ExchangeCredentials.id == credential_id
        ).first()
        
        if not cred:
            await callback.message.edit_text(
                "❌ Ключи не найдены",
                reply_markup=get_exchange_credentials_menu_keyboard(),
                parse_mode="HTML"
            )
            await safe_answer_callback(callback)
            return
        
        exchange_icon = get_exchange_icon(cred.exchange)
        
        message = (
            f"🗑️ <b>УДАЛЕНИЕ API КЛЮЧЕЙ</b>\n\n"
            f"Вы уверены, что хотите удалить?\n\n"
            f"{exchange_icon} <b>{cred.name}</b>\n"
            f"🔑 <code>{cred.mask_api_key()}</code>\n\n"
            f"⚠️ Это действие нельзя отменить!"
        )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_delete_confirm_keyboard(credential_id),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("exchange_cred_confirm_delete_"))
async def execute_delete_credential(callback: CallbackQuery):
    """Выполнить удаление"""
    credential_id = int(callback.data.replace("exchange_cred_confirm_delete_", ""))
    
    auth_manager = get_exchange_auth_manager()
    
    with get_db_session() as session:
        result = auth_manager.delete_credentials_from_db(session, credential_id)
        
        if result['success']:
            message = f"✅ {result['message']}"
        else:
            message = f"❌ {result['message']}"
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_credentials_menu_keyboard(),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)


# =============================================================================
# АКТИВАЦИЯ/ДЕАКТИВАЦИЯ
# =============================================================================

@router.callback_query(F.data.startswith("exchange_cred_toggle_"))
async def toggle_credential_active(callback: CallbackQuery):
    """Переключить активность ключей"""
    credential_id = int(callback.data.replace("exchange_cred_toggle_", ""))
    
    with get_db_session() as session:
        cred = session.query(ExchangeCredentials).filter(
            ExchangeCredentials.id == credential_id
        ).first()
        
        if not cred:
            await callback.answer("❌ Ключи не найдены", show_alert=True)
            return
        
        cred.is_active = not cred.is_active
        session.commit()
        
        status = "активированы" if cred.is_active else "деактивированы"
        await callback.answer(f"✅ Ключи {status}", show_alert=True)
        
        # Обновляем отображение
        await view_credential_details(callback)


# =============================================================================
# СТАТИСТИКА
# =============================================================================

@router.callback_query(F.data == "exchange_cred_stats")
async def show_credentials_stats(callback: CallbackQuery):
    """Показать общую статистику API ключей"""
    with get_db_session() as session:
        credentials = session.query(ExchangeCredentials).all()
        
        if not credentials:
            message = (
                "📊 <b>СТАТИСТИКА API КЛЮЧЕЙ</b>\n\n"
                "Нет добавленных ключей."
            )
        else:
            total = len(credentials)
            active = sum(1 for c in credentials if c.is_active)
            verified = sum(1 for c in credentials if c.is_verified)
            total_requests = sum(c.requests_count for c in credentials)
            total_success = sum(c.success_count for c in credentials)
            total_errors = sum(c.error_count for c in credentials)
            
            success_rate = 0
            if total_requests > 0:
                success_rate = round((total_success / total_requests) * 100, 1)
            
            # Статистика по биржам
            by_exchange = {}
            for c in credentials:
                if c.exchange not in by_exchange:
                    by_exchange[c.exchange] = {'count': 0, 'active': 0, 'verified': 0}
                by_exchange[c.exchange]['count'] += 1
                if c.is_active:
                    by_exchange[c.exchange]['active'] += 1
                if c.is_verified:
                    by_exchange[c.exchange]['verified'] += 1
            
            exchange_stats = []
            for exchange, stats in by_exchange.items():
                icon = get_exchange_icon(exchange)
                name = get_exchange_name(exchange)
                exchange_stats.append(
                    f"{icon} <b>{name}:</b> {stats['count']} "
                    f"(активных: {stats['active']}, проверенных: {stats['verified']})"
                )
            
            message = (
                "📊 <b>СТАТИСТИКА API КЛЮЧЕЙ</b>\n\n"
                f"<b>Общая информация:</b>\n"
                f"├─ Всего ключей: {total}\n"
                f"├─ Активных: {active}\n"
                f"└─ Верифицированных: {verified}\n\n"
                f"<b>Использование:</b>\n"
                f"├─ Всего запросов: {total_requests}\n"
                f"├─ Успешных: {total_success}\n"
                f"├─ Ошибок: {total_errors}\n"
                f"└─ Успешность: {success_rate}%\n\n"
                f"<b>По биржам:</b>\n" +
                "\n".join(exchange_stats)
            )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_exchange_credentials_menu_keyboard(),
            parse_mode="HTML"
        )
    
    await safe_answer_callback(callback)
