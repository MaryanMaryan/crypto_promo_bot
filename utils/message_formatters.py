# utils/message_formatters.py
"""
Универсальные форматтеры сообщений для Telegram уведомлений.
Каждая категория имеет свой уникальный стиль форматирования.
"""

import logging
import html
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ И СТИЛИ
# ═══════════════════════════════════════════════════════════════════════════════

DIVIDER = "━" * 31

EXCHANGE_ICONS = {
    'mexc': '🔵',
    'gate': '⚪',
    'gate.io': '⚪',
    'bybit': '🟡',
    'binance': '🟢',
    'okx': '🟠',
    'bitget': '🔴',
    'weex': '🟣',
    'kucoin': '🟤',
    'htx': '🔷',
    'bingx': '🔶',
    'phemex': '🟪',
}

CATEGORY_ICONS = {
    'launchpad': '🚀',
    'launchpool': '🌊',
    'drops': '🎁',
    'airdrop': '🪂',
    'candybomb': '🍬',
    'staking': '💎',
    'candy': '🍬',
    'boost': '📈',
    'rewards': '🎁',
    'telegram': '📢',
}


def escape_html(text: Any) -> str:
    """Безопасное экранирование HTML"""
    if text is None:
        return ''
    return html.escape(str(text))


def format_number(n: Any, decimals: int = 0) -> str:
    """Форматирует число с разделителями тысяч"""
    try:
        num = float(str(n).replace(',', '').replace(' ', ''))
        if decimals == 0:
            return f"{num:,.0f}".replace(',', ' ')
        return f"{num:,.{decimals}f}".replace(',', ' ')
    except:
        return str(n)


def format_number_short(n: Any) -> str:
    """Короткий формат числа (1K, 1M, 1B)"""
    try:
        num = float(str(n).replace(',', '').replace(' ', ''))
        if num >= 1_000_000_000:
            return f"{num/1_000_000_000:.1f}B"
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.0f}K"
        return f"{num:.0f}"
    except:
        return str(n)


def format_money(amount: float, symbol: str = "$") -> str:
    """Форматирует денежную сумму"""
    if amount >= 1_000_000:
        return f"{symbol}{amount/1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{symbol}{amount/1_000:.0f}K"
    if amount >= 1:
        return f"{symbol}{amount:,.0f}"
    return f"{symbol}{amount:.2f}"


def format_time_remaining(end_time: Any) -> str:
    """Форматирует оставшееся время"""
    if not end_time:
        return ""
    
    now = datetime.now()
    
    # Конвертируем в datetime если нужно
    if isinstance(end_time, str):
        try:
            # Пробуем разные форматы
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',  # SQLite с микросекундами
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%d.%m.%Y %H:%M',
                '%Y-%m-%d',
            ]
            for fmt in formats:
                try:
                    end_time = datetime.strptime(end_time, fmt)
                    break
                except:
                    continue
            else:
                return ""
        except:
            return ""
    elif isinstance(end_time, (int, float)):
        # timestamp в миллисекундах или секундах
        try:
            if end_time > 10**12:
                end_time = datetime.fromtimestamp(end_time / 1000)
            else:
                end_time = datetime.fromtimestamp(end_time)
        except:
            return ""
    
    if not isinstance(end_time, datetime):
        return ""
    
    if end_time <= now:
        return "Завершено"
    
    remaining = end_time - now
    days = remaining.days
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds % 3600) // 60
    
    if days > 0:
        return f"{days}д {hours}ч"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"


def format_date_short(dt: Any) -> str:
    """Форматирует дату коротко: 19.01"""
    if not dt:
        return ""
    
    if isinstance(dt, str):
        try:
            # Пробуем разные форматы
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',  # SQLite с микросекундами
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%d.%m.%Y %H:%M',
                '%Y-%m-%d',
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(dt, fmt)
                    break
                except:
                    continue
            else:
                # Не удалось распарсить, возвращаем как есть (первые 5 символов)
                return dt[:5] if len(dt) >= 5 else dt
        except:
            return str(dt)[:5]
    elif isinstance(dt, (int, float)):
        try:
            if dt > 10**12:
                dt = datetime.fromtimestamp(dt / 1000)
            else:
                dt = datetime.fromtimestamp(dt)
        except:
            return ""
    
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m")
    
    return str(dt)


def get_exchange_icon(exchange: str) -> str:
    """Получает иконку биржи"""
    exchange_lower = exchange.lower().replace('.io', '').replace(' ', '')
    return EXCHANGE_ICONS.get(exchange_lower, '🎉')


def get_exchange_name(exchange: str) -> str:
    """Нормализует название биржи"""
    exchange_lower = exchange.lower()
    name_map = {
        'mexc': 'MEXC',
        'gate': 'GATE.IO',
        'gate.io': 'GATE.IO',
        'bybit': 'BYBIT',
        'binance': 'BINANCE',
        'okx': 'OKX',
        'bitget': 'BITGET',
        'weex': 'WEEX',
        'kucoin': 'KUCOIN',
        'htx': 'HTX',
        'bingx': 'BINGX',
        'phemex': 'PHEMEX',
    }
    return name_map.get(exchange_lower, exchange.upper())


# ═══════════════════════════════════════════════════════════════════════════════
# LAUNCHPAD ФОРМАТТЕР
# ═══════════════════════════════════════════════════════════════════════════════

