"""
FSM состояния для управления Telegram аккаунтами и Exchange API ключами
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


class ExchangeCredentialsStates(StatesGroup):
    """Состояния для добавления API ключей бирж"""
    
    # Выбор биржи
    selecting_exchange = State()
    
    # Ввод данных
    waiting_for_name = State()       # Название для ключей (например "Основной Bybit")
    waiting_for_api_key = State()    # API Key
    waiting_for_api_secret = State() # API Secret
    waiting_for_passphrase = State() # Passphrase (для Kucoin/OKX)
    
    # Подтверждения
    confirming_add = State()         # Подтверждение добавления
    confirming_deletion = State()    # Подтверждение удаления
    
    # Управление
    selecting_credential = State()   # Выбор ключей для действия
    viewing_details = State()        # Просмотр деталей
