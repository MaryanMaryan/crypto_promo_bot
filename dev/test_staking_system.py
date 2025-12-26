"""
Комплексное тестирование системы стейкинга для Bybit и Kucoin
"""
import sys
import io
import logging
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения (.env файл)
load_dotenv()

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_bybit_parser():
    """Тест 1: Парсинг Bybit стейкингов"""
    print("\n" + "="*80)
    print("🧪 ТЕСТ 1: ПАРСИНГ BYBIT СТЕЙКИНГОВ")
    print("="*80)

    from parsers.staking_parser import StakingParser

    parser = StakingParser(
        api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
        exchange_name="Bybit"
    )

    print("📡 Запуск парсинга Bybit...")
    stakings = parser.parse()

    if not stakings:
        print("❌ FAILED: Не удалось получить стейкинги от Bybit")
        return False

    print(f"✅ SUCCESS: Получено {len(stakings)} стейкингов от Bybit")

    # Проверяем структуру данных
    first = stakings[0]
    required_fields = ['exchange', 'product_id', 'coin', 'apr', 'type', 'status']

    missing = [f for f in required_fields if f not in first]
    if missing:
        print(f"❌ FAILED: Отсутствуют поля: {missing}")
        return False

    print(f"✅ Все обязательные поля присутствуют")

    # Проверяем названия монет (не должно быть COIN_X)
    coins_with_real_names = [s for s in stakings if not s['coin'].startswith('COIN_')]
    percentage = (len(coins_with_real_names) / len(stakings)) * 100

    print(f"📊 Монет с реальными названиями: {len(coins_with_real_names)}/{len(stakings)} ({percentage:.1f}%)")

    if percentage < 95:
        print(f"⚠️ WARNING: Много монет с названиями COIN_X ({100-percentage:.1f}%)")
    else:
        print(f"✅ Отлично! Почти все монеты определены")

    # Показываем примеры
    print(f"\n📋 Примеры (первые 5 стейкингов):")
    for i, s in enumerate(stakings[:5], 1):
        print(f"  {i}. {s['coin']:8s} | APR: {s['apr']:6.2f}% | {s['type']:15s} | {s['status']}")

    return True


def test_kucoin_parser():
    """Тест 2: Парсинг Kucoin стейкингов"""
    print("\n" + "="*80)
    print("🧪 ТЕСТ 2: ПАРСИНГ KUCOIN СТЕЙКИНГОВ")
    print("="*80)

    from parsers.staking_parser import StakingParser

    parser = StakingParser(
        api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
        exchange_name="Kucoin"
    )

    print("📡 Запуск парсинга Kucoin...")
    stakings = parser.parse()

    if not stakings:
        print("❌ FAILED: Не удалось получить стейкинги от Kucoin")
        return False

    print(f"✅ SUCCESS: Получено {len(stakings)} стейкингов от Kucoin")

    # Показываем примеры
    print(f"\n📋 Примеры (первые 5 стейкингов):")
    for i, s in enumerate(stakings[:5], 1):
        term = f"{s['term_days']}d" if s['term_days'] > 0 else "Flexible"
        print(f"  {i}. {s['coin']:8s} | APR: {s['apr']:6.2f}% | {term:15s} | {s['status']}")

    return True


