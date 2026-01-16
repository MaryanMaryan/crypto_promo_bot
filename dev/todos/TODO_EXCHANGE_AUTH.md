# TODO: Авторизация для Bybit/Kucoin стейкингов

**Дата создания:** 15.01.2026  
**Статус:** ✅ РЕАЛИЗОВАНО (Этап 1 - Инфраструктура)  
**Приоритет:** Высокий

## 🎯 Цель

Добавить авторизацию через API ключи для Bybit и Kucoin, чтобы получать полные данные о стейкингах:
- ✅ Лимиты на пользователя (user_limit)
- ✅ Заполненность стейкингов (fill_percentage)
- ✅ Доступные квоты (available_quota)
- ✅ Детальная информация о продуктах

## 📋 План действий

### 1. [x] Создать модель ExchangeCredentials в models.py ✅

**Файл:** `data/models.py`

Добавить новую модель для хранения API ключей бирж:

```python
class ExchangeCredentials(Base):
    """Учетные данные для авторизации на биржах"""
    __tablename__ = 'exchange_credentials'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # Название (например "Основной Bybit")
    exchange = Column(String, nullable=False)  # 'bybit', 'kucoin', 'okx'
    
    # API ключи
    api_key = Column(String, nullable=False)
    api_secret = Column(String, nullable=False)  # TODO: зашифровать
    passphrase = Column(String, nullable=True)  # Для Kucoin
    
    # Статус и метаданные
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # Прошел ли проверку
    last_verified = Column(DateTime, nullable=True)
    last_used = Column(DateTime, nullable=True)
    
    # Статистика
    requests_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    
    # Метаданные
    added_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Индексы
    __table_args__ = (
        Index('idx_exchange_active', 'exchange', 'is_active'),
    )
```

**Действия:**
- [x] Добавить модель в `data/models.py` ✅
- [x] Создать миграцию для таблицы ✅ (migration_011)
- [ ] Добавить методы для шифрования/дешифрования ключей (опционально)

---

### 2. [x] Добавить поля API ключей в .env.example ✅

**Файл:** `.env.example`

```env
# =============================================================================
# EXCHANGE API CREDENTIALS (для получения полных данных о стейкингах)
# =============================================================================
# Bybit API (получите на: https://www.bybit.com/app/user/api-management)
# Права: только Read (чтение)
BYBIT_API_KEY=
BYBIT_API_SECRET=

# Kucoin API (получите на: https://www.kucoin.com/account/api)
# Права: General (чтение)
KUCOIN_API_KEY=
KUCOIN_API_SECRET=
KUCOIN_PASSPHRASE=

# OKX API (получите на: https://www.okx.com/account/my-api)
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
```

**Действия:**
- [ ] Добавить секцию в `.env.example`
- [ ] Обновить `config.py` для загрузки ключей
- [ ] Документировать в README.md

---

### 3. [ ] Создать ExchangeAuthManager для работы с API ключами

**Файл:** `utils/exchange_auth_manager.py` (новый)

Класс для управления авторизацией на биржах:

```python
class ExchangeAuthManager:
    """Менеджер авторизации на криптобиржах"""
    
    def __init__(self):
        self.credentials = {}  # Кэш учетных данных
        self._load_credentials()
    
    def _load_credentials(self):
        """Загружает учетные данные из БД и .env"""
        pass
    
    def get_credentials(self, exchange: str) -> Optional[Dict]:
        """Получает активные учетные данные для биржи"""
        pass
    
    def sign_request_bybit(self, params: Dict, api_key: str, api_secret: str) -> Dict:
        """Подписывает запрос для Bybit API"""
        pass
    
    def sign_request_kucoin(self, method: str, endpoint: str, params: Dict, 
                           api_key: str, api_secret: str, passphrase: str) -> Dict:
        """Подписывает запрос для Kucoin API"""
        pass
    
    def verify_credentials(self, exchange: str, api_key: str, api_secret: str, 
                          passphrase: str = None) -> bool:
        """Проверяет валидность API ключей"""
        pass
```

**Действия:**
- [ ] Создать файл `utils/exchange_auth_manager.py`
- [ ] Реализовать подпись запросов для Bybit
- [ ] Реализовать подпись запросов для Kucoin
- [ ] Добавить метод проверки ключей
- [ ] Добавить ротацию при нескольких аккаунтах

