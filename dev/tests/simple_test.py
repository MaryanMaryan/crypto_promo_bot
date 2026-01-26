"""Простой тест форматирования без лишних импортов"""

import sys
sys.path.insert(0, '.')

# Импортируем только нужное напрямую
from datetime import datetime, timedelta

# Копируем класс напрямую для теста
class BybitTokenSplashFormatter:
    """Форматирование Bybit Token Splash"""
    
    @staticmethod
    def _format_number(value) -> str:
        """Форматирует число с разделителями тысяч"""
        try:
            num = float(value) if value else 0
            if num >= 1_000_000:
                return f"{num/1_000_000:.1f}M".replace('.0M', 'M')
            elif num >= 1_000:
                return f"{num:,.0f}".replace(',', ' ')
            return str(int(num))
        except:
            return str(value)
    
    @staticmethod
    def _format_token_amount(amount, token: str, usd_price: float = None) -> str:
        """Форматирует сумму токенов с USD эквивалентом"""
        try:
            num = float(amount) if amount else 0
            formatted = f"{num:,.0f}".replace(',', ' ')
            result = f"{formatted} {token}"
            
            if usd_price and usd_price > 0:
                usd_value = num * usd_price
                if usd_value >= 1_000_000:
                    usd_str = f"${usd_value/1_000_000:.2f}M"
                elif usd_value >= 1_000:
                    usd_str = f"${usd_value:,.0f}".replace(',', ' ')
                else:
                    usd_str = f"${usd_value:.2f}"
                result += f" (~{usd_str})"
            
            return result
        except:
            return f"{amount} {token}"

    @staticmethod
    def format(data: dict, is_new: bool = True) -> str:
        """Форматирует Token Splash уведомление"""
        
        title = data.get('title', 'Token Splash')
        token = data.get('award_token', 'TOKEN')
        prize_pool = data.get('total_prize_pool', 0)
        participants = data.get('participants_count', 0)
        splash_type = data.get('splash_type', 'regular')
        min_trade = data.get('min_trade_amount')
        trade_token = data.get('trade_token', 'USDT')
        reward_per_winner = data.get('reward_per_winner')
        new_user_winners = data.get('new_user_winners_count')
        total_trade_volume = data.get('total_trade_volume')  # NEW!
        trade_prize_pool = data.get('trade_prize_pool') or float(prize_pool) if prize_pool else 0
        link = data.get('link', '')
        end_time = data.get('end_time')
        
        # Тестовая цена
        usd_price = 0.001076  # Примерная цена PYBOBO
        
        lines = []
        
        # Заголовок
        if splash_type == 'trading':
            lines.append(f"🟡 <b>Bybit Token Splash — Trading</b>")
        elif splash_type == 'combined':
            lines.append(f"🟡 <b>Bybit Token Splash — Combined</b>")
        else:
            lines.append(f"🟡 <b>Bybit Token Splash</b>")
        
        lines.append(f"<b>{title}</b>")
        lines.append("━" * 31)
        
        # Призовой фонд (ОБЩИЙ)
        prize_num = float(prize_pool) if prize_pool else 0
        prize_formatted = BybitTokenSplashFormatter._format_token_amount(prize_num, token, usd_price)
        lines.append(f"💰 Призовий фонд: {prize_formatted}")
        
        # Участники
        lines.append(f"👥 Учасників: {BybitTokenSplashFormatter._format_number(participants)}")
        
        # Блок для новых пользователей (ТОЛЬКО если есть reward_per_winner И это не trading)
        has_new_user_task = reward_per_winner and splash_type != 'trading'
        has_trading_task = splash_type in ('trading', 'combined') or min_trade
        
        if has_new_user_task:
            lines.append("")
            lines.append("🎁 <b>Завдання для нових користувачів:</b>")
            # Парсим reward
            reward_num = None
            if isinstance(reward_per_winner, (int, float)):
                reward_num = float(reward_per_winner)
            elif isinstance(reward_per_winner, str):
                parts = str(reward_per_winner).replace(',', '').split()
                if parts:
                    try:
                        reward_num = float(parts[0])
                    except:
                        pass
            
            if reward_num:
                reward_formatted = BybitTokenSplashFormatter._format_token_amount(reward_num, token, usd_price)
                lines.append(f"   ├ Нагорода: {reward_formatted}")
            
            if new_user_winners:
                lines.append(f"   └ Місць: {BybitTokenSplashFormatter._format_number(new_user_winners)}")
        
        # Блок трейдингового задания
        if has_trading_task:
            lines.append("")
            if has_new_user_task:
                lines.append("📊 <b>Трейдингове завдання (для всіх):</b>")
            else:
                lines.append("📊 <b>Умова участі:</b>")
            
            if min_trade:
                lines.append(f"   ├ Мін. об'єм: {BybitTokenSplashFormatter._format_number(min_trade)} {trade_token} токеном {token}")
            
            # Призовой пул трейдинга
            pool_formatted = BybitTokenSplashFormatter._format_token_amount(trade_prize_pool, token, usd_price)
            lines.append(f"   ├ Призовий пул: {pool_formatted}")
            
            # Если есть данные об общем объёме - показываем калькулятор
            if total_trade_volume and total_trade_volume > 0:
                lines.append(f"   ├ Загальний об'єм: ${total_trade_volume:,.2f}".replace(',', ' '))
                lines.append(f"   ├ 💰 <b>Калькулятор:</b>")
                
                # Расчёт для разных объёмов
                test_volumes = [500, 1000, 5000, 10000]
                for vol in test_volumes:
                    reward_tokens = (vol / total_trade_volume) * trade_prize_pool
                    reward_usd = reward_tokens * usd_price
                    if reward_usd >= 1:
                        lines.append(f"   │  └ ${vol:,} → ~${reward_usd:,.2f}".replace(',', ' '))
            else:
                lines.append(f"   └ 💡 Нагорода = (Ваш об'єм / Загальний об'єм) × Пул")
        
        # Время
        if end_time:
            if isinstance(end_time, datetime):
                time_left = end_time - datetime.now()
                days = time_left.days
                hours = time_left.seconds // 3600
                lines.append("")
                lines.append(f"⏰ Залишилось: {days}д {hours}г")
        
        # Ссылка
        if link:
            lines.append("")
            lines.append(f"🔗 <a href=\"{link}\">Взяти участь</a>")
        
        return "\n".join(lines)


