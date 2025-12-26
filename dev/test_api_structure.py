"""
Скрипт для изучения структуры API данных Kucoin и Bybit
"""

import requests
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def fetch_kucoin_staking():
    """Получить данные о стейкингах Kucoin"""

    logger.info("=" * 80)
    logger.info("KUCOIN STAKING API")
    logger.info("=" * 80)

    url = "https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1"

    try:
        logger.info(f"\n📡 Запрос к: {url}\n")
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Сохраняем полный ответ в файл
        with open('kucoin_api_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("✅ Данные сохранены в kucoin_api_response.json")

        # Показываем структуру первого продукта
        if data.get('data') and len(data['data']) > 0:
            first_product = data['data'][0]
            logger.info("\n📊 СТРУКТУРА ПЕРВОГО ПРОДУКТА:\n")
            logger.info(json.dumps(first_product, indent=2, ensure_ascii=False))

            logger.info("\n🔑 ДОСТУПНЫЕ КЛЮЧИ:\n")
            for key in first_product.keys():
                logger.info(f"  - {key}: {type(first_product[key]).__name__}")

        logger.info(f"\n📈 Всего стейкингов: {len(data.get('data', []))}")

        return data

    except Exception as e:
        logger.error(f"❌ Ошибка запроса к Kucoin: {e}", exc_info=True)
        return None

def fetch_bybit_staking():
    """Получить данные о стейкингах Bybit"""

    logger.info("\n" + "=" * 80)
    logger.info("BYBIT STAKING API")
    logger.info("=" * 80)

    url = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"

    # Добавляем заголовки для обхода блокировки
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.bybit.com/',
        'Origin': 'https://www.bybit.com'
    }

    try:
        logger.info(f"\n📡 Запрос к: {url}\n")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Сохраняем полный ответ в файл
        with open('bybit_api_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("✅ Данные сохранены в bybit_api_response.json")

        # Показываем структуру
        logger.info("\n📊 СТРУКТУРА ОТВЕТА:\n")
        logger.info(f"Ключи верхнего уровня: {list(data.keys())}")

        # Пробуем найти массив продуктов
        products = None
        if data.get('data'):
            if isinstance(data['data'], list):
                products = data['data']
            elif data['data'].get('all'):
                products = data['data']['all']
            elif data['data'].get('list'):
                products = data['data']['list']

        if products and len(products) > 0:
            first_product = products[0]
            logger.info("\n📊 СТРУКТУРА ПЕРВОГО ПРОДУКТА:\n")
            logger.info(json.dumps(first_product, indent=2, ensure_ascii=False))

            logger.info("\n🔑 ДОСТУПНЫЕ КЛЮЧИ:\n")
            for key in first_product.keys():
                logger.info(f"  - {key}: {type(first_product[key]).__name__}")

            logger.info(f"\n📈 Всего стейкингов: {len(products)}")
        else:
            logger.warning("⚠️ Не удалось найти массив продуктов")

        return data

    except Exception as e:
        logger.error(f"❌ Ошибка запроса к Bybit: {e}", exc_info=True)
        return None

def main():
    logger.info("🚀 ИЗУЧЕНИЕ СТРУКТУРЫ API СТЕЙКИНГОВ\n")

    # Kucoin
    kucoin_data = fetch_kucoin_staking()

    # Bybit
    bybit_data = fetch_bybit_staking()

    logger.info("\n" + "=" * 80)
    logger.info("✅ АНАЛИЗ ЗАВЕРШЕН")
    logger.info("=" * 80)
    logger.info("\nПроверьте файлы:")
    logger.info("  - kucoin_api_response.json")
    logger.info("  - bybit_api_response.json")
    logger.info("\nДля детального изучения структуры данных")

if __name__ == "__main__":
    main()