**Ссылки на документацию API:**
- Bybit: https://bybit-exchange.github.io/docs/v5/intro
- Kucoin: https://www.kucoin.com/docs/beginners/introduction
- OKX: https://www.okx.com/docs-v5/en/

---

### 4. [ ] Обновить StakingParser для поддержки авторизации

**Файл:** `parsers/staking_parser.py`

**Изменения в конструкторе:**
```python
def __init__(self, api_url: str, exchange_name: str = None, credentials: Dict = None):
    self.api_url = api_url
    self.exchange_name = self._detect_exchange(api_url, exchange_name)
    self.credentials = credentials  # NEW
    self.auth_manager = ExchangeAuthManager() if credentials else None  # NEW
    self.price_fetcher = get_price_fetcher()
```

**Обновить метод parse():**
- [ ] Проверять наличие credentials
- [ ] Использовать приватные endpoints если авторизован
- [ ] Добавлять подпись к запросам
- [ ] Парсить дополнительные поля из приватного API

**Приватные endpoints:**

**Bybit:**
```python
# Вместо публичного:
POST /earn/fixed-saving/v1/list
# Используем приватный:
POST /v5/earn/fixed-saving/query-list
# Заголовки: X-BAPI-API-KEY, X-BAPI-SIGN, X-BAPI-TIMESTAMP
```

**Kucoin:**
```python
# Вместо публичного:
GET /api/v1/project/list
# Используем приватный:
GET /api/v1/earn/orders
# Заголовки: KC-API-KEY, KC-API-SIGN, KC-API-TIMESTAMP, KC-API-PASSPHRASE
```

**Дополнительные поля для парсинга:**
- `available_quota` - доступная квота
- `user_holding` - текущий холдинг пользователя
- `min_purchase_amount` - минимальная сумма
- `max_purchase_amount` - максимальная сумма
- `is_purchasable` - доступен ли для покупки

**Действия:**
- [ ] Добавить параметр credentials в __init__
- [ ] Создать метод `_get_authenticated_headers()`
- [ ] Обновить `_parse_bybit()` для приватного API
- [ ] Обновить `_parse_kucoin()` для приватного API
- [ ] Добавить fallback на публичные API при ошибках

---

### 5. [ ] Добавить хендлеры для управления учетными данными

**Файл:** `bot/handlers.py`

Добавить новое меню "🔑 API ключи бирж":

**Структура меню:**
```
⚙️ Настройки
  └─ 🔑 API ключи бирж
       ├─ ➕ Добавить ключи
       │    ├─ Bybit
       │    ├─ Kucoin
       │    └─ OKX
       ├─ 📋 Список ключей
       ├─ ✏️ Редактировать
       ├─ ✅ Проверить ключи
       └─ 🗑️ Удалить
```

**Функции:**
- `cmd_exchange_api_menu()` - главное меню
- `cmd_add_exchange_credentials()` - добавление ключей
- `cmd_list_exchange_credentials()` - список ключей
- `cmd_verify_exchange_credentials()` - проверка валидности
- `cmd_delete_exchange_credentials()` - удаление

**Важно:**
- Не показывать API secret в списке (маскировать)
- Подтверждение перед удалением
- Валидация формата ключей
- Автоматическая проверка после добавления

**Действия:**
- [ ] Создать состояния в `bot/states.py`
- [ ] Добавить клавиатуры в `bot/keyboards.py`
- [ ] Реализовать хендлеры в `bot/handlers.py`
- [ ] Добавить валидацию ключей
- [ ] Интегрировать с ExchangeAuthManager

---

### 6. [ ] Создать тестовый скрипт для проверки авторизованного парсинга

**Файл:** `dev/tests/test_exchange_auth.py` (новый)