class LaunchpadFormatter:
    """
    Универсальный форматтер для Launchpad уведомлений.
    
    Поддерживает: MEXC, Gate.io, Bybit Token Splash и любые другие биржи.
    """
    
    @staticmethod
    def format(promo: Dict[str, Any], is_new: bool = True) -> str:
        """
        Форматирует Launchpad промоакцию.
        
        Args:
            promo: Данные промоакции
            is_new: Показывать метку NEW
            
        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # ═══════════════════════════════════════════════════════════════
            # ИЗВЛЕЧЕНИЕ ДАННЫХ
            # ═══════════════════════════════════════════════════════════════
            
            exchange = promo.get('exchange', 'Unknown')
            exchange_name = get_exchange_name(exchange)
            exchange_icon = get_exchange_icon(exchange)
            
            # Токен
            token_symbol = promo.get('award_token', '') or promo.get('token_symbol', '')
            token_name = promo.get('title', '') or promo.get('token_name', token_symbol)
            
            # Очищаем название от дублирования символа
            if token_symbol and f"({token_symbol})" in token_name:
                token_name = token_name.replace(f" ({token_symbol})", "").replace(f"({token_symbol})", "")
            
            # Цены
            buy_price = LaunchpadFormatter._get_price(promo, 'buy')
            market_price = LaunchpadFormatter._get_price(promo, 'market')
            
            # Скидка и ROI
            discount = promo.get('max_discount') or promo.get('discount')
            roi = None
            
            if buy_price and market_price and buy_price > 0:
                if not discount:
                    discount = ((market_price - buy_price) / market_price) * 100
                roi = ((market_price - buy_price) / buy_price) * 100
            
            # Общий пул токенов
            total_tokens = LaunchpadFormatter._get_total_tokens(promo)
            total_tokens_usd = None
            if total_tokens and market_price:
                total_tokens_usd = total_tokens * market_price
            elif total_tokens and buy_price:
                total_tokens_usd = total_tokens * buy_price
            
            # Лимиты на участие
            min_amount, max_amount = LaunchpadFormatter._get_limits(promo)
            
            # Время
            start_time = promo.get('start_time') or promo.get('start_timestamp')
            end_time = promo.get('end_time') or promo.get('end_timestamp')
            
            # Ссылка
            link = promo.get('link', '') or promo.get('project_url', '')
            promo_id = promo.get('promo_id', '')
            
            # ═══════════════════════════════════════════════════════════════
            # ФОРМИРОВАНИЕ СООБЩЕНИЯ
            # ═══════════════════════════════════════════════════════════════
            
            # Заголовок
            new_badge = " │ 🆕 NEW" if is_new else ""
            message = f"🚀 {exchange_name} LAUNCHPAD{new_badge}\n"
            message += f"{DIVIDER}\n\n"
            
            # Название токена
            if token_name and token_symbol and token_name != token_symbol:
                message += f"🪙 {escape_html(token_name)} ({escape_html(token_symbol)})\n\n"
            elif token_symbol:
                message += f"🪙 {escape_html(token_symbol)}\n\n"
            else:
                message += f"🪙 {escape_html(token_name)}\n\n"
            
            # Цена и ROI
            price_line = LaunchpadFormatter._format_price_line(buy_price, market_price, discount, roi)
            if price_line:
                message += f"{price_line}\n"
            
            # Пул токенов и лимиты
            pool_line = LaunchpadFormatter._format_pool_line(total_tokens, total_tokens_usd, token_symbol, min_amount, max_amount)
            if pool_line:
                message += f"{pool_line}\n"
            
            # Аллокация и профит
            allocation_block = LaunchpadFormatter._format_allocation_block(
                buy_price, market_price, min_amount, max_amount, token_symbol
            )
            if allocation_block:
                message += f"\n{allocation_block}\n"
            
            # Период
            time_line = LaunchpadFormatter._format_time_line(start_time, end_time)
            if time_line:
                message += f"\n{time_line}\n"
            
            # Ссылка
            if link:
                # Сокращаем ссылку для красоты
                short_link = link.replace('https://', '').replace('http://', '').replace('www.', '')
                if len(short_link) > 40:
                    short_link = short_link[:37] + "..."
                message += f"🔗 {short_link}\n"
            
            # ID
            if promo_id:
                message += f"\n<code>ID: {escape_html(promo_id)}</code>"
            
            # Проверка лимита Telegram
            if len(message) > 4090:
                message = message[:4000] + "\n\n<i>⚠️ Сообщение обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Launchpad: {e}", exc_info=True)
            return f"🚀 <b>LAUNCHPAD</b>\n\n❌ Ошибка форматирования"
    
    @staticmethod
    def _get_price(promo: Dict[str, Any], price_type: str) -> Optional[float]:
        """Извлекает цену из разных полей"""
        if price_type == 'buy':
            # Цена покупки
            for field in ['min_price', 'buy_price', 'subscription_price', 'taking_price', 'price']:
                value = promo.get(field)
                if value:
                    try:
                        return float(value)
                    except:
                        pass
            
            # Из raw_data
            raw = promo.get('raw_data', {})
            if raw:
                taking_coins = raw.get('launchpadTakingCoins', [])
                if taking_coins:
                    try:
                        return float(taking_coins[0].get('takingPrice', 0))
                    except:
                        pass
        
        elif price_type == 'market':
            # Рыночная цена
            for field in ['market_price', 'line_price', 'listing_price']:
                value = promo.get(field)
                if value:
                    try:
                        return float(value)
                    except:
                        pass
            
            # Из raw_data
            raw = promo.get('raw_data', {})
            if raw:
                taking_coins = raw.get('launchpadTakingCoins', [])
                if taking_coins:
                    try:
                        return float(taking_coins[0].get('linePrice', 0))
                    except:
                        pass
        
        return None
    
    @staticmethod
    def _get_total_tokens(promo: Dict[str, Any]) -> Optional[float]:
        """Извлекает общее количество токенов"""
        for field in ['total_prize_pool', 'total_supply', 'total_tokens', 'total_pool_tokens']:
            value = promo.get(field)
            if value:
                try:
                    # Убираем форматирование
                    clean = str(value).replace(',', '').replace(' ', '')
                    return float(clean)
                except:
                    pass
        return None
    
    @staticmethod
    def _get_limits(promo: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """Извлекает минимальный и максимальный лимит участия"""
        min_amount = None
        max_amount = None
        
        # Прямые поля
        for field in ['min_amount', 'min_subscribe', 'min_limit']:
            value = promo.get(field)
            if value:
                try:
                    min_amount = float(value)
                    break
                except:
                    pass
        
        for field in ['max_amount', 'max_subscribe', 'max_limit', 'user_limit']:
            value = promo.get(field)
            if value:
                try:
                    max_amount = float(value)
                    break
                except:
                    pass
        
        # Из raw_data (MEXC)
        raw = promo.get('raw_data', {})
        if raw:
            taking_coins = raw.get('launchpadTakingCoins', [])
            if taking_coins:
                tc = taking_coins[0]
                if not min_amount:
                    try:
                        min_amount = float(tc.get('minLimit', 0))
                    except:
                        pass
                if not max_amount:
                    try:
                        max_amount = float(tc.get('maxLimit', 0))
                    except:
                        pass
        
        # Дефолты если не нашли
        if not min_amount:
            min_amount = 100
        if not max_amount:
            max_amount = 10000
        
        return min_amount, max_amount
    
    @staticmethod
    def _format_price_line(buy_price: float, market_price: float, 
                           discount: float, roi: float) -> str:
        """Форматирует строку с ценами"""
        parts = []
        
        if buy_price and market_price:
            parts.append(f"${buy_price:.4g} → ${market_price:.4g}")
            
            if discount and discount > 0:
                parts.append(f"-{discount:.0f}%")
            
            if roi and roi > 0:
                parts.append(f"ROI +{roi:.0f}%")
        
        elif buy_price:
            parts.append(f"Цена: ${buy_price:.4g}")
        
        if parts:
            return "💵 " + " │ ".join(parts)
        return ""
    
    @staticmethod
    def _format_pool_line(total_tokens: float, total_usd: float, 
                          symbol: str, min_amount: float, max_amount: float) -> str:
        """Форматирует строку с пулом токенов"""
        parts = []
        
        if total_tokens:
            token_str = format_number_short(total_tokens) + f" {symbol}"
            if total_usd:
                token_str += f" (~{format_money(total_usd)})"
            parts.append(token_str)
        
        if min_amount and max_amount:
            parts.append(f"{format_number(min_amount, 0)}-{format_number(max_amount, 0)} USDT")
        elif max_amount:
            parts.append(f"до {format_number(max_amount, 0)} USDT")
        
        if parts:
            return "📦 " + " │ ".join(parts)
        return ""
    
    @staticmethod
    def _format_allocation_block(buy_price: float, market_price: float,
                                  min_amount: float, max_amount: float,
                                  token_symbol: str) -> str:
        """Форматирует блок аллокации и профита"""
        if not buy_price or buy_price <= 0:
            return ""
        
        if not market_price:
            market_price = buy_price  # Если нет рыночной цены, показываем только токены
        
        lines = ["💰 АЛЛОКАЦИЯ → ПРОФИТ:"]
        
        # Рассчитываем для 3 сумм: мин, средняя, макс
        amounts = []
        if min_amount:
            amounts.append(min_amount)
        
        # Добавляем промежуточное значение
        if min_amount and max_amount:
            mid = (min_amount + max_amount) / 2
            # Округляем до красивого числа
            if mid >= 1000:
                mid = round(mid / 100) * 100
            else:
                mid = round(mid / 10) * 10
            amounts.append(mid)
        
        if max_amount:
            amounts.append(max_amount)
        
        # Убираем дубликаты и сортируем
        amounts = sorted(set(amounts))
        
        # Если только одна сумма, добавляем стандартные
        if len(amounts) < 3:
            amounts = [100, 1000, max_amount or 10000]
        
        for i, amount in enumerate(amounts[:3]):
            tokens = amount / buy_price
            profit = (market_price - buy_price) * tokens
            
            # Форматируем токены
            tokens_str = format_number_short(tokens)
            
            # Древовидный префикс
            if i < len(amounts) - 1:
                prefix = "   ├─"
            else:
                prefix = "   └─"
            
            # Звездочка для максимальной суммы
            star = " ⭐" if i == len(amounts) - 1 else ""
            
            if profit > 0:
                lines.append(f"{prefix} ${format_number(amount, 0)} → {tokens_str} {token_symbol} → +${format_number(profit, 0)}{star}")
            else:
                lines.append(f"{prefix} ${format_number(amount, 0)} → {tokens_str} {token_symbol}{star}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_time_line(start_time: Any, end_time: Any) -> str:
        """Форматирует строку со временем"""
        parts = []
        
        start_str = format_date_short(start_time)
        end_str = format_date_short(end_time)
        
        if start_str and end_str:
            parts.append(f"⏰ {start_str} → {end_str}")
        elif end_str:
            parts.append(f"⏰ до {end_str}")
        
        # Оставшееся время
        remaining = format_time_remaining(end_time)
        if remaining and remaining != "Завершено":
            parts.append(f"⏳ {remaining}")
        elif remaining == "Завершено":
            parts.append("⏳ Завершено")
        
        return " │ ".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════════
# LAUNCHPOOL ФОРМАТТЕР
# ═══════════════════════════════════════════════════════════════════════════════

class LaunchpoolFormatter:
    """
    Универсальный форматтер для Launchpool уведомлений.
    
    Поддерживает: Bybit, Gate.io, Bitget, BingX, MEXC и другие биржи.
    Использует данные из LaunchpoolProject или raw_data dict.
    """
    
    @staticmethod
    def format(promo: Dict[str, Any], is_new: bool = True) -> str:
        """
        Форматирует Launchpool промоакцию в компактном виде.
        
        Args:
            promo: Данные промоакции (LaunchpoolProject или dict)
            is_new: Показывать метку NEW
            
        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # ═══════════════════════════════════════════════════════════════
            # ИЗВЛЕЧЕНИЕ ДАННЫХ
            # ═══════════════════════════════════════════════════════════════
            
            exchange = promo.get('exchange', 'Unknown')
            exchange_name = get_exchange_name(exchange)
            
            # Токен
            token_symbol = (promo.get('token_symbol', '') or 
                          promo.get('award_token', '') or 
                          promo.get('coin', ''))
            token_name = promo.get('token_name', '') or promo.get('title', token_symbol)
            
            # Общий пул токенов
            total_pool = LaunchpoolFormatter._get_total_pool(promo)
            total_pool_usd = promo.get('total_pool_usd', 0) or promo.get('total_prize_pool_usd', 0)
            
            # Пулы для фарминга
            pools = LaunchpoolFormatter._extract_pools(promo)
            
            # Время
            start_time = promo.get('start_time') or promo.get('start_timestamp')
            end_time = promo.get('end_time') or promo.get('end_timestamp')
            days_left = LaunchpoolFormatter._calculate_days_left(end_time)
            
            # Ссылка и ID
            link = promo.get('link', '') or promo.get('project_url', '')
            promo_id = promo.get('promo_id', '') or promo.get('id', '')
            
            # ═══════════════════════════════════════════════════════════════
            # ФОРМИРОВАНИЕ СООБЩЕНИЯ
            # ═══════════════════════════════════════════════════════════════
            
            # Заголовок
            new_badge = " │ 🆕 NEW" if is_new else ""
            message = f"🌊 {exchange_name} LAUNCHPOOL{new_badge}\n"
            message += f"{DIVIDER}\n"
            
            # Название токена
            if token_name and token_symbol and token_name != token_symbol:
                message += f"🪙 {escape_html(token_name)} ({escape_html(token_symbol)})\n"
            elif token_symbol:
                message += f"🪙 {escape_html(token_symbol)}\n"
            else:
                message += f"🪙 {escape_html(token_name)}\n"
            
            # Общий пул и длительность
            pool_info = []
            if total_pool:
                pool_str = f"{format_number_short(total_pool)} {token_symbol}"
                if total_pool_usd:
                    pool_str += f" (~{format_money(total_pool_usd)})"
                pool_info.append(pool_str)
            
            if days_left and days_left > 0:
                pool_info.append(f"{days_left} дн.")
            
            if pool_info:
                message += f"🎁 {' │ '.join(pool_info)}\n"
            
            # Пулы для фарминга
            if pools:
                message += "\n"
                # Находим максимальный APR для пометки 🔥
                max_apr = max(p.get('apr', 0) for p in pools) if pools else 0
                
                for pool in pools[:4]:  # Максимум 4 пула
                    pool_msg = LaunchpoolFormatter._format_pool(pool, max_apr, days_left)
                    if pool_msg:
                        message += pool_msg + "\n"
            
            # Период
            time_line = LaunchpoolFormatter._format_time_line(start_time, end_time)
            if time_line:
                message += f"\n{time_line}\n"
            
            # Ссылка
            if link:
                short_link = link.replace('https://', '').replace('http://', '').replace('www.', '')
                if len(short_link) > 40:
                    short_link = short_link[:37] + "..."
                message += f"🔗 {short_link}\n"
            
            # ID
            if promo_id:
                message += f"<code>ID: {escape_html(str(promo_id))}</code>"
            
            # Проверка лимита Telegram
            if len(message) > 4090:
                message = message[:4000] + "\n\n<i>⚠️ Сообщение обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Launchpool: {e}", exc_info=True)
            return f"🌊 <b>LAUNCHPOOL</b>\n\n❌ Ошибка форматирования"
    
    @staticmethod
    def _get_total_pool(promo: Dict[str, Any]) -> Optional[float]:
        """Извлекает общий пул токенов"""
        for field in ['total_pool_tokens', 'total_prize_pool', 'total_rewards', 'total_supply']:
            value = promo.get(field)
            if value:
                try:
                    return float(str(value).replace(',', '').replace(' ', ''))
                except:
                    pass
        
        # Из raw_data
        raw = promo.get('raw_data', {})
        if raw:
            value = raw.get('totalPoolAmount') or raw.get('totalRewards')
            if value:
                try:
                    return float(str(value).replace(',', '').replace(' ', ''))
                except:
                    pass
        
        return None
    
    @staticmethod
    def _extract_pools(promo: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Извлекает данные о пулах"""
        pools = []
        
        # Прямое поле pools
        if promo.get('pools'):
            raw_pools = promo['pools']
            # Может быть список LaunchpoolPool объектов или словарей
            for p in raw_pools:
                if hasattr(p, '__dict__'):
                    # Это dataclass/object
                    pools.append({
                        'stake_coin': getattr(p, 'stake_coin', ''),
                        'apr': getattr(p, 'apr', 0),
                        'min_stake': getattr(p, 'min_stake', 0),
                        'max_stake': getattr(p, 'max_stake', 0),
                        'participants': getattr(p, 'participants', 0),
                    })
                elif isinstance(p, dict):
                    pools.append(p)
        
        # Из raw_data (Bybit)
        raw = promo.get('raw_data', {})
        if raw and not pools:
            stake_pools = raw.get('stakePoolList', [])
            for sp in stake_pools:
                pools.append({
                    'stake_coin': sp.get('stakeCoin', ''),
                    'apr': float(sp.get('apr', 0)),
                    'min_stake': float(sp.get('minStakeAmount', 0)),
                    'max_stake': float(sp.get('maxStakeAmount', 0)),
                    'participants': int(sp.get('totalUser', 0)),
                })
            
            # Gate.io format
            reward_pools = raw.get('reward_pools', [])
            for rp in reward_pools:
                pools.append({
                    'stake_coin': rp.get('coin', ''),
                    'apr': float(rp.get('maybe_year_rate', 0)),
                    'min_stake': float(rp.get('personal_min_amount', 0)),
                    'max_stake': float(rp.get('personal_max_amount', 0)),
                    'participants': int(rp.get('order_count', 0)),
                })
            
            # Bitget format
            product_subs = raw.get('productSubList', [])
            for ps in product_subs:
                pools.append({
                    'stake_coin': ps.get('productSubCoinName', ''),
                    'apr': float(ps.get('apr', 0)),
                    'min_stake': float(ps.get('minAmount', 0)),
                    'max_stake': float(ps.get('userMaxAmount', 0)),
                    'participants': int(ps.get('participants', 0)),
                })
        
        # Если пулов нет, пробуем собрать из promo напрямую
        if not pools and promo.get('apr'):
            pools.append({
                'stake_coin': promo.get('stake_coin', promo.get('coin', 'TOKEN')),
                'apr': float(promo.get('apr', 0)),
                'min_stake': float(promo.get('min_stake', 0)),
                'max_stake': float(promo.get('max_stake', 0)),
                'participants': int(promo.get('participants', 0)),
            })
        
        return pools
    
    @staticmethod
    def _calculate_days_left(end_time: Any) -> int:
        """Вычисляет количество дней до окончания"""
        if not end_time:
            return 0
        
        now = datetime.now()
        
        # Конвертируем в datetime
        if isinstance(end_time, str):
            formats = ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']
            for fmt in formats:
                try:
                    end_time = datetime.strptime(end_time, fmt)
                    break
                except:
                    continue
            else:
                return 0
        elif isinstance(end_time, (int, float)):
            try:
                if end_time > 10**12:
                    end_time = datetime.fromtimestamp(end_time / 1000)
                else:
                    end_time = datetime.fromtimestamp(end_time)
            except:
                return 0
        
        if isinstance(end_time, datetime):
            delta = end_time - now
            return max(0, delta.days + 1)  # +1 чтобы включить текущий день
        
        return 0
    
    @staticmethod
    def _format_pool(pool: Dict[str, Any], max_apr: float, days_left: int) -> str:
        """Форматирует один пул для фарминга"""
        stake_coin = pool.get('stake_coin', 'TOKEN')
        apr = pool.get('apr', 0)
        max_stake = pool.get('max_stake', 0)
        
        if not stake_coin or apr <= 0:
            return ""
        
        # APR с пометкой 🔥 для максимального
        apr_str = f"{apr:.0f}%" if apr < 100 else f"{apr:.0f}%"
        if apr == max_apr and apr >= 50:
            apr_str += " 🔥"
        
        # Лимит
        limit_str = ""
        if max_stake:
            if max_stake >= 1000:
                limit_str = f"до {format_number_short(max_stake)}"
            else:
                limit_str = f"до {max_stake:.0f}"
        
        # Заголовок пула
        line = f"📊 {stake_coin} │ APR {apr_str}"
        if limit_str:
            line += f" │ {limit_str}"
        
        # Расчёт дохода
        if days_left and days_left > 0 and apr > 0 and max_stake:
            earnings_block = LaunchpoolFormatter._calculate_earnings(
                apr, max_stake, days_left, stake_coin
            )
            if earnings_block:
                line += f"\n{earnings_block}"
        
        return line
    
    @staticmethod
    def _calculate_earnings(apr: float, max_stake: float, days: int, stake_coin: str) -> str:
        """Рассчитывает доход для разных сумм"""
        lines = [f"💵 СТЕЙК → ДОХІД ({days}д):"]
        
        # Определяем суммы для расчёта (относительно max_stake)
        amounts = []
        
        # Маленькая сумма: 10% от макс или фиксированная
        small = min(max_stake * 0.1, 1000)
        if small < 10:
            small = 10
        amounts.append(small)
        
        # Средняя сумма: 50% от макс
        medium = max_stake * 0.5
        amounts.append(medium)
        
        # Максимальная сумма
        amounts.append(max_stake)
        
        # Убираем дубликаты и сортируем
        amounts = sorted(set([round(a, -1 if a >= 100 else 0) for a in amounts if a > 0]))
        
        for i, amount in enumerate(amounts[:3]):
            # Расчёт дохода: сумма * (APR/100) * (дни/365)
            earnings = amount * (apr / 100) * (days / 365)
            
            # Префикс дерева
            if i < len(amounts) - 1:
                prefix = "   ├─"
            else:
                prefix = "   └─"
            
            # Звёздочка для максимальной суммы
            star = " ⭐" if i == len(amounts) - 1 else ""
            
            # Форматирование суммы
            if amount >= 1000:
                amount_str = f"${format_number_short(amount)}"
            else:
                amount_str = f"${amount:.0f}"
            
            lines.append(f"{prefix} {amount_str} → +${earnings:.2f}{star}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_time_line(start_time: Any, end_time: Any) -> str:
        """Форматирует строку со временем"""
        parts = []
        
        start_str = format_date_short(start_time)
        end_str = format_date_short(end_time)
        
        if start_str and end_str:
            parts.append(f"⏰ {start_str} → {end_str}")
        elif end_str:
            parts.append(f"⏰ до {end_str}")
        
        remaining = format_time_remaining(end_time)
        if remaining and remaining != "Завершено":
            parts.append(f"⏳ {remaining}")
        elif remaining == "Завершено":
            parts.append("⏳ Завершено")
        
        return " │ ".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════════
# AIRDROP ФОРМАТТЕР
# ═══════════════════════════════════════════════════════════════════════════════

class AirdropFormatter:
    """
    Универсальный форматтер для Airdrop уведомлений.
    
    Поддерживает:
    - Bybit Token Splash (BybitTS)
    - OKX Boost (X Launch)
    - MEXC Airdrop+
    - Weex Token Airdrop
    
    Формат адаптивный - показывает только доступные поля.
    """
    
    # Типы промо по биржам
    PROMO_TYPES = {
        'bybit': 'PROMO',
        'okx': 'BOOST',
        'mexc': 'AIRDROP+',
        'weex': 'AIRDROP',
        'default': 'AIRDROP'
    }
    
    @staticmethod
    def format(promo: Dict[str, Any], is_new: bool = True) -> str:
        """
        Форматирует Airdrop промоакцию.
        
        Args:
            promo: Данные промоакции
            is_new: Показывать метку NEW
            
        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # ═══════════════════════════════════════════════════════════════
            # ИЗВЛЕЧЕНИЕ ДАННЫХ
            # ═══════════════════════════════════════════════════════════════
            
            exchange = promo.get('exchange', 'Unknown')
            exchange_lower = exchange.lower().replace('.io', '').replace(' ', '')
            exchange_name = get_exchange_name(exchange)
            exchange_icon = get_exchange_icon(exchange)
            
            # Определяем тип промо
            promo_type = AirdropFormatter.PROMO_TYPES.get(
                exchange_lower, 
                AirdropFormatter.PROMO_TYPES['default']
            )
            
            # Название и токен
            title = promo.get('title', '') or promo.get('token_name', '') or promo.get('tokenFullName', '')
            token_symbol = (promo.get('award_token', '') or 
                          promo.get('prizeToken', '') or 
                          promo.get('token', '') or
                          promo.get('token_symbol', ''))
            
            # Призовой фонд
            total_prize_pool = AirdropFormatter._get_prize_pool(promo)
            
            # Токен приза - из явных полей или из строки призового фонда
            prize_token = AirdropFormatter._get_prize_token(promo)
            
            # USD эквивалент
            usd_value = AirdropFormatter._get_usd_value(promo, total_prize_pool, prize_token)
            
            # Призовые места и награда на место (Bybit)
            winners_count = promo.get('winners_count')
            reward_per_winner = promo.get('reward_per_winner')
            reward_per_winner_usd = None
            
            if winners_count and total_prize_pool and not reward_per_winner:
                try:
                    reward_amount = float(total_prize_pool) / int(winners_count)
                    reward_per_winner = f"{reward_amount:,.0f} {prize_token}"
                    if usd_value:
                        reward_per_winner_usd = usd_value / int(winners_count)
                except:
                    pass
            
            # Участники (OKX, Weex)
            participants = (promo.get('participants_count') or 
                          promo.get('participants') or
                          promo.get('applyNum'))
            
            # Время
            start_time = promo.get('start_time') or promo.get('depositStart') or promo.get('join_start_time')
            end_time = promo.get('end_time') or promo.get('depositEnd') or promo.get('join_end_time')
            
            # Ссылка и ID
            link = promo.get('link', '') or promo.get('project_url', '')
            promo_id = promo.get('promo_id', '')
            
            # ═══════════════════════════════════════════════════════════════
            # ФОРМИРОВАНИЕ СООБЩЕНИЯ
            # ═══════════════════════════════════════════════════════════════
            
            # Заголовок: 🟡 BYBIT | 📌 PROMO | 🆕 NEW
            new_badge = " | 🆕 NEW" if is_new else ""
            message = f"{exchange_icon} <b>{exchange_name}</b> | 📌 <b>{promo_type}</b>{new_badge}\n\n"
            
            # 📛 Название
            if title and token_symbol and title.upper() != token_symbol.upper():
                message += f"📛 <b>Название:</b> {escape_html(title)} ({escape_html(token_symbol)})\n"
            elif title:
                message += f"📛 <b>Название:</b> {escape_html(title)}\n"
            elif token_symbol:
                message += f"📛 <b>Название:</b> {escape_html(token_symbol)}\n"
            
            # 💰 Призовой фонд
            if total_prize_pool:
                prize_str = f"{format_number(total_prize_pool)} {prize_token}"
                if usd_value:
                    prize_str += f" (~${format_number(usd_value)})"
                message += f"💰 <b>Призовой фонд:</b> {prize_str}\n"
            
            # 🏆 Призовых мест (только если есть)
            if winners_count:
                message += f"🏆 <b>Призовых мест:</b> {format_number(winners_count)}\n"
            
            # 🎁 Награда на аккаунт (только если есть)
            if reward_per_winner:
                reward_str = escape_html(str(reward_per_winner))
                if reward_per_winner_usd:
                    reward_str += f" (~${reward_per_winner_usd:,.2f})"
                message += f"🎁 <b>Награда на аккаунт:</b> {reward_str}\n"
            
            # 👥 Участников (для OKX, Weex)
            if participants and not winners_count:
                message += f"👥 <b>Участников:</b> {format_number(participants)}\n"
            
            # 🎯 Тип (для OKX Boost - пропорциональный)
            if exchange_lower == 'okx':
                message += f"🎯 <b>Тип:</b> Пропорциональный (Boost Points)\n"
            
            # 📅 Период
            time_str = AirdropFormatter._format_period(start_time, end_time)
            if time_str:
                message += f"📅 <b>Период:</b> {time_str}\n"
            
            # 🔗 Ссылка
            if link:
                message += f"🔗 <b>Ссылка:</b> {escape_html(link)}\n"
            
            # ID
            if promo_id:
                message += f"\n<code>ID: {escape_html(str(promo_id))}</code>"
            
            # Проверка лимита Telegram
            if len(message) > 4090:
                message = message[:4000] + "\n\n<i>⚠️ Сообщение обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Airdrop: {e}", exc_info=True)
            return f"🪂 <b>AIRDROP</b>\n\n❌ Ошибка форматирования"
    
    @staticmethod
    def _get_prize_pool(promo: Dict[str, Any]) -> Optional[float]:
        """Извлекает призовой фонд из разных полей"""
        for field in ['total_prize_pool', 'totalPrizePool', 'total_pool_tokens', 'prize_pool']:
            value = promo.get(field)
            if value:
                try:
                    # Конвертируем в строку
                    val_str = str(value)
                    
                    # Убираем валюты/токены из строки (USDT, USD, etc)
                    import re
                    # Извлекаем только число (с запятыми и точкой)
                    numbers = re.findall(r'[\d,\.]+', val_str)
                    if numbers:
                        clean = numbers[0].replace(',', '')
                        return float(clean)
                except:
                    pass
        
        # OKX Boost: reward.amount
        reward = promo.get('reward', {})
        if isinstance(reward, dict) and reward.get('amount'):
            try:
                return float(reward['amount'])
            except:
                pass
        
        return None
    
    @staticmethod
    def _get_prize_token(promo: Dict[str, Any]) -> str:
        """Извлекает токен из призового фонда (если записан в строке)"""
        # Сначала проверяем есть ли токен в строке призового фонда (приоритет для Weex)
        prize_pool = promo.get('total_prize_pool', '')
        if isinstance(prize_pool, str):
            import re
            # Ищем слово после числа (USDT, SKR, etc)
            match = re.search(r'[\d,\.]+\s*([A-Za-z]+)', prize_pool)
            if match:
                return match.group(1).upper()
        
        # Затем проверяем явные поля токена
        for field in ['award_token', 'prizeToken', 'token', 'token_symbol']:
            token = promo.get(field)
            if token:
                return str(token).upper()
        
        return 'TOKEN'
    
    @staticmethod
    def _get_usd_value(promo: Dict[str, Any], amount: float, token: str) -> Optional[float]:
        """Получает USD эквивалент призового фонда"""
        if not amount or not token:
            return None
        
        # Если токен уже USDT/USDC
        if token.upper() in ('USDT', 'USDC', 'USD', 'BUSD', 'DAI'):
            return amount
        
        # Проверяем есть ли готовое значение в данных
        for field in ['total_pool_usd', 'prize_pool_usd', 'total_prize_pool_usd']:
            value = promo.get(field)
            if value:
                try:
                    return float(value)
                except:
                    pass
        
        # Используем PriceFetcher
        try:
            from utils.price_fetcher import get_price_fetcher
            fetcher = get_price_fetcher()
            
            exchange = promo.get('exchange', '').lower()
            price = fetcher.get_token_price(token, preferred_exchange=exchange)
            
            if price:
                return amount * price
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить цену {token}: {e}")
        
        return None
    
    @staticmethod
    def _format_period(start_time: Any, end_time: Any) -> str:
        """Форматирует период проведения"""
        start_str = AirdropFormatter._format_datetime(start_time)
        end_str = AirdropFormatter._format_datetime(end_time)
        
        # Базовый период
        if start_str and end_str:
            period = f"{start_str} - {end_str}"
        elif end_str:
            period = f"до {end_str}"
        elif start_str:
            period = f"с {start_str}"
        else:
            return ""
        
        # Добавляем оставшееся время
        remaining = format_time_remaining(end_time)
        if remaining and remaining != "Завершено":
            period += f" (⏳ {remaining})"
        elif remaining == "Завершено":
            period += " (⏳ Завершено)"
        
        return period
    
    @staticmethod
    def _format_datetime(dt: Any) -> str:
        """Форматирует дату и время"""
        if not dt:
            return ""
        
        # Конвертируем timestamp
        if isinstance(dt, (int, float)):
            try:
                if dt > 10**12:
                    dt = datetime.fromtimestamp(dt / 1000)
                else:
                    dt = datetime.fromtimestamp(dt)
            except:
                return ""
        
        # Конвертируем строку
        if isinstance(dt, str):
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(dt, fmt)
                    break
                except:
                    continue
            else:
                return dt[:16] if len(dt) >= 16 else dt
        
        if isinstance(dt, datetime):
            return dt.strftime("%d.%m.%Y %H:%M")
        
        return str(dt)


