"""Тест валидации шаблонов URL (без эмоджи)"""
import sys
import json
from utils.url_template_builder import URLTemplateAnalyzer, get_url_builder

def test_template_validation():
    """Тестирует валидацию шаблона при создании"""

    output = []
    output.append("=" * 80)
    output.append("ТЕСТ ВАЛИДАЦИИ ШАБЛОНОВ")
    output.append("=" * 80)

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

    output.append(f"\nПример URL: {example_url}")
    output.append(f"API данные: {json.dumps(api_data[0], indent=2, ensure_ascii=False)}")

    # Создаем анализатор
    output.append("\n" + "=" * 80)
    output.append("АНАЛИЗ URL И СОЗДАНИЕ ШАБЛОНА")
    output.append("=" * 80)

    analyzer = URLTemplateAnalyzer(example_url, api_data)
    template = analyzer.analyze()

    if template:
        output.append("\n[УСПЕХ] Шаблон создан и валидирован:")
        output.append(json.dumps(template, indent=2, ensure_ascii=False))
    else:
        output.append("\n[ОШИБКА] Не удалось создать валидный шаблон")
        print("\n".join(output))
        return False

    # Проверяем генерацию URL с использованием созданного шаблона
    output.append("\n" + "=" * 80)
    output.append("ПРОВЕРКА ГЕНЕРАЦИИ URL")
    output.append("=" * 80)

    builder = get_url_builder()

    # Добавляем шаблон временно
    builder.templates = {'okx': {'boost': template}}

    # Генерируем URL
    test_promo = api_data[0].copy()
    test_promo['exchange'] = 'Okx'

    generated_url = builder.build_url('okx', test_promo)

    output.append(f"\nСгенерированный URL: {generated_url}")
    output.append(f"Ожидаемый URL:       {example_url}")

    if generated_url and generated_url.rstrip('/').lower() == example_url.rstrip('/').lower():
        output.append("\n[УСПЕХ] URL совпадает с примером")
        output.append("\n" + "=" * 80)
        output.append("ИТОГ: ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
        output.append("=" * 80)
        print("\n".join(output))
        return True
    else:
        output.append("\n[ОШИБКА] URL не совпадает")
        print("\n".join(output))
        return False

if __name__ == '__main__':
    success = test_template_validation()
    sys.exit(0 if success else 1)
