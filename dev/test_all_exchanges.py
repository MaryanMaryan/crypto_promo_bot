#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест универсальности решения для всех бирж
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.parser_service import ParserService
from data.database import get_db_session, ApiLink

print('=' * 70)
print('ТЕСТ УНИВЕРСАЛЬНОСТИ РЕШЕНИЯ ДЛЯ ВСЕХ БИРЖ')
print('=' * 70)
print()

service = ParserService()

# Получаем все ссылки из БД
with get_db_session() as db:
    all_links = db.query(ApiLink).filter(ApiLink.is_active == True).all()

    print(f'Найдено активных ссылок: {len(all_links)}')
    print()

    for link in all_links:
        exchange_name = link.name or 'Unknown'
        print(f'\n{"=" * 70}')
        print(f'БИРЖА: {exchange_name}')
        print(f'URL: {link.url[:60]}...' if len(link.url) > 60 else f'URL: {link.url}')
        print(f'{"=" * 70}')

        # Парсим каждую биржу
        new_promos = service.check_for_new_promos(link.id, link.url)

        print(f'\nНовых промоакций: {len(new_promos)}')

        if new_promos:
            print(f'\nСПИСОК:')
            for i, promo in enumerate(new_promos[:3], 1):
                promo_id = promo.get('promo_id', 'N/A')
                is_fallback = '_fallback_' in promo_id

                print(f'{i}. {promo.get("title", "Без названия")}')
                print(f'   ID: {promo_id} {"[FALLBACK]" if is_fallback else "[REAL]"}')
                print(f'   Prize: {promo.get("total_prize_pool", "N/A")}')
                print(f'   Token: {promo.get("award_token", "N/A")}')
                print(f'   Link: {"Да" if promo.get("link") else "Нет"}')
                print()

# Итоговая статистика
print('\n' + '=' * 70)
print('ИТОГОВАЯ СТАТИСТИКА ПО ВСЕМ БИРЖАМ')
print('=' * 70)
stats = service.get_stats()
print(f'Всего проверок: {stats["total_checks"]}')
print(f'Успешных проверок: {stats["successful_checks"]}')
print(f'Новых промо найдено: {stats["new_promos_found"]}')
print(f'Fallback ОТКЛОНЕНО: {stats["fallback_rejected"]}')
print(f'Fallback ПРИНЯТО: {stats["fallback_accepted"]}')
print()

# Вывод
if stats["fallback_rejected"] > 0 and stats["fallback_accepted"] == 0:
    print('✓ УСПЕХ: Решение универсально! Все фейковые fallback отклонены.')
elif stats["fallback_accepted"] > 0:
    print(f'⚠ ЧАСТИЧНЫЙ УСПЕХ: {stats["fallback_accepted"]} fallback промо прошли валидацию')
    print('  (это качественные fallback с достаточным количеством данных)')
else:
    print('ℹ INFO: Не было fallback промо для проверки')

if stats["new_promos_found"] > 0:
    print(f'\n✓ Реальные промо: {stats["new_promos_found"]} новых промоакций сохранено')
