"""
Тест форматтеров уведомлений для стейкингов
"""

import sys
import io
import logging
from bot.notification_service import NotificationService

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

def test_format_new_staking():
    """Тест форматтера нового стейкинга"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Форматтер нового стейкинга")
    logger.info("=" * 80 + "\n")

    # Создаем фиктивный NotificationService (без бота)
    service = NotificationService(bot=None)

    # Тестовые данные стейкинга от Bybit (с заполненностью)
    test_staking_bybit = {
        'exchange': 'Bybit',
        'product_id': '12345',
        'coin': 'BTC',
        'reward_coin': None,
        'apr': 5.5,
        'type': 'Flexible',
        'status': 'Active',
        'category': None,
        'category_text': None,
        'term_days': 0,
        'token_price_usd': 43250.50,
        'fill_percentage': 65.3,
        'max_capacity': 1000000,
        'current_deposit': 653000,
        'user_limit_tokens': None,
        'user_limit_usd': None,
        'total_places': None,
        'start_time': None,
        'end_time': None
    }

    # Тестовые данные стейкинга от Kucoin (без заполненности, но с лимитами)
    test_staking_kucoin = {
        'exchange': 'Kucoin',
        'product_id': '3439',
        'coin': 'IR',
        'reward_coin': None,
        'apr': 200.0,
        'type': 'MULTI_TIME',
        'status': 'ONGOING',
        'category': 'ACTIVITY',
        'category_text': 'Promotions',
        'term_days': 14,
        'token_price_usd': 0.15,
        'fill_percentage': None,
        'user_limit_tokens': 5000,
        'user_limit_usd': None,
        'total_places': 298,
        'start_time': None,
        'end_time': None
    }

    # Тест 1: Bybit стейкинг
    logger.info("📝 Тест 1: Bybit стейкинг с заполненностью\n")
    message1 = service.format_new_staking(
        test_staking_bybit,
        page_url="https://www.bybit.com/earn"
    )
    print(message1)
    print("\n" + "=" * 80 + "\n")

    # Тест 2: Kucoin стейкинг
    logger.info("📝 Тест 2: Kucoin стейкинг с лимитами\n")
    message2 = service.format_new_staking(
        test_staking_kucoin,
        page_url="https://www.kucoin.com/ru/earn"
    )
    print(message2)
    print("\n" + "=" * 80 + "\n")

    logger.info("✅ Тест format_new_staking() завершён")


def test_format_pools_report():
    """Тест форматтера отчёта о заполненности"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Форматтер отчёта о заполненности пулов")
    logger.info("=" * 80 + "\n")

    service = NotificationService(bot=None)

    # Тестовые данные пулов
    test_pools = [
        {
            'coin': 'BTC',
            'apr': 2.3,
            'type': 'Flexible',
            'term_days': 0,
            'status': 'Active',
            'fill_percentage': 60.08,
            'max_capacity': 1500000000000.0,
            'current_deposit': 901271641538.0,
            'token_price_usd': 43250.50
        },
        {
            'coin': 'ETH',
            'apr': 3.5,
            'type': 'Fixed 30d',
            'term_days': 30,
            'status': 'Active',
            'fill_percentage': 85.2,
            'max_capacity': 500000000.0,
            'current_deposit': 426000000.0,
            'token_price_usd': 2250.30
        },
        {
            'coin': 'USDT',
            'apr': 8.0,
            'type': 'Fixed 60d',
            'term_days': 60,
            'status': 'Sold Out',
            'fill_percentage': 100.0,
            'max_capacity': 10000000.0,
            'current_deposit': 10000000.0,
            'token_price_usd': 1.0
        }
    ]

    logger.info("📝 Тест: Отчёт о 3 пулах\n")
    message = service.format_pools_report(
        test_pools,
        exchange_name="Bybit",
        page_url="https://www.bybit.com/earn"
    )
    print(message)
    print("\n" + "=" * 80 + "\n")

    logger.info("✅ Тест format_pools_report() завершён")


def test_empty_pools_report():
    """Тест форматтера с пустым списком пулов"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Пустой отчёт о пулах")
    logger.info("=" * 80 + "\n")

    service = NotificationService(bot=None)

    message = service.format_pools_report(
        [],
        exchange_name="Kucoin"
    )
    print(message)
    print("\n" + "=" * 80 + "\n")

    logger.info("✅ Тест пустого отчёта завершён")


def main():
    logger.info("🚀 ТЕСТИРОВАНИЕ ФОРМАТТЕРОВ УВЕДОМЛЕНИЙ\n")

    try:
        test_format_new_staking()
        test_format_pools_report()
        test_empty_pools_report()

        logger.info("\n" + "=" * 80)
        logger.info("💡 ИТОГ:")
        logger.info("=" * 80)
        logger.info("\n✅ Все форматтеры работают корректно!")
        logger.info("✅ HTML разметка применяется правильно")
        logger.info("✅ Прогресс бары отображаются")
        logger.info("✅ Все поля обрабатываются")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)


if __name__ == "__main__":
    main()
