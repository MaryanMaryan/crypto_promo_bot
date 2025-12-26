"""
Тестовый скрипт для проверки работы парсера стейкингов
"""

import sys
import logging
from parsers.staking_parser import StakingParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_kucoin_parser():
    """Тест парсера Kucoin"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Парсер стейкингов Kucoin")
    logger.info("=" * 80 + "\n")

    # Создаем парсер
    parser = StakingParser(
        api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
        exchange_name="Kucoin"
    )

    # Парсим стейкинги
    logger.info("📡 Запрос данных о стейкингах...\n")
    stakings = parser.parse()

    if not stakings:
        logger.error("❌ Не удалось получить данные о стейкингах")
        return

    logger.info(f"✅ Получено {len(stakings)} стейкингов\n")
    logger.info("=" * 80)

    # Показываем топ-5 стейкингов с наибольшим APR
    sorted_stakings = sorted(stakings, key=lambda x: x.get('apr', 0), reverse=True)
    top_5 = sorted_stakings[:5]

    logger.info("🏆 ТОП-5 СТЕЙКИНГОВ ПО APR:\n")

    for i, staking in enumerate(top_5, 1):
        coin = staking.get('coin', 'N/A')
        apr = staking.get('apr', 0)
        term_days = staking.get('term_days', 0)
        status = staking.get('status', 'N/A')
        category = staking.get('category_text', staking.get('category', 'N/A'))
        token_price = staking.get('token_price_usd')

        logger.info(f"#{i}. {coin}")
        logger.info(f"   💰 APR: {apr}%")
        logger.info(f"   📅 Период: {term_days} дней" if term_days > 0 else "   📅 Период: Flexible")
        logger.info(f"   📊 Статус: {status}")
        logger.info(f"   🏷️ Категория: {category}")
        if token_price:
            logger.info(f"   💵 Цена: ${token_price:.4f}")
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

    # Категории
    categories = {}
    for s in stakings:
        category = s.get('category', 'Unknown')
        categories[category] = categories.get(category, 0) + 1

    # Типы
    types = {}
    for s in stakings:
        stype = s.get('type', 'Unknown')
        types[stype] = types.get(stype, 0) + 1

    logger.info(f"Всего стейкингов: {total}")
    logger.info(f"Средний APR: {avg_apr:.2f}%")
    logger.info(f"Максимальный APR: {max(s.get('apr', 0) for s in stakings):.2f}%")
    logger.info(f"Минимальный APR: {min(s.get('apr', 0) for s in stakings):.2f}%")
    logger.info("")

    logger.info("Распределение по статусам:")
    for status, count in statuses.items():
        logger.info(f"  - {status}: {count}")
    logger.info("")

    logger.info("Распределение по категориям:")
    for category, count in categories.items():
        logger.info(f"  - {category}: {count}")
    logger.info("")

    logger.info("Распределение по типам:")
    for stype, count in types.items():
        logger.info(f"  - {stype}: {count}")
    logger.info("")

    # Примеры фильтрации
    logger.info("=" * 80)
    logger.info("🔍 ПРИМЕРЫ ФИЛЬТРАЦИИ:")
    logger.info("=" * 80 + "\n")

    # Стейкинги с APR > 50%
    high_apr = [s for s in stakings if s.get('apr', 0) > 50]
    logger.info(f"📈 Стейкингов с APR > 50%: {len(high_apr)}")

    # Flexible стейкинги
    flexible = [s for s in stakings if s.get('term_days', 0) == 0]
    logger.info(f"🔄 Flexible стейкингов: {len(flexible)}")

    # ACTIVITY категория
    activity = [s for s in stakings if s.get('category') == 'ACTIVITY']
    logger.info(f"🎯 ACTIVITY стейкингов: {len(activity)}")

    logger.info("\n" + "=" * 80)
    logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    logger.info("=" * 80)

def main():
    logger.info("🚀 ТЕСТИРОВАНИЕ ПАРСЕРА СТЕЙКИНГОВ\n")

    try:
        test_kucoin_parser()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
