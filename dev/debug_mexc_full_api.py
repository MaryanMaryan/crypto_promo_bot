"""
Отладочный скрипт для полной проверки MEXC API
Проверяет реальный ответ от API и как парсер его обрабатывает
"""
import sys
import os
import io

# Фиксим кодировку для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.universal_parser import UniversalParser
import json
import requests

def debug_mexc_api():
    """Отладка реального ответа от MEXC API"""

    url = "https://www.mexc.com/api/operateactivity/eftd/list"

    print("=" * 80)
    print("ОТЛАДКА MEXC API")
    print("=" * 80)
    print(f"\nURL: {url}\n")

    # Запрашиваем данные напрямую без парсера
    print("1. Запрос к API...\n")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        print(f"Статус: {response.status_code}")
        print(f"Размер ответа: {len(response.text)} байт")

        # Сохраняем сырой ответ
        with open("dev/mexc_raw_api_response.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("Сырой ответ сохранён в: dev/mexc_raw_api_response.json\n")

        # Анализируем структуру
        print("=" * 80)
        print("2. АНАЛИЗ СТРУКТУРЫ ДАННЫХ")
        print("=" * 80)

        if isinstance(data, dict) and 'data' in data:
            items = data['data']
            print(f"\nВсего элементов в data: {len(items)}")

            # Проверяем первые 5 элементов
            print("\nПроверка первых 5 элементов:")
            for i, item in enumerate(items[:5], 1):
                print(f"\n--- Элемент {i} ---")
                print(f"ID: {item.get('id')}")
                print(f"activityCurrency: {item.get('activityCurrency')}")
                print(f"activityCurrencyFullName: {item.get('activityCurrencyFullName')}")
                print(f"activityName: {item.get('activityName')}")

                # Проверяем наличие eftdVOS
                if 'eftdVOS' in item and item['eftdVOS']:
                    print(f"eftdVOS: {len(item['eftdVOS'])} подпромоакций")

                    # Проверяем первую подпромоакцию
                    sub = item['eftdVOS'][0]
                    print(f"  └─ Подпромоакция ID: {sub.get('id')}")
                    print(f"     activityCurrency: {sub.get('activityCurrency', 'НЕТ')}")
                    print(f"     activityCurrencyFullName: {sub.get('activityCurrencyFullName', 'НЕТ')}")

        # Парсим через наш парсер
        print("\n" + "=" * 80)
        print("3. ПАРСИНГ ЧЕРЕЗ UniversalParser")
        print("=" * 80)

        parser = UniversalParser(url)
        promotions = parser.parse_json_data(data)

        print(f"\nНайдено промоакций после парсинга: {len(promotions)}")

        # Подсчитываем fallback промоакции
        fallback_count = sum(1 for p in promotions if p.get('title', '').startswith('MEXC Promo mexc_'))
        normal_count = len(promotions) - fallback_count

        print(f"\nСтатистика:")
        print(f"  ✅ Нормальные названия: {normal_count}")
        print(f"  ❌ Fallback названия (MEXC Promo): {fallback_count}")

        # Показываем примеры
        print("\nПримеры промоакций:")
        for i, promo in enumerate(promotions[:10], 1):
            title = promo.get('title', 'Без названия')
            promo_id = promo.get('promo_id', 'N/A')
            token = promo.get('award_token', 'N/A')

            status = "✅" if not title.startswith('MEXC Promo mexc_') else "❌"
            print(f"{status} {i}. {title} (ID: {promo_id}, Token: {token})")

        # Сохраняем результат парсинга
        with open("dev/mexc_parsed_promotions.json", "w", encoding="utf-8") as f:
            json.dump(promotions[:20], f, ensure_ascii=False, indent=2)

        print(f"\nПервые 20 промоакций сохранены в: dev/mexc_parsed_promotions.json")
        print("=" * 80)

    except Exception as e:
        print(f"ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_mexc_api()
