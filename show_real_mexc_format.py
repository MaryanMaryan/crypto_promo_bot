#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показує реальне форматування з реальними даними MEXC API"""

import sys
import io
import requests
from datetime import datetime

# Фікс кодування для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def strip_html_tags(text: str) -> str:
    """Видаляє HTML теги і замінює на текстове форматування для візуалізації"""
    import re

    # Замінюємо жирний текст
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text)

    # Замінюємо курсив
    text = re.sub(r'<i>(.*?)</i>', r'_\1_', text)

    # Замінюємо посилання
    text = re.sub(r"<a href='(.*?)'>(.*?)</a>", r'\2 (\1)', text)

    # Видаляємо інші теги
    text = re.sub(r'<[^>]+>', '', text)

    return text


def format_mexc_launchpad_page(promos: list) -> str:
    """Форматує повну сторінку текущих промоакцій"""

    # === ЗАГОЛОВОК ===
    message = "🎁 **ТЕКУЩИЕ ПРОМОАКЦИИ**\n\n"
    message += "**🏦 Биржа:** MEXC Launchpad\n"

    now = datetime.now()
    message += f"**⏱️ Обновлено:** {now.strftime('%d.%m.%Y %H:%M')}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if not promos:
        message += "📭 _Нет активных промоакций_\n\n"
        return message

    # === ПРОЕКТИ ===
    for idx, promo in enumerate(promos):
        # ЗАГОЛОВОК
        token = promo.get('activityCoin', 'Unknown')
        full_name = promo.get('activityCoinFullName', token)

        if full_name and full_name != token:
            message += f"🚀 **{full_name} ({token})**\n"
        else:
            message += f"🚀 **{token}**\n"

        # СТАТУС
        status = promo.get('activityStatus', 'UNKNOWN')
        status_map = {
            'UNDERWAY': '✅ Активна',
            'ONGOING': '✅ Активна',
            'NOT_STARTED': '🔜 Скоро',
            'FINISHED': '⏹ Завершена',
            'SETTLED': '⏹ Завершена',
            'CANCELLED': '❌ Отменена'
        }
        message += f"**📊 Статус:** {status_map.get(status, '❓ ' + status)}\n"

        # SUPPLY
        total_supply = promo.get('totalSupply')
        if total_supply:
            try:
                supply_num = float(total_supply)
                message += f"**📦 Всего токенов:** {supply_num:,.0f} {token}\n"
            except:
                message += f"**📦 Всего токенов:** {total_supply} {token}\n"

        message += "\n"

        # ВАРІАНТИ ПІДПИСКИ
        taking_coins = promo.get('launchpadTakingCoins', [])

        if len(taking_coins) > 1:
            message += f"💰 **ВАРИАНТЫ ПОДПИСКИ ({len(taking_coins)}):**\n\n"
        elif len(taking_coins) == 1:
            message += f"💰 **ПОДПИСКА:**\n\n"

        for tc_idx, tc in enumerate(taking_coins, 1):
            invest_curr = tc.get('investCurrency', 'USDT')
            taking_price = tc.get('takingPrice', '0')
            label = tc.get('label', '')
            supply = tc.get('supply', '0')
            taking_amount = tc.get('takingAmount', '0')
            join_num = tc.get('joinNum', 0)
            line_price = tc.get('linePrice')
            only_new = tc.get('onlyForNewUser', False)

            # Заголовок варіанту
            if len(taking_coins) > 1:
                message += f"**Вариант {tc_idx}:** {invest_curr}"
                if only_new:
                    message += " 🆕 _(только новые пользователи)_"
                message += "\n"
            else:
                message += f"**Валюта:** {invest_curr}"
                if only_new:
                    message += " 🆕 _(только новые пользователи)_"
                message += "\n"

            # Ціна
            message += f"   • **Цена подписки:** 1 {token} = {taking_price} {invest_curr}\n"

            # Знижка
            if label:
                message += f"   • **Скидка:** {label} 🔥\n"

            # Ринкова ціна
            if line_price:
                try:
                    market = float(line_price)
                    current = float(taking_price)
                    savings = ((market - current) / market) * 100 if market > 0 else 0
                    message += f"   • **Рыночная цена:** {line_price} {invest_curr} "
                    message += f"_(экономия {savings:.0f}%)_\n"
                except:
                    message += f"   • **Рыночная цена:** {line_price} {invest_curr}\n"

            # Доступно
            try:
                supply_num = float(supply)
                message += f"   • **Доступно токенов:** {supply_num:,.0f} {token}\n"
            except:
                message += f"   • **Доступно токенов:** {supply} {token}\n"

            # Зібрано
            try:
                amount_num = float(taking_amount)
                if amount_num > 0:
                    message += f"   • **Собрано:** {amount_num:,.2f} {invest_curr}\n"
            except:
                pass

            # Учасники
            if join_num:
                message += f"   • **Участников:** {join_num:,}\n"

            if tc_idx < len(taking_coins):
                message += "\n"

        # ПЕРІОД
        start_time = promo.get('startTime')
        end_time = promo.get('endTime')

        if start_time or end_time:
            message += "\n⏰ **ПЕРИОД АКЦИИ:**\n"

            if start_time and end_time:
                try:
                    start_dt = datetime.fromtimestamp(start_time / 1000)
                    end_dt = datetime.fromtimestamp(end_time / 1000)
                    message += f"   • Период: {start_dt.strftime('%d.%m.%Y %H:%M')} / {end_dt.strftime('%d.%m.%Y %H:%M')}\n"

                    # Залишок
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

        # РОЗДІЛЮВАЧ
        if idx < len(promos) - 1:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        else:
            message += "\n"

    # ФУТЕР
    message += "\n**🔗 Страница акций:** https://www.mexc.com/ru-RU/launchpad\n"

    return message


def main():
    """Отримує реальні дані з API та форматує"""

    print("=" * 80)
    print("ФІНАЛЬНИЙ ВАРІАНТ З РЕАЛЬНИМИ ДАНИМИ MEXC LAUNCHPAD API")
    print("=" * 80)
    print()
    print("Отримую реальні дані з API...")
    print()

    # Отримуємо реальні дані
    url = "https://www.mexc.com/api/financialactivity/launchpad/list"

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Витягуємо проекти
        launchpads = data.get('data', {}).get('launchpads', [])

        if not launchpads:
            print("❌ Немає доступних проектів в API")
            return

        print(f"✓ Отримано {len(launchpads)} проектів з API")
        print()

        # Беремо перші 3 активних/upcoming проекти
        filtered = []
        for lp in launchpads:
            status = lp.get('activityStatus', '')
            if status in ['UNDERWAY', 'ONGOING', 'NOT_STARTED']:
                filtered.append(lp)
                if len(filtered) >= 3:
                    break

        # Якщо менше 3 активних - додаємо завершені
        if len(filtered) < 3:
            for lp in launchpads:
                if lp not in filtered:
                    filtered.append(lp)
                    if len(filtered) >= 3:
                        break

        print("=" * 80)
        print("ТАК ЦЕ БУДЕ ВИГЛЯДАТИ В TELEGRAM:")
        print("=" * 80)
        print()

        # Форматуємо
        formatted = format_mexc_launchpad_page(filtered[:3])

        # Виводимо
        print(formatted)

        print()
        print("=" * 80)
        print(f"Довжина: {len(formatted)} символів (ліміт: 4096)")
        if len(formatted) > 4096:
            print("⚠️ Перевищує ліміт! Потрібна пагінація")
        else:
            print("✓ В межах ліміту Telegram")
        print("=" * 80)

    except Exception as e:
        print(f"❌ Помилка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
