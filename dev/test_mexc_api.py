"""
Тестовый скрипт для проверки парсинга MEXC API
"""
import sys
import os
import io

# Фиксим кодировку для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.universal_parser import UniversalParser
import json

def test_mexc_api():
    """Тест парсинга MEXC API"""

    # URL MEXC API для промоакций
    url = "https://www.mexc.com/api/operateactivity/eftd/list"

    print("=" * 80)
    print("ТЕСТ ПАРСИНГА MEXC API")
    print("=" * 80)
    print(f"\nURL: {url}\n")

    # Создаем парсер
    parser = UniversalParser(url)

    # Получаем промоакции
    print("Начинаем парсинг...\n")
    promotions = parser.get_promotions()

    if not promotions:
        print("ОШИБКА: Промоакции не найдены!")
        return

    print(f"УСПЕХ: Найдено {len(promotions)} промоакций\n")
    print("=" * 80)
    print("РЕЗУЛЬТАТЫ ПАРСИНГА:")
    print("=" * 80)

    # Выводим первые 5 промоакций для проверки
    for i, promo in enumerate(promotions[:5], 1):
        print(f"\n{i}. {promo.get('title', 'Без названия')}")
        print(f"   ID: {promo.get('promo_id', 'N/A')}")
        print(f"   Токен: {promo.get('award_token', 'N/A')}")
        print(f"   Биржа: {promo.get('exchange', 'N/A')}")

        # Проверяем, что это не fallback title
        if promo.get('title', '').startswith('MEXC Promo mexc_'):
            print(f"   [!] ВНИМАНИЕ: Это fallback title! Парсинг не сработал корректно.")
        else:
            print(f"   [OK] Title корректный")

    if len(promotions) > 5:
        print(f"\n... и еще {len(promotions) - 5} промоакций")

    # Сохраняем результаты в JSON для детального анализа
    output_file = "dev/mexc_parsed_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(promotions[:10], f, ensure_ascii=False, indent=2)

    print(f"\nПервые 10 промоакций сохранены в: {output_file}")
    print("=" * 80)

if __name__ == "__main__":
    test_mexc_api()
