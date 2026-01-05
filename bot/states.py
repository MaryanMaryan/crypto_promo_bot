"""
FSM состояния для управления Telegram аккаунтами
"""

from aiogram.fsm.state import State, StatesGroup


class TelegramAccountStates(StatesGroup):
    """Состояния для добавления Telegram аккаунта"""

    # Настройка API (если не настроено)
    waiting_for_api_id = State()
    waiting_for_api_hash = State()

    # Добавление аккаунта
    waiting_for_account_name = State()
    waiting_for_phone_number = State()
    waiting_for_verification_code = State()
    waiting_for_password = State()  # Двухфакторная аутентификация (2FA)

    # Управление аккаунтом
    selecting_account = State()
    confirming_deletion = State()
