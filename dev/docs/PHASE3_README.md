# 🚀 ФАЗА 3: Парсер стейкинга - Руководство по использованию

## 📋 Что было реализовано

### ✅ Созданные компоненты

1. **`utils/price_fetcher.py`** - Получение цен токенов с CoinGecko
2. **`parsers/staking_parser.py`** - Универсальный парсер стейкингов
3. **Тестовые скрипты** - Для проверки работоспособности
4. **Документация** - Детальное описание API структуры

---

## 🔧 Использование

### 1. Получение цен токенов

```python
from utils.price_fetcher import get_price_fetcher

# Получение цены одного токена
fetcher = get_price_fetcher()
btc_price = fetcher.get_token_price("BTC")
print(f"BTC: ${btc_price}")

# Получение нескольких цен
prices = fetcher.get_multiple_prices(["BTC", "ETH", "DOGE"])
for symbol, price in prices.items():
    print(f"{symbol}: ${price}")
```

**Важно:**
- CoinGecko API имеет лимит 50 запросов/минуту (бесплатный план)
- Цены кэшируются на 5 минут
- Используйте `get_multiple_prices()` для оптимизации

---

### 2. Парсинг стейкингов Kucoin

```python
from parsers.staking_parser import StakingParser

# Создание парсера
parser = StakingParser(
    api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
    exchange_name="Kucoin"
)

# Получение всех стейкингов
stakings = parser.parse()

# Обработка результатов
for staking in stakings:
    print(f"{staking['coin']}: {staking['apr']}% APR")
    print(f"  Период: {staking['term_days']} дней")
    print(f"  Статус: {staking['status']}")
    print(f"  Категория: {staking['category']}")
```

---

### 3. Фильтрация стейкингов

```python
# Стейкинги с APR > 50%
high_apr = [s for s in stakings if s['apr'] > 50]

# Flexible стейкинги (без фиксированного срока)
flexible = [s for s in stakings if s['term_days'] == 0]

# Только ACTIVITY категория
activity = [s for s in stakings if s['category'] == 'ACTIVITY']

# Только ONGOING статус
ongoing = [s for s in stakings if s['status'] == 'ONGOING']
```

---

## 📊 Структура данных стейкинга

Каждый стейкинг возвращается в виде словаря:

```python
{
    'exchange': 'Kucoin',           # Биржа
    'product_id': '3439',            # ID продукта
    'coin': 'IR',                    # Основной токен
    'reward_coin': None,             # Токен вознаграждения (если отличается)
    'apr': 200.0,                    # APR в процентах
    'type': 'MULTI_TIME',            # Тип стейкинга
    'status': 'ONGOING',             # Статус
    'category': 'ACTIVITY',          # Категория
    'category_text': 'Promotions',  # Текстовое описание категории
    'term_days': 14,                 # Длительность в днях (0 = flexible)
    'token_price_usd': 0.15,        # Цена токена в USD

    # Следующие поля недоступны в публичном API Kucoin:
    'start_time': None,
    'end_time': None,
    'user_limit_tokens': None,
    'user_limit_usd': None,
    'total_places': None,
    'max_capacity': None,
    'current_deposit': None,
    'fill_percentage': None
}
```

---

## 🎯 Примеры использования

### Пример 1: Поиск лучших стейкингов

```python
from parsers.staking_parser import StakingParser

parser = StakingParser(
    api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
    exchange_name="Kucoin"
)

stakings = parser.parse()

# Сортировка по APR
sorted_stakings = sorted(stakings, key=lambda x: x['apr'], reverse=True)

print("ТОП-5 стейкингов по APR:")
for i, s in enumerate(sorted_stakings[:5], 1):
    print(f"{i}. {s['coin']}: {s['apr']}% APR ({s['term_days']} дней)")
```

### Пример 2: Уведомления о новых стейкингах

