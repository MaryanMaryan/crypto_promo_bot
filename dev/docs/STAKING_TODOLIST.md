# 📋 TODOLIST: РЕАЛИЗАЦИЯ СТЕЙКИНГ СИСТЕМЫ

## 🎯 ЦЕЛЬ ПРОЕКТА
Создать универсальную систему парсинга и мониторинга стейкингов с криптобирж (Kucoin, Bybit) с двумя типами уведомлений:
1. **Автоматические уведомления о новых стейкингах**
2. **Заполненность пулов по запросу через кнопку**

---

## 📊 АРХИТЕКТУРА СИСТЕМЫ

```
crypto_promo_bot/
├── bot/
│   ├── handlers.py (обновить меню и навигацию)
│   ├── notification_service.py (добавить форматтеры стейкинга)
│   └── parser_service.py (интеграция со стейкинг-парсером)
├── parsers/
│   ├── staking_parser.py (НОВЫЙ - универсальный парсер стейкинга)
│   └── base_parser.py (без изменений)
├── data/
│   ├── models.py (добавить поля для стейкинга)
│   └── database.py (миграция БД)
├── utils/
│   └── price_fetcher.py (НОВЫЙ - получение цен с CoinGecko/CMC)
└── config.py (настройки API ключей)
```

---

# 🔴 ФАЗА 1: БАЗА ДАННЫХ И МОДЕЛИ

## ✅ Задача 1.1: Обновить модель ApiLink
**Файл:** `data/models.py`

**Добавить поля:**
```python
class ApiLink(Base):
    # ... существующие поля ...

    # НОВЫЕ ПОЛЯ:
    category = Column(String, default='general')  # 'staking', 'launchpool', 'airdrop', 'announcement'
    page_url = Column(String, nullable=True)  # Ссылка на страницу акций

    # Фильтры для стейкинга (только для category='staking'):
    min_apr = Column(Float, nullable=True)  # Минимальный APR для показа
    track_fill = Column(Boolean, default=False)  # Отслеживать заполненность
    statuses_filter = Column(String, nullable=True)  # JSON список статусов: ["ONGOING", "INTERESTING"]
    types_filter = Column(String, nullable=True)  # JSON список типов: ["Flexible", "Fixed"]
```

**Что делать:**
- Открыть `data/models.py`
- Найти класс `ApiLink`
- Добавить новые поля после существующих
- Сохранить файл

---

## ✅ Задача 1.2: Создать таблицу StakingHistory
**Файл:** `data/models.py`

**Добавить новую модель:**
```python
class StakingHistory(Base):
    __tablename__ = 'staking_history'

    id = Column(Integer, primary_key=True)

    # Основная информация
    exchange = Column(String, nullable=False)  # 'Kucoin', 'Bybit'
    product_id = Column(String, nullable=False)  # ID от биржи
    coin = Column(String, nullable=False)  # 'BTC', 'ETH', 'DOGE'
    reward_coin = Column(String, nullable=True)  # Для Bybit (награда в другой монете)

    # Условия стейкинга
    apr = Column(Float, nullable=False)  # 200.0, 100.0
    type = Column(String, nullable=True)  # 'Flexible', 'Fixed 30d', 'MULTI_TIME'
    status = Column(String, nullable=True)  # 'Active', 'Sold Out', 'ONGOING', 'INTERESTING'
    category = Column(String, nullable=True)  # 'ACTIVITY', 'DEMAND' (Kucoin)
    term_days = Column(Integer, nullable=True)  # 14, 30, 90

    # Лимиты и пулы
    user_limit_tokens = Column(Float, nullable=True)  # 5000 IR, 7.24 DOGE
    user_limit_usd = Column(Float, nullable=True)  # $664, $2.50
    total_places = Column(Integer, nullable=True)  # 298 мест

    # Данные о заполненности (если доступны)
    max_capacity = Column(Float, nullable=True)  # Максимальная вместимость
    current_deposit = Column(Float, nullable=True)  # Текущий депозит
    fill_percentage = Column(Float, nullable=True)  # Процент заполнения

    # Цены токенов
    token_price_usd = Column(Float, nullable=True)  # Цена основной монеты
    reward_token_price_usd = Column(Float, nullable=True)  # Цена наградной монеты

    # Временные метки
    start_time = Column(String, nullable=True)  # ISO format
    end_time = Column(String, nullable=True)  # ISO format
    first_seen = Column(DateTime, default=datetime.utcnow)  # Когда впервые нашли
    last_updated = Column(DateTime, default=datetime.utcnow)  # Последнее обновление

    # Флаги
    notification_sent = Column(Boolean, default=False)  # Отправили ли уведомление о новом

    # Уникальность по бирже и product_id
    __table_args__ = (
        UniqueConstraint('exchange', 'product_id', name='_exchange_product_uc'),
    )
```

**Что делать:**
- Открыть `data/models.py`
- Добавить новый класс `StakingHistory` в конец файла
- Добавить импорт `from datetime import datetime` вверху файла если его нет
- Сохранить файл

---

## ✅ Задача 1.3: Создать миграцию БД
**Файл:** `data/database.py`

**Что делать:**
1. Открыть `data/database.py`
2. Найти функцию `init_db()` или аналогичную
3. Убедиться, что она вызывает `Base.metadata.create_all(engine)` для создания всех таблиц
4. Запустить скрипт для применения миграции:

```python
# Создать временный скрипт migration.py в корне проекта:
from data.database import init_db

if __name__ == "__main__":
    print("🔄 Применение миграции БД...")
    init_db()
    print("✅ Миграция завершена!")
```

5. Запустить: `python migration.py`
6. Проверить, что таблица `staking_history` создана

---

# 🔵 ФАЗА 2: ИНТЕРФЕЙС БОТА

## ✅ Задача 2.1: Обновить главное меню
**Файл:** `bot/handlers.py`

**Текущее меню:**
```
📊 Список ссылок
➕ Добавить ссылку
⚙️ Управление ссылками
🔧 Управление прокси
👤 Управление User-Agent
📈 Статистика системы
⚙️ Настройки ротации
🔄 Проверить все
📋 История промоакций
❓ Помощь
```

