# TODO: Система умных уведомлений - ИСПРАВЛЕНИЯ И ДОРАБОТКИ

**Дата обновления:** 2026-01-13
**Статус:** 🔴 КРИТИЧЕСКИЕ ОШИБКИ - ТРЕБУЕТСЯ СРОЧНОЕ ИСПРАВЛЕНИЕ

---

## 🚨 НАЙДЕННЫЕ КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### ❌ ПРОБЛЕМА 1: Фильтр min_apr игнорируется для существующих стейкингов
**Файл:** `bot/parser_service.py:574`
**Описание:** Существующие стейкинги с изменениями APR добавляются в `new_stakings` БЕЗ проверки фильтра `min_apr`. Это приводит к спаму уведомлениями о стейкингах с низким APR (например, 1.43% при лимите 100%).

**Почему происходит:**
- Новые стейкинги проверяются на `min_apr` в строке 611: `passes_filter = (min_apr is None or apr >= min_apr)`
- Существующие стейкинги добавляются в строке 574: `new_stakings.append(staking)` БЕЗ проверки фильтра
- Flexible стейкинги после 6 часов стабилизации проходят проверку и отправляются, игнорируя `min_apr`

**Решение:**
```python
# В bot/parser_service.py, строка 565-574
stability_result = stability_tracker.check_stability(existing, api_link)
if stability_result['should_notify']:
    # ДОБАВИТЬ ПРОВЕРКУ min_apr
    if min_apr is None or existing.apr >= min_apr:
        logger.info(f"📣 Готово к уведомлению...")
        staking['_should_notify'] = True
        new_stakings.append(staking)
    else:
        logger.info(f"🔽 Пропущен (APR {existing.apr}% < {min_apr}%)")
```

---

### ❌ ПРОБЛЕМА 2: Ошибка БД при коммите (SystemError)
**Файл:** `bot/parser_service.py:582`
**Описание:**
```
SystemError: <built-in method commit of sqlite3.Connection object> returned NULL without setting an exception
```

**Возможные причины:**
1. Множественные `session.commit()` в одной транзакции
2. Коммит выполняется во время другой операции БД
3. Проблемы с SQLAlchemy session management
4. Circuit breaker от price_fetcher может вызывать проблемы с БД

**Решение:**
- Обернуть весь блок обработки стейкингов в try-except
- Использовать `session.flush()` вместо `commit()` внутри циклов
- Один финальный `commit()` в конце функции
- Добавить rollback при ошибках

---

### ❌ ПРОБЛЕМА 3: Отсутствует UI настроек умных уведомлений
**Файл:** `bot/handlers.py`
**Описание:** Нет интерфейса для настройки:
- Время стабилизации Flexible (flexible_stability_hours)
- Порог изменения APR (notify_min_apr_change)
- Включение/выключение уведомлений (notify_new_stakings, notify_apr_changes)
- Поведение Fixed/Combined (fixed_notify_immediately, notify_combined_as_fixed)

**Решение:** См. раздел ФАЗА 2 ниже.

---

## 📋 СТАТУС РЕАЛИЗАЦИИ

### ✅ УЖЕ РЕАЛИЗОВАНО (работает частично):
- [x] Модели БД (StakingHistory, ApiLink) с полями для умных уведомлений
- [x] StabilityTrackerService с логикой Fixed/Flexible/Combined
- [x] Интеграция в parser_service.py
- [x] Базовое форматирование уведомлений (format_new_staking)
- [x] Определение типов стейкингов (_is_fixed, _is_flexible, _is_combined)
- [x] Проверка стабильности (check_stability)
- [x] Обновление статуса (update_stability_status)

### 🔴 ТРЕБУЕТСЯ ИСПРАВЛЕНИЕ:
- [ ] Фильтр min_apr для существующих стейкингов (КРИТИЧНО)
- [ ] Ошибка БД SystemError (КРИТИЧНО)
- [ ] mark_notification_sent() не вызывается (флаг notification_sent не обновляется)
- [ ] Обработка ошибок при парсинге

### 🟡 ТРЕБУЕТСЯ ДОБАВЛЕНИЕ:
- [ ] UI настроек умных уведомлений
- [ ] Форматирование уведомлений с информацией о стабилизации
- [ ] Настройка подписок пользователей (UserLinkSubscription)
- [ ] Расширенное логирование для отладки
- [ ] Документация и примеры

---

## 🎯 ПЛАН ИСПРАВЛЕНИЙ И ДОРАБОТОК

