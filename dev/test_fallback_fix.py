#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест исправления фейковых fallback уведомлений
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.parser_service import ParserService

print('=' * 60)
print('ТЕСТ ПАРСИНГА OKX (источник fallback промо)')
print('=' * 60)
print()

service = ParserService()

# Парсим OKX (ID=6)
print('Запуск парсинга OKX...')
print()
new_promos = service.check_for_new_promos(6, 'https://web3.okx.com/priapi/v1/dapp/boost/launchpool/list')

print()
print('=' * 60)
print('РЕЗУЛЬТАТ')
print('=' * 60)
print(f'Новых промоакций найдено: {len(new_promos)}')
print()

if new_promos:
    print('СПИСОК НОВЫХ ПРОМО:')
    for i, promo in enumerate(new_promos[:5], 1):
        print(f'\n{i}. {promo.get("title", "Без названия")}')
        print(f'   ID: {promo.get("promo_id")}')
        print(f'   Prize: {promo.get("total_prize_pool", "N/A")}')
        print(f'   Token: {promo.get("award_token", "N/A")}')
        print(f'   Link: {promo.get("link", "N/A")[:60]}...' if promo.get("link") else '   Link: N/A')
else:
    print('НЕТ новых промоакций (фейки отфильтрованы!)')

# Показываем статистику
print()
print('=' * 60)
print('СТАТИСТИКА')
print('=' * 60)
stats = service.get_stats()
print(f'Всего проверок: {stats["total_checks"]}')
print(f'Новых промо: {stats["new_promos_found"]}')
print(f'Fallback отклонено: {stats["fallback_rejected"]}')
print(f'Fallback принято: {stats["fallback_accepted"]}')
print()

if stats["fallback_rejected"] > 0:
    print('SUCCESS: Фейковые fallback промо были отклонены!')
else:
    print('WARNING: Не было fallback промо для проверки')
