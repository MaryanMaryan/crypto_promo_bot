#!/usr/bin/env python3
"""Аналіз HTML сторінки MEXC Launchpad для визначення структури даних"""

from bs4 import BeautifulSoup
import json
import re

def analyze_mexc_launchpad(html_path):
    """Аналізує HTML і виводить структуру промоакцій"""

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')

    print("=" * 80)
    print("АНАЛІЗ СТРУКТУРИ MEXC LAUNCHPAD")
    print("=" * 80)

    # Шукаємо JSON дані в скриптах
    scripts = soup.find_all('script')
    print(f"\n[INFO] Знайдено {len(scripts)} script тегів")

    # Шукаємо можливі JSON об'єкти з даними про проекти
    json_patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
        r'window\.__NUXT__\s*=\s*({.*?});',
        r'"launchpad":\s*({.*?})',
        r'"projects":\s*(\[.*?\])',
        r'projectList["\']?\s*:\s*(\[.*?\])',
    ]

    for i, script in enumerate(scripts):
        if script.string:
            script_text = script.string

            # Пошук JSON даних
            for pattern in json_patterns:
                matches = re.findall(pattern, script_text, re.DOTALL)
                if matches:
                    print(f"\n[ЗНАЙДЕНО] Паттерн '{pattern}' в script #{i}")
                    for match in matches[:2]:  # Перші 2 результати
                        try:
                            # Спроба парсити JSON
                            data = json.loads(match)
                            print(f"\n>>> JSON структура (перші 500 символів):")
                            print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
                        except:
                            print(f"\n>>> Сирі дані (перші 500 символів):")
                            print(match[:500])

    # Шукаємо елементи з класами/id що містять 'launch', 'project', 'promo'
    print("\n" + "=" * 80)
    print("СТРУКТУРА DOM ЕЛЕМЕНТІВ")
    print("=" * 80)

    # Шукаємо можливі контейнери
    keywords = ['launch', 'project', 'promo', 'card', 'item', 'list']
    for keyword in keywords:
        # Пошук за class
        elements = soup.find_all(class_=re.compile(keyword, re.I))
        if elements:
            print(f"\n[Клас містить '{keyword}'] Знайдено {len(elements)} елементів")
            if elements:
                elem = elements[0]
                print(f"  Приклад: <{elem.name} class='{elem.get('class')}'")
                # Виводимо структуру
                print(f"  Вміст (перші 200 символів):")
                print(f"  {str(elem)[:200]}")

        # Пошук за id
        elements = soup.find_all(id=re.compile(keyword, re.I))
        if elements:
            print(f"\n[ID містить '{keyword}'] Знайдено {len(elements)} елементів")

    # Шукаємо текстові дані
    print("\n" + "=" * 80)
    print("ТЕКСТОВІ ДАНІ (можливі назви проектів)")
    print("=" * 80)

    # Шукаємо текст що може бути назвами проектів (великі літери, коротки слова)
    texts = soup.find_all(string=re.compile(r'^[A-Z]{2,10}$'))
    if texts:
        print("\n[Можливі тікери токенів]:")
        for text in texts[:20]:  # Перші 20
            print(f"  - {text.strip()}")

    # Шукаємо дати
    date_patterns = [
        r'\d{4}-\d{2}-\d{2}',
        r'\d{2}/\d{2}/\d{4}',
        r'\d{2}\.\d{2}\.\d{4}',
    ]

    print("\n[Можливі дати]:")
    for pattern in date_patterns:
        dates = re.findall(pattern, html)
        if dates:
            print(f"  Формат {pattern}:")
            for date in set(dates[:10]):
                print(f"    - {date}")

    print("\n" + "=" * 80)
    print("АНАЛІЗ ЗАВЕРШЕНО")
    print("=" * 80)

if __name__ == "__main__":
    html_path = r"c:\Users\Мар'ян\Downloads\Launchpad_ Подписывайтесь на новые запуски токенов и получайте криптовалютные вознаграждения _ MEXC.html"
    analyze_mexc_launchpad(html_path)
