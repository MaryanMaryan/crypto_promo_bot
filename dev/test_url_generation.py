"""Тест генерации URL для промоакций"""
import sys
import json
from utils.url_template_builder import get_url_builder
from parsers.universal_parser import UniversalParser

def test_okx_url_generation():
    """Тестирует генерацию URL для OKX"""

    # Пример промоакции из API OKX
    test_promo = {
        'promo_id': 'okx_test_123',
        'exchange': 'Okx',
        'title': 'My Lovely Planet X Launch',
        'description': 'Test promo',
        'award_token': 'MLC',
        'total_prize_pool': '4000000 MLC'
    }

    print("=" * 80)
    print("ТЕСТ ГЕНЕРАЦИИ URL ДЛЯ OKX")
    print("=" * 80)
    print(f"\nТестовая промоакция:")
    print(json.dumps(test_promo, indent=2, ensure_ascii=False))

    # Получаем builder
    url_builder = get_url_builder()

    # Проверяем шаблоны
    print(f"\n{'='*80}")
    print("Загруженные шаблоны:")
    print(json.dumps(url_builder.templates, indent=2, ensure_ascii=False))

    # Пробуем сгенерировать URL
    print(f"\n{'='*80}")
    print("Генерация URL...")

    # Тест 1: С заглавной буквы
    print(f"\n1. Попытка с 'Okx' (как возвращает _extract_domain_name):")
    url1 = url_builder.build_url('Okx', test_promo)
    print(f"   Результат: {url1 or 'FAILED'}")

    # Тест 2: Со строчной буквы
    print(f"\n2. Попытка с 'okx' (lowercase):")
    url2 = url_builder.build_url('okx', test_promo)
    print(f"   Результат: {url2 or 'FAILED'}")

    # Проверяем шаблон info
    print(f"\n{'='*80}")
    print("Информация о шаблонах для OKX:")
    info = url_builder.get_template_info('okx')
    print(json.dumps(info, indent=2, ensure_ascii=False))

    # Тест полного цикла через UniversalParser
    print(f"\n{'='*80}")
    print("ТЕСТ ПОЛНОГО ЦИКЛА ЧЕРЕЗ UniversalParser")
    print("=" * 80)

    api_url = "https://web3.okx.com/priapi/v1/dapp/boost/launchpool/list"
    print(f"\nAPI URL: {api_url}")

    parser = UniversalParser(api_url)
    exchange_name = parser._extract_domain_name(api_url)
    print(f"Exchange name (из _extract_domain_name): {exchange_name}")

    # Проверяем генерацию в парсере
    promo_data = {
        'exchange': exchange_name,
        'promo_id': 'okx_test_456',
        'title': 'Test Promo 2',
        'award_token': 'TEST'
    }

    print(f"\nПопытка генерации через _create_promo_from_object:")
    # Имитируем логику из _create_promo_from_object
    if not promo_data.get('link'):
        try:
            generated_link = url_builder.build_url(exchange_name, promo_data)
            if generated_link:
                promo_data['link'] = generated_link
                print(f"✅ Ссылка сгенерирована: {generated_link}")
            else:
                print(f"⚠️ Не удалось сгенерировать ссылку для {exchange_name}")
        except Exception as e:
            print(f"❌ Ошибка генерации: {e}")

    print(f"\n{'='*80}")
    print("РЕЗУЛЬТАТЫ:")
    print(f"URL 1 (Okx): {url1 or 'НЕ СГЕНЕРИРОВАН'}")
    print(f"URL 2 (okx): {url2 or 'НЕ СГЕНЕРИРОВАН'}")
    print(f"URL через парсер: {promo_data.get('link', 'НЕ СГЕНЕРИРОВАН')}")
    print("=" * 80)

if __name__ == '__main__':
    test_okx_url_generation()
