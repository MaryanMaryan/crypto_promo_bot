"""
Тест фильтрации подпромоакций MEXC
"""
import sys
import os
import io

# Фиксим кодировку для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.universal_parser import UniversalParser
import json

def test_mexc_filter():
    """Тест фильтрации подпромоакций MEXC"""

    # Реальные данные от MEXC API с основной промоакцией и подпромоакциями
    real_mexc_data = {
        "data": [
            {
                "id": 2746,
                "activityName": None,
                "activityCurrency": "FF",
                "activityCurrencyFullName": "Falcon Finance",
                "activityCurrencyId": "c01780bec3aa48eb9331736bdb085b57",
                "startTime": 1759140000000,
                "endTime": 1759917600000,
                # Подпромоакции в массиве eftdVOS
                "eftdVOS": [
                    {
                        "id": 2747,
                        "activityName": None,
                        "startTime": 1759140000000,
                        "endTime": 1759917600000,
                        "state": "END",
                        # У подпромоакций НЕТ activityCurrency!
                        "taskVOList": []
                    },
                    {
                        "id": 2748,
                        "activityName": None,
                        "startTime": 1759140000000,
                        "endTime": 1759917600000,
                        "state": "END",
                        "taskVOList": []
                    }
                ]
            }
        ]
    }

    print("=" * 80)
    print("ТЕСТ ФИЛЬТРАЦИИ ПОДПРОМОАКЦИЙ MEXC")
    print("=" * 80)
    print("\nТестируем, что подпромоакции из eftdVOS не создаются\n")

    # Создаем парсер
    url = "https://www.mexc.com/api/operateactivity/eftd/list"
    parser = UniversalParser(url)

    # Парсим данные
    print("Парсинг JSON данных...\n")
    promotions = parser.parse_json_data(real_mexc_data)

    print(f"Найдено промоакций: {len(promotions)}\n")
    print("=" * 80)
    print("РЕЗУЛЬТАТЫ:")
    print("=" * 80)

    if len(promotions) == 1:
        print("\n[OK] Найдена только 1 основная промоакция (подпромоакции отфильтрованы)")
        promo = promotions[0]
        print(f"\nНазвание: {promo.get('title')}")
        print(f"ID: {promo.get('promo_id')}")
        print(f"Токен: {promo.get('award_token')}")

        if promo.get('title') == 'Falcon Finance':
            print("\n[OK] Название корректное: 'Falcon Finance'")
        else:
            print(f"\n[FAIL] Ожидалось 'Falcon Finance', получено '{promo.get('title')}'")

    elif len(promotions) == 0:
        print("\n[FAIL] Промоакции не найдены! Возможно фильтр слишком строгий")
    else:
        print(f"\n[FAIL] Найдено {len(promotions)} промоакций (ожидалась 1)")
        print("\nПромоакции:")
        for i, promo in enumerate(promotions, 1):
            print(f"{i}. {promo.get('title')} (ID: {promo.get('promo_id')})")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_mexc_filter()