# ═══════════════════════════════════════════════════════════════════════════════
# CANDYBOMB FORMATTER (Gate Candy, Bitget Candy Bomb, Phemex Candy Drop)
# ═══════════════════════════════════════════════════════════════════════════════

class CandybombFormatter:
    """
    Форматтер для Candy Drop / Candy Bomb промоакцій.
    
    Підтримувані біржі:
    - Gate.io Candy Drop (з завданнями та типами нагород)
    - Bitget Candy Bomb (з умовами участі)
    - Phemex Candy Drop
    """
    
    # Іконки бірж
    EXCHANGE_ICONS = {
        'gate': '⚪',
        'gate.io': '⚪',
        'bitget': '🔴',
        'phemex': '🟪',
    }
    
    # Типи промо
    PROMO_TYPES = {
        'gate': 'CANDY DROP',
        'gate.io': 'CANDY DROP',
        'bitget': 'CANDY BOMB',
        'phemex': 'CANDY DROP',
    }
    
    @staticmethod
    def format(promo: Dict[str, Any], is_new: bool = True) -> str:
        """
        Форматує повідомлення для Candybomb промоакції.
        
        Args:
            promo: Словник з даними промоакції
            is_new: Чи нова промоакція
            
        Returns:
            HTML відформатоване повідомлення
        """
        try:
            # Визначаємо біржу
            exchange = promo.get('exchange', '').lower()
            if not exchange:
                promo_id = str(promo.get('promo_id', '')).lower()
                if 'gate' in promo_id:
                    exchange = 'gate'
                elif 'bitget' in promo_id:
                    exchange = 'bitget'
                elif 'phemex' in promo_id:
                    exchange = 'phemex'
                else:
                    exchange = 'unknown'
            
            # Іконка та тип
            icon = CandybombFormatter.EXCHANGE_ICONS.get(exchange, '🍬')
            promo_type = CandybombFormatter.PROMO_TYPES.get(exchange, 'CANDY')
            exchange_name = exchange.upper().replace('.IO', '.io')
            if exchange == 'gate':
                exchange_name = 'GATE.IO'
            
            new_badge = " | 🆕 NEW" if is_new else ""
            
            lines = []
            
            # Заголовок
            lines.append(f"{icon} <b>{exchange_name}</b> | 🍬 <b>{promo_type}</b>{new_badge}")
            lines.append("")
            
            # Токен
            token = CandybombFormatter._get_token(promo)
            title = promo.get('title', '')
            
            # Для Gate.io використовуємо title як назву
            if exchange in ('gate', 'gate.io') and title:
                lines.append(f"📛 <b>Назва:</b> {title}")
                lines.append(f"🪙 <b>Токен:</b> {token}")
            else:
                lines.append(f"📛 <b>Токен:</b> {token}")
            
            # Призовий фонд
            raw_data = promo.get('raw_data', {})
            if isinstance(raw_data, str):
                try:
                    import json
                    raw_data = json.loads(raw_data)
                except:
                    raw_data = {}
            
            # Якщо raw_data None - робимо пустий словник
            if raw_data is None:
                raw_data = {}
            
            prize_pool = CandybombFormatter._get_prize_pool(promo, raw_data)
            prize_usd = CandybombFormatter._get_prize_usd(promo, raw_data, token, prize_pool)
            
            if prize_pool:
                if prize_usd and token.upper() not in ('USDT', 'USDC', 'USD'):
                    lines.append(f"💰 <b>Призовий фонд:</b> {prize_pool:,.0f} {token} (~${prize_usd:,.0f})")
                else:
                    lines.append(f"💰 <b>Призовий фонд:</b> {prize_pool:,.0f} {token}")
            
            # Макс. на акаунт (тільки для Gate)
            if exchange in ('gate', 'gate.io'):
                max_reward = raw_data.get('user_max_rewards')
                max_reward_usd = raw_data.get('user_max_rewards_usdt')
                if max_reward:
                    try:
                        max_val = float(max_reward)
                        if max_reward_usd:
                            lines.append(f"🏆 <b>Макс. на акаунт:</b> {max_val:,.2f} {token} (~${float(max_reward_usd):,.0f})")
                        else:
                            lines.append(f"🏆 <b>Макс. на акаунт:</b> {max_val:,.2f} {token}")
                    except:
                        pass
            
            # Учасники
            participants = CandybombFormatter._get_participants(promo, raw_data)
            if participants:
                lines.append(f"👥 <b>Учасників:</b> {participants:,}")
            
            # === Специфічні поля для Gate ===
            if exchange in ('gate', 'gate.io'):
                # Завдання (rule_name)
                rule_names = raw_data.get('rule_name', [])
                if rule_names and isinstance(rule_names, list):
                    lines.append("")
                    lines.append("📋 <b>Завдання:</b>")
                    for rule in rule_names:
                        lines.append(f"  • {rule}")
                
                # Тип нагороди (reward_type)
                reward_types = raw_data.get('reward_type', [])
                if reward_types and isinstance(reward_types, list):
                    lines.append(f"🎁 <b>Тип нагороди:</b> {', '.join(reward_types)}")
            
            # === Специфічні поля для Bitget ===
            if exchange == 'bitget':
                conditions = CandybombFormatter._get_bitget_conditions(promo, raw_data)
                if conditions:
                    lines.append("")
                    lines.append(f"⚠️ <b>Умови:</b> {', '.join(conditions)}")
            
            # Період
            lines.append("")
            period = CandybombFormatter._format_period(promo)
            if period:
                lines.append(f"📅 <b>Період:</b> {period}")
            
            # Посилання
            link = promo.get('link', promo.get('project_url', ''))
            if link:
                lines.append(f"🔗 <b>Посилання:</b> {link}")
            
            # ID промоакції
            promo_id = promo.get('promo_id', '')
            if promo_id:
                lines.append("")
                lines.append(f"<code>ID: {promo_id}</code>")
            
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"❌ Помилка форматування Candybomb: {e}", exc_info=True)
            return f"🍬 <b>CANDY DROP</b>\n\n❌ Помилка форматування"
    
    @staticmethod
    def _get_token(promo: Dict[str, Any]) -> str:
        """Отримує токен з промоакції"""
        for field in ['award_token', 'token_symbol', 'currency', 'token']:
            token = promo.get(field)
            if token:
                return str(token).upper()
        
        # Спроба з title (наприклад "Win up to 0.3 ETH")
        title = promo.get('title', '')
        if title:
            import re
            # Шукаємо токен в кінці title
            match = re.search(r'[\d,\.]+\s+([A-Z]{2,10})$', title)
            if match:
                return match.group(1)
        
        return 'TOKEN'
    
    @staticmethod
    def _get_prize_pool(promo: Dict[str, Any], raw_data: Dict[str, Any]) -> Optional[float]:
        """Отримує призовий фонд"""
        # З raw_data (Gate)
        total_rewards = raw_data.get('total_rewards')
        if total_rewards:
            try:
                return float(total_rewards)
            except:
                pass
        
        # Зі стандартних полів
        for field in ['total_prize_pool', 'ieoTotal', 'total_pool_tokens', 'prize_pool']:
            value = promo.get(field)
            if value:
                try:
                    return float(value)
                except:
                    pass
        
        return None
    
    @staticmethod
    def _get_prize_usd(promo: Dict[str, Any], raw_data: Dict[str, Any], token: str, amount: float) -> Optional[float]:
        """Отримує USD еквівалент"""
        if not amount:
            return None
        
        # Якщо токен вже стейбл
        if token.upper() in ('USDT', 'USDC', 'USD', 'BUSD', 'DAI'):
            return amount
        
        # З raw_data (Gate)
        total_usd = raw_data.get('total_rewards_usdt')
        if total_usd:
            try:
                return float(total_usd)
            except:
                pass
        
        # Bitget ieoTotalUsdt
        ieo_usd = promo.get('ieoTotalUsdt') or promo.get('total_pool_usd')
        if ieo_usd:
            try:
                return float(ieo_usd)
            except:
                pass
        
        # Використовуємо PriceFetcher
        try:
            from utils.price_fetcher import get_price_fetcher
            fetcher = get_price_fetcher()
            
            exchange = promo.get('exchange', '').lower()
            price = fetcher.get_token_price(token, preferred_exchange=exchange)
            
            if price:
                return amount * price
        except Exception as e:
            logger.debug(f"⚠️ Не вдалося отримати ціну {token}: {e}")
        
        return None
    
    @staticmethod
    def _get_participants(promo: Dict[str, Any], raw_data: Dict[str, Any]) -> Optional[int]:
        """Отримує кількість учасників"""
        # З raw_data
        participants = raw_data.get('participants')
        if participants:
            try:
                return int(participants)
            except:
                pass
        
        # Зі стандартних полів
        for field in ['participants_count', 'totalPeople', 'total_participants']:
            value = promo.get(field)
            if value:
                try:
                    return int(value)
                except:
                    pass
        
        return None
    
    @staticmethod
    def _get_bitget_conditions(promo: Dict[str, Any], raw_data: Dict[str, Any]) -> List[str]:
        """Отримує умови участі для Bitget"""
        conditions = []
        
        # Перевіряємо в title (парсер додає інфо в title)
        title = promo.get('title', '')
        if 'Нові користувачі' in title:
            if "ф'ючерсів" in title:
                conditions.append("Нові користувачі ф'ючерсів")
            else:
                conditions.append("Нові користувачі")
        if 'торгівля' in title.lower():
            conditions.append("Потрібна торгівля ф'ючерсами")
        
        # Перевіряємо raw_data
        if raw_data.get('newContractUserLabel'):
            if "Нові користувачі ф'ючерсів" not in conditions:
                conditions.append("Нові користувачі ф'ючерсів")
        if raw_data.get('newUserLabel'):
            if "Нові користувачі" not in conditions:
                conditions.append("Нові користувачі")
        
        biz_line = raw_data.get('bizLineLabel', '')
        if biz_line == 'contract' and not conditions:
            conditions.append("Ф'ючерси")
        
        return conditions
    
    @staticmethod
    def _format_period(promo: Dict[str, Any]) -> str:
        """Форматує період проведення"""
        start = promo.get('start_time')
        end = promo.get('end_time')
        
        start_str = CandybombFormatter._format_datetime(start)
        end_str = CandybombFormatter._format_datetime(end)
        
        # Базовий період
        if start_str and end_str:
            period = f"{start_str} - {end_str}"
        elif end_str:
            period = f"до {end_str}"
        elif start_str:
            period = f"з {start_str}"
        else:
            return ""
        
        # Додаємо час, що залишився
        remaining = format_time_remaining(end)
        if remaining and remaining != "Завершено":
            period += f" (⏳ {remaining})"
        elif remaining == "Завершено":
            period += " (⏳ Завершено)"
        
        return period
    
    @staticmethod
    def _format_datetime(dt: Any) -> str:
        """Форматує дату і час"""
        if not dt:
            return ""
        
        # Конвертуємо timestamp
        if isinstance(dt, (int, float)):
            try:
                if dt > 10**12:
                    dt = datetime.fromtimestamp(dt / 1000)
                else:
                    dt = datetime.fromtimestamp(dt)
            except:
                return ""
        
        # Конвертуємо строку
        if isinstance(dt, str):
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(dt, fmt)
                    break
                except:
                    continue
            else:
                return dt[:16] if len(dt) >= 16 else dt
        
        if isinstance(dt, datetime):
            return dt.strftime("%d.%m.%Y %H:%M")
        
        return str(dt)


