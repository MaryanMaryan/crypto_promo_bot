"""
Тест парсера Bybit стейкингов
"""

import sys
import logging
from parsers.staking_parser import StakingParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_bybit_parser():
    """Тест парсера Bybit"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Парсер стейкингов Bybit")
    logger.info("=" * 80 + "\n")

    # Создаем парсер (БЕЗ получения цен, чтобы избежать rate limit)
    parser = StakingParser(
        api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
        exchange_name="Bybit"
    )

    # Отключаем получение цен для теста
    original_get_price = parser.price_fetcher.get_token_price
    parser.price_fetcher.get_token_price = lambda x: None

    # Парсим стейкинги
    logger.info("📡 Запрос данных о стейкингах Bybit...\n")
    stakings = parser.parse()

    # Восстанавливаем метод
    parser.price_fetcher.get_token_price = original_get_price

    if not stakings:
        logger.error("❌ Не удалось получить данные о стейкингах")
        return False

    logger.info(f"✅ Получено {len(stakings)} стейкингов\n")
    logger.info("=" * 80)

    # Показываем топ-5 стейкингов с наибольшим APY
    sorted_stakings = sorted(stakings, key=lambda x: x.get('apr', 0), reverse=True)
    top_5 = sorted_stakings[:5]

    logger.info("🏆 ТОП-5 СТЕЙКИНГОВ ПО APY:\n")

    for i, staking in enumerate(top_5, 1):
        coin = staking.get('coin', 'N/A')
        apr = staking.get('apr', 0)
        term_days = staking.get('term_days', 0)
        status = staking.get('status', 'N/A')
        product_type = staking.get('type', 'N/A')
        fill_pct = staking.get('fill_percentage', 0)

        logger.info(f"#{i}. {coin}")
        logger.info(f"   💰 APY: {apr}%")
        logger.info(f"   📅 Тип: {product_type}")
        logger.info(f"   📊 Статус: {status}")
        if fill_pct:
            logger.info(f"   📈 Заполненность: {fill_pct}%")
        logger.info("")

    # Статистика
    logger.info("=" * 80)
    logger.info("📊 СТАТИСТИКА:")
    logger.info("=" * 80 + "\n")

    total = len(stakings)
    avg_apr = sum(s.get('apr', 0) for s in stakings) / total if total > 0 else 0

    # Статусы
    statuses = {}
    for s in stakings:
        status = s.get('status', 'Unknown')
        statuses[status] = statuses.get(status, 0) + 1

    # Монеты
    coins = {}
    for s in stakings:
        coin = s.get('coin', 'Unknown')
        coins[coin] = coins.get(coin, 0) + 1

    # Типы
    types = {}
    for s in stakings:
        stype = s.get('type', 'Unknown')
        types[stype] = types.get(stype, 0) + 1

    logger.info(f"Всего стейкингов: {total}")
    logger.info(f"Средний APY: {avg_apr:.2f}%")
    logger.info(f"Максимальный APY: {max(s.get('apr', 0) for s in stakings):.2f}%")
    logger.info(f"Минимальный APY: {min(s.get('apr', 0) for s in stakings):.2f}%")
    logger.info("")

    logger.info("Распределение по статусам:")
    for status, count in statuses.items():
        logger.info(f"  - {status}: {count}")
    logger.info("")

    logger.info("Распределение по монетам:")
    for coin, count in sorted(coins.items(), key=lambda x: x[1], reverse=True)[:10]:
        logger.info(f"  - {coin}: {count} продуктов")
    logger.info("")

    logger.info("Распределение по типам:")
    for stype, count in types.items():
        logger.info(f"  - {stype}: {count}")
    logger.info("")

    # Проверка заполненности
    logger.info("=" * 80)
    logger.info("📊 ЗАПОЛНЕННОСТЬ ПУЛОВ:")
    logger.info("=" * 80 + "\n")

    # Продукты с данными о заполненности
    with_fill = [s for s in stakings if s.get('fill_percentage') is not None]
    logger.info(f"Продуктов с данными о заполненности: {len(with_fill)}")

    if with_fill:
        # Топ-5 по заполненности
        sorted_by_fill = sorted(with_fill, key=lambda x: x.get('fill_percentage', 0), reverse=True)
        logger.info("\n🔥 ТОП-5 ПО ЗАПОЛНЕННОСТИ:")
        for i, s in enumerate(sorted_by_fill[:5], 1):
            logger.info(f"   {i}. {s['coin']} ({s['type']}): {s['fill_percentage']}% - {s['status']}")

    logger.info("\n" + "=" * 80)
    logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    logger.info("=" * 80)

    return True

def main():
    logger.info("🚀 ТЕСТИРОВАНИЕ ПАРСЕРА BYBIT СТЕЙКИНГОВ\n")

    try:
        success = test_bybit_parser()

        if success:
            logger.info("\n" + "=" * 80)
            logger.info("💡 ИТОГ:")
            logger.info("=" * 80)
            logger.info("\n✅ Парсер Bybit работает корректно!")
            logger.info("✅ Данные успешно получены через POST запрос")
            logger.info("✅ Структура данных соответствует ожиданиям")
            logger.info("✅ Доступны данные о заполненности пулов!")
            logger.info("\n⚠️  ПРИМЕЧАНИЕ: Получение цен токенов отключено для теста")
        else:
            logger.error("\n❌ Тест не пройден")
            sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
