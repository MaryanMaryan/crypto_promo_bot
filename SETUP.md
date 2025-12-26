# Инструкция по установке Crypto Promo Bot

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Установка браузеров Playwright (критично!)

После установки зависимостей обязательно установите браузеры:

```bash
playwright install chromium
```

**Важно:** Без этого шага парсинг через браузер (browser_parser) НЕ БУДЕТ РАБОТАТЬ!

### 3. Настройка конфигурации

Создайте файл `.env` на основе шаблона:

```bash
cp .env.example .env
```

Откройте `.env` и заполните необходимые параметры:

```bash
# Обязательные параметры
BOT_TOKEN=your_bot_token_here          # Получите у @BotFather
ADMIN_CHAT_ID=your_admin_chat_id_here   # Ваш Telegram ID

# Опциональные параметры (можно оставить по умолчанию)
DATABASE_URL=sqlite:///data/database.db
DEFAULT_CHECK_INTERVAL=300
```

#### Как получить BOT_TOKEN:
1. Откройте Telegram и найдите @BotFather
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и скопируйте полученный токен

#### Как узнать свой ADMIN_CHAT_ID:
1. Откройте @userinfobot в Telegram
2. Отправьте любое сообщение
3. Скопируйте ваш ID (число)

### 4. Запуск бота

```bash
python main.py
```

---

## Решение проблем

### Ошибка: "Playwright не готов к работе"

Если при запуске видите ошибку о Playwright:

```bash
playwright install chromium
```

### Ошибка: "BOT_TOKEN не установлен"

Убедитесь, что:
1. Файл `.env` создан в корневой директории проекта
2. В `.env` есть строка `BOT_TOKEN=ваш_токен`
3. Токен скопирован БЕЗ лишних пробелов

### Ошибка: "playwright: command not found"

Переустановите playwright:

```bash
pip uninstall playwright
pip install playwright==1.56.0
playwright install chromium
```

### Ошибка импорта модулей

Если вы видите ошибки вида "ModuleNotFoundError":

```bash
pip install -r requirements.txt --upgrade
```

---

## Проверка установки

Для проверки корректности установки запустите:

```bash
python check_setup.py
```

Этот скрипт проверит:
- Наличие `.env` файла
- Корректность переменных окружения
- Установку всех зависимостей
- Установку браузеров Playwright

---

## Структура проекта

```
crypto_promo_bot/
├── .env                    # Ваша конфигурация (НЕ коммитится)
├── .env.example            # Шаблон конфигурации
├── config.py               # Загрузка конфигурации
├── main.py                 # Точка входа
├── requirements.txt        # Зависимости Python
├── check_setup.py          # Скрипт проверки установки
├── bot/                    # Логика бота
│   ├── handlers.py         # Обработчики команд
│   ├── keyboards.py        # Клавиатуры
│   └── ...
├── parsers/                # Парсеры (включая browser_parser)
│   ├── universal_parser.py
│   ├── browser_parser.py
│   └── ...
├── data/                   # База данных
│   └── database.db
└── utils/                  # Утилиты
    ├── playwright_checker.py  # Проверка Playwright
    └── ...
```

---

## Безопасность

**ВАЖНО:** Файл `.env` содержит секретные данные!

- ✅ `.env` уже добавлен в `.gitignore`
- ✅ НЕ коммитьте `.env` в Git
- ✅ НЕ делитесь содержимым `.env`
- ✅ Для шаринга используйте `.env.example`

---

## Дополнительная информация

### Зависимости

- `playwright==1.56.0` - Браузерная автоматизация
- `playwright-stealth==2.0.0` - Обход детекции автоматизации
- `python-dotenv==1.0.0` - Загрузка переменных окружения
- `aiogram==3.17.0` - Telegram Bot API
- `beautifulsoup4==4.12.2` - HTML парсинг
- `sqlalchemy==2.0.23` - ORM для работы с БД

Полный список в `requirements.txt`

### Автоматическая установка браузеров

Бот автоматически проверяет наличие браузеров Playwright при запуске.
Если браузеры не найдены, вы увидите предупреждение с инструкциями.

---

## Поддержка

Если у вас возникли проблемы:

1. Проверьте, что все шаги из "Быстрый старт" выполнены
2. Запустите `python check_setup.py` для диагностики
3. Проверьте логи бота в консоли
4. Убедитесь, что Python версии 3.11+

---

## Обновление

Для обновления зависимостей:

```bash
pip install -r requirements.txt --upgrade
playwright install chromium
```