### ФАЗА 1: КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ (2-3ч) 🔴

#### 1.1 Исправить фильтр min_apr
**Файл:** `bot/parser_service.py`

**Задачи:**
- [ ] Добавить проверку `min_apr` для существующих стейкингов в строке 565
- [ ] Добавить проверку `min_apr` для новых стейкингов Flexible в строке 658
- [ ] Добавить счетчик отфильтрованных уведомлений
- [ ] Логировать причину фильтрации

**Код для изменения:**
```python
# Строка 563-574 (существующие стейкинги)
stability_result = stability_tracker.check_stability(existing, api_link)
if stability_result['should_notify']:
    # ДОБАВИТЬ ПРОВЕРКУ min_apr ЗДЕСЬ
    if min_apr is None or existing.apr >= min_apr:
        logger.info(...)
        staking['_should_notify'] = True
        new_stakings.append(staking)
    else:
        logger.info(f"🔽 Пропущен (APR {existing.apr}% < {min_apr}%): {exchange} {staking.get('coin')}")

# Строка 656-662 (новые стейкинги Flexible)
elif lock_type == 'Flexible':
    stability_result = stability_tracker.check_stability(new_staking_record, api_link)
    should_notify_now = stability_result['should_notify']
    # ПРОВЕРИТЬ min_apr И ЗДЕСЬ если should_notify_now = True
```

#### 1.2 Исправить ошибку БД
**Файл:** `bot/parser_service.py`

**Задачи:**
- [ ] Обернуть весь блок `check_and_save_new_stakings` в try-except с rollback
- [ ] Использовать `session.flush()` внутри цикла вместо `commit()`
- [ ] Один финальный `commit()` в конце функции
- [ ] Добавить логирование транзакций

**Код для изменения:**
```python
def check_and_save_new_stakings(stakings, link_id=None, min_apr=None):
    with get_db_session() as session:
        try:
            # ... весь код обработки ...

            # Вместо session.commit() в циклах
            session.flush()  # Синхронизация без коммита

            # ... продолжение обработки ...

            # В конце один коммит
            session.commit()
            logger.info("✅ Транзакция успешно завершена")

        except Exception as e:
            logger.error(f"❌ Ошибка в транзакции БД: {e}", exc_info=True)
            session.rollback()
            raise

        return new_stakings
```

#### 1.3 Исправить mark_notification_sent
**Файл:** `bot/parser_service.py` + `main.py`

**Проблема:** После отправки уведомления нужно вызывать `stability_tracker.mark_notification_sent(staking)`, но это нигде не делается.

**Задачи:**
- [ ] Добавить вызов `mark_notification_sent()` в `main.py` после отправки уведомления
- [ ] Сохранить staking_id в словаре уведомления для доступа к объекту БД
- [ ] Обновить флаг `notification_sent_at`

**Код для изменения:**
```python
# В main.py, после отправки уведомления:
for staking in new_stakings:
    message = self.notification_service.format_new_staking(staking, page_url=...)
    await self.bot.send_message(...)

    # ДОБАВИТЬ: Отметить уведомление как отправленное
    if staking.get('_staking_db_id'):
        with get_db_session() as db:
            staking_record = db.query(StakingHistory).filter(
                StakingHistory.id == staking['_staking_db_id']
            ).first()
            if staking_record:
                stability_tracker = StabilityTrackerService(db)
                stability_tracker.mark_notification_sent(staking_record)
                db.commit()
```

---

### ФАЗА 2: UI НАСТРОЕК (3-4ч) 🟡

**Примеры UI:** См. файл `dev/docs/SMART_NOTIFICATIONS_EXAMPLES.md`

#### 2.1 Добавить кнопку "Настройки уведомлений"
**Файл:** `bot/keyboards.py`

**Задачи:**
- [ ] Добавить кнопку в `get_current_stakings_keyboard()`
- [ ] Расположение: после "Настройки APR"

**Код:**
```python
def get_current_stakings_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Навигация...

    # Управление
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="stakings_refresh"),
        InlineKeyboardButton(text="⚙️ Настройки APR", callback_data="stakings_configure_apr")
    )

    # НОВАЯ КНОПКА
    builder.row(
        InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="notification_settings_show")
    )

    # Закрыть
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="manage_cancel"))

    return builder.as_markup()
```

#### 2.2 Handler показа настроек
**Файл:** `bot/handlers.py`