**НОВОЕ меню:**
```
📊 Список ссылок
➕ Добавить ссылку
⚙️ Управление ссылками  <-- изменить на подменю
🔄 Проверить всё
🛡️ Обход блокировок  <-- НОВАЯ КНОПКА
```

**Что делать:**
1. Найти функцию `get_main_menu()` в `bot/handlers.py`
2. Заменить кнопки на новые (убрать лишние, добавить "Обход блокировок")
3. Кнопка "Управление ссылками" должна вести в подменю (следующая задача)

**Код:**
```python
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Список ссылок"))
    builder.add(KeyboardButton(text="➕ Добавить ссылку"))
    builder.add(KeyboardButton(text="⚙️ Управление ссылками"))
    builder.add(KeyboardButton(text="🔄 Проверить всё"))
    builder.add(KeyboardButton(text="🛡️ Обход блокировок"))
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)
```

---

## ✅ Задача 2.2: Создать подменю "Управление ссылками"
**Файл:** `bot/handlers.py`

**Подменю с разделами:**
```
⚙️ Управление ссылками:

🪂 Аирдроп
💰 Стейкинг
🚀 Лаунчпул
📢 Анонс
❌ Назад
```

**Что делать:**
1. Создать функцию `get_category_management_menu()`:

```python
def get_category_management_menu():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data="category_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

2. Создать обработчик для кнопки "⚙️ Управление ссылками":

```python
@router.message(F.text == "⚙️ Управление ссылками")
async def show_category_management(message: Message):
    await message.answer(
        "🗂️ Выберите раздел для управления:",
        reply_markup=get_category_management_menu()
    )
```

---

## ✅ Задача 2.3: Обработка выбора категории
**Файл:** `bot/handlers.py`

**Что делать:**
При нажатии на категорию (например, "💰 Стейкинг") показывать список ссылок ТОЛЬКО этой категории с действиями:

```python
@router.callback_query(F.data.startswith("category_"))
async def handle_category_selection(callback: CallbackQuery):
    category = callback.data.replace("category_", "")  # 'staking', 'airdrop', и т.д.

    # Получаем ссылки из БД по категории
    with get_db_session() as session:
        links = session.query(ApiLink).filter(ApiLink.category == category).all()

    if not links:
        await callback.message.edit_text(
            f"📭 В разделе '{category}' пока нет ссылок",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Назад", callback_data="back_to_categories")]
            ])
        )
        return

    # Показываем список ссылок с действиями
    keyboard = get_links_keyboard_for_category(links, category)
    await callback.message.edit_text(
        f"🗂️ Ссылки в категории '{category}':\n\n"
        f"Выберите ссылку для управления:",
        reply_markup=keyboard
    )
