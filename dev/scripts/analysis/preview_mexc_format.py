#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Превью форматування MEXC Launchpad"""

import sys
import io

# Фікс кодування для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def format_mexc_launchpad_promo(promo_data: dict) -> str:
    """
    Форматує MEXC Launchpad промоакцію для відображення в Telegram

    Приклад структури з API:
    {
        "activityCoin": "SKR",
        "activityCoinFullName": "Seeker",
        "activityStatus": "UNDERWAY",
        "totalSupply": "3000000",
        "startTime": 1768788000000,
        "endTime": 1768960800000,
        "launchpadTakingCoins": [
            {
                "investCurrency": "USDT",
                "takingPrice": "0.005",
                "label": "70% Off",
                "supply": "2000000",
                "takingAmount": "73835.79",
                "joinNum": 38,
                "linePrice": "0.015",
                "onlyForNewUser": true
            }
        ]
    }
    """
    from datetime import datetime

    message = ""

    # === ЗАГОЛОВОК ===
    token = promo_data.get('activityCoin', 'Unknown')
    full_name = promo_data.get('activityCoinFullName', token)

    if full_name and full_name != token:
        message += f"🚀 <b>{full_name} ({token})</b>\n"
    else:
        message += f"🚀 <b>{token}</b>\n"

    # === СТАТУС ===
    status = promo_data.get('activityStatus', 'UNKNOWN')
    status_emoji = {
        'UNDERWAY': '✅ Активна',
        'ONGOING': '✅ Активна',
        'NOT_STARTED': '🔜 Скоро',
        'FINISHED': '⏹ Завершена',
        'SETTLED': '⏹ Завершена',
        'CANCELLED': '❌ Отменена'
    }
    message += f"📊 <b>Статус:</b> {status_emoji.get(status, '❓ ' + status)}\n"

    # === ЗАГАЛЬНИЙ SUPPLY ===
    total_supply = promo_data.get('totalSupply')
    if total_supply:
        try:
            supply_num = float(total_supply)
            message += f"📦 <b>Всего токенов:</b> {supply_num:,.0f} {token}\n"
        except:
            message += f"📦 <b>Всего токенов:</b> {total_supply} {token}\n"

    message += "\n"

    # === ВАРИАНТЫ ПОДПИСКИ ===
    taking_coins = promo_data.get('launchpadTakingCoins', [])

    if len(taking_coins) > 1:
        message += f"💰 <b>ВАРИАНТЫ ПОДПИСКИ ({len(taking_coins)}):</b>\n\n"
    elif len(taking_coins) == 1:
        message += f"💰 <b>ПОДПИСКА:</b>\n\n"

    for idx, tc in enumerate(taking_coins, 1):
        invest_currency = tc.get('investCurrency', 'USDT')
        taking_price = tc.get('takingPrice', '0')
        label = tc.get('label', '')
        supply = tc.get('supply', '0')
        taking_amount = tc.get('takingAmount', '0')
        join_num = tc.get('joinNum', 0)
        line_price = tc.get('linePrice')
        only_new_user = tc.get('onlyForNewUser', False)

        # Если несколько вариантов - нумеруем
        if len(taking_coins) > 1:
            message += f"<b>Вариант {idx}:</b> {invest_currency}"
            if only_new_user:
                message += " 🆕 <i>(только новые пользователи)</i>"
            message += "\n"
        else:
            message += f"<b>Валюта:</b> {invest_currency}"
            if only_new_user:
                message += " 🆕 <i>(только новые пользователи)</i>"
            message += "\n"

        # Цена подписки
        message += f"   • <b>Цена подписки:</b> 1 {token} = {taking_price} {invest_currency}\n"

        # Знижка
        if label:
            message += f"   • <b>Скидка:</b> {label} 🔥\n"

        # Рыночная цена (для сравнения)
        if line_price:
            try:
                market = float(line_price)
                current = float(taking_price)
                savings = market - current
                savings_percent = (savings / market) * 100 if market > 0 else 0
                message += f"   • <b>Рыночная цена:</b> {line_price} {invest_currency} "
                message += f"<i>(экономия {savings_percent:.0f}%)</i>\n"
            except:
                message += f"   • <b>Рыночная цена:</b> {line_price} {invest_currency}\n"

        # Доступно токенов
        try:
            supply_num = float(supply)
            message += f"   • <b>Доступно токенов:</b> {supply_num:,.0f} {token}\n"
        except:
            message += f"   • <b>Доступно токенов:</b> {supply} {token}\n"

        # Собрано средств
        try:
            amount_num = float(taking_amount)
            if amount_num > 0:
                message += f"   • <b>Собрано:</b> {amount_num:,.2f} {invest_currency}\n"
        except:
            pass

        # Участники
        if join_num:
            message += f"   • <b>Участников:</b> {join_num:,}\n"

        # Разделитель между вариантами
        if idx < len(taking_coins):
            message += "\n"

    # === ПЕРИОД АКЦИИ ===
    start_time = promo_data.get('startTime')
    end_time = promo_data.get('endTime')

    if start_time or end_time:
        message += "\n⏰ <b>ПЕРИОД АКЦИИ:</b>\n"

        if start_time:
            try:
                start_dt = datetime.fromtimestamp(start_time / 1000)
                message += f"   • Начало: {start_dt.strftime('%d.%m.%Y %H:%M')}\n"
            except:
                pass

        if end_time:
            try:
                end_dt = datetime.fromtimestamp(end_time / 1000)
                message += f"   • Конец: {end_dt.strftime('%d.%m.%Y %H:%M')}\n"

                # Оставшееся время
                if status in ['UNDERWAY', 'ONGOING']:
                    now = datetime.now()
                    if end_dt > now:
                        remaining = end_dt - now
                        days = remaining.days
                        hours = remaining.seconds // 3600

                        if days > 0:
                            message += f"   • Осталось: {days} дн. {hours} ч.\n"
                        else:
                            minutes = (remaining.seconds % 3600) // 60
                            message += f"   • Осталось: {hours} ч. {minutes} мин.\n"
            except:
                pass

    # === ДОПОЛНИТЕЛЬНЫЕ ССЫЛКИ ===
    official_url = promo_data.get('officialUrl', '')
    twitter_url = promo_data.get('twitterUrl', '')
    launchpad_id = promo_data.get('launchpadId', '')

    if official_url or twitter_url or launchpad_id:
        message += "\n🔗 <b>ССЫЛКИ:</b>\n"

        if launchpad_id:
            # Основна ссылка на проект в MEXC Launchpad
            message += f"   • <a href='https://www.mexc.com/ru-RU/launchpad/{launchpad_id}'>Страница проекта на MEXC</a>\n"

        if official_url:
            message += f"   • <a href='{official_url}'>Официальный сайт</a>\n"

        if twitter_url:
            message += f"   • <a href='{twitter_url}'>Twitter</a>\n"

    return message