**Задачи:**
- [ ] Создать handler `notification_settings_show()`
- [ ] Форматировать текущие настройки
- [ ] Показать клавиатуру с опциями

**Код:**
```python
@router.callback_query(F.data == "notification_settings_show")
async def notification_settings_show(callback: CallbackQuery):
    """Показать настройки умных уведомлений"""
    try:
        user_id = callback.from_user.id
        link_id = user_selections.get(user_id)

        if not link_id:
            await callback.answer("❌ Ссылка не выбрана", show_alert=True)
            return

        with get_db_session() as db:
            link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

            if not link:
                await callback.answer("❌ Ссылка не найдена", show_alert=True)
                return

            # Форматирование настроек
            message = format_notification_settings_message(link)
            keyboard = get_notification_settings_keyboard()

            await callback.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await callback.answer()

    except Exception as e:
        logger.error(f"❌ Ошибка показа настроек: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)
```

#### 2.3 Форматирование UI настроек
**Файл:** `bot/handlers.py`

**Задачи:**
- [ ] Создать функцию `format_notification_settings_message(link: ApiLink) -> str`
- [ ] Показать текущие значения всех настроек
- [ ] Использовать ✅/❌ для вкл/выкл

**Код:**
```python
def format_notification_settings_message(link: ApiLink) -> str:
    """Форматирует сообщение с настройками уведомлений"""

    # Преобразование bool в эмодзи
    def bool_emoji(value):
        return "✅ Включено" if value else "❌ Выключено"

    message = (
        f"⚙️ <b>НАСТРОЙКИ УМНЫХ УВЕДОМЛЕНИЙ</b>\n\n"
        f"🏦 <b>Биржа:</b> {link.name}\n"
        f"📌 <b>Категория:</b> Стейкинг\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>ТЕКУЩИЕ НАСТРОЙКИ:</b>\n\n"
        f"🔔 <b>Новые стейкинги:</b> {bool_emoji(link.notify_new_stakings)}\n"
        f"📈 <b>Изменения APR:</b> {bool_emoji(link.notify_apr_changes)}\n"
        f"📊 <b>Заполненность:</b> {bool_emoji(link.notify_fill_changes)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ <b>FLEXIBLE СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Время стабилизации:</b> {link.flexible_stability_hours} часов\n"
        f"├─ <b>Уведомлять после стабилизации:</b> {bool_emoji(link.notify_only_stable_flexible)}\n"
        f"└─ <b>Только стабильные:</b> {bool_emoji(link.notify_only_stable_flexible)}\n\n"
        f"⚡ <b>FIXED СТЕЙКИНГИ:</b>\n"
        f"├─ <b>Уведомлять сразу:</b> {bool_emoji(link.fixed_notify_immediately)}\n"
        f"└─ <b>Combined как Fixed:</b> {bool_emoji(link.notify_combined_as_fixed)}\n\n"
        f"📊 <b>ИЗМЕНЕНИЯ APR:</b>\n"
        f"└─ <b>Минимальное изменение:</b> {link.notify_min_apr_change}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Выберите действие:"
    )

    return message
```

#### 2.4 Handlers изменения настроек
**Файл:** `bot/handlers.py`

**Задачи:**
- [ ] Handler изменения времени стабилизации (1, 2, 3, 4, 6, 8, 12, 24, 48 часов)
- [ ] Handler изменения порога APR (1%, 2%, 3%, 5%, 10%, 15%, 20%, 50%)
- [ ] Handlers переключения флагов (notify_new_stakings, notify_apr_changes и т.д.)

**Примеры handlers:**
```python
@router.callback_query(F.data == "notification_settings_change_stability")
async def change_stability_hours(callback: CallbackQuery):
    """Показать пресеты времени стабилизации"""
    # Клавиатура с пресетами 1, 2, 3, 4, 6, 8, 12, 24, 48
    pass

@router.callback_query(F.data.startswith("set_stability_"))
async def set_stability_hours(callback: CallbackQuery):
    """Установить время стабилизации из пресета"""
    # Извлечь hours из callback.data
    # Обновить link.flexible_stability_hours в БД
    # Показать обновленные настройки
    pass

@router.callback_query(F.data == "notification_settings_change_apr_threshold")
async def change_apr_threshold(callback: CallbackQuery):
    """Показать пресеты порога APR"""
    # Клавиатура с пресетами 1, 2, 3, 5, 10, 15, 20, 50
    pass

@router.callback_query(F.data.startswith("set_apr_threshold_"))
async def set_apr_threshold(callback: CallbackQuery):
    """Установить порог APR из пресета"""
    # Извлечь threshold из callback.data
    # Обновить link.notify_min_apr_change в БД
    # Показать обновленные настройки
    pass

@router.callback_query(F.data == "notification_toggle_new_stakings")
async def toggle_new_stakings(callback: CallbackQuery):
    """Переключить уведомления о новых стейкингах"""
    # Инвертировать link.notify_new_stakings в БД
    # Показать обновленные настройки
    pass

# Аналогично для остальных флагов...
```

