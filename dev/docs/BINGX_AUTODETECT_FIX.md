# Исправление автоопределения BingX/Bitget Launchpool - 21.01.2026

## Проблема

При добавлении URL для BingX/Bitget Launchpool (например, `https://bingx.com/ru-ru/launchpool`) система не определяла парсер автоматически и требовала ручного выбора:

```
⚠️ Парсер не определен автоматически
Шаг 3/3: Выберите парсер вручную
```

## Причина

В методе `_select_parser` (файл `bot/parser_service.py`) использовалась только прямая проверка биржи без учета типа (launchpool/launchpad):

```python
# ❌ БЫЛО:
exchange = self._extract_exchange_from_url(url)  # Возвращает 'bingx'

if exchange in self.SPECIAL_PARSERS:  # Ищет 'bingx', но есть только 'bingx_launchpool'
    parser_class = self.SPECIAL_PARSERS[exchange]
```

`_extract_exchange_from_url()` возвращает только название биржи (например, `'bingx'`), но в `SPECIAL_PARSERS` ключи содержат суффиксы: `'bingx_launchpool'`, `'gate_launchpool'`, etc.

## Решение

Добавлена интеллектуальная проверка с учетом:
1. **Категории** из БД (`category='launchpool'`)
2. **Содержимого URL** (проверка на `'launchpool'` или `'launchpad'` в пути)

```python
# ✅ СТАЛО:
# 1. Проверка по категории
if category in ['launchpool', 'launchpad']:
    parser_key = f"{exchange}_{category}"  # bingx_launchpool
    if parser_key in self.SPECIAL_PARSERS:
        return parser_class(target_url)

# 2. Проверка по содержимому URL
if 'launchpool' in url_lower:
    parser_key = f"{exchange}_launchpool"  # bingx_launchpool
    if parser_key in self.SPECIAL_PARSERS:
        return parser_class(target_url)
```

## Результат

✅ **BingX Launchpool** - определяется автоматически по URL или категории
✅ **Bitget Launchpool** - определяется автоматически
✅ **Gate Launchpool** - продолжает работать (без регрессии)
✅ **MEXC Launchpool** - продолжает работать
✅ **Bybit Launchpool** - продолжает работать

## Примеры автоопределения

| URL | Биржа | Категория | Парсер |
|-----|-------|-----------|--------|
| `https://bingx.com/ru-ru/launchpool` | bingx | launchpool | BingxLaunchpoolParser |
| `https://www.bitget.com/ru/launchpool` | bitget | launchpool | BitgetLaunchpoolParser |
| `https://www.gate.com/ru/launchpool` | gate | launchpool | GateLaunchpoolParser |
| `https://bingx.com/activity` | bingx | launchpool | BingxLaunchpoolParser (по категории) |

## Файлы изменены

- `bot/parser_service.py` - улучшен метод `_select_parser()` (строки 145-172)

## Преимущества

1. **Удобство** - не нужно вручную выбирать парсер
2. **Надежность** - работает даже если URL не содержит явного `launchpool`
3. **Гибкость** - учитывается и URL, и категория
4. **Обратная совместимость** - все существующие парсеры продолжают работать