# === ТЕСТОВЫЕ ДАННЫЕ ===

# Пример 1: SKR с двумя вариантами подписки
test_data_1 = {
    "id": 44,
    "launchpadId": "6969ef1ae4b0a024438b72a1",
    "activityCoin": "SKR",
    "activityCoinFullName": "Seeker",
    "activityStatus": "UNDERWAY",
    "totalSupply": "3000000",
    "startTime": 1768788000000,
    "endTime": 1768960800000,
    "officialUrl": "https://solanamobile.com/",
    "twitterUrl": "https://x.com/solanamobile",
    "launchpadTakingCoins": [
        {
            "investCurrency": "USDT",
            "takingPrice": "0.005",
            "label": "70% Off",
            "supply": "2000000",
            "takingAmount": "73835.79",
            "joinNum": 38,
            "linePrice": "0.015",
            "onlyForNewUser": True
        },
        {
            "investCurrency": "USD1",
            "takingPrice": "0.0075",
            "label": "50% Off",
            "supply": "1000000",
            "takingAmount": "144909.43",
            "joinNum": 70,
            "linePrice": "0.015",
            "onlyForNewUser": False
        }
    ]
}

# Пример 2: LIT с одним вариантом
test_data_2 = {
    "id": 42,
    "launchpadId": "694ab635e4b01e2fce5f9009",
    "activityCoin": "LIT",
    "activityCoinFullName": "Lighter",
    "activityStatus": "FINISHED",
    "totalSupply": "17500",
    "startTime": 1766577600000,
    "endTime": 1767175200000,
    "officialUrl": "https://lighter.xyz/",
    "twitterUrl": "https://x.com/lighter_xyz",
    "launchpadTakingCoins": [
        {
            "investCurrency": "USDT",
            "takingPrice": "1.6",
            "label": "60% Off",
            "supply": "12500",
            "takingAmount": "1030485.64",
            "joinNum": 529,
            "linePrice": "4.0",
            "onlyForNewUser": True
        }
    ]
}


if __name__ == "__main__":
    print("=" * 80)
    print("ПРЕВЬЮ ФОРМАТУВАННЯ MEXC LAUNCHPAD")
    print("=" * 80)
    print()

    print("=" * 80)
    print("ПРИКЛАД 1: Проект з ДВОМА варіантами підписки (USDT + USD1)")
    print("=" * 80)
    print()
    print(format_mexc_launchpad_promo(test_data_1))
    print()

    print("=" * 80)
    print("ПРИКЛАД 2: Завершений проект з ОДНИМ варіантом підписки")
    print("=" * 80)
    print()
    print(format_mexc_launchpad_promo(test_data_2))
    print()

    print("=" * 80)
    print("ПРИМІТКИ:")
    print("=" * 80)
    print()
    print("1. HTML теги (<b>, <a>) будуть відображатись в Telegram як форматування")
    print("2. Емодзі додають візуальну привабливість")
    print("3. Структура чітка і легко читається")
    print("4. Всі важливі дані присутні: ціни, знижки, учасники, терміни")
    print("5. Підтримка декількох варіантів підписки (USDT/USD1/інші)")
    print()
