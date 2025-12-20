#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для анализа структуры извлеченных данных
"""
import logging
import sys
import io
import json

# Фикс кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.WARNING,  # Только предупреждения и ошибки
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

from parsers.universal_fallback_parser import UniversalFallbackParser

def analyze_promotions(exchange_name, url, limit=3):
    """Анализ структуры промоакций"""
    print(f"\n{'='*80}")
    print(f"АНАЛИЗ СТРУКТУРЫ: {exchange_name}")
    print(f"URL: {url}")
    print(f"{'='*80}\n")

    try:
        parser = UniversalFallbackParser(url)
        promotions = parser.get_promotions()

        if not promotions:
            print(f"❌ Промоакции не найдены\n")
            return

        print(f"✅ Найдено промоакций: {len(promotions)}")
        print(f"\nПоказываю первые {min(limit, len(promotions))} промоакции:\n")

        for i, promo in enumerate(promotions[:limit], 1):
            print(f"\n{'─'*80}")
            print(f"ПРОМОАКЦИЯ #{i}")
            print(f"{'─'*80}")

            # Выводим все поля кроме raw_data
            for key, value in promo.items():
                if key == 'raw_data':
                    print(f"\n📦 raw_data (исходные данные из API):")
                    # Показываем только первые 5 полей из raw_data
                    if isinstance(value, dict):
                        count = 0
                        for raw_key, raw_value in value.items():
                            if count >= 5:
                                print(f"   ... еще {len(value) - 5} полей")
                                break
                            # Обрезаем длинные значения
                            if isinstance(raw_value, str) and len(raw_value) > 50:
                                raw_value = raw_value[:50] + "..."
                            print(f"   {raw_key}: {raw_value}")
                            count += 1
                else:
                    # Обрезаем длинные строки
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    print(f"{key}: {value}")

        # Показываем какие поля есть у всех промоакций
        print(f"\n{'='*80}")
        print(f"СТАТИСТИКА ПОЛЕЙ для {exchange_name}")
        print(f"{'='*80}\n")

        field_counts = {}
        for promo in promotions:
            for key in promo.keys():
                if key not in ['raw_data', 'data_source', 'source_url']:
                    field_counts[key] = field_counts.get(key, 0) + 1

        print(f"Всего промоакций: {len(promotions)}\n")
        print("Поле → Заполнено в:")
        for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
            percentage = (count / len(promotions)) * 100
            print(f"  {field:20} → {count:4}/{len(promotions)} ({percentage:.1f}%)")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}\n")
        import traceback
        traceback.print_exc()

def main():
    """Основная функция"""
    print("\n" + "="*80)
    print("АНАЛИЗ СТРУКТУРЫ ИЗВЛЕЧЕННЫХ ДАННЫХ")
    print("="*80 + "\n")

    # Анализируем данные из разных источников
    test_cases = [
        ("Bybit TokenSplash", "https://www.bybit.com/x-api/spot/api/deposit-activity/v2/project/ongoing/projectList"),
        ("MEXC Launchpad", "https://www.mexc.com/api/financialactivity/launchpad/list"),
        ("MEXC Airdrop (только 2 примера)", "https://www.mexc.com/api/operateactivity/eftd/list"),
    ]

    for exchange_name, url in test_cases:
        # Для MEXC Airdrop показываем только 2 примера из-за большого количества
        limit = 2 if "Airdrop" in exchange_name else 3
        analyze_promotions(exchange_name, url, limit=limit)

    print("\n" + "="*80)
    print("АНАЛИЗ ЗАВЕРШЕН")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
