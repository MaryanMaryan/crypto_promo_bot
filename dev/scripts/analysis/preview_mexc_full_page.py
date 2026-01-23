#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Превью повної сторінки текущих промоакцій MEXC Launchpad"""

import sys
import io
from datetime import datetime, timedelta

# Фікс кодування для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def format_mexc_launchpad_page(promos: list, page: int = 1, total_pages: int = 2) -> str:
    """
    Форматує повну сторінку текущих промоакцій MEXC Launchpad
    Аналогічно до format_current_promos_page в notification_service.py
    """

    # === ЗАГОЛОВОК ===
    message = "🎁 <b>ТЕКУЩИЕ ПРОМОАКЦИИ</b>\n\n"
    message += "<b>🏦 Биржа:</b> MEXC Launchpad\n"

    # Час оновлення
    now = datetime.now()
    message += f"<b>⏱️ Обновлено:</b> {now.strftime('%d.%m.%Y %H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # === ПРОЕКТИ ===
    if not promos:
        message += "📭 <i>Нет активных промоакций</i>\n\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        return message

    for idx, promo in enumerate(promos):
        # ЗАГОЛОВОК ПРОЕКТУ
        token = promo.get('activityCoin', 'Unknown')
        full_name = promo.get('activityCoinFullName', token)

        if full_name and full_name != token:
            message += f"🚀 <b>{full_name} ({token})</b>\n"
        else:
            message += f"🚀 <b>{token}</b>\n"

        # СТАТУС
        status = promo.get('activityStatus', 'UNKNOWN')
        status_emoji = {
            'UNDERWAY': '✅ Активна',
            'ONGOING': '✅ Активна',
            'NOT_STARTED': '🔜 Скоро',
            'FINISHED': '⏹ Завершена',
            'SETTLED': '⏹ Завершена',
            'CANCELLED': '❌ Отменена'
        }
        message += f"<b>📊 Статус:</b> {status_emoji.get(status, '❓ ' + status)}\n"

        # ЗАГАЛЬНИЙ SUPPLY
        total_supply = promo.get('totalSupply')
        if total_supply:
            try:
                supply_num = float(total_supply)
                message += f"<b>📦 Всего токенов:</b> {supply_num:,.0f} {token}\n"
            except:
                message += f"<b>📦 Всего токенов:</b> {total_supply} {token}\n"

        message += "\n"

        # ВАРІАНТИ ПІДПИСКИ
        taking_coins = promo.get('launchpadTakingCoins', [])

        if len(taking_coins) > 1:
            message += f"💰 <b>ВАРИАНТЫ ПОДПИСКИ ({len(taking_coins)}):</b>\n\n"
        elif len(taking_coins) == 1:
            message += f"💰 <b>ПОДПИСКА:</b>\n\n"

        for tc_idx, tc in enumerate(taking_coins, 1):
            invest_currency = tc.get('investCurrency', 'USDT')
            taking_price = tc.get('takingPrice', '0')
            label = tc.get('label', '')
            supply = tc.get('supply', '0')
            taking_amount = tc.get('takingAmount', '0')
            join_num = tc.get('joinNum', 0)
            line_price = tc.get('linePrice')
            only_new_user = tc.get('onlyForNewUser', False)

            # Нумерація варіантів
            if len(taking_coins) > 1:
                message += f"<b>Вариант {tc_idx}:</b> {invest_currency}"
                if only_new_user:
                    message += " 🆕 <i>(только новые пользователи)</i>"
                message += "\n"
            else:
                message += f"<b>Валюта:</b> {invest_currency}"
                if only_new_user:
                    message += " 🆕 <i>(только новые пользователи)</i>"
                message += "\n"

            # Ціна підписки
            message += f"   • <b>Цена подписки:</b> 1 {token} = {taking_price} {invest_currency}\n"

            # Знижка
            if label:
                message += f"   • <b>Скидка:</b> {label} 🔥\n"

            # Ринкова ціна
            if line_price:
                try:
                    market = float(line_price)
                    current = float(taking_price)
                    savings_percent = ((market - current) / market) * 100 if market > 0 else 0
                    message += f"   • <b>Рыночная цена:</b> {line_price} {invest_currency} "
                    message += f"<i>(экономия {savings_percent:.0f}%)</i>\n"
                except:
                    message += f"   • <b>Рыночная цена:</b> {line_price} {invest_currency}\n"

            # Доступно токенів
            try:
                supply_num = float(supply)
                message += f"   • <b>Доступно токенов:</b> {supply_num:,.0f} {token}\n"
            except:
                message += f"   • <b>Доступно токенов:</b> {supply} {token}\n"

            # Зібрано коштів
            try:
                amount_num = float(taking_amount)
                if amount_num > 0:
                    message += f"   • <b>Собрано:</b> {amount_num:,.2f} {invest_currency}\n"
            except:
                pass

            # Учасники
            if join_num:
                message += f"   • <b>Участников:</b> {join_num:,}\n"

            if tc_idx < len(taking_coins):
                message += "\n"

        # ПЕРІОД АКЦІЇ
        start_time = promo.get('startTime')
        end_time = promo.get('endTime')

        if start_time or end_time:
            message += "\n⏰ <b>ПЕРИОД АКЦИИ:</b>\n"

            if start_time and end_time:
                try:
                    start_dt = datetime.fromtimestamp(start_time / 1000)
                    end_dt = datetime.fromtimestamp(end_time / 1000)
                    message += f"   • Период: {start_dt.strftime('%d.%m.%Y %H:%M')} / {end_dt.strftime('%d.%m.%Y %H:%M')}\n"

                    # Залишок часу для активних
                    if status in ['UNDERWAY', 'ONGOING']:
                        now_dt = datetime.now()
                        if end_dt > now_dt:
                            remaining = end_dt - now_dt
                            days = remaining.days
                            hours = remaining.seconds // 3600

                            if days > 0:
                                message += f"   • Осталось: {days} дн. {hours} ч.\n"
                            else:
                                minutes = (remaining.seconds % 3600) // 60
                                message += f"   • Осталось: {hours} ч. {minutes} мин.\n"
                except:
                    pass

        # ПОСИЛАННЯ
        launchpad_id = promo.get('launchpadId', '')
        if launchpad_id:
            message += f"\n🔗 https://www.mexc.com/ru-RU/launchpad/{launchpad_id}\n"

        # РОЗДІЛЮВАЧ між проектами
        if idx < len(promos) - 1:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        else:
            message += "\n"

    # === ФУТЕР ===
    message += "\n<b>🔗 Страница акций:</b> https://www.mexc.com/ru-RU/launchpad\n"

    # Пагінація
    if total_pages > 1:
        message += f"\n<i>📄 Страница {page} из {total_pages}</i>"

    return message


