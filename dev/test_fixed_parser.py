"""
Тест исправленного BrowserParser с fallback на direct connection
"""
import logging
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def test_browser_parser():
    """Тестирование BrowserParser с новыми исправлениями"""
    from parsers.browser_parser import BrowserParser

    test_urls = [
        "https://www.mexc.com/launchpad",
        # "https://www.bybit.com/trade/spot/token-splash"  # Пропускаем Bybit из-за HTTP/2 ошибки
    ]

    for url in test_urls:
        logger.info("=" * 80)
        logger.info(f"Тестирование: {url}")
        logger.info("=" * 80)

        try:
            parser = BrowserParser(url)
            promotions = parser.get_promotions()

            logger.info(f"\nРЕЗУЛЬТАТ:")
            logger.info(f"  Найдено промоакций: {len(promotions)}")

            if promotions:
                logger.info(f"\n  Первые 3 промоакции:")
                for i, promo in enumerate(promotions[:3], 1):
                    logger.info(f"    {i}. {promo.get('title', 'Без названия')}")
                    logger.info(f"       promo_id: {promo.get('promo_id', 'N/A')}")
                    logger.info(f"       link: {promo.get('link', 'N/A')}")
            else:
                logger.warning(f"  ⚠️ Промоакции не найдены")

        except Exception as e:
            logger.error(f"❌ Ошибка теста: {e}", exc_info=True)

    logger.info("\n" + "=" * 80)
    logger.info("Все тесты завершены")

if __name__ == "__main__":
    test_browser_parser()
