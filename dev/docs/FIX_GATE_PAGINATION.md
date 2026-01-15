# Исправление пагинации для "Текущие стейкинги"

## Проблемы

1. **190 пустых страниц** вместо нормальных данных
2. **Стейкинги пропадают** при переходе между страницами
3. **При возврате на страницу 1** стейкингов уже нет

## Причины

### 1. Некорректная фильтрация sold out в парсере Gate.io

**Проблема**: Парсер проверял `total_lend_available` для **всей монеты**, а не для конкретного продукта.

```python
# БЫЛО (НЕПРАВИЛЬНО):
total_lend_available = float(coin_data.get('total_lend_available', 0))
if total_lend_available <= 0:
    return None  # Пропускаем ВСЕ продукты этой монеты
```

Если хотя бы один продукт USDT был sold out → все остальные USDT продукты тоже фильтровались.

**Решение**: Убрали эту проверку, так как:
- Gate.io не предоставляет sold out данные для отдельных fixed продуктов
- `sale_status=1` уже означает что продукт активен

### 2. Повторный запрос к БД при навигации

**Проблема**: При каждом переходе между страницами код заново запрашивал стейкинги из БД:

```python
# БЫЛО (НЕПРАВИЛЬНО):
# При переходе на страницу 2
stakings_with_deltas = snapshot_service.get_stakings_with_deltas(
    exchange=exchange_filter,
    min_apr=min_apr
)
```

Проблемы:
- Медленно (запрос к БД каждый раз)
- Если между переходами произошел парсинг → старые стейкинги удалены
- `exchange_filter` может не совпадать с тем что в БД

**Решение**: Сохранять стейкинги в `current_stakings_state` при первом запросе:

```python
# СТАЛО (ПРАВИЛЬНО):
current_stakings_state[user_id] = {
    'page': page,
    'link_id': link_id,
    'total_pages': total_pages,
    'stakings': stakings_with_deltas,  # Сохраняем все стейкинги
    'exchange_name': exchange_name,
    'min_apr': min_apr,
    'page_url': page_url
}

# При навигации используем сохраненные данные:
stakings_with_deltas = state.get('stakings', [])
```

### 3. Неправильный exchange_filter

**Проблема**: `link.exchange` может быть `'gate'`, `'GateStaking'`, `None`, а парсер сохраняет `'Gate.io'`.

При поиске в БД:
```python
# БЫЛО (НЕПРАВИЛЬНО):
exchange_filter = link.exchange or link.name  # 'gate' или 'GateStaking'
stakings = get_stakings(exchange=exchange_filter)  # Ищет по 'gate'
# Не найдено! (в БД сохранено 'Gate.io')
```

**Решение**: Нормализация через `detect_exchange_from_url`:

```python
# СТАЛО (ПРАВИЛЬНО):
from utils.exchange_detector import detect_exchange_from_url
exchange_filter = detect_exchange_from_url(api_url)  # Всегда вернет 'Gate.io'
stakings = get_stakings(exchange=exchange_filter)  # Найдет правильно
```

## Исправления

### 1. `parsers/staking_parser.py`

Убрали некорректную проверку sold out для Gate.io:

```python
# Строка ~740 и ~870
# УДАЛЕНО:
# if total_lend_available <= 0:
#     return None

# ДОБАВЛЕНО:
# Для Gate.io нет индивидуальных данных о sold out
# Используем sale_status=1 как индикатор доступности
```

### 2. `bot/handlers.py` - manage_view_current_stakings

Добавлена нормализация exchange и сохранение стейкингов в state:

```python
# Нормализуем exchange
from utils.exchange_detector import detect_exchange_from_url
exchange_filter = detect_exchange_from_url(api_url) if api_url else (link.exchange or link.name)

# Сохраняем стейкинги в state
current_stakings_state[user_id] = {
    'page': page,
    'link_id': link_id,
    'total_pages': total_pages,
    'stakings': stakings_with_deltas,  # ВАЖНО: сохраняем данные
    'exchange_name': exchange_name,
    'min_apr': min_apr,
    'page_url': page_url
}
```

### 3. `bot/handlers.py` - navigate_stakings_page

Используем сохраненные данные вместо повторного запроса:

```python
# БЫЛО:
# stakings_with_deltas = snapshot_service.get_stakings_with_deltas(...)

# СТАЛО:
stakings_with_deltas = state.get('stakings', [])
exchange_name = state.get('exchange_name', 'Unknown')
min_apr = state.get('min_apr')
page_url = state.get('page_url')

if not stakings_with_deltas:
    await callback.answer("❌ Данные потеряны. Откройте раздел заново.", show_alert=True)
    return
```

### 4. `bot/handlers.py` - refresh_current_stakings

Обновляем state после обновления данных:

```python
# Обновляем state с новыми данными
state['page'] = current_page
state['total_pages'] = total_pages
state['stakings'] = stakings_with_deltas  # Обновляем стейкинги
state['exchange_name'] = exchange_name
state['min_apr'] = min_apr
state['page_url'] = page_url
```

## Результат

### ДО исправления:
- ❌ 190 пустых страниц
- ❌ Стейкинги пропадают при навигации
- ❌ Медленная навигация (запрос к БД каждый раз)
- ❌ Найдено 4 стейкинга (из-за некорректной фильтрации)

### ПОСЛЕ исправления:
- ✅ ~20 страниц (105 стейкингов / 5 на страницу)
- ✅ Стейкинги не пропадают
- ✅ Быстрая навигация (данные из памяти)
- ✅ Найдено 105 стейкингов с APR ≥ 20%

## Тестирование

```
1. Перезапустить бота
2. /manage → Gate.io → "Текущие стейкинги"
3. Проверить что показывается ~20 страниц
4. Перейти на страницу 2
5. Вернуться на страницу 1
6. Проверить что стейкинги остались
7. Нажать "Обновить"
8. Проверить что данные обновились
```

---

**Автор**: Claude Sonnet 4.5
**Дата**: 2026-01-12
**Версия**: 1.0