def test_database_integration():
    """Тест 3: Интеграция с БД"""
    print("\n" + "="*80)
    print("🧪 ТЕСТ 3: ИНТЕГРАЦИЯ С БАЗОЙ ДАННЫХ")
    print("="*80)

    from bot.parser_service import check_and_save_new_stakings
    from data.database import get_db_session
    from data.models import StakingHistory

    # Тестовые данные
    test_stakings = [
        {
            'exchange': 'TestExchange',
            'product_id': 'TEST_001',
            'coin': 'BTC',
            'reward_coin': None,
            'apr': 5.5,
            'type': 'Flexible',
            'status': 'Active',
            'category': None,
            'category_text': None,
            'term_days': 0,
            'token_price_usd': 43000.0,
            'fill_percentage': None,
            'max_capacity': None,
            'current_deposit': None,
            'user_limit_tokens': None,
            'user_limit_usd': None,
            'total_places': None,
            'start_time': None,
            'end_time': None
        }
    ]

    print("💾 Сохранение тестового стейкинга в БД...")

    # Первое сохранение - должен быть новым
    new_stakings_1 = check_and_save_new_stakings(test_stakings, link_id=999)

    if len(new_stakings_1) != 1:
        print(f"❌ FAILED: Ожидалось 1 новый стейкинг, получено {len(new_stakings_1)}")
        return False

    print(f"✅ SUCCESS: Новый стейкинг сохранен")

    # Второе сохранение того же - НЕ должен быть новым (дубликат)
    new_stakings_2 = check_and_save_new_stakings(test_stakings, link_id=999)

    if len(new_stakings_2) != 0:
        print(f"❌ FAILED: Дубликат не был отфильтрован")
        return False

    print(f"✅ SUCCESS: Дубликаты корректно фильтруются")

    # Проверяем что записи в БД
    with get_db_session() as session:
        count = session.query(StakingHistory).filter(
            StakingHistory.exchange == 'TestExchange',
            StakingHistory.product_id == 'TEST_001'
        ).count()

        if count != 1:
            print(f"❌ FAILED: В БД {count} записей вместо 1")
            return False

    print(f"✅ SUCCESS: В БД ровно 1 запись (дубликаты не создаются)")

    # Очистка тестовых данных
    with get_db_session() as session:
        session.query(StakingHistory).filter(
            StakingHistory.exchange == 'TestExchange'
        ).delete()
        session.commit()

    print(f"🧹 Тестовые данные очищены")

    return True


def test_notification_formatters():
    """Тест 4: Форматтеры уведомлений"""
    print("\n" + "="*80)
    print("🧪 ТЕСТ 4: ФОРМАТТЕРЫ УВЕДОМЛЕНИЙ")
    print("="*80)

    from bot.notification_service import NotificationService

    service = NotificationService(bot=None)

    # Тестовый стейкинг Bybit с заполненностью
    test_staking_bybit = {
        'exchange': 'Bybit',
        'product_id': '12345',
        'coin': 'BTC',
        'apr': 5.5,
        'type': 'Flexible',
        'status': 'Active',
        'term_days': 0,
        'token_price_usd': 43250.50,
        'fill_percentage': 65.3,
        'max_capacity': 1000000,
        'current_deposit': 653000
    }

    print("📝 Тест format_new_staking() для Bybit...")
    message1 = service.format_new_staking(
        test_staking_bybit,
        page_url="https://www.bybit.com/earn"
    )

    # Проверяем что в сообщении есть ключевые элементы
    checks = [
        ('НОВЫЙ СТЕЙКИНГ' in message1, "Заголовок"),
        ('BTC' in message1, "Название монеты"),
        ('5.5%' in message1, "APR"),
        ('65.3%' in message1 or '65.30%' in message1, "Заполненность"),
        ('▓' in message1 or '░' in message1, "Прогресс-бар")
    ]

    all_ok = True
    for check, name in checks:
        if check:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}")
            all_ok = False

    if not all_ok:
        print("❌ FAILED: Не все элементы присутствуют в уведомлении")
        return False

    print("✅ SUCCESS: format_new_staking() работает корректно")

    # Тест format_pools_report()
    test_pools = [
        {
            'coin': 'BTC',
            'apr': 2.3,
            'type': 'Flexible',
            'term_days': 0,
            'status': 'Active',
            'fill_percentage': 60.08,
            'max_capacity': 1500000,
            'current_deposit': 901271,
            'token_price_usd': 43250.50
        },
        {
            'coin': 'ETH',
            'apr': 3.5,
            'type': 'Fixed 30d',
            'term_days': 30,
            'status': 'Active',
            'fill_percentage': 85.2,
            'max_capacity': 500000,
            'current_deposit': 426000,
            'token_price_usd': 2250.30
        }
    ]

    print("\n📝 Тест format_pools_report()...")
    message2 = service.format_pools_report(
        test_pools,
        exchange_name="Bybit",
        page_url="https://www.bybit.com/earn"
    )

    checks2 = [
        ('ЗАПОЛНЕННОСТЬ ПУЛОВ' in message2, "Заголовок"),
        ('BTC' in message2, "Монета BTC"),
        ('ETH' in message2, "Монета ETH"),
        ('Средняя заполненность' in message2, "Статистика"),
        ('▓' in message2 or '░' in message2, "Прогресс-бары")
    ]

    all_ok2 = True
    for check, name in checks2:
        if check:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}")
            all_ok2 = False

    if not all_ok2:
        print("❌ FAILED: Не все элементы присутствуют в отчёте")
        return False

    print("✅ SUCCESS: format_pools_report() работает корректно")

    return True


