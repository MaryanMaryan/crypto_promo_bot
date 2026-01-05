"""
Менеджер авторизации Telegram аккаунтов через чат бота
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Callable
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PasswordHashInvalidError
)
from data.database import get_db_session
from data.models import TelegramSettings, TelegramAccount

logger = logging.getLogger(__name__)


class TelegramAuthManager:
    """Менеджер авторизации Telegram аккаунтов через чат бота"""

    def __init__(self):
        self.pending_auths: Dict[int, Dict] = {}  # user_id -> auth data

    def get_api_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """Получить API ID и API Hash из базы данных"""
        try:
            with get_db_session() as db:
                settings = db.query(TelegramSettings).first()
                if settings and settings.api_id and settings.api_hash:
                    return settings.api_id, settings.api_hash
                return None, None
        except Exception as e:
            logger.error(f"Ошибка получения API credentials: {e}")
            return None, None

    def save_api_credentials(self, api_id: str, api_hash: str) -> bool:
        """Сохранить API ID и API Hash в базу данных"""
        try:
            with get_db_session() as db:
                settings = db.query(TelegramSettings).first()
                if settings:
                    settings.api_id = api_id
                    settings.api_hash = api_hash
                    settings.is_configured = True
                    settings.updated_at = datetime.utcnow()
                else:
                    settings = TelegramSettings(
                        api_id=api_id,
                        api_hash=api_hash,
                        is_configured=True
                    )
                    db.add(settings)
                db.commit()
                logger.info("API credentials сохранены")
                return True
        except Exception as e:
            logger.error(f"Ошибка сохранения API credentials: {e}")
            return False

    async def start_auth(
        self,
        user_id: int,
        account_name: str,
        phone_number: str,
        callback: Optional[Callable] = None
    ) -> tuple[bool, str]:
        """
        Начать процесс авторизации аккаунта

        Returns:
            (success, message)
        """
        try:
            # Проверяем API credentials
            api_id, api_hash = self.get_api_credentials()
            if not api_id or not api_hash:
                return False, "API ID и API Hash не настроены. Сначала настройте их."

            # Проверяем, не существует ли уже аккаунт с таким номером
            with get_db_session() as db:
                existing = db.query(TelegramAccount).filter_by(phone_number=phone_number).first()
                if existing:
                    return False, f"Аккаунт с номером {phone_number} уже существует"

            # Создаем уникальное имя сессии
            session_name = f"sessions/tg_session_{user_id}_{phone_number.replace('+', '').replace(' ', '')}"

            # Создаем клиент Telethon
            client = TelegramClient(session_name, api_id, api_hash)
            await client.connect()

            # Отправляем код
            await client.send_code_request(phone_number)

            # Сохраняем данные для последующей авторизации
            self.pending_auths[user_id] = {
                'client': client,
                'phone_number': phone_number,
                'account_name': account_name,
                'session_name': session_name,
                'callback': callback
            }

            logger.info(f"Код авторизации отправлен на {phone_number}")
            return True, "Код отправлен на ваш телефон. Введите его:"

        except PhoneNumberInvalidError:
            return False, "Неверный формат номера телефона. Используйте формат: +1234567890"
        except FloodWaitError as e:
            return False, f"Слишком много попыток. Подождите {e.seconds} секунд"
        except Exception as e:
            logger.error(f"Ошибка начала авторизации: {e}", exc_info=True)
            return False, f"Ошибка: {str(e)}"

    async def verify_code(
        self,
        user_id: int,
        code: str
    ) -> tuple[bool, str, bool]:
        """
        Проверить код авторизации

        Returns:
            (success, message, needs_password)
        """
        if user_id not in self.pending_auths:
            return False, "Сессия авторизации не найдена. Начните заново.", False

        auth_data = self.pending_auths[user_id]
        client = auth_data['client']
        phone_number = auth_data['phone_number']

        try:
            # Пытаемся войти с кодом
            await client.sign_in(phone_number, code)

            # Если дошли сюда - успех
            await self._finalize_auth(user_id)
            return True, "Авторизация успешна!", False

        except SessionPasswordNeededError:
            # Требуется 2FA пароль
            logger.info(f"Требуется 2FA пароль для {phone_number}")
            return False, "Введите пароль двухфакторной аутентификации (2FA):", True

        except PhoneCodeInvalidError:
            return False, "Неверный код. Попробуйте еще раз:", False

        except Exception as e:
            logger.error(f"Ошибка проверки кода: {e}", exc_info=True)
            await self._cleanup_auth(user_id)
            return False, f"Ошибка: {str(e)}", False

    async def verify_password(
        self,
        user_id: int,
        password: str
    ) -> tuple[bool, str]:
        """
        Проверить пароль 2FA

        Returns:
            (success, message)
        """
        if user_id not in self.pending_auths:
            return False, "Сессия авторизации не найдена. Начните заново."

        auth_data = self.pending_auths[user_id]
        client = auth_data['client']

        try:
            # Входим с паролем
            await client.sign_in(password=password)

            # Успех
            await self._finalize_auth(user_id)
            return True, "Авторизация успешна!"

        except PasswordHashInvalidError:
            return False, "Неверный пароль. Попробуйте еще раз:"

        except Exception as e:
            logger.error(f"Ошибка проверки пароля: {e}", exc_info=True)
            await self._cleanup_auth(user_id)
            return False, f"Ошибка: {str(e)}"

    async def _finalize_auth(self, user_id: int):
        """Завершить авторизацию и сохранить аккаунт в БД"""
        auth_data = self.pending_auths[user_id]
        client = auth_data['client']
        phone_number = auth_data['phone_number']
        account_name = auth_data['account_name']
        session_name = auth_data['session_name']

        try:
            # Сохраняем аккаунт в БД
            with get_db_session() as db:
                account = TelegramAccount(
                    name=account_name,
                    phone_number=phone_number,
                    session_file=session_name,
                    is_active=True,
                    is_authorized=True,
                    added_by=user_id,
                    last_used=datetime.utcnow()
                )
                db.add(account)
                db.commit()
                logger.info(f"Аккаунт {phone_number} успешно добавлен")

            # Отключаемся от клиента
            await client.disconnect()

            # Вызываем callback если есть
            if auth_data.get('callback'):
                await auth_data['callback'](user_id, True, "Аккаунт добавлен")

        except Exception as e:
            logger.error(f"Ошибка финализации авторизации: {e}", exc_info=True)
            await client.disconnect()

        finally:
            # Очищаем временные данные
            del self.pending_auths[user_id]

    async def _cleanup_auth(self, user_id: int):
        """Очистить данные неудачной авторизации"""
        if user_id in self.pending_auths:
            auth_data = self.pending_auths[user_id]
            client = auth_data.get('client')

            if client:
                try:
                    await client.disconnect()
                except:
                    pass

            # Удаляем файл сессии если он был создан
            try:
                import os
                session_file = f"{auth_data['session_name']}.session"
                if os.path.exists(session_file):
                    os.remove(session_file)
            except:
                pass

            del self.pending_auths[user_id]

    def cancel_auth(self, user_id: int):
        """Отменить текущую авторизацию"""
        if user_id in self.pending_auths:
            asyncio.create_task(self._cleanup_auth(user_id))
            return True
        return False

    def get_all_accounts(self, user_id: int) -> list[dict]:
        """Получить все аккаунты пользователя (возвращает словари, не ORM объекты)"""
        try:
            with get_db_session() as db:
                accounts = db.query(TelegramAccount).filter_by(added_by=user_id).all()
                # Преобразуем в словари, чтобы избежать проблем с detached instances
                result = []
                for acc in accounts:
                    result.append({
                        'id': acc.id,
                        'name': acc.name,
                        'phone_number': acc.phone_number,
                        'session_file': acc.session_file,
                        'is_active': acc.is_active,
                        'is_authorized': acc.is_authorized,
                        'last_used': acc.last_used,
                        'messages_parsed': acc.messages_parsed,
                        'channels_monitored': acc.channels_monitored,
                        'last_error': acc.last_error,
                        'created_at': acc.created_at
                    })
                return result
        except Exception as e:
            logger.error(f"Ошибка получения аккаунтов: {e}")
            return []

    def delete_account(self, account_id: int, user_id: int) -> tuple[bool, str]:
        """Удалить аккаунт"""
        try:
            with get_db_session() as db:
                account = db.query(TelegramAccount).filter_by(
                    id=account_id,
                    added_by=user_id
                ).first()

                if not account:
                    return False, "Аккаунт не найден"

                # Удаляем файл сессии
                try:
                    import os
                    session_file = f"{account.session_file}.session"
                    if os.path.exists(session_file):
                        os.remove(session_file)
                        logger.info(f"Удален файл сессии: {session_file}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл сессии: {e}")

                # Удаляем из БД
                db.delete(account)
                db.commit()

                logger.info(f"Аккаунт {account.phone_number} удален")
                return True, "Аккаунт успешно удален"

        except Exception as e:
            logger.error(f"Ошибка удаления аккаунта: {e}")
            return False, f"Ошибка: {str(e)}"

    def toggle_account(self, account_id: int, user_id: int) -> tuple[bool, str, bool]:
        """
        Активировать/деактивировать аккаунт

        Returns:
            (success, message, new_state)
        """
        try:
            with get_db_session() as db:
                account = db.query(TelegramAccount).filter_by(
                    id=account_id,
                    added_by=user_id
                ).first()

                if not account:
                    return False, "Аккаунт не найден", False

                account.is_active = not account.is_active
                account.updated_at = datetime.utcnow()
                db.commit()

                status = "активирован" if account.is_active else "деактивирован"
                logger.info(f"Аккаунт {account.phone_number} {status}")
                return True, f"Аккаунт {status}", account.is_active

        except Exception as e:
            logger.error(f"Ошибка переключения аккаунта: {e}")
            return False, f"Ошибка: {str(e)}", False

    async def test_account(self, account_id: int, user_id: int) -> tuple[bool, str]:
        """
        Тестирование аккаунта - проверка подключения и получение информации

        Returns:
            (success, message)
        """
        try:
            with get_db_session() as db:
                account = db.query(TelegramAccount).filter_by(
                    id=account_id,
                    added_by=user_id
                ).first()

                if not account:
                    return False, "Аккаунт не найден"

                # Получаем API credentials
                api_id, api_hash = self.get_api_credentials()
                if not api_id or not api_hash:
                    return False, "API credentials не настроены"

                # Создаем клиент
                client = TelegramClient(account.session_file, api_id, api_hash)

                try:
                    # Подключаемся
                    await client.connect()

                    # Проверяем авторизацию
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        account.is_authorized = False
                        db.commit()
                        return False, "Аккаунт не авторизован. Требуется повторная авторизация."

                    # Получаем информацию о пользователе
                    me = await client.get_me()

                    # Обновляем информацию в БД
                    account.is_authorized = True
                    account.last_used = datetime.utcnow()
                    db.commit()

                    await client.disconnect()

                    # Формируем результат
                    username = f"@{me.username}" if me.username else "Нет username"
                    name = f"{me.first_name or ''} {me.last_name or ''}".strip()

                    result = (
                        f"✅ Тест успешен!\n\n"
                        f"👤 Имя: {name}\n"
                        f"🆔 ID: {me.id}\n"
                        f"📱 Username: {username}\n"
                        f"📞 Телефон: {me.phone}\n\n"
                        f"Аккаунт авторизован и готов к работе!"
                    )

                    logger.info(f"Тест аккаунта {account.phone_number} успешен")
                    return True, result

                except Exception as e:
                    await client.disconnect()
                    account.last_error = str(e)
                    db.commit()
                    raise

        except Exception as e:
            logger.error(f"Ошибка теста аккаунта: {e}", exc_info=True)
            return False, f"Ошибка подключения: {str(e)}"


# Глобальный экземпляр менеджера
telegram_auth_manager = TelegramAuthManager()
