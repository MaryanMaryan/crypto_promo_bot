# Dev - Тестовые файлы и документация

Эта папка содержит файлы для разработки и тестирования, которые не влияют на работу бота.

## Структура

### tests/ - Тестовые скрипты

**Проверка настроек:**
- check_telegram_settings.py - Проверка настроек Telegram API в БД
- check_weex_link.py - Проверка конфигурации ссылки WEEX News
- check_promo_history.py - Просмотр истории промоакций

**Тестирование парсинга:**
- test_telegram_connection.py - Тест подключения к Telegram
- test_telegram_forward.py - Тест пересылки сообщений
- test_from_bot.py - Эмуляция вызова из бота
- test_weex_parsing.py - Тест парсинга WEEX News
- test_detailed.py - Детальный тест с DEBUG логами

**Утилиты:**
- clear_weex_promos.py - Очистка тестовых промоакций

### docs/ - Документация для разработчиков

- TELEGRAM_FIX_GUIDE.md - Руководство по исправлению проблем
- TELEGRAM_FORWARD_TEST.md - Инструкция по тестированию пересылки
- TELEGRAM_PARSER_TODO.md - TODO список

## Использование

```bash
# Проверка настроек
python dev/tests/check_telegram_settings.py

# Тестирование
python dev/tests/test_telegram_connection.py

# Очистка данных
python dev/tests/clear_weex_promos.py
```

Эти файлы НЕ нужны для работы бота - только для разработки и отладки.
