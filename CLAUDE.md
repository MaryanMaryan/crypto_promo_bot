# Инструкции для Claude Code

## Структура dev/
- `dev/tests/` - тесты (test_*.py, check_*.py, debug_*.py)
- `dev/todos/` - TODO листы (TODO_*.md)
- `dev/docs/` - документация (*.md, *.txt)
- `dev/test_data/` - тестовые данные (*.json, *.html)
- `dev/scripts/` - утилиты (add_*.py, setup_*.py, fix_*.py, migration.py)

## Защищенные файлы (НЕ перемещать в dev/)
- `bybit_coin_mapping.py` - маппинг для staking_parser.py
- `main.py` - точка входа
- `config.py` - конфигурация

## Сессии Telegram
- Хранить в `sessions/` (не в корне)
- Формат пути: `sessions/имя_сессии`
