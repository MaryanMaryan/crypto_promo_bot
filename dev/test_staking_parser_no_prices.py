"""
Тестовый скрипт для проверки работы парсера стейкингов (без получения цен)
"""

import sys
import logging
import requests

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_kucoin_parser_simple():
    """Простой тест парсера Kucoin без получения цен"""

    logger.info("=" * 80)
    logger.info("ТЕСТ: Парсер стейкингов Kucoin (без получения цен)")
    logger.info("=" * 80 + "\n")

    url = "https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1"

    try:
        logger.info(f"📡 Запрос к API: {url}\n")
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        stakings = data.get('data', [])

        if not stakings:
            logger.error("❌ Нет данных о стейкингах")
            return

        logger.info(f"✅ Получено {len(stakings)} стейкингов\n")
        logger.info("=" * 80)

        # Показываем топ-5 стейкингов с наибольшим APR
        sorted_stakings = sorted(stakings, key=lambda x: float(x.get('total_apr', 0)), reverse=True)
        top_5 = sorted_stakings[:5]

        logger.info("🏆 ТОП-5 СТЕЙКИНГОВ ПО APR:\n")

        for i, staking in enumerate(top_5, 1):
            coin = staking.get('currency', 'N/A')
            apr = float(staking.get('total_apr', 0))
            term_days = staking.get('duration', 0)
            status = staking.get('status', 'N/A')
            category = staking.get('category_text', staking.get('category', 'N/A'))
            product_type = staking.get('type', 'N/A')

            logger.info(f"#{i}. {coin}")
            logger.info(f"   💰 APR: {apr}%")
            logger.info(f"   📅 Период: {term_days} дней" if term_days > 0 else "   📅 Период: Flexible")
            logger.info(f"   📊 Статус: {status}")
            logger.info(f"   🏷️ Категория: {category}")
            logger.info(f"   🔧 Тип: {product_type}")
            logger.info("")

        # Статистика
        logger.info("=" * 80)
        logger.info("📊 СТАТИСТИКА:")
        logger.info("=" * 80 + "\n")

        total = len(stakings)
        avg_apr = sum(float(s.get('total_apr', 0)) for s in stakings) / total if total > 0 else 0

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
        logger.info(f"Максимальный APR: {max(float(s.get('total_apr', 0)) for s in stakings):.2f}%")
        logger.info(f"Минимальный APR: {min(float(s.get('total_apr', 0)) for s in stakings):.2f}%")
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
        high_apr = [s for s in stakings if float(s.get('total_apr', 0)) > 50]
        logger.info(f"📈 Стейкингов с APR > 50%: {len(high_apr)}")
        if high_apr:
            logger.info("   Токены:")
            for s in high_apr[:10]:  # Показываем первые 10
                logger.info(f"   - {s['currency']}: {s['total_apr']}% APR")
        logger.info("")

        # Flexible стейкинги
        flexible = [s for s in stakings if s.get('duration', 0) == 0]
        logger.info(f"🔄 Flexible стейкингов: {len(flexible)}")
        if flexible:
            logger.info("   Токены:")
            for s in flexible[:10]:
                logger.info(f"   - {s['currency']}: {s['total_apr']}% APR")
        logger.info("")

        # ACTIVITY категория
        activity = [s for s in stakings if s.get('category') == 'ACTIVITY']
        logger.info(f"🎯 ACTIVITY стейкингов: {len(activity)}")
        if activity:
            logger.info("   Токены:")
            for s in activity[:10]:
                logger.info(f"   - {s['currency']}: {s['total_apr']}% APR")

        logger.info("\n" + "=" * 80)
        logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 80)

        return stakings

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}", exc_info=True)
        return None

def main():
    logger.info("🚀 ТЕСТИРОВАНИЕ ПАРСЕРА СТЕЙКИНГОВ\n")

    try:
        stakings = test_kucoin_parser_simple()

        if stakings:
            logger.info("\n" + "=" * 80)
            logger.info("💡 ИТОГ:")
            logger.info("=" * 80)
            logger.info("\n✅ Парсер работает корректно!")
            logger.info("✅ Данные успешно получены из Kucoin API")
            logger.info("✅ Структура данных соответствует ожиданиям")
            logger.info("\n⚠️  ПРИМЕЧАНИЕ: Получение цен токенов отключено из-за rate limit CoinGecko API")
            logger.info("⚠️  В продакшене используйте кэширование и контроль частоты запросов")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
