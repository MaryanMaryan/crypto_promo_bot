# Исправление Gate Launchpool - 21.01.2026

## Проблема

При попытке получить текущие промоакции от Gate Launchpool через "Принудительную проверку" возникала ошибка:
```
parsers.universal_parser - ERROR - ❌ Ошибка прямого запроса: Expecting value: line 1 column 1 (char 0)
parsers.universal_parser - ERROR - ❌ Все попытки неудачны для gate
bot.handlers - INFO - 📊 Получено через API: 0 промоакций
```

## Причина

В обработчике "Принудительная проверка" (`force_check_promos` в `bot/handlers.py`) напрямую использовался `UniversalParser` вместо правильного выбора парсера через `ParserService._select_parser()`.

```python
# ❌ БЫЛО (неправильно):
else:
    from parsers.universal_parser import UniversalParser
    parser = UniversalParser(api_url)
    api_promos = parser.get_promotions()
```

Это приводило к тому, что для Gate Launchpool (с `special_parser='gate_launchpool'`) не использовался специализированный `GateLaunchpoolParser`, который правильно обрабатывает Gate.io API.

## Решение

### 1. Исправлен выбор парсера в `bot/handlers.py`

Заменили прямое использование `UniversalParser` на правильный выбор через `ParserService._select_parser()`:

```python
# ✅ СТАЛО (правильно):
# Используем ParserService для правильного выбора парсера
from bot.parser_service import ParserService

def run_parser():
    parser_service = ParserService()
    # Используем _select_parser для правильного выбора парсера (включая gate_launchpool)
    parser = parser_service._select_parser(
        url=page_url or api_url or html_url,
        api_url=api_url,
        html_url=html_url,
        parsing_type=parsing_type,
        special_parser=link.special_parser,
        category=link.category
    )
    return parser.get_promotions()

loop = asyncio.get_event_loop()
api_promos = await loop.run_in_executor(get_executor(), run_parser)
```

### 2. Улучшен `UniversalParser` для диагностики

Добавлена проверка `Content-Type` перед парсингом JSON и логирование содержимого при ошибках:

```python
# Проверяем Content-Type перед парсингом JSON
content_type = response.headers.get('content-type', '').lower()
if 'application/json' not in content_type:
    logger.error(f"❌ Неверный Content-Type: {content_type}")
    logger.debug(f"   Первые 500 символов ответа: {response.text[:500]}")
    raise ValueError(f"Ответ не является JSON (Content-Type: {content_type})")
```

## Результат

✅ `GateLaunchpoolParser` теперь правильно используется для Gate Launchpool
✅ Получаем 50 активных проектов от Gate.io Launchpool
✅ Данные корректно преобразуются в формат промоакций
✅ Улучшена диагностика ошибок в `UniversalParser`

## Файлы изменены

1. `bot/handlers.py` - исправлен выбор парсера в `force_check_promos`
2. `parsers/universal_parser.py` - добавлена проверка Content-Type

## Тестирование

Создан и успешно пройден тест, имитирующий "Принудительную проверку":
- Правильно выбирается `GateLaunchpoolParser`
- Получено 50 проектов от Gate.io
- Данные преобразованы в формат промоакций

## Команда для проверки

```bash
python -c "
from parsers.gate_launchpool_parser import GateLaunchpoolParser
parser = GateLaunchpoolParser()
promos = parser.get_promotions()
print(f'Получено {len(promos)} промоакций')
"
```
