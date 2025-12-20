#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки работы парсеров
"""
import logging
import sys
import io

# Фикс кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

from parsers.universal_fallback_parser import UniversalFallbackParser

def test_parser(exchange_name, url):
    """Тестирование парсера для одной биржи"""
    print(f"\n{'='*80}")
    print(f"ТЕСТИРОВАНИЕ: {exchange_name}")
    print(f"URL: {url}")
    print(f"{'='*80}\n")

    try:
        parser = UniversalFallbackParser(url)
        promotions = parser.get_promotions()

        print(f"\n{'='*80}")
        print(f"РЕЗУЛЬТАТ для {exchange_name}:")
        print(f"  Найдено промоакций: {len(promotions)}")

        if promotions:
            print(f"\n  Первые 3 промоакции:")
            for i, promo in enumerate(promotions[:3], 1):
                print(f"    {i}. {promo.get('title', 'Без названия')}")
                print(f"       ID: {promo.get('promo_id', 'N/A')}")
                print(f"       Биржа: {promo.get('exchange', 'N/A')}")
                print(f"       Источник: {promo.get('data_source', 'N/A')}")
        else:
            print(f"  ❌ Промоакции не найдены")

        print(f"{'='*80}\n")
        return len(promotions)

    except Exception as e:
        print(f"\n❌ ОШИБКА при тестировании {exchange_name}: {e}\n")
        import traceback
        traceback.print_exc()
        return 0

def main():
    """Основная функция тестирования"""
    print("\n" + "="*80)
    print("ЗАПУСК ТЕСТОВ ПАРСЕРОВ")
    print("="*80 + "\n")

    # Тестовые URL (API endpoints для корректной работы)
    test_cases = [
        ("Bybit TokenSplash API", "https://www.bybit.com/x-api/spot/api/deposit-activity/v2/project/ongoing/projectList"),
        ("MEXC Launchpad", "https://www.mexc.com/api/financialactivity/launchpad/list"),
        ("MEXC Airdrop", "https://www.mexc.com/api/operateactivity/eftd/list"),
    ]

    results = {}

    for exchange_name, url in test_cases:
        count = test_parser(exchange_name, url)
        results[exchange_name] = count

    # Итоговая статистика
    print("\n" + "="*80)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("="*80)

    total_promos = 0
    for exchange_name, count in results.items():
        status = "✅" if count > 0 else "❌"
        print(f"{status} {exchange_name}: {count} промоакций")
        total_promos += count

    print(f"\nВсего найдено промоакций: {total_promos}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
