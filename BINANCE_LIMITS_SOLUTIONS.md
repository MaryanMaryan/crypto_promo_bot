# 🔐 Получение лимитов Binance Earn: Решения

## ❌ Проблема

Публичный API Binance **НЕ возвращает**:
- Лимит на пользователя (user limit)
- Максимальную вместимость пула (capacity)
- Текущую заполненность (filled amount)
- Доступное количество (available)

## ✅ Решения

### 1️⃣ **Авторизованный Binance API** (РЕКОМЕНДУЕТСЯ)

**Плюсы:**
- ✅ Официальный API
- ✅ Стабильный
- ✅ Полная информация
- ✅ Быстрый
- ✅ Надежный

**Минусы:**
- ⚠️ Требует API ключи пользователя
- ⚠️ Требует подпись HMAC SHA256

**Реализация:**

```python
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode

class BinanceAuthAPI:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://api.binance.com'
    
    def _generate_signature(self, params: dict) -> str:
        """Генерация HMAC SHA256 подписи"""
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def get_simple_earn_flexible_list(self, asset: str = None):
        """
        Получить список Flexible продуктов Simple Earn
        
        Документация:
        https://binance-docs.github.io/apidocs/spot/en/#get-simple-earn-flexible-product-list-user_data
        """
        endpoint = '/sapi/v1/simple-earn/flexible/list'
        
        params = {
            'timestamp': int(time.time() * 1000)
        }
        
        if asset:
            params['asset'] = asset
        
        params['signature'] = self._generate_signature(params)
        
        headers = {
            'X-MBX-APIKEY': self.api_key
        }
        
        url = self.base_url + endpoint
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        return response.json()
    
    def get_simple_earn_locked_list(self, asset: str = None):
        """
        Получить список Locked продуктов Simple Earn
        
        Документация:
        https://binance-docs.github.io/apidocs/spot/en/#get-simple-earn-locked-product-list-user_data
        """
        endpoint = '/sapi/v1/simple-earn/locked/list'
        
        params = {
            'timestamp': int(time.time() * 1000)
        }
        
        if asset:
            params['asset'] = asset
        
        params['signature'] = self._generate_signature(params)
        
        headers = {
            'X-MBX-APIKEY': self.api_key
        }
        
        url = self.base_url + endpoint
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        return response.json()

# ИСПОЛЬЗОВАНИЕ
api = BinanceAuthAPI(
    api_key='YOUR_API_KEY',
    api_secret='YOUR_API_SECRET'
)

# Flexible продукты
flexible = api.get_simple_earn_flexible_list(asset='USDT')
print(flexible)
# {
#   "rows": [
#     {
#       "asset": "USDT",
#       "latestAnnualPercentageRate": "0.06775211",  # APR
#       "tierAnnualPercentageRate": {...},
#       "dailyPurchaseLimit": "500000.00000000",      # ← ЛИМИТ!
#       "minPurchaseAmount": "0.10000000",
#       "purchasedAmount": "234567.89000000",        # ← КУПЛЕНО!
#       "canPurchase": true,
#       "canRedeem": true,
#       ...
#     }
#   ]
# }

# Locked продукты
locked = api.get_simple_earn_locked_list(asset='BTC')
print(locked)
# {
#   "rows": [
#     {
#       "asset": "BTC",
#       "projectId": "PROJECT123",
#       "duration": 30,
#       "interestPerLot": "0.00123000",
#       "interestRate": "0.05000000",
#       "lotSize": "0.01000000",
#       "lotsLowLimit": 1,
#       "lotsUpLimit": 100,                         # ← МАКС ЛОТОВ!
#       "maxLotsPerUser": 10,                       # ← ЛИМИТ НА ЮЗЕРА!
#       "needKyc": false,
#       ...
#     }
#   ]
# }
```

**Как добавить в бота:**

1. Добавить поля в модель `ApiLink`:
```python
# В data/models.py
class ApiLink(Base):
    # ...
    binance_api_key = Column(String, nullable=True)
    binance_api_secret = Column(String, nullable=True)  # Зашифровать!
```

2. Добавить в хендлеры настройки:
```python
# В bot/exchange_credentials_handlers.py
async def add_binance_api_credentials(user_id, link_id, api_key, api_secret):
    """Добавить API ключи Binance для получения полной информации"""
    # Сохранить в БД (api_secret зашифровать!)
```

3. Обновить парсер:
```python
# В parsers/staking_parser.py
def _parse_binance(self):
    # Если есть API ключи - использовать авторизованный API
    if self.binance_api_key:
        return self._parse_binance_with_auth()
    else:
        return self._parse_binance_public()  # Текущая реализация
```

---

### 2️⃣ **Браузерный парсинг (Playwright)**

**Плюсы:**
- ✅ Не требует API ключей
- ✅ Получает ту же информацию, что видит пользователь

**Минусы:**
- ❌ Медленный (запуск браузера)
- ❌ Нестабильный (структура HTML может меняться)
- ❌ Может требовать авторизацию
- ❌ Защита Cloudflare/reCAPTCHA

**Реализация:**

```python
from playwright.async_api import async_playwright

async def parse_binance_with_browser():
    """Парсинг Binance Earn через браузер"""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Открываем страницу Simple Earn
        await page.goto('https://www.binance.com/en/earn/simple-earn')
        
        # Ждем загрузки
        await page.wait_for_selector('.product-card')
        
        # Извлекаем данные
        products = await page.locator('.product-card').all()
        
        for product in products:
            # Извлекаем лимиты через селекторы
            coin = await product.locator('.coin-name').text_content()
            limit = await product.locator('.purchase-limit').text_content()
            available = await product.locator('.available-amount').text_content()
            # ...
        
        await browser.close()
```

**НЕ РЕКОМЕНДУЕТСЯ** из-за нестабильности и медленности.

---

### 3️⃣ **Показывать без лимитов** (ТЕКУЩЕЕ РЕШЕНИЕ)

**Плюсы:**
- ✅ Работает сейчас
- ✅ Не требует дополнительных настроек
- ✅ Стабильно

**Минусы:**
- ⚠️ Нет информации о лимитах

**Улучшения:**

Добавить информационное сообщение:

```python
# В notification_service.py для Binance

if 'binance' in exchange_name.lower():
    message += f"\n📊 <b>FIXED{term_str}</b> ({apr:.1f}% APR):\n"
    
    # Если нет лимитов - показываем инфо
    if not user_limit:
        message += f"   ℹ️ <i>Для просмотра лимитов и заполненности добавьте API ключи Binance</i>\n"
        message += f"   🔗 <a href='https://www.binance.com/en/earn'>Перейти на Binance →</a>\n"
```

---

## 🎯 Рекомендация

**Оптимальное решение:**

1. **По умолчанию** - показывать без лимитов (текущая реализация)
2. **Добавить функцию** - возможность подключить API ключи Binance (для продвинутых пользователей)
3. **В форматировании** - добавить информационное сообщение о том, что можно добавить API ключи

Это даст:
- ✅ Работает для всех сразу
- ✅ Продвинутые пользователи могут получить больше информации
- ✅ Стабильность и надежность

## 📚 Документация

- [Binance Simple Earn API](https://binance-docs.github.io/apidocs/spot/en/#simple-earn-endpoints)
- [API Authentication](https://binance-docs.github.io/apidocs/spot/en/#signed-trade-and-user_data-endpoint-security)
- [API Key Management](https://www.binance.com/en/my/settings/api-management)
