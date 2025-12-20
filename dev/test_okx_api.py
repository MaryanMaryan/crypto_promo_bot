"""Тест реального API OKX для проверки данных"""
import sys
import json
from parsers.universal_parser import UniversalParser

def test_okx_api():
    """Парсит реальное API OKX и показывает данные"""

    api_url = "https://web3.okx.com/priapi/v1/dapp/boost/launchpool/list"
    print("=" * 80)
    print(f"ПАРСИНГ API: {api_url}")
    print("=" * 80)

    parser = UniversalParser(api_url)
    promotions = parser.get_promotions()

    if not promotions:
        print("\nПромоакции не найдены!")
        return

    print(f"\nНайдено {len(promotions)} промоакций\n")
    print("=" * 80)

    # Показываем первые 3 промоакции в деталях
    for i, promo in enumerate(promotions[:3], 1):
        print(f"\nПРОМОАКЦИЯ #{i}:")
        print("-" * 80)
        print(f"Promo ID: {promo.get('promo_id')}")
        print(f"Exchange: {promo.get('exchange')}")
        print(f"Title: {promo.get('title')}")
        print(f"Description: {promo.get('description', '')[:100]}...")
        print(f"Award Token: {promo.get('award_token')}")
        print(f"Total Prize Pool: {promo.get('total_prize_pool')}")
        print(f"Link: {promo.get('link', 'НЕТ ССЫЛКИ')}")
        print(f"Icon: {promo.get('icon', '')}")

        # Показываем raw_data для понимания структуры API
        if 'raw_data' in promo:
            print(f"\nRAW DATA (первые 500 символов):")
            raw_str = json.dumps(promo['raw_data'], indent=2, ensure_ascii=False)
            print(raw_str[:500])
            print("...")

    print("\n" + "=" * 80)
    print("АНАЛИЗ:")
    print("=" * 80)
    print(f"\nСсылки сгенерированы: {sum(1 for p in promotions if p.get('link'))}/{len(promotions)}")

    # Проверяем какие поля есть в raw_data первой промоакции
    if promotions and 'raw_data' in promotions[0]:
        print("\nДоступные поля в raw_data первой промоакции:")
        for key in promotions[0]['raw_data'].keys():
            value = promotions[0]['raw_data'][key]
            value_type = type(value).__name__
            value_preview = str(value)[:50] if value else 'None'
            print(f"  - {key}: ({value_type}) {value_preview}")

if __name__ == '__main__':
    test_okx_api()
