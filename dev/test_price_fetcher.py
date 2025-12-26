"""
Тестовый скрипт для проверки работы price_fetcher
"""

import sys
import logging
from utils.price_fetcher import get_price_fetcher

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_price_fetcher():
    """Тестирование получения цен"""

    logger.info("=" * 60)
    logger.info("ТЕСТ: Получение цен токенов с CoinGecko")
    logger.info("=" * 60)

    fetcher = get_price_fetcher()

    # Тестовые токены
    test_tokens = ['BTC', 'ETH', 'DOGE', 'USDT']

    logger.info(f"\n📊 Тестирование получения цен для: {', '.join(test_tokens)}\n")

    for token in test_tokens:
        try:
            price = fetcher.get_token_price(token)
            if price:
                logger.info(f"✅ {token}: ${price:,.4f}")
            else:
                logger.warning(f"⚠️ {token}: Цена не найдена")
        except Exception as e:
            logger.error(f"❌ {token}: Ошибка - {e}")

    # Тест кэширования
    logger.info("\n" + "=" * 60)
    logger.info("ТЕСТ: Проверка кэширования")
    logger.info("=" * 60 + "\n")

    logger.info("Повторный запрос BTC (должен вернуться из кэша):")
    price = fetcher.get_token_price('BTC')
    if price:
        logger.info(f"✅ BTC (из кэша): ${price:,.4f}")

    # Тест получения нескольких цен
    logger.info("\n" + "=" * 60)
    logger.info("ТЕСТ: Получение нескольких цен одновременно")
    logger.info("=" * 60 + "\n")

    multiple_tokens = ['SOL', 'ADA', 'XRP']
    prices = fetcher.get_multiple_prices(multiple_tokens)

    for token, price in prices.items():
        if price:
            logger.info(f"✅ {token}: ${price:,.4f}")
        else:
            logger.warning(f"⚠️ {token}: Цена не найдена")

    logger.info("\n" + "=" * 60)
    logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    logger.info("=" * 60)

if __name__ == "__main__":
    try:
        test_price_fetcher()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
