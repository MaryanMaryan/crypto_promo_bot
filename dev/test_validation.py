"""Тест валидации шаблонов URL"""
import sys
import json
from utils.url_template_builder import URLTemplateAnalyzer, get_url_builder

def test_template_validation():
    """Тестирует валидацию шаблона при создании"""

    print("=" * 80)
    print("ТЕСТ ВАЛИДАЦИИ ШАБЛОНОВ")
    print("=" * 80)

    # Пример URL
    example_url = "https://web3.okx.com/ua/boost/x-launch/mylovelyplanet"

    # Пример данных из API (упрощенные)
    api_data = [{
        'id': 371,
        'name': 'My Lovely Planet X Launch',
        'navName': 'mylovelyplanet',
        'homeName': 'My Lovely Planet',
        'participants': 22424,
        'reward': {'amount': 4000000.0, 'chainId': 56, 'token': 'MLC'},
        'status': 2
    }]

    print(f"\nПример URL: {example_url}")
    print(f"API данные: {json.dumps(api_data[0], indent=2, ensure_ascii=False)}")

    # Создаем анализатор
    print("\n" + "=" * 80)
    print("АНАЛИЗ URL И СОЗДАНИЕ ШАБЛОНА")
    print("=" * 80)

    analyzer = URLTemplateAnalyzer(example_url, api_data)
    template = analyzer.analyze()

    if template:
        print("\n✅ УСПЕХ! Шаблон создан и валидирован:")
        print(json.dumps(template, indent=2, ensure_ascii=False))
    else:
        print("\n❌ ОШИБКА! Не удалось создать валидный шаблон")
        return

    # Проверяем генерацию URL с использованием созданного шаблона
    print("\n" + "=" * 80)
    print("ПРОВЕРКА ГЕНЕРАЦИИ URL")
    print("=" * 80)

    builder = get_url_builder()

    # Добавляем шаблон временно
    builder.templates = {'okx': {'boost': template}}

    # Генерируем URL
    test_promo = api_data[0].copy()
    test_promo['exchange'] = 'Okx'

    generated_url = builder.build_url('okx', test_promo)

    print(f"\nСгенерированный URL: {generated_url}")
    print(f"Ожидаемый URL:       {example_url}")

    if generated_url and generated_url.rstrip('/').lower() == example_url.rstrip('/').lower():
        print("\n✅ УСПЕХ! URL совпадает с примером")
        return True
    else:
        print("\n❌ ОШИБКА! URL не совпадает")
        return False

if __name__ == '__main__':
    success = test_template_validation()
    sys.exit(0 if success else 1)