```python
def check_for_new_stakings(min_apr=50):
    """Проверить новые стейкинги с минимальным APR"""

    parser = StakingParser(
        api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
        exchange_name="Kucoin"
    )

    stakings = parser.parse()

    # Фильтр по APR
    good_stakings = [s for s in stakings if s['apr'] >= min_apr]

    for staking in good_stakings:
        message = f"""
🆕 НОВЫЙ СТЕЙКИНГ

💎 Монета: {staking['coin']}
💰 APR: {staking['apr']}%
📅 Период: {staking['term_days']} дней
📊 Статус: {staking['status']}
🏷️ Категория: {staking['category_text']}
        """

        # Отправить уведомление
        print(message)

    return good_stakings
```

### Пример 3: Интеграция с базой данных

```python
from data.database import get_db_session
from data.models import StakingHistory
from datetime import datetime

def save_stakings_to_db(stakings):
    """Сохранить стейкинги в базу данных"""

    with get_db_session() as session:
        for staking in stakings:
            # Проверяем, есть ли уже в БД
            existing = session.query(StakingHistory).filter(
                StakingHistory.exchange == staking['exchange'],
                StakingHistory.product_id == staking['product_id']
            ).first()

            if not existing:
                # Создаем новую запись
                new_staking = StakingHistory(
                    exchange=staking['exchange'],
                    product_id=staking['product_id'],
                    coin=staking['coin'],
                    reward_coin=staking['reward_coin'],
                    apr=staking['apr'],
                    type=staking['type'],
                    status=staking['status'],
                    category=staking['category'],
                    term_days=staking['term_days'],
                    token_price_usd=staking['token_price_usd'],
                    notification_sent=False
                )

                session.add(new_staking)
                print(f"✅ Новый стейкинг: {staking['coin']} {staking['apr']}% APR")
            else:
                # Обновляем существующую запись
                existing.apr = staking['apr']
                existing.status = staking['status']
                existing.last_updated = datetime.utcnow()

        session.commit()
```

---

## ⚠️ Важные замечания

### CoinGecko API

- **Rate Limit:** 50 запросов/минуту (бесплатный план)
- **Кэширование:** Цены кэшируются на 5 минут
- **Рекомендация:** Используйте `get_multiple_prices()` для массовых запросов

### Kucoin API

- **Доступно:** Основная информация о стейкингах
- **Недоступно:** Лимиты пользователя, заполненность пулов, временные метки
- **Обновление:** Рекомендуется проверять каждые 5-15 минут

### Bybit API

- **Статус:** Требует дополнительной аутентификации (403 Forbidden)
- **Решение:** Использовать browser parser (Playwright)
- **Альтернатива:** Искать другие публичные endpoints

---

## 🧪 Тестирование

### Запуск тестов

```bash
# Тест получения цен (может достичь rate limit)
python test_price_fetcher.py

# Тест парсера стейкингов (без получения цен)
python test_staking_parser_no_prices.py

# Изучение структуры API
python test_api_structure.py
```

### Ожидаемые результаты

- ✅ Успешное получение данных от Kucoin
- ✅ Парсинг 10-20 стейкингов
- ✅ Корректная структура данных
- ⚠️ 403 ошибка от Bybit (ожидаемо)

---

## 🔜 Следующие шаги

### Для продолжения реализации:

1. **Интеграция с browser parser** для Bybit
   - Использовать `parsers/browser_parser.py`
   - Обход защиты API

2. **Фаза 4: Сервис уведомлений**
   - Форматтеры сообщений
   - Проверка дубликатов
   - Отправка в Telegram

3. **Фаза 5: Интеграция**
   - Добавить в главный цикл парсинга
   - Настроить фильтры
   - Тестирование end-to-end

---

## 📚 Дополнительные ресурсы

- **PHASE3_SUMMARY.md** - Детальный отчет о выполнении
- **STAKING_TODOLIST.md** - Полный план реализации
- **kucoin_api_response.json** - Пример ответа API

---

## 💡 Советы по использованию

1. **Кэширование** - Используйте встроенное кэширование цен
2. **Rate Limiting** - Контролируйте частоту запросов к CoinGecko
3. **Обработка ошибок** - Всегда используйте try/except
4. **Логирование** - Включите логирование для отладки
5. **Мониторинг** - Проверяйте доступность API регулярно

---

**Дата:** 2025-12-25
**Версия:** 1.0
**Статус:** ✅ Готово к интеграции