```

---

## ✅ Задача 2.4: Меню управления ссылкой (с новой кнопкой для стейкинга)
**Файл:** `bot/handlers.py`

**Текущее меню управления:**
```
🗑️ Удалить ссылку
⏰ Изменить интервал
✏️ Переименовать ссылку
🎯 Настроить парсинг
⏸️ Остановить парсинг
▶️ Возобновить парсинг
🔧 Принудительно проверить
❌ Отмена
```

**НОВОЕ меню для стейкинга (добавить кнопку):**
```
🗑️ Удалить ссылку
⏰ Изменить интервал
✏️ Переименовать ссылку
🎯 Настроить парсинг
📊 Проверить заполненность пулов  <-- НОВАЯ КНОПКА (только для стейкинга!)
⏸️ Остановить парсинг
▶️ Возобновить парсинг
🔧 Принудительно проверить
❌ Отмена
```

**Что делать:**
1. Найти функцию `get_management_keyboard()` или создать новую `get_staking_management_keyboard()`:

```python
def get_staking_management_keyboard():
    """Меню управления для ссылок категории 'staking'"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data="manage_delete"))
    builder.add(InlineKeyboardButton(text="⏰ Изменить интервал", callback_data="manage_interval"))
    builder.add(InlineKeyboardButton(text="✏️ Переименовать ссылку", callback_data="manage_rename"))
    builder.add(InlineKeyboardButton(text="🎯 Настроить парсинг", callback_data="manage_configure_parsing"))
    # НОВАЯ КНОПКА:
    builder.add(InlineKeyboardButton(text="📊 Проверить заполненность пулов", callback_data="manage_check_pools"))
    builder.add(InlineKeyboardButton(text="⏸️ Остановить парсинг", callback_data="manage_pause"))
    builder.add(InlineKeyboardButton(text="▶️ Возобновить парсинг", callback_data="manage_resume"))
    builder.add(InlineKeyboardButton(text="🔧 Принудительно проверить", callback_data="manage_force_check"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="manage_cancel"))
    builder.adjust(1)
    return builder.as_markup()
```

2. При выборе ссылки проверять категорию и показывать соответствующее меню:

```python
@router.callback_query(F.data.startswith("manage_link_"))
async def show_link_management(callback: CallbackQuery):
    link_id = int(callback.data.replace("manage_link_", ""))

    with get_db_session() as session:
        link = session.query(ApiLink).filter(ApiLink.id == link_id).first()

        if link.category == 'staking':
            keyboard = get_staking_management_keyboard()
        else:
            keyboard = get_management_keyboard()

    await callback.message.edit_text(
        f"⚙️ Управление ссылкой: {link.name}\n\n"
        f"Выберите действие:",
        reply_markup=keyboard
    )
```

---

## ✅ Задача 2.5: Обработчик кнопки "Проверить заполненность пулов"
**Файл:** `bot/handlers.py`

**Что делать:**
Создать обработчик, который:
1. Получает ID выбранной ссылки из контекста
2. Запускает парсинг заполненности пулов
3. Отправляет форматированное сообщение с отчётом

```python
@router.callback_query(F.data == "manage_check_pools")
async def check_staking_pools(callback: CallbackQuery):
    """Проверка заполненности пулов для выбранной ссылки стейкинга"""

    # Получаем ID ссылки из navigation_stack или user_selections
    user_id = callback.from_user.id
    current_nav = get_current_navigation(user_id)
    link_id = current_nav.get('data', {}).get('link_id') if current_nav else None

    if not link_id:
        await callback.answer("❌ Ошибка: ссылка не выбрана", show_alert=True)
        return

    await callback.message.edit_text("⏳ Проверяю заполненность пулов...")

    try:
        # Получаем ссылку из БД
        with get_db_session() as session:
            link = session.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.message.edit_text("❌ Ссылка не найдена")
                return

        # Парсим заполненность (вызываем парсер)
        from parsers.staking_parser import StakingParser
        parser = StakingParser(link.url, link.name)
        pools_data = parser.get_pool_fills()

        # Форматируем сообщение
        from bot.notification_service import format_pools_report
        message_text = format_pools_report(pools_data, link.name, link.page_url)

        # Отправляем результат
        await callback.message.edit_text(message_text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Ошибка при проверке заполненности пулов: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Ошибка при проверке: {e}")
```

---

## ✅ Задача 2.6: Обновить процесс добавления ссылки
**Файл:** `bot/handlers.py`

**Что добавить:**
1. Выбор категории (Аирдроп, Стейкинг, Лаунчпул, Анонс) в начале
2. Для стейкинга: запрос фильтров (мин. APR, статусы, типы)
3. Запрос ссылки на страницу акций (`page_url`)

**Обновить FSM состояния:**
```python
class AddLinkStates(StatesGroup):
    waiting_for_category = State()  # НОВОЕ: выбор категории
    waiting_for_name = State()
    waiting_for_parsing_type = State()
    waiting_for_api_url = State()
    waiting_for_html_url = State()
    waiting_for_page_url = State()  # НОВОЕ: ссылка на страницу акций
    waiting_for_interval = State()
    # Для стейкинга:
    waiting_for_min_apr = State()  # НОВОЕ: минимальный APR
    waiting_for_statuses = State()  # НОВОЕ: выбор статусов
```

**Обработчик начала добавления:**
```python
@router.message(F.text == "➕ Добавить ссылку")
async def start_add_link(message: Message, state: FSMContext):
    """Начало процесса добавления ссылки"""

    # Показываем выбор категории
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🪂 Аирдроп", callback_data="add_category_airdrop"))
    builder.add(InlineKeyboardButton(text="💰 Стейкинг", callback_data="add_category_staking"))
    builder.add(InlineKeyboardButton(text="🚀 Лаунчпул", callback_data="add_category_launchpool"))
    builder.add(InlineKeyboardButton(text="📢 Анонс", callback_data="add_category_announcement"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add"))
    builder.adjust(2, 2, 1)

    await message.answer(
        "🗂️ Выберите категорию ссылки:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AddLinkStates.waiting_for_category)
```

**Обработчик выбора категории:**
```python
@router.callback_query(F.data.startswith("add_category_"), StateFilter(AddLinkStates.waiting_for_category))
async def handle_category_choice(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("add_category_", "")

    # Сохраняем категорию в state
    await state.update_data(category=category)

    await callback.message.edit_text(
        f"✅ Категория: {category}\n\n"
        f"📝 Введите название биржи или ссылки:"
    )
    await state.set_state(AddLinkStates.waiting_for_name)
```

**Добавить запрос page_url после получения API URL:**
```python
# После получения API/HTML URL:
@router.message(StateFilter(AddLinkStates.waiting_for_api_url))
async def process_api_url(message: Message, state: FSMContext):
    api_url = message.text.strip()
    await state.update_data(api_url=api_url)

    # Запрашиваем ссылку на страницу акций
    await message.answer(
        "🔗 Отлично! Теперь отправьте ссылку на СТРАНИЦУ АКЦИЙ\n\n"
        "Эта ссылка будет добавлена в уведомления.\n"
        "Например: https://www.kucoin.com/ru/earn\n\n"
        "Или отправьте '-' если не нужно:"
    )
    await state.set_state(AddLinkStates.waiting_for_page_url)

@router.message(StateFilter(AddLinkStates.waiting_for_page_url))
async def process_page_url(message: Message, state: FSMContext):
    page_url = message.text.strip() if message.text.strip() != '-' else None
    await state.update_data(page_url=page_url)

    # Продолжаем дальше (интервал или фильтры для стейкинга)
    data = await state.get_data()
    category = data.get('category')

    if category == 'staking':
        # Запрашиваем фильтры для стейкинга
        await message.answer(
            "⚙️ Настройка фильтров для стейкинга\n\n"
            "Введите минимальный APR (в процентах) или '-' чтобы пропустить:\n"
            "Например: 50"
        )
        await state.set_state(AddLinkStates.waiting_for_min_apr)
    else:
        # Для других категорий - запрашиваем интервал
        await message.answer("⏰ Введите интервал проверки (в секундах):")
        await state.set_state(AddLinkStates.waiting_for_interval)
```

**Обработка фильтров стейкинга:**
```python
@router.message(StateFilter(AddLinkStates.waiting_for_min_apr))
async def process_min_apr(message: Message, state: FSMContext):
    min_apr_text = message.text.strip()
    min_apr = None

    if min_apr_text != '-':
        try:
            min_apr = float(min_apr_text)
        except ValueError:
            await message.answer("❌ Неверный формат. Введите число или '-'")
            return

    await state.update_data(min_apr=min_apr)

    # Запрашиваем статусы
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ ONGOING", callback_data="status_ongoing"))
    builder.add(InlineKeyboardButton(text="✅ INTERESTING", callback_data="status_interesting"))
    builder.add(InlineKeyboardButton(text="✅ ОБА", callback_data="status_both"))
    builder.add(InlineKeyboardButton(text="➡️ Пропустить", callback_data="status_skip"))
    builder.adjust(2, 1, 1)

    await message.answer(
        "📊 Какие статусы стейкингов парсить?",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AddLinkStates.waiting_for_statuses)

@router.callback_query(F.data.startswith("status_"), StateFilter(AddLinkStates.waiting_for_statuses))
async def process_statuses(callback: CallbackQuery, state: FSMContext):
    status_choice = callback.data.replace("status_", "")

    statuses = None
    if status_choice == "ongoing":
        statuses = ["ONGOING"]
    elif status_choice == "interesting":
        statuses = ["INTERESTING"]
    elif status_choice == "both":
        statuses = ["ONGOING", "INTERESTING"]

    await state.update_data(statuses_filter=json.dumps(statuses) if statuses else None)

    # Теперь запрашиваем интервал
    await callback.message.edit_text("⏰ Введите интервал проверки (в секундах):")
    await state.set_state(AddLinkStates.waiting_for_interval)
```

**Сохранение в БД с новыми полями:**
```python
# В финальном обработчике после получения интервала:
@router.message(StateFilter(AddLinkStates.waiting_for_interval))
async def save_new_link(message: Message, state: FSMContext):
    interval_text = message.text.strip()

    try:
        interval = int(interval_text)
    except ValueError:
        await message.answer("❌ Неверный формат интервала")
        return

    # Получаем все данные
    data = await state.get_data()

    # Создаём новую ссылку
    new_link = ApiLink(
        name=data['name'],
        url=data.get('api_url') or data.get('html_url'),
        parsing_type=data.get('parsing_type'),
        check_interval=interval,
        is_active=True,
        # НОВЫЕ ПОЛЯ:
        category=data.get('category', 'general'),
        page_url=data.get('page_url'),
        min_apr=data.get('min_apr'),
        statuses_filter=data.get('statuses_filter')
    )

    # Сохраняем в БД
    with get_db_session() as session:
        session.add(new_link)
        session.commit()

    await message.answer(
        f"✅ Ссылка добавлена!\n\n"
        f"Название: {new_link.name}\n"
        f"Категория: {new_link.category}\n"
        f"Интервал: {new_link.check_interval}с",
        reply_markup=get_main_menu()
    )
    await state.clear()
```

---

# 🟢 ФАЗА 3: ПАРСЕР СТЕЙКИНГА

## ✅ Задача 3.1: Создать утилиту получения цен токенов
**Файл:** `utils/price_fetcher.py` (НОВЫЙ)

**Что создать:**
Утилита для получения цен токенов с CoinGecko или CoinMarketCap.

**Код:**
```python
"""
utils/price_fetcher.py
Утилита для получения актуальных цен криптовалют
"""

import requests
import logging
from typing import Optional, Dict
import time

logger = logging.getLogger(__name__)

class PriceFetcher:
    """Получение цен токенов с CoinGecko"""

    COINGECKO_API = "https://api.coingecko.com/api/v3"
    CACHE_DURATION = 300  # 5 минут кэш

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # {symbol: (price, timestamp)}

    def get_token_price(self, symbol: str) -> Optional[float]:
        """
        Получить цену токена в USD

        Args:
            symbol: Символ токена (BTC, ETH, DOGE)

        Returns:
            Цена в USD или None если не найдена
        """
        symbol = symbol.upper()

        # Проверяем кэш
        if symbol in self._cache:
            price, timestamp = self._cache[symbol]
            if time.time() - timestamp < self.CACHE_DURATION:
                logger.debug(f"💰 Цена {symbol} из кэша: ${price}")
                return price

        try:
            # Получаем цену с CoinGecko
            logger.info(f"📡 Запрос цены {symbol} с CoinGecko...")

            # Сначала находим ID монеты
            search_url = f"{self.COINGECKO_API}/search"
            params = {"query": symbol}
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()

            search_data = response.json()

            # Ищем точное совпадение по symbol
            coin_id = None
            for coin in search_data.get('coins', []):
                if coin['symbol'].upper() == symbol:
                    coin_id = coin['id']
                    break

            if not coin_id:
                logger.warning(f"⚠️ Монета {symbol} не найдена на CoinGecko")
                return None

            # Получаем цену
            price_url = f"{self.COINGECKO_API}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd"
            }
            response = requests.get(price_url, params=params, timeout=10)
            response.raise_for_status()

            price_data = response.json()
            price = price_data.get(coin_id, {}).get('usd')

            if price:
                # Сохраняем в кэш
                self._cache[symbol] = (price, time.time())
                logger.info(f"✅ Цена {symbol}: ${price}")
                return price
            else:
                logger.warning(f"⚠️ Цена {symbol} не найдена в ответе")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка запроса цены {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при получении цены {symbol}: {e}")
            return None

    def get_multiple_prices(self, symbols: list) -> Dict[str, Optional[float]]:
        """
        Получить цены нескольких токенов

        Args:
            symbols: Список символов ['BTC', 'ETH', 'DOGE']

        Returns:
            Словарь {symbol: price}
        """
        prices = {}
        for symbol in symbols:
            prices[symbol] = self.get_token_price(symbol)
        return prices


# Singleton instance
_price_fetcher = None

def get_price_fetcher() -> PriceFetcher:
    """Получить singleton instance PriceFetcher"""
    global _price_fetcher
    if _price_fetcher is None:
        _price_fetcher = PriceFetcher()
    return _price_fetcher
```

**Что делать:**
1. Создать файл `utils/price_fetcher.py`
2. Скопировать код выше
3. Протестировать:

```python
# Тест:
from utils.price_fetcher import get_price_fetcher

fetcher = get_price_fetcher()
price = fetcher.get_token_price("BTC")
print(f"BTC price: ${price}")
```

---

## ✅ Задача 3.2: Создать универсальный парсер стейкинга
**Файл:** `parsers/staking_parser.py` (НОВЫЙ)

**Что создать:**
Универсальный парсер для Kucoin и Bybit стейкингов.

**Структура класса:**
```python
"""
parsers/staking_parser.py
Универсальный парсер стейкингов для Kucoin и Bybit
"""

import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from utils.price_fetcher import get_price_fetcher

logger = logging.getLogger(__name__)

class StakingParser:
    """Парсер стейкингов"""

    def __init__(self, api_url: str, exchange_name: str):
        self.api_url = api_url
        self.exchange_name = exchange_name.lower()
        self.price_fetcher = get_price_fetcher()

    def parse(self) -> List[Dict[str, Any]]:
        """
        Основной метод парсинга стейкингов

        Returns:
            Список стейкингов в унифицированном формате
        """
        try:
            logger.info(f"🔍 Парсинг стейкингов: {self.exchange_name}")

            # Получаем JSON от API
            response = requests.get(self.api_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Парсим в зависимости от биржи
            if 'kucoin' in self.exchange_name:
                return self._parse_kucoin(data)
            elif 'bybit' in self.exchange_name:
                return self._parse_bybit(data)
            else:
                logger.warning(f"⚠️ Неизвестная биржа: {self.exchange_name}")
                return []

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга стейкингов: {e}", exc_info=True)
            return []

    def _parse_kucoin(self, data: dict) -> List[Dict[str, Any]]:
        """Парсинг Kucoin стейкингов"""
        stakings = []

        products = data.get('data', [])
        if not products:
            logger.warning("⚠️ Kucoin: нет данных о стейкингах")
            return []

        logger.info(f"📊 Kucoin: найдено {len(products)} стейкингов")

        for product in products:
            try:
                coin = product.get('currency')
                apr = float(product.get('total_apr', 0))

                # Получаем цену токена
                token_price = self.price_fetcher.get_token_price(coin)

                # Рассчитываем лимиты (примерные, нужно уточнить в API)
                # Kucoin не всегда предоставляет эти данные напрямую
                # Может быть в других полях API

                staking = {
                    'exchange': 'Kucoin',
                    'product_id': str(product.get('product_id')),
                    'coin': coin,
                    'reward_coin': None,
                    'apr': apr,
                    'type': product.get('type'),
                    'status': product.get('status'),
                    'category': product.get('category'),
                    'term_days': product.get('duration', 0),
                    'token_price_usd': token_price,
                    'start_time': None,  # Kucoin не всегда предоставляет
                    'end_time': None,
                    # Для Kucoin эти данные могут отсутствовать:
                    'user_limit_tokens': None,
                    'user_limit_usd': None,
                    'total_places': None,
                    'max_capacity': None,
                    'current_deposit': None,
                    'fill_percentage': None,
                }

                stakings.append(staking)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга Kucoin продукта: {e}")
                continue

        return stakings

    def _parse_bybit(self, data: dict) -> List[Dict[str, Any]]:
        """Парсинг Bybit стейкингов"""
        stakings = []

        # Bybit структура: может быть data.all, data.list, или просто массив
        products = data.get('data', {}).get('all', [])
        if not products:
            products = data.get('data', {}).get('list', [])
        if not products:
            products = data.get('data', [])

        if not products:
            logger.warning("⚠️ Bybit: нет данных о стейкингах")
            return []

        logger.info(f"📊 Bybit: найдено {len(products)} стейкингов")

        for product in products:
            try:
                coin = product.get('coin')
                apy = product.get('apy', '0%').replace('%', '')
                apy_float = float(apy)

                # Получаем цены токенов
                token_price = self.price_fetcher.get_token_price(coin)

                # Reward coin (может быть другая монета)
                # Нужно уточнить структуру API Bybit

                # Рассчитываем лимиты
                max_capacity = product.get('max_capacity', 0)
                current_deposit = product.get('current_deposit', 0)
                fill_percentage = product.get('fill_percentage', 0)

                # User limit (примерный расчёт, нужно уточнить)
                # Может быть в других полях API

                staking = {
                    'exchange': 'Bybit',
                    'product_id': str(product.get('product_id')),
                    'coin': coin,
                    'reward_coin': None,  # Уточнить
                    'apr': apy_float,
                    'type': product.get('type'),
                    'status': product.get('status'),
                    'category': None,
                    'term_days': int(product.get('term_days', 0)),
                    'token_price_usd': token_price,
                    'start_time': None,  # Уточнить
                    'end_time': None,
                    'user_limit_tokens': None,  # Уточнить
                    'user_limit_usd': None,
                    'total_places': None,
                    'max_capacity': max_capacity,
                    'current_deposit': current_deposit,
                    'fill_percentage': fill_percentage,
                }

                stakings.append(staking)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга Bybit продукта: {e}")
                continue

        return stakings

    def get_pool_fills(self) -> List[Dict[str, Any]]:
        """
        Получить данные о заполненности пулов (для кнопки "Проверить заполненность")

        Returns:
            Список активных стейкингов с данными о заполненности
        """
        all_stakings = self.parse()

        # Фильтруем только активные с данными о заполненности
        pools_with_fill = []
        for staking in all_stakings:
            if staking.get('fill_percentage') is not None:
                pools_with_fill.append(staking)

        logger.info(f"📊 Найдено {len(pools_with_fill)} пулов с данными о заполненности")
        return pools_with_fill
```

**Что делать:**
1. Создать файл `parsers/staking_parser.py`
2. Скопировать код выше
3. **ВАЖНО:** Уточнить структуру API данных для:
   - Kucoin: user limits, total places, start/end time
   - Bybit: reward coin, user limits, dates
4. Дополнить парсинг после изучения реальных данных

---

## ✅ Задача 3.3: Уточнить структуру API данных
**Файлы:** Изучить реальные данные из API

**Что сделать:**
1. Запустить запросы к API вручную:

```bash
# Kucoin:
curl "https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1"

# Bybit:
curl "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"
```

2. Изучить JSON ответы
3. Найти поля для:
   - User limit (лимит на человека)
   - Total places (количество мест)
   - Start/End time
   - Reward coin (для Bybit)

4. Обновить парсер `_parse_kucoin()` и `_parse_bybit()` с правильными полями

---

# 🟣 ФАЗА 4: СЕРВИС УВЕДОМЛЕНИЙ

## ✅ Задача 4.1: Создать форматтер новых стейкингов
**Файл:** `bot/notification_service.py`

**Что добавить:**
Функцию форматирования сообщения о новом стейкинге.

**Код:**
```python
def format_new_staking(staking: dict, page_url: str = None) -> str:
    """
    Форматирование уведомления о новом стейкинге

    Args:
        staking: Данные стейкинга из парсера
        page_url: Ссылка на страницу стейкингов

    Returns:
        Отформатированное сообщение
    """

    # Базовая информация
    coin = staking.get('coin', 'N/A')
    reward_coin = staking.get('reward_coin')
    exchange = staking.get('exchange', 'N/A')
    apr = staking.get('apr', 0)
    term_days = staking.get('term_days', 0)
    term_type = staking.get('type', 'N/A')
    token_price = staking.get('token_price_usd')

    # Лимиты
    user_limit_tokens = staking.get('user_limit_tokens')
    user_limit_usd = staking.get('user_limit_usd')
    total_places = staking.get('total_places')

    # Даты
    start_time = staking.get('start_time')
    end_time = staking.get('end_time')

    # Формируем сообщение
    message = "🆕 НОВЫЙ СТЕЙКИНГ\n\n"

    # Основная информация
    if reward_coin:
        message += f"💎 Стейкай: {coin}\n"
        message += f"🎁 Награда: {reward_coin}\n"
    else:
        message += f"💎 Монета: {coin}\n"

    message += f"🏦 Биржа: {exchange}\n"
    message += f"💰 APR: {apr}%\n"

    # Период
    if term_days == 0:
        message += f"📅 Период: Flexible (бессрочно)\n"
    else:
        message += f"📅 Период: {term_days} дней\n"

    # Цена токена
    if token_price:
        message += f"💵 Цена токена: ${token_price:.4f}\n"

    message += "\n"

    # Лимиты
    if user_limit_tokens or user_limit_usd or total_places:
        message += "👤 ЛИМИТ НА ЧЕЛОВЕКА:\n"

        if user_limit_tokens:
            message += f"├─ Макс. сумма: {user_limit_tokens:,.2f} {coin}\n"

        if user_limit_usd:
            message += f"├─ Примерно: ${user_limit_usd:,.2f}\n"
        elif user_limit_tokens and token_price:
            # Рассчитываем USD эквивалент
            usd_value = user_limit_tokens * token_price
            message += f"├─ Примерно: ${usd_value:,.2f}\n"

        if total_places:
            message += f"└─ Всего мест: {total_places}\n"
        else:
            message += f"└─ Всего мест: N/A\n"

        message += "\n"

    # Даты
    if start_time or end_time:
        if start_time:
            message += f"⏰ Старт: {start_time}\n"
        if end_time:
            message += f"🕐 Конец: {end_time}\n"
        message += "\n"

    # Ссылка
    if page_url:
        message += f"🔗 {page_url}"

    return message
```

**Что делать:**
1. Открыть `bot/notification_service.py`
2. Добавить функцию `format_new_staking()` в класс `NotificationService` или как отдельную функцию
3. Протестировать форматирование

---

## ✅ Задача 4.2: Создать форматтер отчёта о заполненности
**Файл:** `bot/notification_service.py`

**Код:**
```python
def format_pools_report(pools: List[dict], exchange_name: str, page_url: str = None) -> str:
    """
    Форматирование отчёта о заполненности пулов

    Args:
        pools: Список стейкингов с данными о заполненности
        exchange_name: Название биржи
        page_url: Ссылка на страницу

    Returns:
        Отформатированный отчёт
    """

    if not pools:
        return f"📭 Нет активных пулов с данными о заполненности на {exchange_name}"

    # Заголовок
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    message = f"📊 ОТЧЁТ: ЗАПОЛНЕННОСТЬ ПУЛОВ\n\n"
    message += f"🏦 Биржа: {exchange_name}\n"
    message += f"🕐 Обновлено: {now}\n\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Перебираем пулы
    for pool in pools:
        coin = pool.get('coin', 'N/A')
        apr = pool.get('apr', 0)
        term_days = pool.get('term_days', 0)
        term_type = pool.get('type', 'N/A')

        fill_percentage = pool.get('fill_percentage', 0)
        max_capacity = pool.get('max_capacity', 0)
        current_deposit = pool.get('current_deposit', 0)

        # Заголовок пула
        if term_days == 0:
            term_text = "Flexible"
        else:
            term_text = f"{term_days} дней" if term_days > 1 else f"{term_days} день"

        message += f"💰 {coin} | {apr}% APR | {term_text}\n"

        # Прогресс бар
        filled_blocks = int(fill_percentage / 5)  # 20 блоков = 100%
        empty_blocks = 20 - filled_blocks
        progress_bar = "▓" * filled_blocks + "░" * empty_blocks
        message += f"{progress_bar} {fill_percentage:.2f}%\n"

        # Данные о пуле
        if max_capacity and current_deposit:
            available = max_capacity - current_deposit
            message += f"Лимит: {max_capacity:,.2f} {coin} | "
            message += f"Занято: {current_deposit:,.2f} {coin}\n"
            message += f"Осталось: {available:,.2f} {coin}"

            # Если есть цена токена - показываем в USD
            token_price = pool.get('token_price_usd')
            if token_price:
                available_usd = available * token_price
                message += f" (~${available_usd:,.2f})"

            message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Статистика
    total_pools = len(pools)
    avg_fill = sum(p.get('fill_percentage', 0) for p in pools) / total_pools if total_pools > 0 else 0

    message += f"📊 Активных пулов: {total_pools}\n"
    message += f"📈 Средняя заполненность: {avg_fill:.2f}%\n"

    # Ссылка
    if page_url:
        message += f"\n🔗 {page_url}"

    return message
```

**Что делать:**
1. Добавить функцию в `bot/notification_service.py`
2. Протестировать с тестовыми данными

---

## ✅ Задача 4.3: Проверка дубликатов в БД
**Файл:** `bot/parser_service.py`

**Что добавить:**
Логику проверки, был ли стейкинг уже найден ранее.

**Код:**
```python
def check_and_save_new_stakings(stakings: List[dict], link_id: int) -> List[dict]:
    """
    Проверяет стейкинги на новизну и сохраняет новые в БД

    Args:
        stakings: Список распарсенных стейкингов
        link_id: ID ссылки из которой получены стейкинги

    Returns:
        Список НОВЫХ стейкингов (которых не было в БД)
    """
    from data.database import get_db_session
    from data.models import StakingHistory

    new_stakings = []

    with get_db_session() as session:
        for staking in stakings:
            exchange = staking.get('exchange')
            product_id = staking.get('product_id')

            # Проверяем, есть ли уже в БД
            existing = session.query(StakingHistory).filter(
                StakingHistory.exchange == exchange,
                StakingHistory.product_id == product_id
            ).first()

            if existing:
                # Стейкинг уже есть, обновляем данные о заполненности
                existing.fill_percentage = staking.get('fill_percentage')
                existing.current_deposit = staking.get('current_deposit')
                existing.last_updated = datetime.utcnow()
                logger.debug(f"🔄 Обновлён стейкинг: {exchange} {product_id}")
            else:
                # Новый стейкинг!
                new_staking_record = StakingHistory(
                    exchange=exchange,
                    product_id=product_id,
                    coin=staking.get('coin'),
                    reward_coin=staking.get('reward_coin'),
                    apr=staking.get('apr'),
                    type=staking.get('type'),
                    status=staking.get('status'),
                    category=staking.get('category'),
                    term_days=staking.get('term_days'),
                    user_limit_tokens=staking.get('user_limit_tokens'),
                    user_limit_usd=staking.get('user_limit_usd'),
                    total_places=staking.get('total_places'),
                    max_capacity=staking.get('max_capacity'),
                    current_deposit=staking.get('current_deposit'),
                    fill_percentage=staking.get('fill_percentage'),
                    token_price_usd=staking.get('token_price_usd'),
                    reward_token_price_usd=staking.get('reward_token_price_usd'),
                    start_time=staking.get('start_time'),
                    end_time=staking.get('end_time'),
                    notification_sent=False
                )

                session.add(new_staking_record)
                new_stakings.append(staking)
                logger.info(f"🆕 Новый стейкинг: {exchange} {staking.get('coin')} {staking.get('apr')}% APR")

        session.commit()

    logger.info(f"✅ Найдено {len(new_stakings)} новых стейкингов")
    return new_stakings
```

**Что делать:**
1. Открыть `bot/parser_service.py`
2. Добавить функцию `check_and_save_new_stakings()`
3. Использовать её при парсинге

---

# 🟠 ФАЗА 5: ИНТЕГРАЦИЯ И ТЕСТИРОВАНИЕ

## ✅ Задача 5.1: Интеграция парсера в ParserService
**Файл:** `bot/parser_service.py`

**Что добавить:**
Метод для парсинга стейкингов в основной сервис.

**Код:**
```python
class ParserService:
    # ... существующий код ...

    async def parse_staking_link(self, link: ApiLink) -> int:
        """
        Парсинг ссылки категории 'staking'

        Args:
            link: ApiLink объект со стейкингом

        Returns:
            Количество новых стейкингов
        """
        try:
            logger.info(f"🔍 Парсинг стейкинга: {link.name}")

            # Создаём парсер
            from parsers.staking_parser import StakingParser
            parser = StakingParser(link.url, link.name)

            # Парсим стейкинги
            all_stakings = parser.parse()

            # Применяем фильтры (если есть)
            filtered_stakings = self._apply_staking_filters(all_stakings, link)

            # Проверяем на новизну и сохраняем в БД
            new_stakings = check_and_save_new_stakings(filtered_stakings, link.id)

            # Отправляем уведомления о новых
            if new_stakings:
                await self._send_staking_notifications(new_stakings, link)

            return len(new_stakings)

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга стейкинга {link.name}: {e}", exc_info=True)
            return 0

    def _apply_staking_filters(self, stakings: List[dict], link: ApiLink) -> List[dict]:
        """Применение фильтров к стейкингам"""
        filtered = stakings

        # Фильтр по минимальному APR
        if link.min_apr:
            filtered = [s for s in filtered if s.get('apr', 0) >= link.min_apr]
            logger.debug(f"📊 После фильтра APR >={link.min_apr}: {len(filtered)} стейкингов")

        # Фильтр по статусам
        if link.statuses_filter:
            import json
            allowed_statuses = json.loads(link.statuses_filter)
            filtered = [s for s in filtered if s.get('status') in allowed_statuses]
            logger.debug(f"📊 После фильтра статусов {allowed_statuses}: {len(filtered)} стейкингов")

        return filtered

    async def _send_staking_notifications(self, stakings: List[dict], link: ApiLink):
        """Отправка уведомлений о новых стейкингах"""
        from bot.notification_service import format_new_staking

        for staking in stakings:
            try:
                # Форматируем сообщение
                message = format_new_staking(staking, link.page_url)

                # Отправляем в телеграм
                await self.notification_service.send_notification(message)

                # Помечаем как отправленное
                with get_db_session() as session:
                    record = session.query(StakingHistory).filter(
                        StakingHistory.exchange == staking['exchange'],
                        StakingHistory.product_id == staking['product_id']
                    ).first()

                    if record:
                        record.notification_sent = True
                        session.commit()

                logger.info(f"✅ Уведомление отправлено: {staking['coin']} {staking['apr']}% APR")

            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления: {e}")
```

**Что делать:**
1. Открыть `bot/parser_service.py`
2. Добавить методы в класс `ParserService`
3. Интегрировать вызов `parse_staking_link()` в основной цикл парсинга

---

## ✅ Задача 5.2: Обновить основной цикл парсинга
**Файл:** `main.py` или `bot/parser_service.py`

**Что изменить:**
При парсинге ссылки проверять её категорию и вызывать соответствующий парсер.

**Код:**
```python
async def parse_single_link(link: ApiLink):
    """Парсинг одной ссылки с учётом категории"""

    if link.category == 'staking':
        # Стейкинг - используем специальный парсер
        new_count = await parser_service.parse_staking_link(link)
        logger.info(f"✅ {link.name}: найдено {new_count} новых стейкингов")

    elif link.category in ['launchpool', 'airdrop', 'announcement']:
        # Другие категории - используем универсальный парсер
        promotions = await parser_service.parse_link(link)
        logger.info(f"✅ {link.name}: найдено {len(promotions)} промоакций")

    else:
        # Старые ссылки без категории - используем универсальный
        promotions = await parser_service.parse_link(link)
        logger.info(f"✅ {link.name}: найдено {len(promotions)} промоакций")
```

**Что делать:**
1. Найти основной цикл парсинга в `main.py`
2. Добавить проверку категории
3. Вызывать соответствующий парсер

---

## ✅ Задача 5.3: Тестирование стейкинг системы
**Что протестировать:**

### 1. База данных:
- ✅ Создана таблица `staking_history`
- ✅ Добавлены поля в `api_links`

### 2. Интерфейс бота:
- ✅ Главное меню обновлено
- ✅ Подменю "Управление ссылками" с категориями
- ✅ Добавление ссылки с выбором категории
- ✅ Фильтры для стейкинга (мин. APR, статусы)
- ✅ Кнопка "Проверить заполненность пулов" в настройках

### 3. Парсер:
- ✅ Парсинг Kucoin стейкингов
- ✅ Парсинг Bybit стейкингов
- ✅ Получение цен с CoinGecko
- ✅ Сохранение в БД
- ✅ Проверка дубликатов

### 4. Уведомления:
- ✅ Форматирование новых стейкингов
- ✅ Форматирование отчёта о заполненности
- ✅ Отправка в Telegram

### 5. End-to-End тест:
```
1. Добавить ссылку Kucoin стейкинга
2. Запустить парсинг
3. Проверить, что уведомление о новом стейкинге пришло
4. Нажать "Проверить заполненность пулов"
5. Проверить, что отчёт пришёл (для Bybit)
```

---

# 📝 ИТОГОВЫЙ CHECKLIST

## База данных:
- [ ] Добавлены поля в `ApiLink`: `category`, `page_url`, `min_apr`, `track_fill`, `statuses_filter`, `types_filter`
- [ ] Создана модель `StakingHistory` в `data/models.py`
- [ ] Применена миграция БД (создана таблица)

## Интерфейс:
- [ ] Обновлено главное меню (убраны лишние кнопки, добавлена "Обход блокировок")
- [ ] Создано подменю "Управление ссылками" с категориями
- [ ] Добавлен выбор категории при добавлении ссылки
- [ ] Добавлены фильтры для стейкинга (мин. APR, статусы)
- [ ] Добавлен запрос `page_url` при добавлении ссылки
- [ ] Добавлена кнопка "Проверить заполненность пулов" для стейкингов
- [ ] Обработчик кнопки реализован

## Парсер:
- [ ] Создан `utils/price_fetcher.py` (получение цен с CoinGecko)
- [ ] Создан `parsers/staking_parser.py`
- [ ] Реализован парсинг Kucoin
- [ ] Реализован парсинг Bybit
- [ ] Уточнена структура API данных (user limits, dates и т.д.)
- [ ] Метод `get_pool_fills()` для отчётов о заполненности

## Уведомления:
- [ ] Функция `format_new_staking()` в `notification_service.py`
- [ ] Функция `format_pools_report()` в `notification_service.py`
- [ ] Проверка дубликатов `check_and_save_new_stakings()` в `parser_service.py`

## Интеграция:
- [ ] Метод `parse_staking_link()` в `ParserService`
- [ ] Применение фильтров `_apply_staking_filters()`
- [ ] Отправка уведомлений `_send_staking_notifications()`
- [ ] Обновлён основной цикл парсинга с проверкой категории

## Тестирование:
- [ ] Тест добавления ссылки стейкинга
- [ ] Тест парсинга Kucoin
- [ ] Тест парсинга Bybit
- [ ] Тест получения цен CoinGecko
- [ ] Тест форматирования уведомлений
- [ ] Тест кнопки "Проверить заполненность"
- [ ] End-to-End тест

---

# 🎯 ПОРЯДОК ВЫПОЛНЕНИЯ (РЕКОМЕНДУЕМЫЙ)

1. **ФАЗА 1**: База данных (1-3 часа)
   - Обновить модели
   - Применить миграцию
   - Проверить создание таблиц

2. **ФАЗА 2**: Интерфейс бота (3-5 часов)
   - Обновить меню
   - Добавить подменю категорий
   - Обновить добавление ссылки
   - Добавить кнопку заполненности

3. **ФАЗА 3**: Парсер (4-6 часов)
   - Создать price_fetcher
   - Создать staking_parser
   - Уточнить структуру API
   - Протестировать парсинг

4. **ФАЗА 4**: Уведомления (2-3 часа)
   - Форматтеры сообщений
   - Проверка дубликатов
   - Интеграция с NotificationService

5. **ФАЗА 5**: Интеграция и тестирование (2-4 часа)
   - Интеграция в ParserService
   - Обновление основного цикла
   - Тестирование всех компонентов

**Итого: 12-21 часов работы**

---

# 📌 ВАЖНЫЕ ЗАМЕЧАНИЯ

1. **API структура**: Обязательно уточните структуру данных Kucoin и Bybit через реальные запросы
2. **CoinGecko лимиты**: Бесплатный API имеет ограничения (50 запросов/минуту), используйте кэш
3. **Хранение истории**: Подумайте о регулярной очистке старых записей (>30 дней)
4. **Ошибки парсинга**: Добавьте обработку всех возможных ошибок (API недоступен, неверная структура и т.д.)
5. **Тестирование**: Тестируйте каждую фазу отдельно перед переходом к следующей

---

# 🚀 СЛЕДУЮЩИЕ ШАГИ

После завершения стейкинг системы можно приступать к:
1. **Лаунчпул** (аналогичная система)
2. **Аирдроп** (отдельная логика)
3. **Анонсы** (простой парсинг новостей)
4. **Обход блокировок** (настройка прокси, VPN, и т.д.)

Удачи! 🎉