#### 2.5 Клавиатура настроек
**Файл:** `bot/keyboards.py`

**Задачи:**
- [ ] Создать функцию `get_notification_settings_keyboard()`

**Код:**
```python
def get_notification_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек умных уведомлений"""
    builder = InlineKeyboardBuilder()

    builder.add(InlineKeyboardButton(
        text="⏱️ Изменить время стабилизации",
        callback_data="notification_settings_change_stability"
    ))
    builder.add(InlineKeyboardButton(
        text="📊 Изменить порог изменения APR",
        callback_data="notification_settings_change_apr_threshold"
    ))
    builder.add(InlineKeyboardButton(
        text="🔔 Новые стейкинги (вкл/выкл)",
        callback_data="notification_toggle_new_stakings"
    ))
    builder.add(InlineKeyboardButton(
        text="📈 Изменения APR (вкл/выкл)",
        callback_data="notification_toggle_apr_changes"
    ))
    builder.add(InlineKeyboardButton(
        text="⚡ Fixed сразу (вкл/выкл)",
        callback_data="notification_toggle_fixed_immediately"
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Combined как Fixed (вкл/выкл)",
        callback_data="notification_toggle_combined_as_fixed"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 Только стабильные Flexible (вкл/выкл)",
        callback_data="notification_toggle_only_stable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Назад",
        callback_data="manage_view_current_stakings"
    ))

    builder.adjust(1)  # По одной кнопке в ряд
    return builder.as_markup()
```

---

### ФАЗА 3: УЛУЧШЕНИЕ ФОРМАТИРОВАНИЯ (1-2ч) 🟢

#### 3.1 Обновить format_new_staking()
**Файл:** `bot/notification_service.py`

**Задачи:**
- [ ] Добавить информацию о типе уведомления (новый/изменение/стабилизирован)
- [ ] Показывать время добавления и стабилизации для Flexible
- [ ] Показывать предыдущий APR для изменений
- [ ] Добавить эмодзи индикаторы

**Пример:**
```python
def format_new_staking(self, staking: Dict[str, Any], page_url: str = None) -> str:
    """Форматирует уведомление о стейкинге"""

    # ... существующий код ...

    # ДОБАВИТЬ: Информация о типе уведомления
    notification_info = ""
    notification_type = staking.get('_notification_type', 'new')
    lock_type = staking.get('_lock_type', staking.get('lock_type', 'Unknown'))

    if notification_type == 'new':
        if lock_type == 'Fixed' or lock_type == 'Combined':
            notification_info = f"\n\n⏱️ <b>Уведомление:</b> Новый {lock_type} стейкинг (отправлено сразу)"
        elif lock_type == 'Flexible':
            notification_info = (
                f"\n\n⏱️ <b>Уведомление:</b> Flexible стейкинг стабилизирован "
                f"({staking.get('_stability_hours', 6)} часов без изменений)\n"
                f"⏰ <b>Добавлен:</b> {staking.get('_added_at', 'N/A')}\n"
                f"⏰ <b>Стабилизирован:</b> {staking.get('_stable_at', 'N/A')}"
            )

    elif notification_type == 'apr_change':
        old_apr = staking.get('_previous_apr', 0)
        new_apr = staking.get('apr', 0)
        change = new_apr - old_apr
        change_percent = (change / old_apr * 100) if old_apr > 0 else 0

        notification_info = (
            f"\n\n📈 <b>ИЗМЕНЕНИЕ APR!</b>\n"
            f"📊 <b>Старый APR:</b> {old_apr}%\n"
            f"📊 <b>Новый APR:</b> {new_apr}%\n"
            f"🔺 <b>Изменение:</b> {'+' if change > 0 else ''}{change:.1f}% "
            f"(↑ {change_percent:.1f}%)\n\n"
            f"⏱️ <b>Уведомление:</b> Изменение APR ≥ {staking.get('_apr_threshold', 5)}% "
            f"({lock_type} стейкинг)"
        )

        if lock_type == 'Flexible':
            notification_info += (
                f"\n⏰ <b>Последнее изменение:</b> {staking.get('_last_change', 'N/A')}\n"
                f"⏰ <b>Стабилизирован:</b> {staking.get('_stable_at', 'N/A')}"
            )

    message += notification_info

    return message
```

