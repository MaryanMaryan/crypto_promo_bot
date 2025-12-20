"""
Тест playwright-stealth на обход детекции автоматизации
Проверяет сайты MEXC и Bybit на детекцию бота
"""

import logging
from parsers.browser_parser import BrowserParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

logger = logging.getLogger(__name__)

def test_stealth_mexc():
    """Тест на MEXC launchpad"""
    print("\n" + "="*80)
    print("ТЕСТ 1: MEXC Launchpad (HTML парсинг)")
    print("="*80 + "\n")

    url = "https://www.mexc.com/launchpad"
    parser = BrowserParser(url)

    promotions = parser.get_promotions()

    print(f"\n✅ Результат: Найдено {len(promotions)} промоакций")

    if promotions:
        print("\n[FOUND] Найденные промоакции:")
        for i, promo in enumerate(promotions[:3], 1):
            print(f"  {i}. {promo.get('title', 'Без названия')}")
            if promo.get('link'):
                print(f"     Ссылка: {promo['link']}")
    else:
        print("\n[WARNING] Промоакции не найдены (возможно капча)")

    return len(promotions) > 0

def test_stealth_bybit():
    """Тест на Bybit token-splash"""
    print("\n" + "="*80)
    print("ТЕСТ 2: Bybit Token Splash (HTML парсинг)")
    print("="*80 + "\n")

    url = "https://www.bybit.com/trade/spot/token-splash"
    parser = BrowserParser(url)

    promotions = parser.get_promotions()

    print(f"\n✅ Результат: Найдено {len(promotions)} промоакций")

    if promotions:
        print("\n[FOUND] Найденные промоакции:")
        for i, promo in enumerate(promotions[:3], 1):
            print(f"  {i}. {promo.get('title', 'Без названия')}")
            if promo.get('link'):
                print(f"     Ссылка: {promo['link']}")
    else:
        print("\n[WARNING] Промоакции не найдены (возможно капча)")

    return len(promotions) > 0

def main():
    print("\n" + "="*80)
    print("ТЕСТИРОВАНИЕ PLAYWRIGHT-STEALTH")
    print("Проверка обхода детекции автоматизации на реальных сайтах")
    print("="*80)

    results = {}

    # Тест MEXC
    try:
        results['mexc'] = test_stealth_mexc()
    except Exception as e:
        logger.error(f"❌ Ошибка при тесте MEXC: {e}")
        results['mexc'] = False

    # Тест Bybit
    try:
        results['bybit'] = test_stealth_bybit()
    except Exception as e:
        logger.error(f"❌ Ошибка при тесте Bybit: {e}")
        results['bybit'] = False

    # Итоги
    print("\n" + "="*80)
    print("[RESULTS] ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
    print("="*80)
    print(f"MEXC:  {'[OK] УСПЕХ' if results.get('mexc') else '[FAIL] ПРОВАЛ (капча обнаружена)'}")
    print(f"Bybit: {'[OK] УСПЕХ' if results.get('bybit') else '[FAIL] ПРОВАЛ (капча обнаружена)'}")
    print("="*80)

    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    print(f"\nОбщая успешность: {success_count}/{total_count} ({success_count/total_count*100:.0f}%)")

    if success_count == total_count:
        print("\n[SUCCESS] Все тесты пройдены! playwright-stealth работает отлично!")
    elif success_count > 0:
        print("\n[WARNING] Частичный успех. Некоторые сайты все еще детектят бота.")
        print("[TIP] Рекомендация: Рассмотрите интеграцию сервиса решения капч (2captcha)")
    else:
        print("\n[FAIL] Все тесты провалены. Капча все еще блокирует.")
        print("[TIP] Рекомендация: Необходима интеграция сервиса решения капч (2captcha, CapSolver)")

if __name__ == "__main__":
    main()