def test_end_to_end():
    """Тест 5: End-to-End тест полного цикла"""
    print("\n" + "="*80)
    print("🧪 ТЕСТ 5: END-TO-END ТЕСТ (Bybit полный цикл)")
    print("="*80)

    from parsers.staking_parser import StakingParser
    from bot.parser_service import check_and_save_new_stakings
    from bot.notification_service import NotificationService

    # 1. Парсинг
    print("1️⃣ Парсинг стейкингов от Bybit...")
    parser = StakingParser(
        api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
        exchange_name="Bybit"
    )
    stakings = parser.parse()

    if not stakings:
        print("❌ FAILED: Парсинг не вернул данных")
        return False

    print(f"   ✅ Получено {len(stakings)} стейкингов")

    # 2. Сохранение в БД
    print("2️⃣ Проверка дубликатов и сохранение...")
    new_stakings = check_and_save_new_stakings(stakings, link_id=888)

    print(f"   ✅ Новых стейкингов: {len(new_stakings)}")
    print(f"   ✅ Дубликатов отфильтровано: {len(stakings) - len(new_stakings)}")

    # 3. Форматирование уведомлений
    print("3️⃣ Форматирование уведомлений...")
    service = NotificationService(bot=None)

    if new_stakings:
        first_new = new_stakings[0]
        message = service.format_new_staking(
            first_new,
            page_url="https://www.bybit.com/earn"
        )
        print(f"   ✅ Уведомление создано ({len(message)} символов)")
    else:
        print(f"   ℹ️ Нет новых стейкингов для уведомлений (все уже в БД)")

    # 4. Отчёт о заполненности
    print("4️⃣ Создание отчёта о заполненности...")
    pools_with_fill = [s for s in stakings if s.get('fill_percentage') is not None]

    if pools_with_fill:
        report = service.format_pools_report(
            pools_with_fill[:10],  # Первые 10
            exchange_name="Bybit",
            page_url="https://www.bybit.com/earn"
        )
        print(f"   ✅ Отчёт создан ({len(report)} символов)")
        print(f"   ✅ Пулов с заполненностью: {len(pools_with_fill)}")
    else:
        print(f"   ⚠️ Нет пулов с данными о заполненности")

    print("\n✅ SUCCESS: End-to-End тест пройден успешно!")

    # Очистка
    from data.database import get_db_session
    from data.models import StakingHistory

    with get_db_session() as session:
        deleted = session.query(StakingHistory).filter(
            StakingHistory.api_link_id == 888
        ).delete()
        session.commit()
        print(f"🧹 Очищено {deleted} тестовых записей из БД")

    return True


def main():
    """Запуск всех тестов"""
    print("\n" + "🚀" * 40)
    print("🚀 КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ СТЕЙКИНГА")
    print("🚀" * 40)

    tests = [
        ("Парсинг Bybit", test_bybit_parser),
        ("Парсинг Kucoin", test_kucoin_parser),
        ("Интеграция с БД", test_database_integration),
        ("Форматтеры уведомлений", test_notification_formatters),
        ("End-to-End тест", test_end_to_end)
    ]

    results = []

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в тесте '{name}': {e}", exc_info=True)
            results.append((name, False))

    # Итоговая сводка
    print("\n" + "="*80)
    print("📊 ИТОГОВАЯ СВОДКА")
    print("="*80)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status:12s} | {name}")

    print("="*80)
    print(f"📈 Результат: {passed}/{total} тестов пройдено ({passed/total*100:.1f}%)")

    if passed == total:
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print(f"⚠️ {total - passed} тест(ов) провалено")

    print("="*80)


if __name__ == "__main__":
    main()
