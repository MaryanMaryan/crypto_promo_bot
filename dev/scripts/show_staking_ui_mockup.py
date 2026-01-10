"""
Полный мокап UI для раздела "Текущие стейкинги" с примерами Bybit и OKX
"""
import sys
import os

# Устанавливаем UTF-8 для Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from datetime import datetime, timedelta

def format_change(value, decimals=2):
    """Форматирует изменение с стрелкой"""
    if value > 0:
        return f"↑ +{value:.{decimals}f}"
    elif value < 0:
        return f"↓ {value:.{decimals}f}"
    else:
        return "—"

def show_staking_card(coin, apr, apr_change, fill_pct, fill_change, price, price_change_pct,
                      staking_type, status, end_time=None, page_url=None, index=1, total=5):
    """Показать карточку стейкинга"""

    print(f"\n{'━'*60}")
    print(f"[{index}/{total}] 💰 {coin}")
    print(f"{'─'*60}")

    # APR с дельтой
    apr_delta_str = f" ({format_change(apr_change)}%)" if apr_change != 0 else ""
    print(f"📊 APR: {apr:.2f}%{apr_delta_str}")

    # Заполненность с дельтой
    if fill_pct is not None:
        fill_delta_str = f" ({format_change(fill_change)}%)" if fill_change != 0 else ""

        # Цветовой индикатор заполненности
        if fill_pct < 30:
            fill_icon = "🟢"
        elif fill_pct < 70:
            fill_icon = "🟡"
        elif fill_pct < 90:
            fill_icon = "🟠"
        else:
            fill_icon = "🔴"

        print(f"{fill_icon} Заполненность: {fill_pct:.2f}%{fill_delta_str}")

    # Цена токена с дельтой
    if price is not None:
        price_delta_str = f" ({format_change(price_change_pct, 1)}%)" if price_change_pct != 0 else ""
        print(f"💵 Цена токена: ${price:,.4f}{price_delta_str}")

    # Тип и статус
    status_icon = {"Active": "✅", "Sold Out": "❌", "Coming Soon": "🕐"}.get(status, "❓")
    print(f"📋 Тип: {staking_type}")
    print(f"{status_icon} Статус: {status}")

    # Дата окончания
    if end_time:
        print(f"⏰ Окончание: {end_time}")

    # Кнопка перехода
    if page_url:
        print(f"🔗 [Перейти] {page_url}")

    print(f"{'━'*60}")


def show_bybit_mockup():
    """Мокап для Bybit с полными данными"""
    print("\n" + "="*70)
    print("🔷 BYBIT - ТЕКУЩИЕ СТЕЙКИНГИ".center(70))
    print("="*70)
    print("\n📊 Всего найдено: 24 стейкинга")
    print("✅ После фильтрации (APR >= 100%): 8")
    print(f"\n{'━'*70}")
    print("СТРАНИЦА 1 из 2".center(70))
    print(f"{'━'*70}")

    # Пример 1: USDT - очень высокий APR, низкая заполненность
    show_staking_card(
        coin="USDT",
        apr=600.00,
        apr_change=+15.50,  # APR вырос
        fill_pct=31.73,
        fill_change=+2.45,  # Заполненность растет
        price=1.0001,
        price_change_pct=-0.01,
        staking_type="Fixed 3d",
        status="Active",
        end_time="2026-01-15 18:00",
        page_url="https://www.bybit.com/earn/fixed-earn",
        index=1,
        total=5
    )

    # Пример 2: BTC - средний APR, средняя заполненность
    show_staking_card(
        coin="BTC",
        apr=120.00,
        apr_change=-3.20,  # APR снизился
        fill_pct=65.42,
        fill_change=+8.30,  # Заполненность сильно выросла
        price=45230.50,
        price_change_pct=+2.3,  # Цена выросла
        staking_type="Fixed 7d",
        status="Active",
        end_time="2026-01-20 12:00",
        page_url="https://www.bybit.com/earn/fixed-earn",
        index=2,
        total=5
    )

    # Пример 3: ETH - высокая заполненность (почти полный)
    show_staking_card(
        coin="ETH",
        apr=150.00,
        apr_change=+5.00,
        fill_pct=89.75,
        fill_change=+12.50,  # Быстро заполняется!
        price=2380.25,
        price_change_pct=-1.5,  # Цена упала
        staking_type="Fixed 14d",
        status="Active",
        end_time="2026-01-25 10:00",
        page_url="https://www.bybit.com/earn/fixed-earn",
        index=3,
        total=5
    )

    # Пример 4: MATIC - flexible стейкинг
    show_staking_card(
        coin="MATIC",
        apr=105.50,
        apr_change=0,  # APR не изменился
        fill_pct=42.10,
        fill_change=-1.20,  # Заполненность уменьшилась (кто-то вывел)
        price=0.8542,
        price_change_pct=+0.8,
        staking_type="Flexible",
        status="Active",
        end_time=None,  # Flexible не имеет окончания
        page_url="https://www.bybit.com/earn/flexible-earn",
        index=4,
        total=5
    )

    # Пример 5: SOL - новый стейкинг
    show_staking_card(
        coin="SOL",
        apr=180.00,
        apr_change=0,  # Новый, еще нет истории
        fill_pct=5.30,
        fill_change=0,  # Только появился
        price=98.75,
        price_change_pct=+3.2,
        staking_type="Fixed 30d",
        status="Active",
        end_time="2026-02-09 08:00",
        page_url="https://www.bybit.com/earn/fixed-earn",
        index=5,
        total=5
    )

    print(f"\n{'━'*70}")
    print("⬅️ [Назад]  [Вперед ➡️]  [Обновить 🔄]  [Настройки ⚙️]".center(70))
    print(f"{'━'*70}")


