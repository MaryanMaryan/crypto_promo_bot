"""
Скрипт для автоматического обновления маппинга Bybit Coin ID → Symbol
Извлекает данные из Bybit API и обновляет bybit_coin_mapping.py
"""
import requests
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_bybit_coins():
    """Получает список всех монет от Bybit API"""
    url = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list"

    headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://www.bybit.com',
        'referer': 'https://www.bybit.com/en/earn/easy-earn',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    payload = {
        "tab": "0",  # Все продукты
        "page": 1,
        "limit": 500,  # Максимальное количество
        "fixed_saving_version": 1,
        "fuzzy_coin_name": "",
        "sort_type": 0,
        "match_user_asset": False,
        "eligible_only": False
    }

    try:
        logger.info("🔍 Запрос к Bybit API...")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get('ret_code') != 0:
            logger.error(f"❌ Bybit API error: {data.get('ret_msg')}")
            return {}

        logger.info(f"✅ Получен ответ от Bybit API")
        return data

    except Exception as e:
        logger.error(f"❌ Ошибка запроса к Bybit API: {e}")
        return {}

def extract_coin_mapping(data):
    """Извлекает маппинг coin_id -> symbol из данных API"""
    mapping = {}
    seen_symbols = {}  # Для отслеживания дубликатов

    result = data.get('result', {})
    coin_products = result.get('coin_products', [])

    logger.info(f"📊 Обработка {len(coin_products)} монет...")

    # Сохраняем сырые данные для анализа
    debug_file = Path(__file__).parent.parent / "test_data" / "bybit_api_response.json"
    debug_file.parent.mkdir(exist_ok=True)
    with open(debug_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"💾 Сырые данные сохранены в: {debug_file}")

    for coin_product in coin_products:
        coin_id = coin_product.get('coin')

        # Получаем coin_name напрямую из coin_product
        coin_name = coin_product.get('coin_name')

        if coin_name and coin_id not in mapping:
            # coin_name - это правильное название монеты!
            symbol = coin_name.upper().strip()
            mapping[coin_id] = symbol
            if symbol not in seen_symbols:
                seen_symbols[symbol] = []
            seen_symbols[symbol].append(coin_id)
            logger.info(f"   Найдено: {coin_id} -> {symbol} (из coin_name)")
            continue

        # Если coin_name нет, пробуем другие способы
        saving_products = coin_product.get('saving_products', [])

        for product in saving_products:
            if coin_id in mapping:
                break

            # Получаем тег для определения монеты
            tag_info = product.get('product_tag_info', {})
            tag = tag_info.get('display_tag_key', '')

            # Пытаемся извлечь символ из тега
            if tag:
                parts = tag.split('_')
                if parts:
                    potential_symbol = parts[0].upper()
                    # Проверяем что это похоже на символ токена (2-10 букв)
                    if len(potential_symbol) >= 2 and len(potential_symbol) <= 10 and potential_symbol.isalpha():
                        mapping[coin_id] = potential_symbol
                        if potential_symbol not in seen_symbols:
                            seen_symbols[potential_symbol] = []
                        seen_symbols[potential_symbol].append(coin_id)
                        logger.info(f"   Найдено: {coin_id} -> {potential_symbol} (из тега)")
                        break

    # Удаляем дубликаты (оставляем первое вхождение)
    duplicates = {symbol: ids for symbol, ids in seen_symbols.items() if len(ids) > 1}
    if duplicates:
        logger.warning(f"⚠️ Найдены дубликаты символов:")
        for symbol, ids in duplicates.items():
            logger.warning(f"   {symbol}: {ids}")

    logger.info(f"✅ Извлечено {len(mapping)} маппингов")
    return mapping

def update_mapping_file(new_mapping):
    """Обновляет файл bybit_coin_mapping.py"""
    # Путь к файлу маппинга (в корне проекта)
    project_root = Path(__file__).parent.parent.parent
    mapping_file = project_root / "bybit_coin_mapping.py"

    logger.info(f"📝 Обновление файла: {mapping_file}")

    # Читаем существующий маппинг
    existing_mapping = {}
    if mapping_file.exists():
        with open(mapping_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # Находим словарь в файле
            if 'BYBIT_COIN_MAPPING = {' in content:
                try:
                    # Извлекаем существующий маппинг
                    start = content.find('BYBIT_COIN_MAPPING = {')
                    end = content.find('\n}', start) + 2
                    dict_str = content[start:end]
                    dict_str = dict_str.replace('BYBIT_COIN_MAPPING = ', '')
                    existing_mapping = eval(dict_str)
                    logger.info(f"   Загружено {len(existing_mapping)} существующих маппингов")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось прочитать существующий маппинг: {e}")

    # Объединяем существующий и новый маппинг (новый перезаписывает старый)
    combined_mapping = {**existing_mapping, **new_mapping}

    # Сортируем по coin_id
    sorted_mapping = dict(sorted(combined_mapping.items()))

    # Формируем содержимое файла
    content = '''"""
Маппинг Bybit Coin ID → Symbol
Автоматически сгенерировано
"""

BYBIT_COIN_MAPPING = {
'''

    for coin_id, symbol in sorted_mapping.items():
        content += f'    {coin_id}: "{symbol}",\n'

    content += '}\n'

    # Записываем в файл
    with open(mapping_file, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"✅ Файл обновлен! Всего маппингов: {len(sorted_mapping)}")
    logger.info(f"   Новых: {len(new_mapping)}, Существующих: {len(existing_mapping)}")

    # Показываем новые маппинги
    new_additions = {k: v for k, v in new_mapping.items() if k not in existing_mapping}
    if new_additions:
        logger.info(f"\n🆕 Добавлено новых маппингов: {len(new_additions)}")
        for coin_id, symbol in sorted(new_additions.items()):
            logger.info(f"   {coin_id}: {symbol}")

def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("Обновление Bybit Coin Mapping")
    logger.info("=" * 60)

    # Получаем данные от API
    data = fetch_bybit_coins()
    if not data:
        logger.error("❌ Не удалось получить данные от API")
        return

    # Извлекаем маппинг
    new_mapping = extract_coin_mapping(data)
    if not new_mapping:
        logger.warning("⚠️ Не удалось извлечь маппинг")
        return

    # Обновляем файл
    update_mapping_file(new_mapping)

    logger.info("=" * 60)
    logger.info("✅ Готово!")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