# ═══════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENT ALERT FORMATTER (Browser-парсер анонсів)
# ═══════════════════════════════════════════════════════════════════════════════

class AnnouncementAlertFormatter:
    """
    Форматтер для сповіщень про нові анонси з браузерного парсера.
    
    Формат з рамками та попереднім переглядом:
    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃ 📣 НОВИЙ АНОНС │ MEXC      ┃
    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
    """
    
    # Іконки бірж
    EXCHANGE_ICONS = {
        'mexc': '🔵',
        'binance': '🟢',
        'bybit': '🟡',
        'okx': '🟠',
        'gate': '⚪',
        'bitget': '🔴',
        'kucoin': '🟤',
        'htx': '🔷',
    }
    
    # Типи анонсів за ключовими словами
    ANNOUNCEMENT_TYPES = {
        'airdrop': ('🪂', 'Airdrop'),
        'launchpad': ('🚀', 'Launchpad'),
        'launchpool': ('🌊', 'Launchpool'),
        'listing': ('📈', 'New Listing'),
        'delisting': ('📉', 'Delisting'),
        'staking': ('💎', 'Staking'),
        'trading': ('📊', 'Trading Event'),
        'competition': ('🏆', 'Competition'),
        'maintenance': ('🔧', 'Maintenance'),
        'update': ('🔄', 'Update'),
    }
    
    @staticmethod
    def format(
        link_name: str,
        result: Dict[str, Any],
        link_url: str = None
    ) -> str:
        """
        Форматує сповіщення про новий анонс.
        
        Args:
            link_name: Назва посилання (напр. "Mexc0%FEE")
            result: Результат парсингу з announcement_parser
            link_url: URL сторінки анонсів
            
        Returns:
            Відформатоване HTML повідомлення
        """
        try:
            # Визначаємо біржу
            exchange = AnnouncementAlertFormatter._detect_exchange(link_name, link_url)
            exchange_icon = AnnouncementAlertFormatter.EXCHANGE_ICONS.get(exchange.lower(), '📣')
            exchange_name = exchange.upper()
            
            # Отримуємо дані
            matched_keywords = result.get('matched_keywords', [])
            if not matched_keywords:
                # Парсимо з message якщо є
                message = result.get('message', '')
                if 'ключевые слова:' in message.lower():
                    import re
                    match = re.search(r'ключевые слова:\s*(.+)', message, re.IGNORECASE)
                    if match:
                        matched_keywords = [kw.strip() for kw in match.group(1).split(',')]
            
            announcement_links = result.get('announcement_links', [])
            matched_content = result.get('matched_content', '')
            
            # Визначаємо тип анонсу
            ann_type_icon, ann_type_name = AnnouncementAlertFormatter._detect_type(matched_keywords)
            
            # === ФОРМУЄМО ПОВІДОМЛЕННЯ ===
            lines = []
            
            # Заголовок з рамкою
            header_text = f"📣 НОВИЙ АНОНС │ {exchange_name}"
            header_width = max(29, len(header_text) + 2)
            
            lines.append(f"┏{'━' * header_width}┓")
            lines.append(f"┃ {exchange_icon} {header_text.ljust(header_width - 3)}┃")
            lines.append(f"┗{'━' * header_width}┛")
            lines.append("")
            
            # Заголовок анонсу (якщо є)
            if announcement_links:
                first_ann = announcement_links[0]
                title = first_ann.get('title', '')
                if title:
                    # Обрізаємо довгий заголовок
                    if len(title) > 50:
                        title = title[:47] + "..."
                    lines.append(f"📰 <b>{escape_html(title)}</b>")
                    lines.append("")
            
            # Тип анонсу
            lines.append(f"🏷️ <b>Тип:</b> {ann_type_icon} {ann_type_name}")
            
            # Триггери (ключові слова)
            if matched_keywords:
                keywords_str = ", ".join([f"<code>{escape_html(kw)}</code>" for kw in matched_keywords[:5]])
                lines.append(f"🔑 <b>Триггеры:</b> {keywords_str}")
            
            # Час виявлення
            lines.append(f"📅 <b>Обнаружено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            
            # Попередній перегляд тексту (якщо є)
            preview_text = AnnouncementAlertFormatter._get_preview_text(result, announcement_links)
            if preview_text:
                lines.append("")
                lines.append("━━━ ПРЕДПРОСМОТР ━━━")
                # Обмежуємо текст 150 символами
                if len(preview_text) > 150:
                    preview_text = preview_text[:147] + "..."
                lines.append(f"<i>{escape_html(preview_text)}</i>")
                lines.append("━━━━━━━━━━━━━━━━━━━━")
            
            # Список знайдених анонсів
            if len(announcement_links) > 1:
                lines.append("")
                lines.append(f"📋 <b>Найдено анонсов:</b> {len(announcement_links)}")
                for i, ann in enumerate(announcement_links[:3], 1):
                    ann_title = ann.get('title', 'Без названия')
                    if len(ann_title) > 40:
                        ann_title = ann_title[:37] + "..."
                    ann_url = ann.get('url', '')
                    if ann_url:
                        lines.append(f"   {i}. <a href=\"{ann_url}\">{escape_html(ann_title)}</a>")
                    else:
                        lines.append(f"   {i}. {escape_html(ann_title)}")
                
                if len(announcement_links) > 3:
                    lines.append(f"   <i>...и ещё {len(announcement_links) - 3}</i>")
            
            # Посилання
            lines.append("")
            if announcement_links and announcement_links[0].get('url'):
                first_url = announcement_links[0]['url']
                # Скорочуємо URL для краси
                short_url = first_url.replace('https://', '').replace('http://', '').replace('www.', '')
                if len(short_url) > 35:
                    short_url = short_url[:32] + "..."
                lines.append(f"👉 <b>Подробнее:</b> <a href=\"{first_url}\">{short_url}</a>")
            elif link_url:
                short_url = link_url.replace('https://', '').replace('http://', '').replace('www.', '')
                if len(short_url) > 35:
                    short_url = short_url[:32] + "..."
                lines.append(f"🔗 <b>Страница:</b> <a href=\"{link_url}\">{short_url}</a>")
            
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Announcement: {e}", exc_info=True)
            return f"📣 <b>НОВЫЙ АНОНС</b>\n\n{result.get('message', 'Обнаружены изменения')}"
    
    @staticmethod
    def _detect_exchange(link_name: str, link_url: str = None) -> str:
        """Визначає біржу з назви посилання або URL"""
        search_text = f"{link_name} {link_url or ''}".lower()
        
        exchanges = ['mexc', 'binance', 'bybit', 'okx', 'gate', 'bitget', 'kucoin', 'htx', 'weex', 'bingx']
        for ex in exchanges:
            if ex in search_text:
                return ex
        
        return 'Crypto'
    
    @staticmethod
    def _detect_type(keywords: List[str]) -> Tuple[str, str]:
        """Визначає тип анонсу за ключовими словами"""
        keywords_lower = [kw.lower() for kw in keywords]
        
        for keyword, (icon, name) in AnnouncementAlertFormatter.ANNOUNCEMENT_TYPES.items():
            if keyword in keywords_lower or any(keyword in kw for kw in keywords_lower):
                return icon, name
        
        # За замовчуванням
        return '📢', 'Announcement'
    
    @staticmethod
    def _get_preview_text(result: Dict[str, Any], announcement_links: List[Dict]) -> str:
        """Отримує текст для попереднього перегляду"""
        # Спочатку пробуємо description з першого анонсу
        if announcement_links:
            first_ann = announcement_links[0]
            description = first_ann.get('description', '')
            if description and len(description) > 20:
                return description
        
        # Потім matched_content
        matched_content = result.get('matched_content', '')
        if matched_content and 'ключевые слова' not in matched_content.lower():
            return matched_content
        
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

def format_promo_by_category(promo: Dict[str, Any], category: str = None, is_new: bool = True) -> str:
    """
    Универсальная функция форматирования по категории.
    
    Args:
        promo: Данные промоакции
        category: Категория (launchpad, launchpool, airdrop, staking, etc.)
        is_new: Показывать метку NEW
        
    Returns:
        Отформатированное HTML сообщение
    """
    # Автоопределение категории
    if not category:
        promo_type = promo.get('promo_type', '').lower()
        promo_id = str(promo.get('promo_id', '')).lower()
        exchange_type = promo.get('type', '').lower()
        
        if 'launchpool' in promo_type or 'launchpool' in promo_id or exchange_type == 'launchpool':
            category = 'launchpool'
        elif 'launchpad' in promo_type or 'launchpad' in promo_id or exchange_type == 'launchpad':
            category = 'launchpad'
        elif 'candybomb' in promo_type or 'candybomb' in promo_id or 'candy-bomb' in promo_id or 'candydrop' in promo_type or 'candy-drop' in promo_id:
            category = 'candybomb'
        elif 'airdrop' in promo_type or 'airdrop' in promo_id:
            category = 'airdrop'
        elif 'staking' in promo_type or 'staking' in promo_id:
            category = 'staking'
        elif 'candy' in promo_type or 'candy' in promo_id:
            category = 'candybomb'  # Map old 'candy' to 'candybomb'
        elif 'boost' in promo_type or 'boost' in promo_id:
            category = 'boost'
        else:
            category = 'launchpad'  # Default
    
    # Выбор форматтера
    if category == 'launchpad':
        return LaunchpadFormatter.format(promo, is_new)
    elif category == 'launchpool':
        return LaunchpoolFormatter.format(promo, is_new)
    elif category in ('airdrop', 'boost'):
        return AirdropFormatter.format(promo, is_new)
    elif category == 'candybomb':
        return CandybombFormatter.format(promo, is_new)
    else:
        # Fallback на launchpad
        return LaunchpadFormatter.format(promo, is_new)


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТИРОВАНИЕ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Тестовые данные MEXC Launchpad
    test_mexc = {
        'exchange': 'MEXC',
        'promo_id': 'mexc_launchpad_44',
        'title': 'Seeker',
        'award_token': 'SKR',
        'total_prize_pool': '3000000',
        'min_price': 0.005,
        'market_price': 0.015,
        'max_discount': 70,
        'participants_count': 111,
        'start_time': 1737262800000,
        'end_time': 1737435600000,
        'link': 'https://www.mexc.com/ru-RU/launchpad/44',
        'raw_data': {
            'launchpadTakingCoins': [
                {'minLimit': 100, 'maxLimit': 10000}
            ]
        }
    }
    
    # Тестовые данные Gate.io Launchpad
    test_gate = {
        'exchange': 'Gate.io',
        'promo_id': 'gate_launchpad_2374',
        'title': 'Immunefi',
        'award_token': 'IMU',
        'total_prize_pool': '3000000',
        'min_price': 0.15,
        'market_price': 0.25,
        'start_time': 1768878000,
        'end_time': 1769680800,
        'link': 'https://www.gate.com/ru/launchpad/2374',
    }
    
    # Тестовые данные Bybit Launchpool
    test_launchpool_bybit = {
        'exchange': 'Bybit',
        'promo_id': 'bybit_launchpool_20260119073908',
        'type': 'launchpool',
        'token_symbol': 'ELSA',
        'token_name': 'Elsa Token',
        'total_pool_tokens': 3000000,
        'total_pool_usd': 150000,
        'start_time': 1768878000000,
        'end_time': 1769680800000,
        'link': 'https://www.bybit.com/en/trade/spot/launchpool/20260119073908',
        'pools': [
            {'stake_coin': 'USDT', 'apr': 150, 'min_stake': 100, 'max_stake': 10000, 'participants': 500},
            {'stake_coin': 'ELSA', 'apr': 800, 'min_stake': 400, 'max_stake': 20000, 'participants': 300},
        ]
    }
    
    # Тестовые данные Gate.io Launchpool
    test_launchpool_gate = {
        'exchange': 'Gate.io',
        'promo_id': 'gate_launchpool_491',
        'type': 'launchpool',
        'token_symbol': 'FOGO',
        'token_name': 'FOGO Token',
        'total_pool_tokens': 5000000,
        'total_pool_usd': 250000,
        'start_time': 1768878000,
        'end_time': 1769680800,
        'link': 'https://www.gate.com/ru/launchpool',
        'pools': [
            {'stake_coin': 'GT', 'apr': 45, 'min_stake': 10, 'max_stake': 5000, 'participants': 1200},
            {'stake_coin': 'USDT', 'apr': 35, 'min_stake': 100, 'max_stake': 50000, 'participants': 800},
        ]
    }
    
    def clean_html(text):
        return text.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<i>', '').replace('</i>', '')
    
    print("=" * 60)
    print("ТЕСТ 1: MEXC LAUNCHPAD")
    print("=" * 60)
    result = LaunchpadFormatter.format(test_mexc)
    print(clean_html(result))
    
    print("\n" + "=" * 60)
    print("ТЕСТ 2: GATE.IO LAUNCHPAD")
    print("=" * 60)
    result = LaunchpadFormatter.format(test_gate)
    print(clean_html(result))
    
    print("\n" + "=" * 60)
    print("ТЕСТ 3: BYBIT LAUNCHPOOL")
    print("=" * 60)
    result = LaunchpoolFormatter.format(test_launchpool_bybit)
    print(clean_html(result))
    
    print("\n" + "=" * 60)
    print("ТЕСТ 4: GATE.IO LAUNCHPOOL")
    print("=" * 60)
    result = LaunchpoolFormatter.format(test_launchpool_gate)
    print(clean_html(result))
    
    print("\n" + "=" * 60)
    print("ТЕСТ 5: AUTO-DETECT (format_promo_by_category)")
    print("=" * 60)
    result = format_promo_by_category(test_launchpool_bybit)
    print(clean_html(result))
