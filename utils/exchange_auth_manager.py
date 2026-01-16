"""
utils/exchange_auth_manager.py
Менеджер авторизации на криптобиржах для получения полных данных о стейкингах
"""

import os
import time
import hmac
import hashlib
import base64
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class ExchangeAuthManager:
    """
    Менеджер авторизации на криптобиржах
    
    Поддерживаемые биржи:
    - Bybit: HMAC-SHA256 подпись
    - Kucoin: HMAC-SHA256 + passphrase
    - OKX: HMAC-SHA256 + passphrase
    """
    
    def __init__(self):
        self.credentials: Dict[str, Dict] = {}
        self._load_credentials_from_env()
    
    def _load_credentials_from_env(self):
        """Загружает учетные данные из переменных окружения"""
        # Bybit
        bybit_key = os.getenv('BYBIT_API_KEY', '')
        bybit_secret = os.getenv('BYBIT_API_SECRET', '')
        if bybit_key and bybit_secret:
            self.credentials['bybit'] = {
                'api_key': bybit_key,
                'api_secret': bybit_secret,
                'source': 'env'
            }
            logger.info("✅ Bybit API ключи загружены из .env")
        
        # Kucoin
        kucoin_key = os.getenv('KUCOIN_API_KEY', '')
        kucoin_secret = os.getenv('KUCOIN_API_SECRET', '')
        kucoin_passphrase = os.getenv('KUCOIN_PASSPHRASE', '')
        if kucoin_key and kucoin_secret:
            self.credentials['kucoin'] = {
                'api_key': kucoin_key,
                'api_secret': kucoin_secret,
                'passphrase': kucoin_passphrase,
                'source': 'env'
            }
            logger.info("✅ Kucoin API ключи загружены из .env")
        
        # OKX
        okx_key = os.getenv('OKX_API_KEY', '')
        okx_secret = os.getenv('OKX_API_SECRET', '')
        okx_passphrase = os.getenv('OKX_PASSPHRASE', '')
        if okx_key and okx_secret:
            self.credentials['okx'] = {
                'api_key': okx_key,
                'api_secret': okx_secret,
                'passphrase': okx_passphrase,
                'source': 'env'
            }
            logger.info("✅ OKX API ключи загружены из .env")
    
    def load_credentials_from_db(self, db_session) -> None:
        """
        Загружает учетные данные из БД (дополняет или перезаписывает .env)
        
        Args:
            db_session: Сессия SQLAlchemy
        """
        from data.models import ExchangeCredentials
        
        try:
            # Получаем все активные и верифицированные ключи
            creds = db_session.query(ExchangeCredentials).filter(
                ExchangeCredentials.is_active == True
            ).order_by(
                ExchangeCredentials.is_verified.desc(),  # Верифицированные первые
                ExchangeCredentials.success_count.desc()  # С большим успехом первые
            ).all()
            
            for cred in creds:
                exchange = cred.exchange.lower()
                
                # БД имеет приоритет над .env
                self.credentials[exchange] = {
                    'id': cred.id,
                    'name': cred.name,
                    'api_key': cred.api_key,
                    'api_secret': cred.api_secret,
                    'passphrase': cred.passphrase,
                    'is_verified': cred.is_verified,
                    'source': 'db'
                }
                logger.info(f"✅ {exchange.capitalize()} API ключи загружены из БД: {cred.name}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки ключей из БД: {e}")
    
    def get_credentials(self, exchange: str) -> Optional[Dict]:
        """
        Получает активные учетные данные для биржи
        
        Args:
            exchange: Название биржи (bybit, kucoin, okx)
            
        Returns:
            Dict с ключами или None если не настроены
        """
        exchange = exchange.lower()
        return self.credentials.get(exchange)
    
    def has_credentials(self, exchange: str) -> bool:
        """Проверяет наличие ключей для биржи"""
        return exchange.lower() in self.credentials
    
    def get_configured_exchanges(self) -> List[str]:
        """Возвращает список бирж с настроенными ключами"""
        return list(self.credentials.keys())
    
    # =========================================================================
    # BYBIT API SIGNING
    # =========================================================================
    
    def _get_bybit_server_time(self) -> int:
        """Получить серверное время Bybit для синхронизации"""
        try:
            response = requests.get("https://api.bybit.com/v5/market/time", timeout=5)
            data = response.json()
            if data.get('retCode') == 0:
                return int(data['result']['timeSecond']) * 1000
        except:
            pass
        return int(time.time() * 1000)
    
    def sign_request_bybit(self, params: Dict, api_key: str, api_secret: str) -> Dict:
        """
        Подписывает запрос для Bybit API v5
        
        Документация: https://bybit-exchange.github.io/docs/v5/intro
        
        Args:
            params: Параметры запроса
            api_key: API ключ
            api_secret: API секрет
            
        Returns:
            Dict с заголовками для запроса
        """
        # Используем серверное время Bybit для синхронизации
        timestamp = str(self._get_bybit_server_time())
        recv_window = "5000"
        
        # Формируем строку для подписи
        # POST: timestamp + api_key + recv_window + json_body
        # GET: timestamp + api_key + recv_window + query_string
        
        param_str = ""
        if params:
            # Для POST запроса нужен JSON-строка
            import json
            param_str = json.dumps(params)
        
        sign_str = timestamp + api_key + recv_window + param_str
        
        # HMAC-SHA256
        signature = hmac.new(
            api_secret.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-SIGN': signature,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'Content-Type': 'application/json'
        }
        
        return headers
    
    def get_bybit_headers(self, params: Dict = None) -> Optional[Dict]:
        """
        Получает подписанные заголовки для Bybit API (POST запросы)
        
        Args:
            params: Параметры запроса (будут сериализованы как JSON)
            
        Returns:
            Dict с заголовками или None если ключи не настроены
        """
        creds = self.get_credentials('bybit')
        if not creds:
            return None
        
        return self.sign_request_bybit(
            params or {},
            creds['api_key'],
            creds['api_secret']
        )
    
    def get_bybit_headers_for_get(self, params: Dict = None) -> Optional[Dict]:
        """
        Получает подписанные заголовки для Bybit API GET запросов
        
        Для GET запросов параметры передаются как query string
        
        Args:
            params: Query параметры
            
        Returns:
            Dict с заголовками или None если ключи не настроены
        """
        creds = self.get_credentials('bybit')
        if not creds:
            return None
        
        return self.sign_request_bybit_get(
            params or {},
            creds['api_key'],
            creds['api_secret']
        )
    
    def sign_request_bybit_get(self, params: Dict, api_key: str, api_secret: str) -> Dict:
        """
        Подписывает GET запрос для Bybit API v5
        
        Args:
            params: Query параметры
            api_key: API ключ
            api_secret: API секрет
            
        Returns:
            Dict с заголовками для запроса
        """
        # Используем серверное время Bybit для синхронизации
        timestamp = str(self._get_bybit_server_time())
        recv_window = "5000"
        
        # Для GET запроса - query string вместо JSON
        param_str = urlencode(params) if params else ""
        
        sign_str = timestamp + api_key + recv_window + param_str
        
        # HMAC-SHA256
        signature = hmac.new(
            api_secret.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-SIGN': signature,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window
        }
        
        return headers
    
    # =========================================================================
    # KUCOIN API SIGNING
    # =========================================================================
    
    def sign_request_kucoin(self, method: str, endpoint: str, 
                            params: Dict = None, body: Dict = None,
                            api_key: str = None, api_secret: str = None, 
                            passphrase: str = None) -> Dict:
        """
        Подписывает запрос для Kucoin API
        
        Документация: https://www.kucoin.com/docs/beginners/introduction
        
        Args:
            method: HTTP метод (GET, POST, DELETE)
            endpoint: Endpoint API (например /api/v1/earn/orders)
            params: Query параметры для GET
            body: Body для POST
            api_key: API ключ
            api_secret: API секрет
            passphrase: Passphrase
            
        Returns:
            Dict с заголовками для запроса
        """
        import json
        
        timestamp = str(int(time.time() * 1000))
        
        # Формируем строку для подписи
        # timestamp + method + endpoint + body
        
        # Для GET с параметрами добавляем query string к endpoint
        endpoint_with_params = endpoint
        if method.upper() == 'GET' and params:
            endpoint_with_params = endpoint + '?' + urlencode(params)
        
        body_str = ""
        if body:
            body_str = json.dumps(body)
        
        sign_str = timestamp + method.upper() + endpoint_with_params + body_str
        
        # HMAC-SHA256 + Base64
        signature = base64.b64encode(
            hmac.new(
                api_secret.encode('utf-8'),
                sign_str.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        # Подпись passphrase
        passphrase_sign = base64.b64encode(
            hmac.new(
                api_secret.encode('utf-8'),
                passphrase.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        headers = {
            'KC-API-KEY': api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': timestamp,
            'KC-API-PASSPHRASE': passphrase_sign,
            'KC-API-KEY-VERSION': '2',  # Для версии 2 подписи
            'Content-Type': 'application/json'
        }
        
        return headers
    
    def get_kucoin_headers(self, method: str, endpoint: str, 
                           params: Dict = None, body: Dict = None) -> Optional[Dict]:
        """
        Получает подписанные заголовки для Kucoin API
        
        Args:
            method: HTTP метод
            endpoint: Endpoint API
            params: Query параметры
            body: Body запроса
            
        Returns:
            Dict с заголовками или None если ключи не настроены
        """
        creds = self.get_credentials('kucoin')
        if not creds:
            return None
        
        return self.sign_request_kucoin(
            method=method,
            endpoint=endpoint,
            params=params,
            body=body,
            api_key=creds['api_key'],
            api_secret=creds['api_secret'],
            passphrase=creds.get('passphrase', '')
        )
    
    # =========================================================================
    # OKX API SIGNING
    # =========================================================================
    
    def sign_request_okx(self, method: str, endpoint: str,
                         params: Dict = None, body: Dict = None,
                         api_key: str = None, api_secret: str = None,
                         passphrase: str = None) -> Dict:
        """
        Подписывает запрос для OKX API
        
        Документация: https://www.okx.com/docs-v5/en/
        
        Args:
            method: HTTP метод
            endpoint: Endpoint API
            params: Query параметры
            body: Body запроса
            api_key: API ключ
            api_secret: API секрет
            passphrase: Passphrase
            
        Returns:
            Dict с заголовками
        """
        import json
        from datetime import timezone
        
        # ISO timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + \
                   f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
        
        # Формируем строку для подписи
        endpoint_with_params = endpoint
        if method.upper() == 'GET' and params:
            endpoint_with_params = endpoint + '?' + urlencode(params)
        
        body_str = ""
        if body:
            body_str = json.dumps(body)
        
        sign_str = timestamp + method.upper() + endpoint_with_params + body_str
        
        # HMAC-SHA256 + Base64
        signature = base64.b64encode(
            hmac.new(
                api_secret.encode('utf-8'),
                sign_str.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        headers = {
            'OK-ACCESS-KEY': api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': passphrase,
            'Content-Type': 'application/json'
        }
        
        return headers
    
    def get_okx_headers(self, method: str, endpoint: str,
                        params: Dict = None, body: Dict = None) -> Optional[Dict]:
        """
        Получает подписанные заголовки для OKX API
        """
        creds = self.get_credentials('okx')
        if not creds:
            return None
        
        return self.sign_request_okx(
            method=method,
            endpoint=endpoint,
            params=params,
            body=body,
            api_key=creds['api_key'],
            api_secret=creds['api_secret'],
            passphrase=creds.get('passphrase', '')
        )
    
    # =========================================================================
    # VERIFICATION
    # =========================================================================
    
    def verify_bybit_credentials(self, api_key: str, api_secret: str) -> Dict[str, Any]:
        """
        Проверяет валидность Bybit API ключей
        
        Returns:
            Dict с результатом: {'success': bool, 'message': str, 'data': dict}
        """
        try:
            # Используем endpoint для получения информации об аккаунте
            url = "https://api.bybit.com/v5/user/query-api"
            
            headers = self.sign_request_bybit({}, api_key, api_secret)
            headers['Referer'] = 'https://www.bybit.com/'
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get('retCode') == 0:
                api_info = data.get('result', {})
                return {
                    'success': True,
                    'message': f"✅ Ключ подтверждён! Права: {api_info.get('readOnly', 'unknown')}",
                    'data': api_info
                }
            else:
                return {
                    'success': False,
                    'message': f"❌ Ошибка: {data.get('retMsg', 'Unknown error')}",
                    'data': data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"❌ Ошибка подключения: {str(e)}",
                'data': {}
            }
    
    def verify_kucoin_credentials(self, api_key: str, api_secret: str, 
                                  passphrase: str) -> Dict[str, Any]:
        """
        Проверяет валидность Kucoin API ключей
        
        Returns:
            Dict с результатом
        """
        try:
            # Используем endpoint для получения информации об аккаунте
            url = "https://api.kucoin.com/api/v1/accounts"
            endpoint = "/api/v1/accounts"
            
            headers = self.sign_request_kucoin(
                method='GET',
                endpoint=endpoint,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase
            )
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get('code') == '200000':
                return {
                    'success': True,
                    'message': f"✅ Ключ подтверждён! Найдено {len(data.get('data', []))} аккаунтов",
                    'data': data
                }
            else:
                return {
                    'success': False,
                    'message': f"❌ Ошибка: {data.get('msg', 'Unknown error')}",
                    'data': data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"❌ Ошибка подключения: {str(e)}",
                'data': {}
            }
    
    def verify_okx_credentials(self, api_key: str, api_secret: str,
                               passphrase: str) -> Dict[str, Any]:
        """
        Проверяет валидность OKX API ключей
        
        Returns:
            Dict с результатом
        """
        try:
            url = "https://www.okx.com/api/v5/account/balance"
            endpoint = "/api/v5/account/balance"
            
            headers = self.sign_request_okx(
                method='GET',
                endpoint=endpoint,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase
            )
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get('code') == '0':
                return {
                    'success': True,
                    'message': "✅ Ключ подтверждён!",
                    'data': data
                }
            else:
                return {
                    'success': False,
                    'message': f"❌ Ошибка: {data.get('msg', 'Unknown error')}",
                    'data': data
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"❌ Ошибка подключения: {str(e)}",
                'data': {}
            }
    
    def verify_credentials(self, exchange: str, api_key: str, api_secret: str,
                          passphrase: str = None) -> Dict[str, Any]:
        """
        Универсальный метод проверки ключей для любой биржи
        
        Args:
            exchange: Название биржи
            api_key: API ключ
            api_secret: API секрет
            passphrase: Passphrase (для Kucoin, OKX)
            
        Returns:
            Dict с результатом проверки
        """
        exchange = exchange.lower()
        
        if exchange == 'bybit':
            return self.verify_bybit_credentials(api_key, api_secret)
        elif exchange == 'kucoin':
            return self.verify_kucoin_credentials(api_key, api_secret, passphrase or '')
        elif exchange == 'okx':
            return self.verify_okx_credentials(api_key, api_secret, passphrase or '')
        else:
            return {
                'success': False,
                'message': f"❌ Неизвестная биржа: {exchange}",
                'data': {}
            }
    
    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================
    
    def add_credentials_to_db(self, db_session, exchange: str, name: str,
                              api_key: str, api_secret: str, passphrase: str = None,
                              added_by: int = 0, verify: bool = True) -> Dict[str, Any]:
        """
        Добавляет API ключи в базу данных
        
        Args:
            db_session: Сессия SQLAlchemy
            exchange: Название биржи
            name: Название для ключей
            api_key: API ключ
            api_secret: API секрет
            passphrase: Passphrase
            added_by: ID пользователя
            verify: Проверять ключи перед добавлением
            
        Returns:
            Dict с результатом
        """
        from data.models import ExchangeCredentials
        
        # Проверяем ключи если требуется
        is_verified = False
        if verify:
            result = self.verify_credentials(exchange, api_key, api_secret, passphrase)
            is_verified = result['success']
            if not result['success']:
                return {
                    'success': False,
                    'message': f"Ключи не прошли проверку: {result['message']}",
                    'data': {}
                }
        
        try:
            # Создаем запись
            cred = ExchangeCredentials(
                name=name,
                exchange=exchange.lower(),
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                is_active=True,
                is_verified=is_verified,
                last_verified=datetime.utcnow() if is_verified else None,
                added_by=added_by
            )
            
            db_session.add(cred)
            db_session.commit()
            
            # Обновляем кэш
            self.credentials[exchange.lower()] = {
                'id': cred.id,
                'name': name,
                'api_key': api_key,
                'api_secret': api_secret,
                'passphrase': passphrase,
                'is_verified': is_verified,
                'source': 'db'
            }
            
            return {
                'success': True,
                'message': f"✅ Ключи {name} добавлены для {exchange.capitalize()}",
                'data': {'id': cred.id}
            }
            
        except Exception as e:
            db_session.rollback()
            return {
                'success': False,
                'message': f"❌ Ошибка добавления: {str(e)}",
                'data': {}
            }
    
    def delete_credentials_from_db(self, db_session, credential_id: int) -> Dict[str, Any]:
        """
        Удаляет API ключи из базы данных
        
        Args:
            db_session: Сессия SQLAlchemy
            credential_id: ID записи для удаления
            
        Returns:
            Dict с результатом
        """
        from data.models import ExchangeCredentials
        
        try:
            cred = db_session.query(ExchangeCredentials).filter(
                ExchangeCredentials.id == credential_id
            ).first()
            
            if not cred:
                return {
                    'success': False,
                    'message': "❌ Ключи не найдены",
                    'data': {}
                }
            
            exchange = cred.exchange
            name = cred.name
            
            db_session.delete(cred)
            db_session.commit()
            
            # Удаляем из кэша если это были активные ключи
            if exchange in self.credentials:
                cached = self.credentials[exchange]
                if cached.get('id') == credential_id:
                    del self.credentials[exchange]
            
            return {
                'success': True,
                'message': f"✅ Ключи {name} удалены",
                'data': {}
            }
            
        except Exception as e:
            db_session.rollback()
            return {
                'success': False,
                'message': f"❌ Ошибка удаления: {str(e)}",
                'data': {}
            }
    
    def get_all_credentials_from_db(self, db_session) -> List[Dict]:
        """
        Получает все API ключи из базы данных
        
        Returns:
            Список словарей с информацией о ключах (секреты замаскированы)
        """
        from data.models import ExchangeCredentials
        
        try:
            creds = db_session.query(ExchangeCredentials).order_by(
                ExchangeCredentials.exchange,
                ExchangeCredentials.created_at.desc()
            ).all()
            
            result = []
            for cred in creds:
                result.append({
                    'id': cred.id,
                    'name': cred.name,
                    'exchange': cred.exchange,
                    'api_key_masked': cred.mask_api_key(),
                    'is_active': cred.is_active,
                    'is_verified': cred.is_verified,
                    'last_verified': cred.last_verified,
                    'last_used': cred.last_used,
                    'requests_count': cred.requests_count,
                    'success_count': cred.success_count,
                    'error_count': cred.error_count,
                    'last_error': cred.last_error,
                    'created_at': cred.created_at
                })
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения ключей из БД: {e}")
            return []
    
    def update_usage_stats(self, db_session, exchange: str, 
                          success: bool, error_message: str = None) -> None:
        """
        Обновляет статистику использования ключей
        
        Args:
            db_session: Сессия SQLAlchemy
            exchange: Название биржи
            success: Успешный ли запрос
            error_message: Сообщение об ошибке
        """
        from data.models import ExchangeCredentials
        
        creds = self.get_credentials(exchange)
        if not creds or creds.get('source') != 'db':
            return
        
        try:
            cred = db_session.query(ExchangeCredentials).filter(
                ExchangeCredentials.id == creds.get('id')
            ).first()
            
            if cred:
                cred.requests_count += 1
                cred.last_used = datetime.utcnow()
                
                if success:
                    cred.success_count += 1
                else:
                    cred.error_count += 1
                    cred.last_error = error_message
                
                db_session.commit()
                
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики: {e}")
            db_session.rollback()


# Синглтон для глобального доступа
_exchange_auth_manager: Optional[ExchangeAuthManager] = None


def get_exchange_auth_manager() -> ExchangeAuthManager:
    """Получить глобальный экземпляр ExchangeAuthManager"""
    global _exchange_auth_manager
    if _exchange_auth_manager is None:
        _exchange_auth_manager = ExchangeAuthManager()
    return _exchange_auth_manager