def show_okx_mockup():
    """Мокап для OKX с полными данными"""
    print("\n" + "="*70)
    print("🟠 OKX - ТЕКУЩИЕ СТЕЙКИНГИ (FLASH EARN)".center(70))
    print("="*70)
    print("\n📊 Всего найдено: 15 активных пулов")
    print("✅ После фильтрации (APR >= 5%): 12")
    print(f"\n{'━'*70}")
    print("СТРАНИЦА 1 из 3".center(70))
    print(f"{'━'*70}")

    # Пример 1: USDT - высокий APR
    show_staking_card(
        coin="USDT",
        apr=18.50,
        apr_change=+1.20,
        fill_pct=None,  # OKX не предоставляет заполненность
        fill_change=None,
        price=1.0000,
        price_change_pct=0,
        staking_type="Flash Earn (Flexible)",
        status="Active",
        end_time="2026-01-30 00:00",
        page_url="https://www.okx.com/earn/flash-deals",
        index=1,
        total=5
    )

    # Пример 2: BTC - награда в другом токене
    show_staking_card(
        coin="BTC → USDT",  # Награда в USDT
        apr=12.30,
        apr_change=-0.50,
        fill_pct=None,
        fill_change=None,
        price=45230.50,
        price_change_pct=+2.1,
        staking_type="Flash Earn (Flexible)",
        status="Active",
        end_time="2026-02-05 00:00",
        page_url="https://www.okx.com/earn/flash-deals",
        index=2,
        total=5
    )

    # Пример 3: ETH
    show_staking_card(
        coin="ETH",
        apr=8.75,
        apr_change=+0.35,
        fill_pct=None,
        fill_change=None,
        price=2380.25,
        price_change_pct=-1.2,
        staking_type="Flash Earn (Flexible)",
        status="Active",
        end_time="2026-01-28 00:00",
        page_url="https://www.okx.com/earn/flash-deals",
        index=3,
        total=5
    )

    # Пример 4: ATOM
    show_staking_card(
        coin="ATOM",
        apr=15.20,
        apr_change=+2.10,  # Сильно вырос
        fill_pct=None,
        fill_change=None,
        price=9.82,
        price_change_pct=+4.5,
        staking_type="Flash Earn (Flexible)",
        status="Active",
        end_time="2026-02-10 00:00",
        page_url="https://www.okx.com/earn/flash-deals",
        index=4,
        total=5
    )

    # Пример 5: DOT
    show_staking_card(
        coin="DOT",
        apr=11.00,
        apr_change=-1.80,  # Упал
        fill_pct=None,
        fill_change=None,
        price=6.45,
        price_change_pct=-0.5,
        staking_type="Flash Earn (Flexible)",
        status="Active",
        end_time="2026-01-22 00:00",
        page_url="https://www.okx.com/earn/flash-deals",
        index=5,
        total=5
    )

    print(f"\n{'━'*70}")
    print("⬅️ [Назад]  [Вперед ➡️]  [Обновить 🔄]  [Настройки ⚙️]".center(70))
    print(f"{'━'*70}")
    print("\nℹ️ OKX Flash Earn не предоставляет данные о заполненности пулов")


def show_settings_dialog():
    """Мокап диалога настройки фильтра APR"""
    print("\n" + "="*70)
    print("⚙️ НАСТРОЙКА ФИЛЬТРА APR".center(70))
    print("="*70)
    print("\n📊 Биржа: Bybit Earn")
    print(f"📌 Текущий минимальный APR: 100%")
    print(f"\n{'─'*70}")
    print("Выберите новое значение минимального APR:")
    print(f"{'─'*70}")
    print("\n  [1%]  [5%]  [10%]  [20%]  [50%]")
    print("  [100%]  [200%]  [500%]  [Свой вариант ✏️]")
    print(f"\n{'─'*70}")
    print("💡 Будут показаны только стейкинги с APR >= выбранного значения")
    print(f"\n[Отмена ❌]")
    print("="*70)


if __name__ == "__main__":
    print("\n" + "🎨 ПОЛНЫЙ МОКАП UI: РАЗДЕЛ 'ТЕКУЩИЕ СТЕЙКИНГИ'".center(80))
    print("="*80)

    # Показываем Bybit
    show_bybit_mockup()

    # Показываем OKX
    show_okx_mockup()

    # Показываем диалог настройки
    show_settings_dialog()

    print("\n" + "="*80)
    print("✅ МОКАП UI ЗАВЕРШЕН".center(80))
    print("="*80)

    print("\n📋 КЛЮЧЕВЫЕ ОСОБЕННОСТИ:")
    print("  ✓ Пагинация: 5 стейкингов на страницу")
    print("  ✓ Дельты: показывают изменения с прошлой проверки")
    print("  ✓ Цветовые индикаторы заполненности: 🟢🟡🟠🔴")
    print("  ✓ Фильтр APR: настраивается индивидуально для каждой ссылки")
    print("  ✓ Кнопки навигации: Вперед/Назад/Обновить/Настройки")
    print("  ✓ История изменений: сохраняется каждый час")
    print("  ✓ Автоматический расчет дельт из таблицы StakingSnapshot")

    print("\n🔧 ТЕХНИЧЕСКИЕ ДЕТАЛИ:")
    print("  • Новая таблица: StakingSnapshot (для истории)")
    print("  • Снимки сохраняются: не чаще 1 раза в час")
    print("  • Данные включают: APR, заполненность, цену токена, timestamp")
    print("  • Расчет дельт: автоматически при загрузке страницы")
