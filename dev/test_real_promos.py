#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест что реальные промоакции проходят валидацию
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.parser_service import ParserService

print('=' * 70)
print('ТЕСТ: РЕАЛЬНЫЕ ПРОМОАКЦИИ ПРОХОДЯТ ВАЛИДАЦИЮ')
print('=' * 70)
print()

service = ParserService()

# Тестируем Bybit - источник реальных промо
print('Проверка Bybit (источник реальных промоакций)...')
print()

bybit_url = 'https://www.bybit.com/x-api/spot/api/deposit-activity/v2/promotion-list'
new_promos = service.check_for_new_promos(3, bybit_url)

print('=' * 70)
print('РЕЗУЛЬТАТ')
print('=' * 70)
print(f'Новых промоакций: {len(new_promos)}')
print()

if new_promos:
    print('РЕАЛЬНЫЕ ПРОМОАКЦИИ:')
    for i, promo in enumerate(new_promos[:5], 1):
        promo_id = promo.get('promo_id', 'N/A')
        is_fallback = '_fallback_' in promo_id or '_html_' in promo_id

        print(f'\n{i}. {promo.get("title", "Без названия")}')
        print(f'   ID: {promo_id}')
        print(f'   Тип: {"FALLBACK (но с данными)" if is_fallback else "РЕАЛЬНЫЙ API ID"}')
        print(f'   Prize: {promo.get("total_prize_pool", "N/A")}')
        print(f'   Token: {promo.get("award_token", "N/A")}')
        print(f'   Participants: {promo.get("participants_count", "N/A")}')
        link = promo.get("link", "")
        print(f'   Link: {link[:60]}...' if len(link) > 60 else f'   Link: {link if link else "N/A"}')

print()
print('=' * 70)
print('СТАТИСТИКА')
print('=' * 70)
stats = service.get_stats()
print(f'Новых промо: {stats["new_promos_found"]}')
print(f'Fallback отклонено: {stats["fallback_rejected"]}')
print(f'Fallback принято: {stats["fallback_accepted"]}')
print()

if stats["new_promos_found"] > 0:
    print('SUCCESS: Реальные промоакции проходят валидацию!')
    if stats["fallback_accepted"] > 0:
        print(f'INFO: {stats["fallback_accepted"]} fallback промо прошли (имеют достаточно данных)')
else:
    print('INFO: Нет новых промоакций (возможно все уже в базе)')
