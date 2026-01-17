"""
Скрипт для демонстрации примеров отображения стейкингов Bybit и OKX
"""
import sys
import os

# Устанавливаем UTF-8 для Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from parsers.staking_parser import StakingParser
from datetime import datetime

def format_staking_card(staking, previous_apr=None, previous_fill=None, previous_price=None):
    """
    Форматирует карточку стейкинга с дельтами

    Args:
        staking: данные стейкинга
        previous_apr: предыдущее значение APR для расчета дельты
        previous_fill: предыдущая заполненность для расчета дельты
        previous_price: предыдущая цена для расчета дельты
    """
    coin = staking.get('coin', 'N/A')
    apr = staking.get('apr', 0)
    fill_pct = staking.get('fill_percentage')
    price = staking.get('token_price_usd')
    product_type = staking.get('type', 'N/A')
    status = staking.get('status', 'N/A')
    end_time = staking.get('end_time')

    # Форматируем заголовок
    card = f"\n{'='*50}\n"
    card += f"💰 {coin}\n"
    card += f"{'-'*50}\n"

    # APR с дельтой
    apr_str = f"📊 APR: {apr:.2f}%"
    if previous_apr is not None:
        delta_apr = apr - previous_apr
        if delta_apr > 0:
            apr_str += f" (↑ +{delta_apr:.2f}%)"
        elif delta_apr < 0:
            apr_str += f" (↓ {delta_apr:.2f}%)"
        else:
            apr_str += " (—)"
    card += apr_str + "\n"

    # Заполненность с дельтой
    if fill_pct is not None:
        fill_str = f"🏊 Заполненность: {fill_pct:.2f}%"
        if previous_fill is not None:
            delta_fill = fill_pct - previous_fill
            if delta_fill > 0:
                fill_str += f" (↑ +{delta_fill:.2f}%)"
            elif delta_fill < 0:
                fill_str += f" (↓ {delta_fill:.2f}%)"
            else:
                fill_str += " (—)"
        card += fill_str + "\n"

    # Цена токена с дельтой
    if price is not None:
        price_str = f"💵 Цена: ${price:,.2f}"
        if previous_price is not None:
            delta_price_pct = ((price - previous_price) / previous_price) * 100
            if delta_price_pct > 0:
                price_str += f" (↑ +{delta_price_pct:.2f}%)"
            elif delta_price_pct < 0:
                price_str += f" (↓ {delta_price_pct:.2f}%)"
            else:
                price_str += " (—)"
        card += price_str + "\n"

    # Тип и статус
    card += f"📋 Тип: {product_type}\n"
    card += f"🔔 Статус: {status}\n"

    # Дата окончания
    if end_time:
        try:
            # Если timestamp в миллисекундах
            if isinstance(end_time, (int, float)) and end_time > 10000000000:
                end_dt = datetime.fromtimestamp(end_time / 1000)
                card += f"⏰ Окончание: {end_dt.strftime('%Y-%m-%d %H:%M')}\n"
            elif isinstance(end_time, str):
                card += f"⏰ Окончание: {end_time}\n"
        except:
            pass

    card += f"{'='*50}\n"
    return card


def show_bybit_example():
    """Показать пример для Bybit"""
    print("\n" + "="*60)
    print("🔷 BYBIT - ПРИМЕР ОТОБРАЖЕНИЯ ТЕКУЩИХ СТЕЙКИНГОВ")
    print("="*60)

    api_url = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"

    try:
        parser = StakingParser(api_url=api_url, exchange_name='bybit')
        stakings = parser.parse()

        if not stakings:
            print("❌ Нет данных о стейкингах")
            return

        # Фильтруем: только активные с заполненностью и APR >= 100%
        filtered = [
            s for s in stakings
            if s.get('status') == 'Active'
            and s.get('fill_percentage') is not None
            and s.get('apr', 0) >= 100
            and s.get('fill_percentage', 100) < 95  # Не заполненные >= 95%
        ]

        print(f"\n📊 Всего найдено: {len(stakings)} стейкингов")
        print(f"✅ После фильтрации (Active, APR>=100%, заполненность <95%): {len(filtered)}")

        # Показываем первые 5 с симуляцией дельт
        print("\n" + "🎯 ПРИМЕР: ПЕРВАЯ СТРАНИЦА (5 стейкингов)".center(60))

        for i, staking in enumerate(filtered[:5], 1):
            # Симулируем предыдущие значения для демонстрации
            prev_apr = staking['apr'] - (5.5 if i % 2 == 0 else -3.2)
            prev_fill = staking.get('fill_percentage', 50) - (2.3 if i % 3 == 0 else 1.5)
            prev_price = staking.get('token_price_usd')
            if prev_price:
                prev_price = prev_price * (0.98 if i % 2 == 0 else 1.02)

            print(f"\n[{i}/5]")
            print(format_staking_card(staking, prev_apr, prev_fill, prev_price))

        if len(filtered) > 5:
            print(f"\n... и еще {len(filtered) - 5} стейкингов")
            print("(используйте кнопки 'Вперед/Назад' для навигации)")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


def show_okx_example():
    """Показать пример для OKX"""
    print("\n" + "="*60)
    print("🟠 OKX - ПРИМЕР ОТОБРАЖЕНИЯ ТЕКУЩИХ СТЕЙКИНГОВ")
    print("="*60)

    api_url = "https://www.okx.com/priapi/v3/stake-earn/projects"

    try:
        parser = StakingParser(api_url=api_url, exchange_name='okx')
        stakings = parser.parse()

        if not stakings:
            print("❌ Нет данных о стейкингах")
            return

        # OKX всегда возвращает активные
        print(f"\n📊 Всего найдено: {len(stakings)} активных пулов")

        # Фильтруем по APR >= 5%
        filtered = [s for s in stakings if s.get('apr', 0) >= 5]
        print(f"✅ После фильтрации (APR >= 5%): {len(filtered)}")

        # Показываем первые 5 с симуляцией дельт
        print("\n" + "🎯 ПРИМЕР: ПЕРВАЯ СТРАНИЦА (5 стейкингов)".center(60))

        for i, staking in enumerate(filtered[:5], 1):
            # Симулируем предыдущие значения для демонстрации
            prev_apr = staking['apr'] - (1.2 if i % 2 == 0 else -0.8)
            # У OKX нет данных о заполненности
            prev_fill = None
            prev_price = staking.get('token_price_usd')
            if prev_price:
                prev_price = prev_price * (0.99 if i % 2 == 0 else 1.01)

            print(f"\n[{i}/5]")
            print(format_staking_card(staking, prev_apr, prev_fill, prev_price))

        if len(filtered) > 5:
            print(f"\n... и еще {len(filtered) - 5} стейкингов")
            print("(используйте кнопки 'Вперед/Назад' для навигации)")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n🎨 ДЕМОНСТРАЦИЯ UI ДЛЯ РАЗДЕЛА 'ТЕКУЩИЕ СТЕЙКИНГИ'\n")

    # Показываем Bybit
    show_bybit_example()

    # Показываем OKX
    show_okx_example()

    print("\n" + "="*60)
    print("✅ ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print("\nℹ️ Примечания:")
    print("  • Дельты симулированы для демонстрации")
    print("  • В реальности дельты будут рассчитываться из StakingSnapshot")
    print("  • Пагинация: 5 стейкингов на страницу")
    print("  • Фильтр APR настраивается индивидуально для каждой ссылки")
