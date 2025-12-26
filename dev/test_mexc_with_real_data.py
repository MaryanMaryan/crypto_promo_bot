"""
Тестовый скрипт для проверки парсинга MEXC с реальными данными от API
"""
import sys
import os
import io

# Фиксим кодировку для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.universal_parser import UniversalParser
import json

def test_mexc_parsing():
    """Тест парсинга MEXC с реальными данными"""

    # Реальные данные от MEXC API (первый элемент из массива)
    real_mexc_data = {
        "data": [{
            "id": 2746,
            "activityName": None,
            "startTime": 1759140000000,
            "endTime": 1759917600000,
            "firstProfitCurrencyId": "",
            "firstProfitCurrency": "",
            "firstProfitCurrencyType": "",
            "firstProfitCurrencyQuantity": "0",
            "firstProfitEqualValueType": "",
            "secondProfitCurrencyId": "",
            "secondProfitCurrency": "",
            "secondProfitCurrencyType": "",
            "secondProfitCurrencyQuantity": "0",
            "secondProfitEqualValueType": "",
            "createTime": 1758787720000,
            "updateTime": 1761213600000,
            "onlineTime": 1759150800000,
            "settleDays": 10,
            "state": "AWARDED",
            "validTime": 1759124700000,
            "sort": 125,
            "proxyProfitQuantity": "0",
            "taskVOList": None,
            "mainTaskVOList": None,
            "finishTaskId": None,
            "applyFlag": False,
            "applyTime": None,
            "applyNum": None,
            "mainTaskRelation": "NONE",
            "detailLogoWeb": "F20250929124749926M9QoALpXitusLo",
            "detailLogoReact": "F20250929124749926M9QoALpXitusLo",
            "shareLogo": "F20250929124749926M9QoALpXitusLo",
            "shareLogoRtl": "F20250929124749926M9QoALpXitusLo",
            "ruleContent": "",
            "shareContent": None,
            "introduction": "",
            "label": None,
            "coinIntroduction": None,
            "activityCurrency": "FF",
            "activityCurrencyFullName": "Falcon Finance",
            "activityCurrencyId": "c01780bec3aa48eb9331736bdb085b57",
            "proxyProfitType": "",
            "proxyProfitCurrency": "",
            "proxyProfitCurrencyId": ""
        }]
    }

    print("=" * 80)
    print("ТЕСТ ПАРСИНГА MEXC С РЕАЛЬНЫМИ ДАННЫМИ")
    print("=" * 80)
    print("\nТестируем парсинг данных от MEXC API\n")

    # Создаем парсер
    url = "https://www.mexc.com/api/operateactivity/eftd/list"
    parser = UniversalParser(url)

    # Парсим данные напрямую
    print("Парсинг JSON данных...\n")
    promotions = parser.parse_json_data(real_mexc_data)

    if not promotions:
        print("ОШИБКА: Промоакции не найдены!")
        print("\nВозможные причины:")
        print("- Данные не соответствуют ожидаемой структуре")
        print("- Парсер не смог извлечь нужные поля")
        return

    print(f"УСПЕХ: Найдено {len(promotions)} промоакций\n")
    print("=" * 80)
    print("РЕЗУЛЬТАТЫ ПАРСИНГА:")
    print("=" * 80)

    for i, promo in enumerate(promotions, 1):
        print(f"\n{i}. {promo.get('title', 'Без названия')}")
        print(f"   ID: {promo.get('promo_id', 'N/A')}")
        print(f"   Токен: {promo.get('award_token', 'N/A')}")
        print(f"   Биржа: {promo.get('exchange', 'N/A')}")

        # Детальная проверка
        print(f"\n   === ДЕТАЛЬНАЯ ПРОВЕРКА ===")

        # Проверяем title
        title = promo.get('title', '')
        if title.startswith('MEXC Promo mexc_'):
            print(f"   [FAIL] Title: Используется fallback! '{title}'")
            print(f"   [INFO] Ожидалось: 'Falcon Finance'")
        elif title == 'Falcon Finance':
            print(f"   [OK] Title: Корректно извлечен из activityCurrencyFullName")
        else:
            print(f"   [?] Title: '{title}' (неожиданное значение)")

        # Проверяем award_token
        award_token = promo.get('award_token', '')
        if award_token == 'FF':
            print(f"   [OK] Award Token: Корректно извлечен из activityCurrency")
        else:
            print(f"   [FAIL] Award Token: '{award_token}' (ожидалось 'FF')")

    # Выводим полный JSON первой промоакции для анализа
    print("\n" + "=" * 80)
    print("ПОЛНЫЕ ДАННЫЕ ПЕРВОЙ ПРОМОАКЦИИ:")
    print("=" * 80)
    print(json.dumps(promotions[0], ensure_ascii=False, indent=2))

    # Сохраняем результаты
    output_file = "dev/mexc_test_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "input_data": real_mexc_data,
            "parsed_promotions": promotions
        }, f, ensure_ascii=False, indent=2)

    print(f"\nРезультаты сохранены в: {output_file}")
    print("=" * 80)

if __name__ == "__main__":
    test_mexc_parsing()