```python
"""
Тестовый скрипт для проверки авторизованного парсинга стейкингов
"""

from parsers.staking_parser import StakingParser
from utils.exchange_auth_manager import ExchangeAuthManager

def test_bybit_auth():
    """Тест авторизации Bybit"""
    print("=== Тест Bybit авторизации ===")
    
    # Загружаем credentials
    auth_manager = ExchangeAuthManager()
    credentials = auth_manager.get_credentials('bybit')
    
    if not credentials:
        print("❌ Ключи Bybit не настроены")
        return
    
    # Публичный парсинг
    print("\n1. Публичный API (без авторизации):")
    parser_public = StakingParser(
        api_url='https://api2.bybit.com/fapi/earn/fixed-saving/v1/list',
        exchange_name='bybit'
    )
    stakings_public = parser_public.parse()
    print(f"   Найдено: {len(stakings_public)} стейкингов")
    if stakings_public:
        sample = stakings_public[0]
        print(f"   Пример: {sample.get('coin')} - APR: {sample.get('apr')}%")
        print(f"   Лимит: {sample.get('user_limit_usd', 'НЕТ ДАННЫХ')}")
    
    # Приватный парсинг
    print("\n2. Приватный API (с авторизацией):")
    parser_private = StakingParser(
        api_url='https://api2.bybit.com/fapi/earn/fixed-saving/v1/list',
        exchange_name='bybit',
        credentials=credentials
    )
    stakings_private = parser_private.parse()
    print(f"   Найдено: {len(stakings_private)} стейкингов")
    if stakings_private:
        sample = stakings_private[0]
        print(f"   Пример: {sample.get('coin')} - APR: {sample.get('apr')}%")
        print(f"   Лимит: {sample.get('user_limit_usd', 'ДОЛЖНЫ БЫТЬ ДАННЫЕ')}")
        print(f"   Доступно: {sample.get('available_quota', 'ДОЛЖНЫ БЫТЬ ДАННЫЕ')}")

def test_kucoin_auth():
    """Тест авторизации Kucoin"""
    # Аналогично для Kucoin
    pass

if __name__ == '__main__':
    test_bybit_auth()
    test_kucoin_auth()
```

**Действия:**
- [ ] Создать файл `dev/tests/test_exchange_auth.py`
- [ ] Реализовать тесты для Bybit
- [ ] Реализовать тесты для Kucoin
- [ ] Добавить сравнение публичного vs приватного API
- [ ] Документировать различия в получаемых данных

---

## 🔐 Безопасность

### Рекомендации:
1. **Права API ключей:** Только Read-Only (чтение)
2. **Хранение:** Рассмотреть шифрование в БД (cryptography)
3. **IP whitelist:** Настроить на биржах
4. **Мониторинг:** Логировать все использования ключей
5. **Ротация:** Периодически обновлять ключи

### Планы на будущее:
- [ ] Шифрование ключей в БД (AES-256)
- [ ] Двухфакторная аутентификация
- [ ] Автоматическая ротация ключей
- [ ] Алерты при подозрительной активности

---

## 📊 Ожидаемые результаты

### До авторизации (публичный API):
```json
{
  "coin": "BTC",
  "apr": 5.5,
  "type": "Fixed 30d",
  "user_limit_usd": null,  // ❌ НЕТ
  "available_quota": null,  // ❌ НЕТ
  "fill_percentage": null   // ❌ НЕТ
}
```

### После авторизации (приватный API):
```json
{
  "coin": "BTC",
  "apr": 5.5,
  "type": "Fixed 30d",
  "user_limit_usd": 1000,        // ✅ ЕСТЬ
  "available_quota": 500,        // ✅ ЕСТЬ
  "fill_percentage": 85.5,       // ✅ ЕСТЬ
  "min_purchase_amount": 0.001,  // ✅ БОНУС
  "max_purchase_amount": 1.0     // ✅ БОНУС
}
```

---

## 🔗 Полезные ссылки

### Bybit
- API Management: https://www.bybit.com/app/user/api-management
- API Docs: https://bybit-exchange.github.io/docs/v5/intro
- Earn API: https://bybit-exchange.github.io/docs/v5/earn/product-info

### Kucoin
- API Management: https://www.kucoin.com/account/api
- API Docs: https://www.kucoin.com/docs/beginners/introduction
- Earn API: https://www.kucoin.com/docs/rest/earn/general

### OKX
- API Management: https://www.okx.com/account/my-api
- API Docs: https://www.okx.com/docs-v5/en/

---

## ✅ Чеклист готовности

- [ ] Модель ExchangeCredentials создана
- [ ] Миграция применена к БД
- [ ] .env.example обновлен
- [ ] config.py загружает ключи
- [ ] ExchangeAuthManager реализован
- [ ] StakingParser обновлен
- [ ] Хендлеры для UI добавлены
- [ ] Тестовый скрипт работает
- [ ] Документация обновлена
- [ ] Безопасность проверена

---

## 📝 Примечания

- Начать с Bybit (более простой API)
- Затем Kucoin (требует passphrase)
- OKX можно добавить позже
- Сохранить совместимость с публичным API (fallback)
- Аналогично системе TelegramAccount (проверенный паттерн)