---

### ФАЗА 4: ТЕСТИРОВАНИЕ И ДОКУМЕНТАЦИЯ (2-3ч) 🟢

#### 4.1 Тестирование
**Задачи:**
- [ ] Тест фильтра min_apr (новые и существующие)
- [ ] Тест стабилизации Flexible (через mock времени)
- [ ] Тест изменения APR Fixed (должен уведомлять сразу)
- [ ] Тест изменения APR Flexible (должен сбрасывать таймер)
- [ ] Тест Combined (должен работать как Fixed)
- [ ] Тест UI настроек (изменение всех параметров)
- [ ] Интеграционный тест на реальных данных Gate.io

#### 4.2 Документация
**Файлы:**
- [ ] Обновить `CLAUDE.md` с новой информацией
- [ ] Создать `dev/docs/NOTIFICATION_SETTINGS_GUIDE.md` с инструкциями
- [ ] Обновить примеры в `dev/docs/SMART_NOTIFICATIONS_EXAMPLES.md`

---

## 📝 ЧЕКЛИСТ ИСПРАВЛЕНИЙ

### Критические (СЕЙЧАС):
- [ ] Исправить фильтр min_apr для существующих стейкингов
- [ ] Исправить ошибку БД SystemError (commit)
- [ ] Добавить вызов mark_notification_sent()
- [ ] Тестирование на реальных данных

### UI настроек (ДАЛЕЕ):
- [ ] Добавить кнопку "Настройки уведомлений"
- [ ] Handler показа настроек
- [ ] Форматирование UI
- [ ] Handlers изменения времени стабилизации
- [ ] Handlers изменения порога APR
- [ ] Handlers переключения флагов
- [ ] Тестирование UI

### Улучшения (ОПЦИОНАЛЬНО):
- [ ] Обновить форматирование уведомлений
- [ ] Добавить информацию о стабилизации
- [ ] Показывать предыдущий APR при изменениях
- [ ] Документация

---

## ⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ

### Фильтр min_apr применяется ВЕЗДЕ:
```python
# Проверка для ВСЕХ типов уведомлений
if min_apr is not None and staking.apr < min_apr:
    # НЕ уведомлять
    continue
```

### Ошибка БД решается через flush + один commit:
```python
for staking in stakings:
    # Обработка...
    session.flush()  # Синхронизация без коммита

# В конце один commit
session.commit()
```

### mark_notification_sent ОБЯЗАТЕЛЬНО вызывать:
```python
# После отправки каждого уведомления
stability_tracker.mark_notification_sent(staking_record)
```

### UI настроек - контекстные:
- Привязаны к конкретной ссылке (стейкинг-бирже)
- Изменяются для каждой ссылки отдельно
- Сохраняются в БД сразу

---

## 🎯 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ

После всех исправлений:

1. ✅ Фильтр min_apr работает для ВСЕХ уведомлений
2. ✅ Нет ошибок БД при парсинге
3. ✅ Flexible стейкинги уведомляют после стабилизации
4. ✅ Fixed стейкинги уведомляют сразу
5. ✅ Combined работают как Fixed
6. ✅ Есть UI для настройки всех параметров
7. ✅ Уведомления содержат полную информацию
8. ✅ Документация актуальна

---

## 📚 ДОПОЛНИТЕЛЬНЫЕ РЕСУРСЫ

- **Примеры UI и уведомлений:** `dev/docs/SMART_NOTIFICATIONS_EXAMPLES.md`
- **Основная документация:** `CLAUDE.md` (раздел "Система умных уведомлений")
- **Модели БД:** `data/models.py` (StakingHistory, ApiLink)
- **Логика стабильности:** `services/stability_tracker_service.py`

---

**ВРЕМЯ ОЦЕНКА:** 8-12 часов
**ПРИОРИТЕТ:** 🔴 КРИТИЧЕСКИЙ (фильтр + БД) → 🟡 ВЫСОКИЙ (UI) → 🟢 СРЕДНИЙ (улучшения)

---

Конец TODO листа