# === ТЕСТОВІ ДАНІ (3 проекти) ===

# Активний проект з 2 варіантами підписки
promo1 = {
    "launchpadId": "6969ef1ae4b0a024438b72a1",
    "activityCoin": "SKR",
    "activityCoinFullName": "Seeker",
    "activityStatus": "UNDERWAY",
    "totalSupply": "3000000",
    "startTime": int((datetime.now() - timedelta(days=1)).timestamp() * 1000),
    "endTime": int((datetime.now() + timedelta(hours=25)).timestamp() * 1000),
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

# Активний проект з 1 варіантом
promo2 = {
    "launchpadId": "692ee86de4b0a828c5f3399b",
    "activityCoin": "STABLE",
    "activityCoinFullName": "StableNode",
    "activityStatus": "ONGOING",
    "totalSupply": "6000000",
    "startTime": int((datetime.now() - timedelta(hours=12)).timestamp() * 1000),
    "endTime": int((datetime.now() + timedelta(days=2, hours=6)).timestamp() * 1000),
    "launchpadTakingCoins": [
        {
            "investCurrency": "USDT",
            "takingPrice": "0.01",
            "label": "60% Off",
            "supply": "3000000",
            "takingAmount": "3931574.66",
            "joinNum": 467,
            "linePrice": "0.025",
            "onlyForNewUser": True
        }
    ]
}

# Скоро стартує
promo3 = {
    "launchpadId": "abc123def456",
    "activityCoin": "XPL",
    "activityCoinFullName": "Xplorer Protocol",
    "activityStatus": "NOT_STARTED",
    "totalSupply": "5000000",
    "startTime": int((datetime.now() + timedelta(days=1)).timestamp() * 1000),
    "endTime": int((datetime.now() + timedelta(days=5)).timestamp() * 1000),
    "launchpadTakingCoins": [
        {
            "investCurrency": "USDT",
            "takingPrice": "0.08",
            "label": "50% Off",
            "supply": "2500000",
            "takingAmount": "0",
            "joinNum": 0,
            "linePrice": "0.16",
            "onlyForNewUser": False
        }
    ]
}


if __name__ == "__main__":
    print("=" * 80)
    print("ПРЕВЬЮ ПОВНОЇ СТОРІНКИ 'ТЕКУЩИЕ ПРОМОАКЦИИ' ДЛЯ MEXC LAUNCHPAD")
    print("=" * 80)
    print()
    print("Це саме те, що побачить користувач в Telegram боті")
    print("коли натисне 'Текущие промоакции' для MEXC Launchpad")
    print()
    print("=" * 80)
    print()

    # Генеруємо повідомлення з 3 проектами
    promos = [promo1, promo2, promo3]
    message = format_mexc_launchpad_page(promos, page=1, total_pages=1)

    print(message)
    print()
    print("=" * 80)
    print(f"Довжина повідомлення: {len(message)} символів")
    print(f"Ліміт Telegram: 4096 символів")

    if len(message) > 4096:
        print("⚠️ УВАГА: Повідомлення перевищує ліміт! Потрібна пагінація.")
    else:
        print("✓ Повідомлення в межах ліміту Telegram")
    print("=" * 80)
