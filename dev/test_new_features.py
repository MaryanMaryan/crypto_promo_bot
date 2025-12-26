"""
Тестирование новых функций:
1. Парсинг токенов и отображение цен в уведомлениях
2. Функция "Назад" будет протестирована вручную в боте
"""

import sys
import os
import codecs

# Устанавливаем UTF-8 для консоли Windows
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(__file__))

from bot.notification_service import NotificationService
from utils.price_fetcher import get_price_fetcher

def test_token_parsing():
    """Тестирование парсинга токенов из текста наград"""

    print("=" * 60)
    print("ТЕСТ 1: Парсинг токенов и получение цен")
    print("=" * 60)

    # Создаем NotificationService с price_fetcher
    price_fetcher = get_price_fetcher()
    notification_service = NotificationService(bot=None, price_fetcher=price_fetcher)

    # Тестовые тексты с токенами
    test_texts = [
        "Win 100 BTC Prize Pool",
        "10,000 USDT and 500 ETH rewards",
        "Share 1,500,000 SHIB tokens",
        "Prize: 50 BNB or 5000 USDT",
        "Earn up to 100,000 DOGE",
        "No tokens here",  # Без токенов
        "1000000 PEPE airdrop",
    ]

    for i, text in enumerate(test_texts, 1):
        print(f"\n{i}. Текст: '{text}'")
        tokens = notification_service.parse_token_amounts(text)

        if tokens:
            print(f"   ✅ Найдено токенов: {len(tokens)}")
            for amount, symbol, price in tokens:
                formatted = notification_service.format_token_value(amount, symbol, price)
                print(f"      • {formatted}")
        else:
            print("   ❌ Токены не найдены")

def test_promo_formatting():
    """Тестирование форматирования уведомлений о промоакциях"""

    print("\n" + "=" * 60)
    print("ТЕСТ 2: Форматирование уведомлений о промоакциях")
    print("=" * 60)

    # Создаем NotificationService
    price_fetcher = get_price_fetcher()
    notification_service = NotificationService(bot=None, price_fetcher=price_fetcher)

    # Тестовые промоакции
    test_promos = [
        {
            'exchange': 'Bybit',
            'title': 'BTC Trading Competition',
            'description': 'Trade BTC and win amazing prizes!',
            'total_prize_pool': '100 BTC Prize Pool',
            'award_token': '10,000 USDT for top traders',
            'participants_count': 1000,
            'start_time': '2025-01-01',
            'end_time': '2025-01-31',
            'link': 'https://bybit.com/promo/123',
            'promo_id': 'TEST-001'
        },
        {
            'exchange': 'MEXC',
            'title': 'SHIB Airdrop Event',
            'total_prize_pool': '1,000,000 SHIB',
            'award_token': '500 USDT',
            'promo_id': 'TEST-002'
        },
        {
            'exchange': 'OKX',
            'title': 'ETH Staking Bonus',
            'total_prize_pool': '50 ETH and 10,000 USDT',
            'promo_id': 'TEST-003'
        }
    ]

    for i, promo in enumerate(test_promos, 1):
        print(f"\n--- Промоакция {i}: {promo['title']} ---")
        message = notification_service.format_promo_message(promo)
        print(message)
        print()

def test_edge_cases():
    """Тестирование граничных случаев"""

    print("\n" + "=" * 60)
    print("ТЕСТ 3: Граничные случаи")
    print("=" * 60)

    price_fetcher = get_price_fetcher()
    notification_service = NotificationService(bot=None, price_fetcher=price_fetcher)

    edge_cases = [
        ("", "Пустая строка"),
        ("100", "Только число"),
        ("BTC ETH USDT", "Только символы"),
        ("0.5 BTC", "Дробное число"),
        ("1,234,567.89 USDT", "Большое число с запятыми и точкой"),
        ("Win 100BTC", "Без пробела"),
        ("100 NEWUNKNOWNTOKEN123", "Неизвестный токен"),
    ]

    for text, description in edge_cases:
        print(f"\n{description}: '{text}'")
        tokens = notification_service.parse_token_amounts(text)

        if tokens:
            for amount, symbol, price in tokens:
                formatted = notification_service.format_token_value(amount, symbol, price)
                print(f"   ✅ {formatted}")
        else:
            print("   ❌ Токены не найдены")

if __name__ == "__main__":
    print("\n🧪 ЗАПУСК ТЕСТОВ НОВЫХ ФУНКЦИЙ\n")

    try:
        # Тест 1: Парсинг токенов
        test_token_parsing()

        # Тест 2: Форматирование промоакций
        test_promo_formatting()

        # Тест 3: Граничные случаи
        test_edge_cases()

        print("\n" + "=" * 60)
        print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 60)
        print("\nДля тестирования функции 'Назад' при добавлении ссылки:")
        print("1. Запустите бота: python main.py")
        print("2. Нажмите 'Добавить ссылку'")
        print("3. На каждом шаге проверьте кнопку '← Назад'")
        print("4. Убедитесь, что данные сохраняются при возврате")

    except Exception as e:
        print(f"\n❌ ОШИБКА ПРИ ВЫПОЛНЕНИИ ТЕСТОВ: {e}")
        import traceback
        traceback.print_exc()
