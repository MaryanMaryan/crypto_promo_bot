#!/usr/bin/env python3
"""Детальний аналіз карточок MEXC Launchpad"""

from bs4 import BeautifulSoup
import json

def analyze_cards(html_path):
    """Детально аналізує карточки проектів"""

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')

    print("=" * 80)
    print("ДЕТАЛЬНИЙ АНАЛІЗ КАРТОЧОК MEXC LAUNCHPAD")
    print("=" * 80)

    # Знаходимо всі карточки проектів
    cards = soup.find_all('a', class_=lambda x: x and 'card-activity' in str(x))

    print(f"\n[INFO] Знайдено {len(cards)} карточок проектів\n")

    for i, card in enumerate(cards[:5], 1):  # Перші 5 карточок для аналізу
        print(f"\n{'=' * 80}")
        print(f"КАРТОЧКА #{i}")
        print('=' * 80)

        # URL проекту
        url = card.get('href', '')
        print(f"\n[URL]: {url}")

        # Шукаємо всі текстові елементи в карточці
        print(f"\n[ТЕКСТ В КАРТОЧЦІ]:")
        texts = [t.strip() for t in card.stripped_strings if t.strip()]
        for j, text in enumerate(texts, 1):
            print(f"  {j}. {text}")

        # Шукаємо зображення
        images = card.find_all('img')
        if images:
            print(f"\n[ЗОБРАЖЕННЯ]:")
            for img in images:
                alt = img.get('alt', '')
                src = img.get('src', '')[:100]
                print(f"  - alt: {alt}")
                print(f"    src: {src}...")

        # Шукаємо всі div елементи з класами
        print(f"\n[СТРУКТУРА КЛАСІВ]:")
        divs = card.find_all('div', class_=True)
        classes_used = set()
        for div in divs:
            classes = div.get('class', [])
            for cls in classes:
                if cls not in classes_used:
                    classes_used.add(cls)
                    # Виводимо клас і перший текст в ньому
                    text = div.get_text(strip=True)[:50]
                    if text:
                        print(f"  • {cls}: '{text}...'")

        # Шукаємо span елементи
        spans = card.find_all('span')
        if spans:
            print(f"\n[SPAN ЕЛЕМЕНТИ]:")
            for span in spans:
                span_class = span.get('class', [])
                span_text = span.get_text(strip=True)
                if span_text:
                    print(f"  • [{', '.join(span_class)}]: {span_text}")

        # Виводимо повну HTML структуру першої карточки
        if i == 1:
            print(f"\n[ПОВНА HTML СТРУКТУРА ПЕРШОЇ КАРТОЧКИ]:")
            print(card.prettify()[:2000])

    # Шукаємо розділи/категорії
    print(f"\n\n{'=' * 80}")
    print("РОЗДІЛИ/КАТЕГОРІЇ")
    print('=' * 80)

    titles = soup.find_all(['h1', 'h2', 'h3', 'h4'])
    for title in titles:
        title_text = title.get_text(strip=True)
        if title_text:
            print(f"  {title.name.upper()}: {title_text}")

    # Шукаємо всі можливі статуси
    print(f"\n\n{'=' * 80}")
    print("МОЖЛИВІ СТАТУСИ/МІТКИ")
    print('=' * 80)

    # Типові слова для статусів
    status_keywords = ['ongoing', 'ended', 'upcoming', 'live', 'closed', 'open',
                       'активний', 'завершен', 'скоро', 'идет', 'закрыт', 'открыт']

    for keyword in status_keywords:
        elements = soup.find_all(string=lambda text: text and keyword.lower() in text.lower())
        if elements:
            print(f"\n  Знайдено '{keyword}':")
            for elem in elements[:3]:
                print(f"    - {elem.strip()[:100]}")

if __name__ == "__main__":
    html_path = r"c:\Users\Мар'ян\Downloads\Launchpad_ Подписывайтесь на новые запуски токенов и получайте криптовалютные вознаграждения _ MEXC.html"
    analyze_cards(html_path)