def clean_html(text):
    """Удаляет HTML теги"""
    return (text
            .replace('<b>', '')
            .replace('</b>', '')
            .replace('<a href=', '[')
            .replace('</a>', '')
            .replace('">', '] ')
            .replace('<code>', '')
            .replace('</code>', '')
            .replace('<i>', '')
            .replace('</i>', ''))


# ТЕСТЫ
print("=" * 70)
print("ТЕСТ 1: TRADING TOKEN SPLASH (з калькулятором)")
print("=" * 70)

test_trading = {
    'title': 'CAPYBOBO',
    'award_token': 'PYBOBO',
    'total_prize_pool': '150000000',
    'participants_count': 708,
    'splash_type': 'trading',
    'min_trade_amount': 500,
    'trade_token': 'USDT',
    'total_trade_volume': 30112.74,  # Реальные данные из API!
    'trade_prize_pool': 150000000,
    'end_time': datetime.now() + timedelta(days=13, hours=20),
    'link': 'https://www.bybit.com/token-splash',
}
print(clean_html(BybitTokenSplashFormatter.format(test_trading)))

print("\n" + "=" * 70)
print("ТЕСТ 2: REGULAR TOKEN SPLASH (тільки для нових)")
print("=" * 70)

test_regular = {
    'title': 'Sentient',
    'award_token': 'SENT',
    'total_prize_pool': '30000000',
    'participants_count': 7872,
    'splash_type': 'regular',
    'reward_per_winner': '40000',
    'new_user_winners_count': 7500,
    'end_time': datetime.now() + timedelta(days=5),
    'link': 'https://www.bybit.com/token-splash',
}
print(clean_html(BybitTokenSplashFormatter.format(test_regular)))

print("\n" + "=" * 70)
print("ТЕСТ 3: COMBINED TOKEN SPLASH (обидва завдання)")
print("=" * 70)

test_combined = {
    'title': 'Fight',
    'award_token': 'FIGHT',
    'total_prize_pool': '10000000',
    'participants_count': 2507,
    'splash_type': 'combined',
    'reward_per_winner': '200',
    'new_user_winners_count': 50000,
    'min_trade_amount': 500,
    'trade_token': 'USDT',
    'total_trade_volume': 150000,  # Примерное значение
    'trade_prize_pool': 8000000,  # Часть пула для трейдинга
    'end_time': datetime.now() + timedelta(days=10),
    'link': 'https://www.bybit.com/token-splash',
}
print(clean_html(BybitTokenSplashFormatter.format(test_combined)))

print("\n✅ Тестування завершено!")
