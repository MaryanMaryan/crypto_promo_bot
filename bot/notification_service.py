import logging
import html
import re
from datetime import datetime
from aiogram import Bot
from typing import List, Dict, Any, Optional, Tuple

# Универсальный форматтер заголовков
from utils.promo_formatter import format_promo_header, format_promo_header_simple, get_exchange_icon, get_category_icon

# Новые универсальные форматтеры по категориям
from utils.message_formatters import (
    LaunchpadFormatter, 
    LaunchpoolFormatter, 
    BybitTokenSplashFormatter,
    AirdropFormatter,
    format_promo_by_category, 
    format_time_remaining,
    format_universal_header
)

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, bot: Bot, price_fetcher=None, skip_price_fetch: bool = False):
        self.bot = bot
        self.price_fetcher = price_fetcher
        self.skip_price_fetch = skip_price_fetch

        # ИЗМЕНЕНО: Всегда создаём price_fetcher для fallback случаев
        # skip_price_fetch теперь означает "не запрашивать цены активно, только как fallback"
        if self.price_fetcher is None:
            try:
                from utils.price_fetcher import get_price_fetcher
                self.price_fetcher = get_price_fetcher()
            except Exception as e:
                logger.warning(f"⚠️ Не удалось инициализировать price_fetcher: {e}")
                self.price_fetcher = None

    @staticmethod
    def format_timestamp(timestamp) -> str:
        """
        Конвертирует timestamp (секунды или миллисекунды) в читаемую дату.
        Возвращает строку вида "28.01.2026 20:00" или исходное значение если не удалось распарсить.
        """
        if timestamp is None:
            return 'N/A'
        
        try:
            # Если уже строка с датой - возвращаем как есть
            if isinstance(timestamp, str):
                # Проверяем, это числовая строка или уже дата
                if not timestamp.isdigit():
                    return timestamp
                timestamp = int(timestamp)
            
            # Если число слишком большое - это миллисекунды, конвертируем в секунды
            if isinstance(timestamp, (int, float)):
                if timestamp > 9999999999:  # Больше 10^10 = миллисекунды
                    timestamp = timestamp / 1000
                
                dt = datetime.fromtimestamp(timestamp)
                return dt.strftime("%d.%m.%Y %H:%M")
            
            return str(timestamp)
        except Exception:
            return str(timestamp)

    # URL-ссылки на страницы стейкингов по биржам
    STAKING_URLS = {
        'bybit': 'https://www.bybit.com/earn',
        'kucoin': 'https://www.kucoin.com/earn',
        'gate': 'https://www.gate.io/hodl',
        'gate.io': 'https://www.gate.io/hodl',
        'mexc': 'https://www.mexc.com/earn',
        'okx': 'https://www.okx.com/earn',
        'binance': 'https://www.binance.com/earn',
        'bitget': 'https://www.bitget.com/earn',
    }

    @staticmethod
    def escape_html(text: Any) -> str:
        """Безопасное экранирование HTML-символов"""
        if text is None:
            return 'N/A'
        return html.escape(str(text))

    @staticmethod
    def calculate_staking_earnings(
        user_limit: float,
        apr: float,
        term_days: int = 0,
        token_price: float = None,
        coin: str = None
    ) -> tuple:
        """
        Рассчитывает заработок от стейкинга
        
        Args:
            user_limit: Максимальный лимит в токенах
            apr: Годовая процентная ставка
            term_days: Срок стейкинга (0 = Flexible)
            token_price: Цена токена в USD
            coin: Символ монеты
        
        Returns:
            tuple: (earnings_tokens, earnings_usd, period_text, formatted_string)
        """
        if not user_limit or user_limit <= 0 or not apr or apr <= 0:
            return None, None, None, None
        
        coin = coin or 'TOKEN'
        
        if term_days > 0:  # Fixed стейкинг
            # Заработок за весь период
            earnings_tokens = (user_limit * apr / 100) * (term_days / 365)
            
            # Текст периода
            if term_days == 1:
                period_text = "за 1 день"
            elif term_days < 5:
                period_text = f"за {term_days} дня"
            else:
                period_text = f"за {term_days} дней"
        else:  # Flexible стейкинг
            # Заработок в день
            earnings_tokens = (user_limit * apr / 100) / 365
            period_text = "в день"
        
        # Конвертация в USD
        earnings_usd = earnings_tokens * token_price if token_price else None
        
        # Форматирование числа токенов
        if earnings_tokens >= 1000:
            tokens_str = f"{earnings_tokens:,.2f}"
        elif earnings_tokens >= 1:
            tokens_str = f"{earnings_tokens:.2f}"
        elif earnings_tokens >= 0.0001:
            tokens_str = f"{earnings_tokens:.4f}"
        else:
            tokens_str = f"{earnings_tokens:.6f}"
        
        # Форматирование USD с умным округлением
        if earnings_usd:
            if earnings_usd >= 1:
                usd_str = f"${earnings_usd:,.0f}"
            else:
                usd_str = f"${earnings_usd:.2f}"
        else:
            usd_str = None
        
        # Формируем строку
        if term_days == 0:  # Flexible - добавляем ~
            if usd_str:
                formatted = f"~{tokens_str} {coin} ({usd_str}) {period_text}"
            else:
                formatted = f"~{tokens_str} {coin} {period_text}"
        else:  # Fixed
            if usd_str:
                formatted = f"{tokens_str} {coin} ({usd_str}) {period_text}"
            else:
                formatted = f"{tokens_str} {coin} {period_text}"
        
        return earnings_tokens, earnings_usd, period_text, formatted

    def parse_token_amounts(self, text: str) -> List[Tuple[float, str, Optional[float]]]:
        """
        Парсит токены и их количество из текста

        Args:
            text: Текст для парсинга (например, "Win 100 BTC or 10,000 USDT Prize Pool")

        Returns:
            Список кортежей (amount, token_symbol, price_usd)
            Пример: [(100.0, 'BTC', 95000.0), (10000.0, 'USDT', 1.0)]
        """
        if not text:
            return []

        # Паттерн для поиска токенов:
        # - Число (с опциональными разделителями , и пробелами)
        # - Затем символ токена (обычно 2-6 заглавных букв)
        # Примеры: "100 BTC", "10,000 USDT", "1,500,000 SHIB"
        pattern = r'([\d,]+(?:\.\d+)?)\s*([A-Z]{2,10})(?:\s|$|,|\.|\)|!)'

        matches = re.findall(pattern, text)

        if not matches:
            logger.debug(f"🔍 Токены не найдены в тексте: {text[:100]}...")
            return []

        results = []
        for amount_str, token_symbol in matches:
            try:
                # Убираем запятые и конвертируем в float
                amount = float(amount_str.replace(',', ''))

                # Получаем цену токена
                price_usd = None
                if self.price_fetcher:
                    price_usd = self.price_fetcher.get_token_price(token_symbol)
                    if price_usd:
                        logger.info(f"💰 Найден токен: {amount} {token_symbol} = ${amount * price_usd:,.2f}")
                    else:
                        logger.warning(f"⚠️ Цена не найдена для {token_symbol}")
                else:
                    logger.warning(f"⚠️ Price fetcher недоступен для {token_symbol}")

                results.append((amount, token_symbol, price_usd))

            except (ValueError, TypeError) as e:
                logger.error(f"❌ Ошибка парсинга токена {amount_str} {token_symbol}: {e}")
                continue

        return results

    def format_token_value(self, amount: float, token_symbol: str, price_usd: Optional[float]) -> str:
        """
        Форматирует значение токена с опциональной ценой в USD

        Args:
            amount: Количество токенов
            token_symbol: Символ токена
            price_usd: Цена в USD (может быть None)

        Returns:
            Отформатированная строка
            Примеры:
            - "100 BTC (~$9,500,000)"
            - "10,000 USDT (~$10,000)"
            - "500 NEWTOKEN (цена недоступна)"
        """
        # Форматируем количество токенов
        if amount >= 1000:
            amount_str = f"{amount:,.0f}"
        else:
            amount_str = f"{amount:.2f}".rstrip('0').rstrip('.')

        # Добавляем цену в USD если доступна
        if price_usd:
            usd_value = amount * price_usd
            return f"{amount_str} {token_symbol} (~${usd_value:,.2f})"
        else:
            return f"{amount_str} {token_symbol} (цена недоступна)"

    def format_promo_message(self, promo: Dict[str, Any]) -> str:
        """Форматирует сообщение о промоакции в красивый HTML"""
        try:
            # ПРОВЕРКА: Если это launchpool с готовым форматированием - используем его
            if promo.get('is_launchpool') and promo.get('formatted_message'):
                return promo['formatted_message']
            
            # НОВОЕ: Универсальное форматирование для Launchpad и Launchpool
            promo_type = promo.get('promo_type', '').lower()
            promo_id = str(promo.get('promo_id', '')).lower()
            exchange_type = promo.get('type', '').lower()
            exchange = promo.get('exchange', '').lower()
            
            # BYBIT TOKEN SPLASH - универсальный форматтер для всех типов
            # Определяем по exchange='bybit' И по promo_id (начинается с 'bybit_' и содержит числовой код)
            is_bybit = 'bybit' in exchange
            is_tokensplash_id = promo_id.startswith('bybit_') and promo_id.replace('bybit_', '').replace('_', '').isdigit()
            
            # Также проверяем наличие характерных полей Token Splash
            has_tokensplash_fields = (
                promo.get('min_trade_amount') or 
                promo.get('reward_per_winner') or 
                promo.get('splash_type')
            )
            
            if is_bybit and (is_tokensplash_id or has_tokensplash_fields):
                # Проверяем что это НЕ launchpool
                if 'launchpool' not in promo_type and 'launchpool' not in promo_id:
                    return BybitTokenSplashFormatter.format(promo, is_new=True)
            
            # Launchpool - новый форматтер
            if 'launchpool' in promo_type or 'launchpool' in promo_id or exchange_type == 'launchpool':
                return LaunchpoolFormatter.format(promo, is_new=True)
            
            # Launchpad - существующий форматтер
            if 'launchpad' in promo_type or 'launchpad' in promo_id or exchange_type == 'launchpad':
                return LaunchpadFormatter.format(promo, is_new=True)
            
            # OKX Boost - используем AirdropFormatter (это airdrop-like промо)
            if 'okx_boost' in promo_type or 'okx_boost' in promo_id:
                return AirdropFormatter.format(promo, is_new=True)
            
            # MEXC Airdrop - используем AirdropFormatter
            if 'mexc_airdrop' in promo_type or 'mexc_airdrop' in promo_id:
                return AirdropFormatter.format(promo, is_new=True)
            
            # СТАРЫЙ КОД ДЛЯ ОСТАЛЬНЫХ ТИПОВ
            # НОВЫЙ УНИВЕРСАЛЬНЫЙ ЗАГОЛОВОК
            header = format_promo_header(
                exchange=promo.get('exchange'),
                promo_type=promo.get('promo_type'),
                promo_id=promo.get('promo_id'),
                url=promo.get('link'),
                is_new=True
            )
            message = f"{header}\n\n"

            # Название
            if promo.get('title'):
                message += f"📛 <b>Название:</b> {self.escape_html(promo['title'])}\n"
            
            # НОВОЕ: Найденные ключевые слова (для Telegram парсера)
            # Определяем Telegram сообщения по promo_id (начинается с 'telegram_')
            is_telegram_message = promo.get('promo_id', '').startswith('telegram_')
            
            if is_telegram_message and promo.get('total_prize_pool'):
                # Для Telegram сообщений total_prize_pool содержит ключевые слова
                keywords = str(promo['total_prize_pool']).split(', ')
                keywords_formatted = ', '.join([f"<code>{self.escape_html(kw)}</code>" for kw in keywords])
                message += f"<b>🔑 Найденные ключевые слова:</b> {keywords_formatted}\n"

            # Описание (обрезаем если слишком длинное)
            if promo.get('description'):
                desc = str(promo['description'])
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                message += f"<b>📝 Описание:</b> {self.escape_html(desc)}\n"

            # Призовой фонд с токеном награды (ТОЛЬКО если это НЕ Telegram сообщение)
            if not is_telegram_message:
                prize_pool = promo.get('total_prize_pool')
                award_token = promo.get('award_token')
                
                if prize_pool or award_token:
                    # Формируем строку призового фонда
                    if prize_pool and award_token:
                        # Есть и сумма, и токен - объединяем
                        prize_amount = str(prize_pool)
                        token_symbol = str(award_token)
                        
                        # Пытаемся получить цену токена для USD эквивалента
                        combined_text = f"{prize_amount} {token_symbol}"
                        tokens = self.parse_token_amounts(combined_text)
                        
                        if tokens:
                            amount, symbol, price_usd = tokens[0]
                            formatted_value = self.format_token_value(amount, symbol, price_usd)
                            message += f"<b>💰 Призовой фонд:</b> {formatted_value}\n"
                        else:
                            # Пробуем получить цену отдельно для токена
                            price_usd = self.get_token_price(token_symbol)
                            try:
                                amount = float(str(prize_amount).replace(',', '').replace(' ', ''))
                                formatted_value = self.format_token_value(amount, token_symbol, price_usd)
                                message += f"<b>💰 Призовой фонд:</b> {formatted_value}\n"
                            except (ValueError, TypeError):
                                message += f"<b>💰 Призовой фонд:</b> {self.escape_html(str(prize_amount))} {self.escape_html(token_symbol)}\n"
                    elif prize_pool:
                        # Только сумма - парсим токены из неё
                        prize_pool_text = str(prize_pool)
                        tokens = self.parse_token_amounts(prize_pool_text)
                        
                        if tokens:
                            formatted_parts = []
                            for amount, token_symbol, price_usd in tokens:
                                formatted_parts.append(self.format_token_value(amount, token_symbol, price_usd))
                            message += f"<b>💰 Призовой фонд:</b> {', '.join(formatted_parts)}\n"
                        else:
                            message += f"<b>💰 Призовой фонд:</b> {self.escape_html(prize_pool_text)}\n"
                    elif award_token:
                        # Только токен без суммы
                        tokens = self.parse_token_amounts(str(award_token))
                        if tokens:
                            formatted_parts = []
                            for amount, token_symbol, price_usd in tokens:
                                formatted_parts.append(self.format_token_value(amount, token_symbol, price_usd))
                            message += f"<b>💰 Призовой фонд:</b> {', '.join(formatted_parts)}\n"
                        else:
                            message += f"<b>🎯 Токен награды:</b> {self.escape_html(str(award_token))}\n"

            # Количество участников/мест
            if promo.get('participants_count'):
                message += f"<b>👥 Участники:</b> {promo['participants_count']}\n"

            # НОВОЕ: Количество призовых мест
            if promo.get('winners_count'):
                message += f"<b>🏆 Призовых мест:</b> {promo['winners_count']}\n"
            
            # НОВОЕ: Награда на аккаунт
            if promo.get('reward_per_winner'):
                reward_text = str(promo['reward_per_winner'])
                # Пытаемся добавить USD цену
                tokens = self.parse_token_amounts(reward_text)
                if tokens:
                    formatted_rewards = []
                    for amount, token_symbol, price_usd in tokens:
                        formatted_value = self.format_token_value(amount, token_symbol, price_usd)
                        formatted_rewards.append(formatted_value)
                    message += f"<b>🎁 Награда на аккаунт:</b> {', '.join(formatted_rewards)}\n"
                else:
                    message += f"<b>🎁 Награда на аккаунт:</b> {self.escape_html(reward_text)}\n"

            # Период действия с оставшимся временем
            if promo.get('start_time') and promo.get('end_time'):
                start_formatted = self.format_timestamp(promo['start_time'])
                end_formatted = self.format_timestamp(promo['end_time'])
                period_str = f"{start_formatted} - {end_formatted}"
                remaining = format_time_remaining(promo['end_time'])
                if remaining and remaining != "Завершено":
                    period_str += f" (⏳ {remaining})"
                elif remaining == "Завершено":
                    period_str += " (⏳ Завершено)"
                message += f"<b>📅 Период:</b> {period_str}\n"
            elif promo.get('start_time'):
                start_formatted = self.format_timestamp(promo['start_time'])
                message += f"<b>📅 Начало:</b> {start_formatted}\n"
            elif promo.get('end_time'):
                end_formatted = self.format_timestamp(promo['end_time'])
                end_str = f"{end_formatted}"
                remaining = format_time_remaining(promo['end_time'])
                if remaining and remaining != "Завершено":
                    end_str += f" (⏳ {remaining})"
                elif remaining == "Завершено":
                    end_str += " (⏳ Завершено)"
                message += f"<b>📅 Окончание:</b> {end_str}\n"

            # Ссылка
            if promo.get('link'):
                message += f"<b>🔗 Ссылка:</b> {promo['link']}\n"

            # ID промоакции (для отладки)
            message += f"\n<code>ID: {promo.get('promo_id', 'unknown')}</code>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования сообщения: {e}")
            return f"🎉 <b>Новая промоакция!</b>\n\nБиржа: {promo.get('exchange', 'Unknown')}\nID: {promo.get('promo_id', 'unknown')}"

    async def send_promo_notification(self, chat_id: int, promo: Dict[str, Any]):
        """Отправляет уведомление о новой промоакции"""
        try:
            message = self.format_promo_message(promo)
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"📤 Уведомление отправлено в чат {chat_id} - {promo.get('promo_id')}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления в чат {chat_id}: {e}")

    def format_title_change_notification(self, change: Dict[str, Any]) -> str:
        """
        Форматирует уведомление об изменении названия промоакции (для Weex rewards).
        
        Args:
            change: Словарь с информацией об изменении:
                - old_title: старое название
                - new_title: новое название
                - link: ссылка на промоакцию
                - exchange: биржа
                - promo_id: ID промоакции (опционально)
        """
        try:
            old_title = change.get('old_title', 'Неизвестно')
            new_title = change.get('new_title', 'Неизвестно')
            link = change.get('link', '')
            exchange = change.get('exchange', 'weex').upper()
            promo_id = change.get('promo_id', '')
            
            # Заголовок в стиле Weex Rewards
            message = f"🟣 <b>{exchange} | 🎁 REWARDS | 🔄 ОБНОВЛЕНИЕ</b>\n\n"
            
            message += f"📛 <b>Промоакция изменила название</b>\n\n"
            message += f"🔴 <b>Старое название:</b>\n"
            message += f"   {self.escape_html(old_title)}\n\n"
            message += f"🟢 <b>Новое название:</b>\n"
            message += f"   {self.escape_html(new_title)}\n"
            
            if link:
                message += f"\n🔗 <b>Ссылка:</b> {link}"
            
            if promo_id:
                message += f"\n\n<code>ID: {promo_id}</code>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования изменения названия: {e}")
            return f"🔄 <b>Изменение названия промоакции</b>\n\n{change.get('old_title', '')} → {change.get('new_title', '')}"

    async def send_title_change_notification(self, chat_id: int, change: Dict[str, Any]):
        """Отправляет уведомление об изменении названия промоакции"""
        try:
            message = self.format_title_change_notification(change)
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"📤 Уведомление об изменении названия отправлено в чат {chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления об изменении названия: {e}")

    def format_compact_promo_list(self, promos: List[Dict[str, Any]]) -> str:
        """Форматирует компактный список промоакций для одного сообщения"""
        try:
            if not promos:
                return ""

            # Группируем по биржам
            exchanges = {}
            for promo in promos:
                exchange = promo.get('exchange', 'Unknown')
                if exchange not in exchanges:
                    exchanges[exchange] = []
                exchanges[exchange].append(promo)

            message = f"🎉 <b>НАЙДЕНО {len(promos)} НОВЫХ ПРОМОАКЦИЙ!</b>\n\n"

            for exchange, exchange_promos in exchanges.items():
                message += f"<b>🏢 {exchange} ({len(exchange_promos)} шт.):</b>\n"

                for i, promo in enumerate(exchange_promos, 1):
                    title = promo.get('title', 'Без названия')
                    # Обрезаем длинные названия
                    if len(title) > 60:
                        title = title[:60] + "..."

                    message += f"{i}. {title}\n"

                    # Добавляем призовой фонд если есть
                    if promo.get('total_prize_pool'):
                        message += f"   💰 {promo['total_prize_pool']}\n"

                    # Добавляем ссылку если есть
                    if promo.get('link'):
                        message += f"   🔗 {promo['link']}\n"

                    message += "\n"

                message += "\n"

            message += "━━━━━━━━━━━━━━━━━\n"
            message += f"<i>Всего добавлено в базу: {len(promos)} промоакций</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования списка: {e}")
            return f"🎉 Найдено {len(promos)} новых промоакций!"

    async def send_bulk_notifications(self, chat_id: int, promos: List[Dict[str, Any]]):
        """Отправляет уведомления о нескольких промоакциях

        Логика:
        - Если <= 5 промоакций: отправляем по отдельности (детальная информация)
        - Если > 5 промоакций: объединяем в одно сообщение (компактный список)
        """
        if not promos:
            return

        logger.info(f"📨 Отправка {len(promos)} уведомлений в чат {chat_id}")

        # Если промоакций много (больше 5), отправляем одним сообщением
        if len(promos) > 5:
            logger.info(f"📦 Объединяем {len(promos)} промоакций в одно сообщение")
            try:
                message = self.format_compact_promo_list(promos)

                # Telegram ограничение: 4096 символов
                if len(message) > 4096:
                    logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), разбиваем")
                    # Разбиваем на части
                    parts = self._split_long_message(message, promos)
                    for part in parts:
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=part,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        import asyncio
                        await asyncio.sleep(0.5)
                else:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )

                logger.info(f"✅ Отправлено объединенное уведомление с {len(promos)} промоакциями")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки объединенного сообщения: {e}")
        else:
            # Если промоакций мало (≤5), отправляем по отдельности с полной информацией
            logger.info(f"📤 Отправляем {len(promos)} промоакций по отдельности")
            for i, promo in enumerate(promos, 1):
                await self.send_promo_notification(chat_id, promo)
                # Небольшая задержка между сообщениями чтобы не спамить
                if i < len(promos):
                    import asyncio
                    await asyncio.sleep(0.5)

    def _split_long_message(self, message: str, promos: List[Dict[str, Any]]) -> List[str]:
        """Разбивает длинное сообщение на части по 4000 символов"""
        parts = []
        current_part = f"🎉 <b>НАЙДЕНО {len(promos)} НОВЫХ ПРОМОАКЦИЙ!</b>\n\n"

        lines = message.split('\n')
        for line in lines[2:]:  # Пропускаем заголовок, т.к. уже добавили
            if len(current_part) + len(line) + 1 > 4000:
                parts.append(current_part)
                current_part = ""
            current_part += line + "\n"

        if current_part:
            parts.append(current_part)

        # Добавляем номера частей
        if len(parts) > 1:
            for i in range(len(parts)):
                parts[i] = f"<b>Часть {i+1}/{len(parts)}</b>\n\n" + parts[i]

        return parts

    async def send_check_completion_message(self, chat_id: int, total_checked: int, new_promos: int):
        """Отправляет сообщение о завершении проверки"""
        try:
            if new_promos > 0:
                message = f"✅ <b>Проверка завершена!</b>\n\nПроверено ссылок: {total_checked}\nНайдено новых промоакций: <b>{new_promos}</b> 🎉"
            else:
                message = f"ℹ️ <b>Проверка завершена</b>\n\nПроверено ссылок: {total_checked}\nНовых промоакций не найдено"

            await self.bot.send_message(chat_id, message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения о завершении: {e}")

    # ========== ФОРМАТТЕРЫ ДЛЯ СТЕЙКИНГОВ ==========

    def format_okx_project(self, stakings: List[Dict[str, Any]], page_url: str = None) -> str:
        """
        Форматирование уведомления о новом проекте OKX Flash Earn (все пулы в одном сообщении)

        Args:
            stakings: Список пулов проекта
            page_url: Ссылка на страницу

        Returns:
            Отформатированное HTML сообщение
        """
        if not stakings:
            return ""

        from datetime import datetime

        # Берём общие данные из первого пула
        first = stakings[0]
        reward_coin = self.escape_html(first.get('reward_coin') or first.get('coin'))
        exchange = self.escape_html(first.get('exchange', 'OKX'))
        end_time = first.get('end_time')
        start_time = first.get('start_time')
        total_reward = first.get('total_reward_amount') or first.get('reward_amount')
        countdown = first.get('countdown')
        reward_price = first.get('reward_token_price_usd')

        # Функция форматирования времени
        def format_datetime(ts):
            if not ts:
                return ''
            try:
                dt = datetime.fromtimestamp(ts / 1000) if ts > 10**10 else datetime.fromtimestamp(ts)
                return dt.strftime('%d.%m %H:%M')
            except:
                return str(ts)

        def format_countdown(ms):
            if not ms or ms <= 0:
                return None
            seconds = ms // 1000
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            minutes = (seconds % 3600) // 60
            if days > 0:
                return f"{days}д {hours}ч {minutes}мин"
            elif hours > 0:
                return f"{hours}ч {minutes}мин"
            else:
                return f"{minutes}мин"

        # Формируем сообщение
        message = f"🆕 <b>НОВЫЙ СТЕЙКИНГ!</b>\n\n"

        # Награда
        message += f"<b>🎁 Награда:</b> {reward_coin}\n"

        # Пул наград
        if total_reward:
            try:
                total_reward_num = float(str(total_reward).replace(',', ''))
                message += f"<b>💰 Пул наград:</b> {total_reward_num:,.0f} {reward_coin}"
                if reward_price:
                    total_usd = total_reward_num * reward_price
                    message += f" (~${total_usd:,.0f})"
                message += "\n"
            except:
                message += f"<b>💰 Пул наград:</b> {total_reward} {reward_coin}\n"

        message += f"<b>🏦 Биржа:</b> {exchange} Flash Earn\n"

        # Пулы для подписки
        message += f"\n<b>💎 ПУЛЫ ДЛЯ ПОДПИСКИ:</b>\n"
        for i, pool in enumerate(stakings):
            coin = self.escape_html(pool.get('coin', 'N/A'))
            apr = pool.get('apr', 0)
            user_limit = pool.get('user_limit_tokens')
            token_price = pool.get('token_price_usd')

            # Символ ветки
            if i == len(stakings) - 1:
                branch = "└"
            else:
                branch = "├"

            # Строка пула
            pool_str = f"{branch} <b>{coin}</b>: {apr:.2f}% APR"

            # Лимит
            if user_limit:
                pool_str += f" | Лимит: {user_limit:,.2f}"
                if token_price:
                    limit_usd = user_limit * token_price
                    pool_str += f" (~${limit_usd:,.0f})"

            message += pool_str + "\n"

        # Период подписки
        message += "\n"
        if start_time or end_time:
            message += f"<b>📅 Период подписки:</b> "
            if start_time and end_time:
                message += f"{format_datetime(start_time)} — {format_datetime(end_time)}"
            elif end_time:
                message += f"до {format_datetime(end_time)}"
            message += "\n"

        # Осталось времени
        if countdown:
            remaining = format_countdown(countdown)
            if remaining:
                message += f"<b>⏰ Осталось:</b> {remaining}\n"

        # Ссылка
        if page_url:
            message += f"\n<b>🔗 Ссылка:</b> {page_url}"

        return message

    def format_okx_flash_earn_page(
        self,
        stakings_with_deltas: List[Dict],
        page: int,
        total_pages: int,
        exchange_name: str = "OKX Flash Earn",
        min_apr: float = None,
        page_url: str = None,
        last_checked: 'datetime' = None
    ) -> str:
        """
        Форматирует страницу OKX Flash Earn с группировкой по проектам.
        Каждый проект отображается как один блок с несколькими пулами.

        Args:
            stakings_with_deltas: Список стейкингов с дельтами
            page: Текущая страница
            total_pages: Всего страниц
            exchange_name: Название биржи
            min_apr: Фильтр APR
            page_url: Ссылка
            last_checked: Время последней проверки (UTC)

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            from datetime import datetime, timedelta

            # Заголовок - используем last_checked если есть, иначе текущее время
            if last_checked and isinstance(last_checked, datetime):
                local_time = last_checked + timedelta(hours=2)
                now = local_time.strftime("%d.%m.%Y %H:%M")
            else:
                now = (datetime.utcnow() + timedelta(hours=2)).strftime("%d.%m.%Y %H:%M")
            
            message = f"📈 <b>ТЕКУЩИЕ СТЕЙКИНГИ</b>\n\n"
            message += f"<b>🏦 Биржа:</b> {self.escape_html(exchange_name)}\n"
            message += f"<b>⏱️ Обновлено:</b> {now}\n\n"

            if not stakings_with_deltas:
                message += "📭 <i>Нет активных проектов</i>\n\n"
                return message

            # Группируем стейкинги по проектам (reward_coin + start_time + end_time)
            projects = {}
            for item in stakings_with_deltas:
                staking = item['staking'] if isinstance(item, dict) and 'staking' in item else item

                # Получаем данные для группировки
                if hasattr(staking, '__dict__'):
                    # Это объект StakingHistory
                    reward_coin = staking.reward_coin or staking.coin
                    start_time = staking.start_time
                    end_time = staking.end_time
                else:
                    # Это словарь
                    reward_coin = staking.get('reward_coin') or staking.get('coin')
                    start_time = staking.get('start_time')
                    end_time = staking.get('end_time')

                # Ключ группировки
                project_key = (reward_coin, start_time, end_time)

                if project_key not in projects:
                    projects[project_key] = []
                projects[project_key].append(item)

            # Функция форматирования времени
            def format_datetime(ts):
                if not ts:
                    return ''
                try:
                    # Если строка - пробуем преобразовать в число
                    if isinstance(ts, str):
                        # Проверяем, это timestamp или уже отформатированная дата
                        if ts.isdigit():
                            ts = int(ts)
                        else:
                            # Уже отформатированная строка, возвращаем как есть
                            return ts
                    # Теперь ts это число (timestamp)
                    dt = datetime.fromtimestamp(ts / 1000) if ts > 10**10 else datetime.fromtimestamp(ts)
                    return dt.strftime('%d.%m %H:%M')
                except:
                    return str(ts)

            def format_countdown(ms):
                """Форматирует время в мс в читаемый формат"""
                if not ms or ms <= 0:
                    return None
                seconds = ms // 1000
                days = seconds // 86400
                hours = (seconds % 86400) // 3600
                minutes = (seconds % 3600) // 60
                if days > 0:
                    return f"{days}д {hours}ч {minutes}мин"
                elif hours > 0:
                    return f"{hours}ч {minutes}мин"
                else:
                    return f"{minutes}мин"

            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Отображаем каждый проект
            project_list = list(projects.items())
            for idx, (project_key, pools) in enumerate(project_list):
                reward_coin, start_time, end_time = project_key

                # Получаем данные из первого пула
                first_item = pools[0]
                first_staking = first_item['staking'] if isinstance(first_item, dict) and 'staking' in first_item else first_item

                if hasattr(first_staking, '__dict__'):
                    total_reward = getattr(first_staking, 'total_reward_amount', None) or getattr(first_staking, 'reward_amount', None)
                    countdown = getattr(first_staking, 'countdown', None)
                else:
                    total_reward = first_staking.get('total_reward_amount') or first_staking.get('reward_amount')
                    countdown = first_staking.get('countdown')

                # Заголовок проекта - награда
                message += f"🎁 <b>Награда:</b> {self.escape_html(reward_coin or 'N/A')}"
                if total_reward:
                    try:
                        total_reward_num = float(str(total_reward).replace(',', ''))
                        message += f" ({total_reward_num:,.0f} токенов)"
                    except:
                        message += f" ({total_reward})"
                message += "\n"

                # Статус
                message += f"📊 <b>Статус:</b> ✅ Активно\n"

                # Осталось времени
                if countdown:
                    remaining = format_countdown(countdown)
                    if remaining:
                        message += f"⏰ <b>Осталось:</b> {remaining}\n"

                # Пулы
                message += f"\n💎 <b>ДОСТУПНЫЕ ПУЛЫ:</b>\n"
                
                # Рассчитываем оставшиеся дни до конца промоакции
                remaining_days = None
                if countdown:
                    # countdown в миллисекундах
                    remaining_seconds = countdown / 1000
                    remaining_days = max(1, int(remaining_seconds / 86400))  # минимум 1 день
                elif end_time:
                    # Альтернативный расчёт через end_time, если countdown недоступен
                    try:
                        from datetime import datetime
                        now = datetime.utcnow()
                        # end_time может быть в миллисекундах или секундах
                        if isinstance(end_time, str):
                            # Пробуем преобразовать из строки
                            if end_time.isdigit():
                                end_timestamp = int(end_time)
                            else:
                                end_timestamp = None
                        else:
                            end_timestamp = end_time
                        
                        if end_timestamp:
                            # Определяем, миллисекунды или секунды
                            if end_timestamp > 10**10:
                                end_dt = datetime.fromtimestamp(end_timestamp / 1000)
                            else:
                                end_dt = datetime.fromtimestamp(end_timestamp)
                            
                            time_diff = (end_dt - now).total_seconds()
                            if time_diff > 0:
                                remaining_days = max(1, int(time_diff / 86400))
                    except Exception as e:
                        logger.debug(f"Не удалось рассчитать remaining_days из end_time: {e}")

                for i, pool_item in enumerate(pools):
                    pool = pool_item['staking'] if isinstance(pool_item, dict) and 'staking' in pool_item else pool_item

                    if hasattr(pool, '__dict__'):
                        coin = pool.coin
                        apr = pool.apr or 0
                        user_limit = pool.user_limit_tokens
                        token_price = pool.token_price_usd
                    else:
                        coin = pool.get('coin', 'N/A')
                        apr = pool.get('apr', 0)
                        user_limit = pool.get('user_limit_tokens')
                        token_price = pool.get('token_price_usd')

                    # Символ ветки
                    if i == len(pools) - 1:
                        branch = "└"
                    else:
                        branch = "├"

                    # Строка пула
                    pool_str = f"{branch} <b>{self.escape_html(coin)}</b>: {apr:.2f}% APR"

                    # Лимит
                    if user_limit:
                        pool_str += f" | Лимит: {user_limit:,.2f}"
                        if token_price:
                            limit_usd = user_limit * token_price
                            pool_str += f" (~${limit_usd:,.0f})"

                    message += pool_str + "\n"
                    
                    # Расчёт профита за оставшийся период промоакции
                    if user_limit and apr and apr > 0 and remaining_days:
                        _, _, _, earnings_str = self.calculate_staking_earnings(
                            user_limit=user_limit,
                            apr=apr,
                            term_days=remaining_days,  # Используем оставшиеся дни
                            token_price=token_price,
                            coin=coin
                        )
                        if earnings_str:
                            # Отступ для выравнивания с веткой дерева
                            indent = "  " if i == len(pools) - 1 else "│ "
                            message += f"{indent} └ <b>Профит: {earnings_str}</b>\n"

                # Период
                if start_time or end_time:
                    message += f"\n📅 <b>Период:</b> "
                    if start_time and end_time:
                        message += f"{format_datetime(start_time)} — {format_datetime(end_time)}"
                    elif end_time:
                        message += f"до {format_datetime(end_time)}"
                    message += "\n"

                # Разделитель между проектами
                if idx < len(project_list) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"

            # Ссылка
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            # Проверяем лимит Telegram
            if len(message) > 4090:
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования OKX Flash Earn: {e}", exc_info=True)
            return f"📈 <b>Текущие стейкинги</b>\n\n<b>Биржа:</b> OKX Flash Earn\n\n❌ Ошибка"

    def format_new_staking(
        self, 
        staking: Dict[str, Any], 
        page_url: str = None,
        is_stabilized: bool = False,
        stability_hours: int = None
    ) -> str:
        """
        Форматирование уведомления о новом/стабилизированном стейкинге
        
        Форматы:
        1. Bybit USDT - специальный (суммы $100/$200/$300)
        2. Fixed - расчёт для сумм $100/$500/$1000  
        3. Flexible - расчёт для периодов 1/7/14 дней
        4. Combined (Gate) - оба APR с расчётами

        Args:
            staking: Данные стейкинга из парсера
            page_url: Ссылка на страницу стейкингов
            is_stabilized: Это стабилизированный стейкинг (не новый)
            stability_hours: Время стабилизации из настроек пользователя

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # ══════════════════════════════════════════════════════════════
            # БАЗОВАЯ ИНФОРМАЦИЯ
            # ══════════════════════════════════════════════════════════════
            coin = self.escape_html(staking.get('coin', 'N/A'))
            reward_coin = self.escape_html(staking.get('reward_coin')) if staking.get('reward_coin') else None
            exchange = self.escape_html(staking.get('exchange', 'N/A'))
            apr = staking.get('apr', 0)
            term_days = staking.get('term_days', 0)
            token_price = staking.get('token_price_usd')
            product_type = staking.get('type', '')

            # Флаги
            is_vip = staking.get('is_vip', False)
            is_new_user = staking.get('is_new_user', False)
            regional_tag = staking.get('regional_tag')
            regional_countries = staking.get('regional_countries')
            
            # Лимит на аккаунт
            user_limit_tokens = staking.get('user_limit_tokens')
            
            # Gate.io Combined данные
            fixed_apr = staking.get('fixed_apr')
            flexible_apr = staking.get('flexible_apr')
            fixed_term_days = staking.get('fixed_term_days', 30)
            is_combined = (fixed_apr and flexible_apr) or product_type == 'Fixed/Flexible'

            # ══════════════════════════════════════════════════════════════
            # ОПРЕДЕЛЕНИЕ ТИПА
            # ══════════════════════════════════════════════════════════════
            is_dual_investment = (reward_coin and reward_coin != coin) or product_type == 'DUAL_CURRENCY'
            is_bybit_usdt = exchange.lower() == 'bybit' and coin.upper() == 'USDT'
            is_flexible = term_days == 0 and not is_combined
            
            # ══════════════════════════════════════════════════════════════
            # ФОРМАТ ПЕРИОДА
            # ══════════════════════════════════════════════════════════════
            if term_days == 0:
                term_text = "Flexible"
            elif term_days == 1:
                term_text = "1 день"
            elif term_days < 5:
                term_text = f"{term_days} дня"
            else:
                term_text = f"{term_days} дней"

            # ══════════════════════════════════════════════════════════════
            # ЗАГОЛОВОК
            # ══════════════════════════════════════════════════════════════
            exchange_upper = exchange.upper()
            
            # Форматируем APR для заголовка
            apr_display = f"{apr:.0f}%" if apr == int(apr) else f"{apr:.2f}%"
            
            if is_stabilized:
                # Стабилизированный стейкинг
                if is_combined:
                    header = f"🕐 <b>{exchange_upper} EARN | {coin} | Fixed/Flex | STABLE</b>"
                else:
                    header = f"🕐 <b>{exchange_upper} EARN | {coin} {apr_display} | STABLE</b>"
            else:
                # Новый стейкинг
                if is_dual_investment:
                    header = f"🆕 <b>{exchange_upper} DUAL | {coin} ➜ {reward_coin}</b>"
                elif is_combined:
                    header = f"🆕 <b>{exchange_upper} EARN | {coin} | Fixed/Flex</b>"
                else:
                    header = f"🆕 <b>{exchange_upper} EARN | {coin} {apr_display}</b>"
            
            message = f"{header}\n\n"

            # ══════════════════════════════════════════════════════════════
            # ИНФОРМАЦИЯ О МОНЕТЕ (уже в заголовке, не дублируем)
            # ══════════════════════════════════════════════════════════════
            # Монета и APR уже в заголовке, не дублируем

            # ══════════════════════════════════════════════════════════════
            # APR И СРОК
            # ══════════════════════════════════════════════════════════════
            if is_combined:
                # Gate.io Combined: показываем оба APR
                message += f"📊 <b>Fixed:</b> {fixed_apr:.2f}% APR ({fixed_term_days} дней)\n"
                message += f"📊 <b>Flexible:</b> {flexible_apr:.2f}% APR\n"
            else:
                message += f"📈 <b>APR:</b> {apr:.2f}%\n"
                message += f"⏳ <b>Срок:</b> {term_text}\n"

            # ══════════════════════════════════════════════════════════════
            # ПОМЕТКИ (VIP, New User, Regional)
            # ══════════════════════════════════════════════════════════════
            if is_vip:
                message += f"👑 <b>VIP:</b> Только для VIP\n"
            if is_new_user:
                message += f"👤 <b>Только для новых</b>\n"
            if regional_tag:
                region_name = 'СНГ (CIS)' if regional_tag == 'CIS' else regional_tag
                message += f"🌍 <b>Регион:</b> {region_name}"
                if regional_countries:
                    message += f" ({regional_countries})"
                message += "\n"

            # ══════════════════════════════════════════════════════════════
            # ВРЕМЯ СТАБИЛИЗАЦИИ (только для стабилизированных)
            # ══════════════════════════════════════════════════════════════
            if is_stabilized and stability_hours:
                message += f"⏱️ <b>Стабилизация:</b> {stability_hours} ч.\n"

            # ══════════════════════════════════════════════════════════════
            # РАСЧЁТ ДОХОДА
            # ══════════════════════════════════════════════════════════════
            def calc_earnings(amount_usd: float, apr_pct: float, days: int) -> float:
                """Расчёт дохода: amount * (APR/100) * (days/365)"""
                return amount_usd * (apr_pct / 100) * (days / 365)

            if is_combined:
                # ═══ GATE.IO COMBINED: оба расчёта ═══
                
                # Fixed расчёт
                fixed_earnings = calc_earnings(1000, fixed_apr, fixed_term_days)
                message += f"\n💰 <b>Доход с $1000 (Fixed {fixed_term_days}д):</b>\n"
                message += f"└─ <b>+${fixed_earnings:.2f}</b>\n"
                
                # Flexible расчёт (периоды)
                message += f"\n💰 <b>Доход с $1000 (Flexible):</b>\n"
                periods = [1, 7, 14]
                for i, days in enumerate(periods):
                    earnings = calc_earnings(1000, flexible_apr, days)
                    prefix = "├─" if i < len(periods) - 1 else "└─"
                    day_text = "День" if days == 1 else "Дней"
                    message += f"{prefix} {days} {day_text}: <b>+${earnings:.2f}</b>\n"

            elif is_bybit_usdt:
                # ═══ BYBIT USDT: суммы $100/$200/$300 ═══
                message += f"\n💰 <b>Расчёт дохода:</b>\n"
                amounts = [100, 200, 300]
                for i, amount in enumerate(amounts):
                    earnings = calc_earnings(amount, apr, term_days if term_days > 0 else 1)
                    prefix = "├─" if i < len(amounts) - 1 else "└─"
                    if term_days > 0:
                        message += f"{prefix} ${amount} → <b>+${earnings:.2f}</b>\n"
                    else:
                        message += f"{prefix} ${amount} → <b>+${earnings:.2f}</b>/день\n"

            elif is_flexible:
                # ═══ FLEXIBLE: периоды 1/7/14 дней ═══
                message += f"\n💰 <b>Доход с $1000:</b>\n"
                periods = [1, 7, 14]
                for i, days in enumerate(periods):
                    earnings = calc_earnings(1000, apr, days)
                    prefix = "├─" if i < len(periods) - 1 else "└─"
                    day_text = "День" if days == 1 else "Дней"
                    message += f"{prefix} {days} {day_text}: <b>+${earnings:.2f}</b>\n"

            else:
                # ═══ FIXED: суммы $100/$500/$1000 ═══
                message += f"\n💰 <b>Потенциальный доход:</b>\n"
                amounts = [100, 500, 1000]
                for i, amount in enumerate(amounts):
                    earnings = calc_earnings(amount, apr, term_days)
                    prefix = "├─" if i < len(amounts) - 1 else "└─"
                    message += f"{prefix} ${amount} → <b>+${earnings:.2f}</b> за {term_days} дн.\n"

            # ══════════════════════════════════════════════════════════════
            # ЛИМИТ НА АККАУНТ
            # ══════════════════════════════════════════════════════════════
            if user_limit_tokens and user_limit_tokens > 0:
                if token_price and token_price > 0:
                    limit_usd = user_limit_tokens * token_price
                    # Форматируем красиво большие числа
                    if user_limit_tokens >= 1_000_000:
                        tokens_fmt = f"{user_limit_tokens/1_000_000:.1f}M"
                    elif user_limit_tokens >= 1_000:
                        tokens_fmt = f"{user_limit_tokens:,.0f}"
                    else:
                        tokens_fmt = f"{user_limit_tokens:,.2f}"
                    message += f"\n👤 <b>Лимит:</b> {tokens_fmt} {coin} (~${limit_usd:,.0f})\n"
                else:
                    message += f"\n👤 <b>Лимит:</b> {user_limit_tokens:,.2f} {coin}\n"

            # ══════════════════════════════════════════════════════════════
            # ССЫЛКА (просто URL)
            # ══════════════════════════════════════════════════════════════
            exchange_key = exchange.lower().replace('.io', '').replace('.', '')
            staking_url = self.STAKING_URLS.get(exchange_key, page_url)
            if staking_url:
                message += f"\n{staking_url}"

            # ══════════════════════════════════════════════════════════════
            # ПРОВЕРКА ЛИМИТА TELEGRAM
            # ══════════════════════════════════════════════════════════════
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования стейкинга: {e}", exc_info=True)
            return f"💎 <b>Новый стейкинг!</b>\n\n<b>Монета:</b> {self.escape_html(staking.get('coin', 'Unknown'))}\n<b>APR:</b> {staking.get('apr', 0)}%"

    def format_pools_report(self, pools: List[Dict[str, Any]], exchange_name: str, page_url: str = None) -> str:
        """
        Форматирование отчёта о заполненности пулов

        Args:
            pools: Список стейкингов с данными о заполненности
            exchange_name: Название биржи
            page_url: Ссылка на страницу

        Returns:
            Отформатированный HTML отчёт
        """
        try:
            if not pools:
                return f"📭 Нет активных пулов с данными о заполненности на <b>{self.escape_html(exchange_name)}</b>"

            # Заголовок
            from datetime import datetime
            now = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
            message = f"📊 <b>ОТЧЁТ: ЗАПОЛНЕННОСТЬ ПУЛОВ</b>\n\n"
            message += f"<b>🏦 Биржа:</b> {self.escape_html(exchange_name)}\n"
            message += f"<b>🕐 Обновлено:</b> {now}\n\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Перебираем пулы
            for pool in pools:
                coin = self.escape_html(pool.get('coin', 'N/A'))
                apr = pool.get('apr', 0)
                term_days = pool.get('term_days', 0)
                term_type = self.escape_html(pool.get('type', 'N/A'))

                fill_percentage = pool.get('fill_percentage', 0)
                max_capacity = pool.get('max_capacity', 0)
                current_deposit = pool.get('current_deposit', 0)
                status = self.escape_html(pool.get('status', 'N/A'))

                # Заголовок пула
                if term_days == 0:
                    term_text = "Flexible"
                else:
                    term_text = f"{term_days} дней" if term_days > 1 else f"{term_days} день"

                message += f"<b>💰 {coin}</b> | {apr}% APR | {term_text}\n"

                # Пометки для VIP и New User
                is_vip = pool.get('is_vip', False)
                is_new_user = pool.get('is_new_user', False)

                if is_vip:
                    message += f"<b>👑 VIP</b> | "
                if is_new_user:
                    message += f"<b>🎁 NEW USER</b> | "

                message += f"<b>📊 Статус:</b> {status}\n"

                # Прогресс бар
                filled_blocks = int(fill_percentage / 5)  # 20 блоков = 100%
                empty_blocks = 20 - filled_blocks
                progress_bar = "▓" * filled_blocks + "░" * empty_blocks
                message += f"{progress_bar} <b>{fill_percentage:.2f}%</b>\n"

                # Данные о пуле (coin уже экранирован выше)
                if max_capacity and current_deposit:
                    available = max_capacity - current_deposit
                    message += f"Лимит: {max_capacity:,.2f} {coin} | "
                    message += f"Занято: {current_deposit:,.2f} {coin}\n"
                    message += f"Осталось: <b>{available:,.2f} {coin}</b>"

                    # Если есть цена токена - показываем в USD
                    token_price = pool.get('token_price_usd')
                    if token_price:
                        available_usd = available * token_price
                        message += f" (~${available_usd:,.2f})"

                    message += "\n"

                message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Статистика
            total_pools = len(pools)
            avg_fill = sum(p.get('fill_percentage', 0) for p in pools) / total_pools if total_pools > 0 else 0

            message += f"<b>📊 Активных пулов:</b> {total_pools}\n"
            message += f"<b>📈 Средняя заполненность:</b> {avg_fill:.2f}%\n"

            # Ссылка
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            # ВАЖНО: Telegram имеет лимит 4096 символов
            # Если сообщение слишком длинное, обрезаем его безопасно на границе строки
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                # Находим последнюю строку до лимита
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            # Дополнительная проверка на невалидные символы
            if '<' in message.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', ''):
                logger.warning(f"⚠️ В сообщении найдены подозрительные символы '<' вне тегов")
                # Показываем где именно
                for i, char in enumerate(message):
                    if char == '<' and not any(message[i:i+len(tag)] == tag for tag in ['<b>', '</b>', '<i>', '</i>', '<code>', '</code>']):
                        logger.warning(f"   Позиция {i}: ...{message[max(0,i-20):i+20]}...")

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования отчёта о пулах: {e}", exc_info=True)
            return f"📊 <b>Отчёт о заполненности пулов</b>\n\n<b>Биржа:</b> {self.escape_html(exchange_name)}\n\nНайдено пулов: {len(pools)}"

    def _format_bitget_poolx_page(
        self,
        stakings_with_deltas: List[Dict],
        page: int,
        total_pages: int,
        exchange_name: str,
        min_apr: float = None,
        page_url: str = None,
        now: str = None
    ) -> str:
        """
        Специальный форматтер для Bitget PoolX
        Группирует пулы по проекту (reward_coin) и показывает как один блок
        """
        from datetime import datetime, timedelta
        
        if not now:
            now = (datetime.utcnow() + timedelta(hours=2)).strftime("%d.%m.%Y %H:%M")
        
        message = f"💎 <b>BITGET POOLX</b>\n"
        message += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if not stakings_with_deltas:
            message += "📭 <i>Нет активных проектов PoolX</i>\n\n"
            message += f"⏱️ Обновлено: {now}\n"
            if page_url:
                message += f"\n🔗 <a href=\"{self.escape_html(page_url)}\">Открыть на бирже</a>"
            return message
        
        # Группируем стейкинги по reward_coin (проект)
        projects = {}
        for item in stakings_with_deltas:
            staking = item['staking']
            reward_coin = staking.get('reward_coin', 'Unknown')
            if reward_coin not in projects:
                projects[reward_coin] = {
                    'pools': [],
                    'total_rewards': staking.get('total_rewards', 0),
                    'start_time': staking.get('start_time'),
                    'end_time': staking.get('end_time'),
                    'status': staking.get('status', 'Active'),
                }
            projects[reward_coin]['pools'].append(staking)
        
        # Хелперы для форматирования
        def format_num(num):
            if num is None:
                return "N/A"
            if num >= 1_000_000:
                return f"{num/1_000_000:,.2f}M"
            elif num >= 1000:
                return f"{num:,.0f}"
            else:
                return f"{num:.2f}"
        
        def format_usd(num):
            if num is None or num == 0:
                return ""
            if num >= 1_000_000:
                return f"~${num/1_000_000:.1f}M"
            elif num >= 1000:
                return f"~${num/1000:.0f}K"
            else:
                return f"~${num:.0f}"
        
        # Форматируем каждый проект
        for project_idx, (reward_coin, project_data) in enumerate(projects.items()):
            pools = project_data['pools']
            total_rewards = project_data['total_rewards']
            start_time = project_data['start_time']
            end_time = project_data['end_time']
            
            # Заголовок проекта
            message += f"🪙 <b>{self.escape_html(reward_coin)}</b>\n"
            
            # Награды
            if total_rewards and total_rewards > 0:
                message += f"📊 Награды: {format_num(total_rewards)} {self.escape_html(reward_coin)}\n"
            
            # Время до окончания
            if end_time:
                try:
                    if isinstance(end_time, str):
                        # Парсим timestamp в мс если строка
                        if end_time.isdigit():
                            end_dt = datetime.fromtimestamp(int(end_time) / 1000)
                        else:
                            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    else:
                        end_dt = end_time
                    
                    time_left = end_dt - datetime.now()
                    if time_left.total_seconds() > 0:
                        days = time_left.days
                        hours = time_left.seconds // 3600
                        minutes = (time_left.seconds % 3600) // 60
                        
                        if days > 0:
                            message += f"⏳ Осталось: {days}д {hours}ч {minutes}мин\n"
                        else:
                            message += f"⏳ Осталось: {hours}ч {minutes}мин\n"
                        
                        days_left_total = time_left.total_seconds() / 86400
                    else:
                        message += f"⏳ Завершён\n"
                        days_left_total = 0
                except Exception as e:
                    logger.debug(f"Ошибка парсинга времени: {e}")
                    days_left_total = 0
            else:
                days_left_total = 0
            
            message += f"\n📈 <b>ПУЛЫ ДЛЯ СТЕЙКИНГА:</b>\n\n"
            
            # Форматируем каждый пул
            for pool in pools:
                stake_coin = pool.get('coin', 'N/A')
                apr = pool.get('apr', 0)
                max_stake = pool.get('user_limit_tokens', 0)
                current_deposit = pool.get('current_deposit', 0)
                token_price = pool.get('token_price_usd', 0)
                
                message += f"┌─ <b>{self.escape_html(stake_coin)} Pool</b> ────────────────────\n"
                message += f"│  💰 APR: {apr:.2f}%\n"
                
                # Максимум с USD
                if max_stake and max_stake > 0:
                    max_usd = max_stake * token_price if token_price else 0
                    if max_usd > 0:
                        message += f"│  📥 Макс: {format_num(max_stake)} {self.escape_html(stake_coin)} ({format_usd(max_usd)})\n"
                    else:
                        message += f"│  📥 Макс: {format_num(max_stake)} {self.escape_html(stake_coin)}\n"
                    
                    # Расчёт заработка за весь оставшийся период
                    if apr > 0 and days_left_total > 0 and max_stake > 0:
                        # Заработок в токенах стейка
                        earnings_tokens = max_stake * (apr / 100) * (days_left_total / 365)
                        earnings_usd = earnings_tokens * token_price if token_price else 0
                        
                        if earnings_usd > 0:
                            message += f"│  💵 <b>Заработок: ~{earnings_tokens:.4f} {self.escape_html(stake_coin)} ({format_usd(earnings_usd)})*</b>\n"
                        else:
                            message += f"│  💵 <b>Заработок: ~{earnings_tokens:.4f} {self.escape_html(stake_coin)}*</b>\n"
                
                # Застейкано
                if current_deposit and current_deposit > 0:
                    message += f"│  🔒 Застейкано: {format_num(current_deposit)} {self.escape_html(stake_coin)}\n"
                
                message += f"└───────────────────────────────\n\n"
            
            # Период
            if start_time or end_time:
                start_str = ""
                end_str = ""
                
                try:
                    if start_time:
                        if isinstance(start_time, str) and start_time.isdigit():
                            start_dt = datetime.fromtimestamp(int(start_time) / 1000)
                        elif isinstance(start_time, datetime):
                            start_dt = start_time
                        else:
                            start_dt = datetime.fromisoformat(str(start_time).replace('Z', '+00:00'))
                        start_str = start_dt.strftime("%d.%m")
                    
                    if end_time:
                        if isinstance(end_time, str) and end_time.isdigit():
                            end_dt = datetime.fromtimestamp(int(end_time) / 1000)
                        elif isinstance(end_time, datetime):
                            end_dt = end_time
                        else:
                            end_dt = datetime.fromisoformat(str(end_time).replace('Z', '+00:00'))
                        end_str = end_dt.strftime("%d.%m.%Y")
                except:
                    pass
                
                if start_str and end_str:
                    message += f"<i>*за весь период ({start_str} - {end_str})</i>\n\n"
            
            # Разделитель между проектами
            if project_idx < len(projects) - 1:
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"⏱️ Обновлено: {now}\n"
        
        if page_url:
            message += f"\n🔗 <a href=\"{self.escape_html(page_url)}\">Открыть на бирже</a>"
        
        return message

    def format_current_stakings_page(
        self,
        stakings_with_deltas: List[Dict],
        page: int,
        total_pages: int,
        exchange_name: str,
        min_apr: float = None,
        page_url: str = None,
        last_checked: 'datetime' = None
    ) -> str:
        """
        Форматирует страницу текущих стейкингов с историей изменений

        Args:
            stakings_with_deltas: Список словарей с ключами:
                - staking: объект StakingHistory
                - deltas: {apr_delta, fill_delta, price_delta_pct, has_previous}
                - alerts: список строк с алертами
            page: Текущая страница (1-based)
            total_pages: Всего страниц
            exchange_name: Название биржи
            min_apr: Минимальный APR фильтр (если установлен)
            page_url: Ссылка на страницу стейкингов
            last_checked: Время последней проверки (UTC)

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            from datetime import datetime, timedelta

            # Заголовок - используем last_checked если есть, иначе текущее время
            if last_checked and isinstance(last_checked, datetime):
                # Конвертируем UTC в UTC+2
                local_time = last_checked + timedelta(hours=2)
                now = local_time.strftime("%d.%m.%Y %H:%M")
            else:
                now = (datetime.utcnow() + timedelta(hours=2)).strftime("%d.%m.%Y %H:%M")
            
            # ═══════════════════════════════════════════════════════════
            # ПРОВЕРКА: Это Bitget PoolX? Используем специальный формат
            # ═══════════════════════════════════════════════════════════
            is_poolx = (
                stakings_with_deltas and 
                stakings_with_deltas[0].get('staking', {}).get('category') == 'poolx'
            ) or 'poolx' in exchange_name.lower()
            
            if is_poolx and stakings_with_deltas:
                return self._format_bitget_poolx_page(
                    stakings_with_deltas=stakings_with_deltas,
                    page=page,
                    total_pages=total_pages,
                    exchange_name=exchange_name,
                    min_apr=min_apr,
                    page_url=page_url,
                    now=now
                )
            
            message = f"📈 <b>ТЕКУЩИЕ СТЕЙКИНГИ</b>\n\n"
            message += f"<b>🏦 Биржа:</b> {self.escape_html(exchange_name)}\n"

            if min_apr is not None:
                message += f"<b>🔍 Фильтр APR:</b> ≥ {min_apr}%\n"

            message += f"<b>⏱️ Обновлено:</b> {now}\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Если стейкингов нет
            if not stakings_with_deltas:
                message += "📭 <i>Нет стейкингов, соответствующих фильтру</i>\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

                if page_url:
                    message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

                return message

            # Форматируем каждый стейкинг
            for idx, item in enumerate(stakings_with_deltas):
                staking = item['staking']
                deltas = item['deltas']
                alerts = item.get('alerts', [])

                # Базовые данные
                coin = self.escape_html(staking['coin'] or 'N/A')
                apr = staking['apr'] or 0
                term_days = staking.get('term_days', 0)
                product_type = staking.get('type', '')
                token_price = staking.get('token_price_usd')
                
                # Хелпер для форматирования чисел
                def format_num(num):
                    if num is None:
                        return "N/A"
                    if num >= 1_000_000:
                        return f"{num:,.0f}"
                    elif num >= 1000:
                        return f"{num:,.2f}"
                    else:
                        return f"{num:.2f}"

                # ═══════════════════════════════════════════════════════════
                # ПРОВЕРКА: Объединённый продукт Fixed/Flexible (Gate.io)?
                # ═══════════════════════════════════════════════════════════
                if product_type == 'Fixed/Flexible':
                    # ЗАГОЛОВОК с типом
                    message += f"💰 <b>{coin}</b> | {apr:.1f}% APR max | Fixed/Flexible\n"
                    
                    # СТАТУС
                    status = staking.get('status')
                    if status:
                        status_emoji = "✅" if status.lower() in ['active', 'ongoing'] else "🔴" if 'sold' in status.lower() else "⚪"
                        message += f"📈 <b>Статус:</b> {status_emoji} {self.escape_html(status)}\n"
                    
                    # Хелпер для компактного формата больших чисел
                    def format_compact_ff(num):
                        if num is None:
                            return "N/A"
                        if num >= 1_000_000:
                            return f"{num / 1_000_000:.2f}M"
                        elif num >= 1000:
                            return f"{num / 1000:.0f}K"
                        else:
                            return f"{num:.2f}"
                    
                    # FIXED детали (из дополнительных полей)
                    fixed_apr = staking.get('fixed_apr')
                    fixed_term = staking.get('fixed_term_days') or 0
                    fixed_limit = staking.get('fixed_user_limit')
                    
                    if fixed_apr is not None:
                        term_text = f" {fixed_term}d" if fixed_term else ""
                        message += f"\n📊 <b>FIXED{term_text}</b> ({fixed_apr:.1f}% APR):\n"
                        if fixed_limit and fixed_limit > 0:
                            if token_price and token_price >= 0.01:
                                limit_usd = fixed_limit * token_price
                                message += f"   • Максимум: {format_num(fixed_limit)} {coin} (${limit_usd:,.0f})\n"
                            else:
                                message += f"   • Максимум: {format_num(fixed_limit)} {coin}\n"
                            
                            # Расчёт заработка для Fixed
                            _, _, _, earnings_str = self.calculate_staking_earnings(
                                user_limit=fixed_limit,
                                apr=fixed_apr,
                                term_days=fixed_term if fixed_term else 30,  # по умолчанию 30 дней
                                token_price=token_price,
                                coin=coin
                            )
                            if earnings_str:
                                message += f"   • <b>Заработок: {earnings_str}</b>\n"
                    
                    # FLEXIBLE детали
                    flexible_apr = staking.get('flexible_apr')
                    flexible_limit = staking.get('flexible_user_limit')
                    max_capacity = staking.get('max_capacity')
                    current_deposit = staking.get('current_deposit')
                    fill_percentage = staking.get('fill_percentage')
                    
                    if flexible_apr is not None:
                        message += f"\n📊 <b>FLEXIBLE</b> ({flexible_apr:.1f}% APR):\n"
                        if flexible_limit and flexible_limit > 0:
                            if token_price and token_price >= 0.01:
                                limit_usd = flexible_limit * token_price
                                message += f"   • Максимум: {format_num(flexible_limit)} {coin} (${limit_usd:,.0f})\n"
                            else:
                                message += f"   • Максимум: {format_num(flexible_limit)} {coin}\n"
                            
                            # Расчёт заработка для Flexible (в день)
                            _, _, _, earnings_str = self.calculate_staking_earnings(
                                user_limit=flexible_limit,
                                apr=flexible_apr,
                                term_days=0,  # Flexible = 0 дней (расчёт за день)
                                token_price=token_price,
                                coin=coin
                            )
                            if earnings_str:
                                message += f"   • <b>Заработок: {earnings_str}</b>\n"
                        
                        # Заполненность пула (компактная строка) - показываем в секции FLEXIBLE
                        if max_capacity and max_capacity > 0 and current_deposit is not None and fill_percentage is not None:
                            available = max_capacity - current_deposit
                            if token_price and token_price >= 0.01:
                                available_usd = available * token_price
                                message += f"   • Заполненность: {fill_percentage:.2f}% | {format_compact_ff(available)} {coin} (${available_usd:,.0f}) из {format_compact_ff(max_capacity)}\n"
                            else:
                                message += f"   • Заполненность: {fill_percentage:.2f}% | {format_compact_ff(available)} {coin} из {format_compact_ff(max_capacity)}\n"

                # ═══════════════════════════════════════════════════════════
                # BINANCE ПРОДУКТ (новый компактный формат)
                # ═══════════════════════════════════════════════════════════
                elif 'binance' in exchange_name.lower() or staking.get('exchange', '').lower() == 'binance':
                    # Проверяем, есть ли reward_coin (Dual Currency)
                    reward_coin = self.escape_html(staking.get('reward_coin')) if staking.get('reward_coin') else None
                    binance_product_type = staking.get('product_type', '')
                    is_dual = (reward_coin and reward_coin != coin) or binance_product_type == 'DUAL_CURRENCY'
                    
                    # Формат периода
                    if term_days == 0:
                        term_text = "Flexible"
                    elif term_days == 1:
                        term_text = "1 день"
                    elif term_days < 5:
                        term_text = f"{term_days} дня"
                    else:
                        term_text = f"{term_days} дней"

                    # ЗАГОЛОВОК в зависимости от типа
                    if is_dual:
                        # Dual Investment: показываем пару токенов
                        message += f"🔄 <b>{coin} ➜ {reward_coin or '?'}</b>\n"
                    else:
                        # Обычный стейкинг
                        message += f"🪙 <b>{coin}</b>\n"
                    
                    # APR и срок
                    message += f"📈 <b>APR:</b> {apr:.2f}%\n"
                    message += f"⏳ <b>Срок:</b> {term_text}\n"

                    # Флаги (VIP, New User)
                    is_vip = staking.get('is_vip', False)
                    is_new_user = staking.get('is_new_user', False)
                    if is_vip:
                        message += f"👑 VIP\n"
                    if is_new_user:
                        message += f"🎁 Для новых\n"

                    # Время стабилизации для Flexible
                    stability_hours = staking.get('_stability_hours')
                    if term_days == 0 and stability_hours:
                        message += f"🕐 Стабилизация: {stability_hours} ч.\n"

                    # РАСЧЁТ ПОТЕНЦИАЛЬНОГО ДОХОДА
                    def calc_binance_earnings(amount_usd: float, apr_pct: float, days: int) -> float:
                        if days == 0:
                            return amount_usd * (apr_pct / 100) / 365
                        else:
                            return amount_usd * (apr_pct / 100) * (days / 365)

                    message += f"\n💰 <b>Потенциальный доход:</b>\n"
                    amounts = [100, 500, 1000]
                    for i, amount in enumerate(amounts):
                        earnings = calc_binance_earnings(amount, apr, term_days)
                        prefix = "├─" if i < len(amounts) - 1 else "└─"
                        if term_days == 0:
                            message += f"{prefix} ${amount} → <b>+${earnings:.2f}</b>/день\n"
                        else:
                            message += f"{prefix} ${amount} → <b>+${earnings:.2f}</b> за {term_days} дн.\n"

                # ═══════════════════════════════════════════════════════════
                # ОБЫЧНЫЙ ПРОДУКТ (MEXC, Bybit, KuCoin и др.)
                # ═══════════════════════════════════════════════════════════
                else:
                    # ЗАГОЛОВОК: Монета | APR | Срок
                    if term_days == 0:
                        term_text = "Flexible"
                    elif term_days == 1:
                        term_text = "1 день"
                    elif term_days < 5:
                        term_text = f"{term_days} дня"
                    else:
                        term_text = f"{term_days} дней"

                    message += f"💰 <b>{coin}</b> | {apr:.1f}% APR | {term_text}\n"

                    # СТАТУС
                    status = staking.get('status')
                    if status:
                        if status.lower() in ['active', 'ongoing']:
                            status_emoji = "✅"
                        elif status.lower() in ['sold out', 'soldout']:
                            status_emoji = "🔴"
                        elif status.lower() == 'interesting':
                            status_emoji = "⭐"
                        else:
                            status_emoji = "⚪"
                        message += f"📈 <b>Статус:</b> {status_emoji} {self.escape_html(status)}\n"

                    # КАТЕГОРИЯ (для новых пользователей и т.д.)
                    category = staking.get('category')
                    is_new_user = staking.get('is_new_user', False)
                    
                    if is_new_user or category == 'New User':
                        message += f"\n🏷 <b>Категория:</b> 👤 Новые пользователи\n"
                    elif category:
                        if category == 'ACTIVITY':
                            message += f"\n🏷 <b>Категория:</b> 🎯 Акция\n"
                        elif category == 'DEMAND':
                            message += f"\n🏷 <b>Категория:</b> 💰 Сбережения\n"
                        else:
                            message += f"\n🏷 <b>Категория:</b> {self.escape_html(category)}\n"

                    # ТИП ПРОДУКТА с расчётом заработка
                    min_pledge = staking.get('min_pledge_quantity')
                    user_limit = staking.get('user_limit_tokens')
                    max_capacity = staking.get('max_capacity')
                    current_deposit = staking.get('current_deposit')
                    fill_percentage = staking.get('fill_percentage')
                    
                    # Определяем тип: Fixed или Flexible
                    is_flexible = term_days == 0 or (product_type and 'flexible' in product_type.lower())
                    
                    # Хелпер для компактного формата больших чисел
                    def format_compact(num):
                        if num is None:
                            return "N/A"
                        if num >= 1_000_000:
                            return f"{num / 1_000_000:.2f}M"
                        elif num >= 1000:
                            return f"{num / 1000:.0f}K"
                        else:
                            return f"{num:.2f}"
                    
                    # Показываем тип стейкинга и заработок
                    if is_flexible:
                        # FLEXIBLE стейкинг
                        message += f"\n📊 <b>FLEXIBLE</b> ({apr:.1f}% APR):\n"
                    else:
                        # FIXED стейкинг
                        term_str = f" {term_days}d" if term_days else ""
                        message += f"\n📊 <b>FIXED{term_str}</b> ({apr:.1f}% APR):\n"
                    
                    # Лимит на аккаунт (Максимум)
                    if user_limit and user_limit > 0:
                        if token_price and token_price >= 0.01:
                            limit_usd = user_limit * token_price
                            message += f"   • Максимум: {format_num(user_limit)} {coin} (${limit_usd:,.0f})\n"
                        else:
                            message += f"   • Максимум: {format_num(user_limit)} {coin}\n"
                        
                        # Расчёт заработка
                        _, _, _, earnings_str = self.calculate_staking_earnings(
                            user_limit=user_limit,
                            apr=apr,
                            term_days=term_days if not is_flexible else 0,
                            token_price=token_price,
                            coin=coin
                        )
                        if earnings_str:
                            message += f"   • <b>Заработок: {earnings_str}</b>\n"
                    
                    # ЗАПОЛНЕННОСТЬ ПУЛА (компактная строка после заработка)
                    if max_capacity and max_capacity > 0 and current_deposit is not None and fill_percentage is not None:
                        available = max_capacity - current_deposit
                        if token_price and token_price >= 0.01:
                            available_usd = available * token_price
                            message += f"   • Заполненность: {fill_percentage:.2f}% | {format_compact(available)} {coin} (${available_usd:,.0f}) из {format_compact(max_capacity)}\n"
                        else:
                            message += f"   • Заполненность: {fill_percentage:.2f}% | {format_compact(available)} {coin} из {format_compact(max_capacity)}\n"
                    
                    # Минимальный депозит (если есть)
                    if min_pledge and min_pledge > 0:
                        if token_price and token_price >= 0.01:
                            min_usd = min_pledge * token_price
                            message += f"   • Минимум: {format_num(min_pledge)} {coin} (${min_usd:,.0f})\n"
                        else:
                            message += f"   • Минимум: {format_num(min_pledge)} {coin}\n"

                    # ПЕРИОД СТЕЙКИНГА
                    start_time = staking.get('start_time')
                    end_time = staking.get('end_time')

                    if start_time or end_time:
                        message += "\n⏰ <b>ПЕРИОД:</b>\n"
                        if start_time:
                            message += f"   • Начало: {self.escape_html(start_time)}\n"
                        if end_time:
                            message += f"   • Окончание: {self.escape_html(end_time)}\n"
                        if term_days and term_days > 0:
                            if term_days == 1:
                                message += f"   • Длительность: 1 день\n"
                            elif term_days < 5:
                                message += f"   • Длительность: {term_days} дня\n"
                            else:
                                message += f"   • Длительность: {term_days} дней\n"

                # Разделитель между стейкингами (кроме последнего)
                if idx < len(stakings_with_deltas) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"

            # Ссылка на биржу
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования страницы стейкингов: {e}", exc_info=True)
            return f"📈 <b>Текущие стейкинги</b>\n\n<b>Биржа:</b> {self.escape_html(exchange_name)}\n\n❌ Ошибка форматирования данных"

    def format_current_promos_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        exchange_name: str,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу текущих промоакций (аирдропов)

        Args:
            promos: Список словарей с данными промоакций
            page: Текущая страница (1-based)
            total_pages: Всего страниц
            exchange_name: Название биржи
            page_url: Ссылка на страницу промоакций

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            from datetime import datetime, timedelta

            # Заголовок (время обновления добавляется в handlers.py)
            message = f"🎁 <b>ТЕКУЩИЕ ПРОМОАКЦИИ</b>\n\n"
            message += f"<b>🏦 Биржа:</b> {self.escape_html(exchange_name)}\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных промоакций</i>\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                if page_url:
                    message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"
                return message

            # Форматируем каждую промоакцию
            for idx, promo in enumerate(promos):
                # ПРОВЕРКА: Если это launchpool с готовым форматированием - используем его
                if promo.get('is_launchpool') and promo.get('formatted_message'):
                    message += promo['formatted_message']
                    message += "\n\n"
                    continue
                
                # Название и токен
                title = promo.get('title', 'Без названия')
                award_token = promo.get('award_token', '')
                
                if award_token and award_token not in title:
                    message += f"🪂 <b>{self.escape_html(title)}</b> ({self.escape_html(award_token)})\n"
                else:
                    message += f"🪂 <b>{self.escape_html(title)}</b>\n"

                # Статус
                status = promo.get('status', '')
                if status:
                    if status.lower() == 'ongoing':
                        message += f"📊 <b>Статус:</b> ✅ Активна\n"
                    elif status.lower() == 'upcoming':
                        message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                    elif status.lower() == 'ended':
                        message += f"📊 <b>Статус:</b> ⏹ Завершена\n"

                # Награда
                total_pool = promo.get('total_prize_pool', '')
                total_pool_usd = promo.get('total_prize_pool_usd')
                reward_per_winner = promo.get('reward_per_winner', '')
                reward_per_winner_usd = promo.get('reward_per_winner_usd')

                # Получаем winners_count заранее для секции НАГРАДА
                winners = promo.get('winners_count')
                
                # USD данные берём только из БД - цены обновляются при парсинге
                # Для стейблкоинов в reward_per_winner - рассчитываем на месте
                STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP'}
                reward_str_upper = str(reward_per_winner).upper() if reward_per_winner else ''
                reward_is_stablecoin = any(stable in reward_str_upper for stable in STABLECOINS)
                
                if not reward_per_winner_usd and reward_per_winner and reward_is_stablecoin:
                    try:
                        # Парсим число из строки типа "20 USDT"
                        reward_match = re.match(r'([\d,]+(?:\.\d+)?)', str(reward_per_winner).replace(' ', ''))
                        if reward_match:
                            reward_num = float(reward_match.group(1).replace(',', ''))
                            reward_per_winner_usd = reward_num
                    except (ValueError, TypeError):
                        pass
                
                # Если нет winners, пытаемся рассчитать
                if not winners and total_pool_usd and reward_per_winner_usd and reward_per_winner_usd > 0:
                    winners = int(total_pool_usd / reward_per_winner_usd)

                if total_pool or reward_per_winner:
                    message += "\n💰 <b>НАГРАДА:</b>\n"
                    
                    # === СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ MEXC AIRDROP ===
                    # MEXC Airdrop имеет два пула: token_pool (токены) и bonus_usdt (USDT)
                    token_pool = promo.get('token_pool')
                    token_pool_currency = promo.get('token_pool_currency')
                    bonus_usdt = promo.get('bonus_usdt')
                    token_price = promo.get('token_price')
                    
                    if token_pool or bonus_usdt:
                        # Показываем пулы MEXC Airdrop отдельно
                        if token_pool and token_pool_currency:
                            pool_str = f"{token_pool:,.0f} {token_pool_currency}"
                            # Пытаемся получить USD для токен-пула
                            token_pool_usd = None
                            if token_price:
                                token_pool_usd = token_pool * token_price
                            if token_pool_usd:
                                message += f"   • Пул токенов: {self.escape_html(pool_str)} (~${token_pool_usd:,.0f})\n"
                            else:
                                message += f"   • Пул токенов: {self.escape_html(pool_str)}\n"
                        
                        if bonus_usdt:
                            # USDT = USD, поэтому не показываем эквивалент
                            message += f"   • Бонус USDT: {bonus_usdt:,.0f} USDT\n"
                    elif total_pool:
                        # Стандартная обработка для других бирж
                        # Форматируем призовой пул с токеном
                        pool_str = str(total_pool)
                        # Добавляем токен если его нет в строке пула
                        if award_token and award_token.upper() not in pool_str.upper():
                            pool_str = f"{pool_str} {award_token}"
                        
                        # Форматируем число с разделителями
                        try:
                            pool_num = float(str(total_pool).replace(',', '').replace(' ', ''))
                            pool_str = f"{pool_num:,.0f} {award_token}" if award_token else f"{pool_num:,.0f}"
                        except (ValueError, TypeError):
                            pass
                        
                        if total_pool_usd:
                            message += f"   • Призовой пул: {self.escape_html(pool_str)} (~${total_pool_usd:,.0f})\n"
                        else:
                            message += f"   • Призовой пул: {self.escape_html(pool_str)}\n"
                    
                    if reward_per_winner:
                        if reward_per_winner_usd:
                            message += f"   • Награда на место: {self.escape_html(str(reward_per_winner))} (~${reward_per_winner_usd:,.2f})\n"
                        else:
                            message += f"   • Награда на место: {self.escape_html(str(reward_per_winner))}\n"
                    
                    # Призовые места теперь в секции НАГРАДА
                    if winners:
                        message += f"   • Призовых мест: {winners:,}\n"

                # Участники
                participants = promo.get('participants_count')

                if participants:
                    message += "\n👥 <b>УЧАСТНИКИ:</b>\n"
                    
                    try:
                        p_num = int(float(str(participants).replace(',', '').replace(' ', '')))
                        message += f"   • Всего: {p_num:,}\n"
                    except:
                        message += f"   • Всего: {participants}\n"
                    
                    # Получаем статистику из истории (6ч/12ч/24ч)
                    participants_stats = promo.get('participants_stats', {})
                    
                    # Проверяем есть ли данные хотя бы за 6 часов
                    has_any_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                    
                    if has_any_history:
                        # Статистика за 6ч, 12ч, 24ч - показываем только интервалы с данными
                        for hours in [6, 12, 24]:
                            key = f'{hours}h'
                            if key in participants_stats:
                                stat = participants_stats[key]
                                diff = stat.get('diff', 0)
                                percent = stat.get('percent', 0)
                                sign = '+' if diff > 0 else ''
                                message += f"   • {hours} часов: {sign}{diff:,} ({sign}{percent:.0f}%)\n"

                # Период акции
                start_time = promo.get('start_time')
                end_time = promo.get('end_time')

                if start_time or end_time:
                    message += "\n⏰ <b>ПЕРИОД АКЦИИ:</b>\n"
                    
                    # Объединяем начало и конец в одну строку
                    if start_time and end_time:
                        if isinstance(start_time, datetime):
                            start_str = start_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            start_str = str(start_time)
                        
                        if isinstance(end_time, datetime):
                            end_str = end_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            end_str = str(end_time)
                        
                        message += f"   • Период: {self.escape_html(start_str)} / {self.escape_html(end_str)}\n"
                    elif end_time:
                        if isinstance(end_time, datetime):
                            message += f"   • Конец: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                        else:
                            message += f"   • Конец: {self.escape_html(str(end_time))}\n"
                    elif start_time:
                        if isinstance(start_time, datetime):
                            message += f"   • Начало: {start_time.strftime('%d.%m.%Y %H:%M')}\n"
                        else:
                            message += f"   • Начало: {self.escape_html(str(start_time))}\n"
                    
                    # Рассчитываем оставшееся время
                    if end_time and isinstance(end_time, datetime):
                        now_dt = datetime.utcnow()
                        if end_time > now_dt:
                            remaining = end_time - now_dt
                            days = remaining.days
                            hours = remaining.seconds // 3600
                            
                            if days > 0:
                                message += f"   • Осталось: {days} дн. {hours} ч.\n"
                            elif hours > 0:
                                minutes = (remaining.seconds % 3600) // 60
                                message += f"   • Осталось: {hours} ч. {minutes} мин.\n"
                            else:
                                minutes = remaining.seconds // 60
                                message += f"   • Осталось: {minutes} мин.\n"

                # Тип награды (только если это не просто число)
                # Для MEXC Airdrop не показываем reward_type, т.к. пулы уже детализированы выше
                token_pool = promo.get('token_pool')
                bonus_usdt = promo.get('bonus_usdt')

                reward_type = promo.get('reward_type', '')
                if reward_type and not (token_pool or bonus_usdt):
                    # Пропускаем если это просто число (код типа)
                    try:
                        int(str(reward_type))
                        # Это число - пропускаем
                    except ValueError:
                        # Это текст - показываем
                        message += f"🏆 <b>Тип награды:</b> {self.escape_html(str(reward_type))}\n"

                # Ссылка на промоакцию
                promo_link = promo.get('link', '')
                if promo_link:
                    message += f"\n🔗 {self.escape_html(promo_link)}\n"

                # Разделитель между промоакциями (кроме последней)
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"

            # Ссылка на биржу
            if page_url:
                message += f"\n<b>🔗 Страница акций:</b> {self.escape_html(page_url)}"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования страницы промоакций: {e}", exc_info=True)
            return f"🎁 <b>Текущие промоакции</b>\n\n<b>Биржа:</b> {self.escape_html(exchange_name)}\n\n❌ Ошибка форматирования данных"

    def format_okx_boost_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        show_only_active: bool = True
    ) -> str:
        """
        Форматирует страницу OKX Boost (X Launch) промоакций
        Формат:
        🪂 Sport.Fun X Launch (FUN) ⛓ Base
        📊 Статус: ✅ Активна
        
        💰 ОПИСАНИЕ:
           • Призовой пул: 4,000,000 FUN (~$320,320)
           • Участников: 24,998
           • 6 часов: +100 (+0.4%)
        
        ⏰ ПЕРИОД АКЦИИ:
           • Период: 15.01.2026 12:00 / 31.01.2026 14:00
           • Осталось: 11 дн. 13 ч.
        
        🔗 https://web3.okx.com/ua/boost/x-launch/sportfun
        """
        try:
            from datetime import datetime, timedelta
            
            def fmt_datetime(ts):
                """Форматирует timestamp в дату-время"""
                if not ts: 
                    return ''
                dt = datetime.fromtimestamp(ts / 1000) if ts > 10**10 else datetime.fromtimestamp(ts)
                return dt.strftime('%d.%m.%Y %H:%M')
            
            def get_datetime(ts):
                """Конвертирует timestamp в datetime объект"""
                if not ts:
                    return None
                return datetime.fromtimestamp(ts / 1000) if ts > 10**10 else datetime.fromtimestamp(ts)
            
            # Маппинг chain_id -> короткое название сети
            chain_short_names = {
                'Ethereum': 'ETH',
                'BNB Chain': 'BSC',
                'Polygon': 'Polygon',
                'Base': 'Base',
                'Arbitrum': 'Arbitrum',
                'Sui': 'Sui',
                'Solana': 'SOL',
                'Plasma': 'Plasma',
                'Linea': 'Linea'
            }
            
            # Заголовок (время обновления добавляется в handlers.py)
            message = f"⚫️ <b>OKX</b> | 🚀 <b>BOOST</b>\n\n"
            
            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных launchpool'ов</i>\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                return message
            
            # Форматируем каждый launchpool
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без названия')
                award_token = promo.get('award_token', '')
                total_pool = promo.get('total_prize_pool', 0)
                total_pool_usd = promo.get('total_prize_pool_usd')
                chain_name = promo.get('chain_name', '')
                participants = promo.get('participants_count', 0)
                link = promo.get('link', '')
                
                # Времена
                join_start = promo.get('join_start_time')
                join_end = promo.get('join_end_time')
                end_time = promo.get('end_time')
                
                # Короткое название сети
                chain_short = chain_short_names.get(chain_name, chain_name)
                
                # === ЗАГОЛОВОК: Название (TOKEN) ⛓ Сеть ===
                if award_token and award_token not in title:
                    message += f"🪂 <b>{self.escape_html(title)}</b> ({self.escape_html(award_token)})"
                else:
                    message += f"🪂 <b>{self.escape_html(title)}</b>"
                
                if chain_short:
                    message += f" ⛓ {self.escape_html(chain_short)}"
                message += "\n"
                
                # === СТАТУС ===
                status = promo.get('status', '')
                if status == 'ongoing':
                    message += f"📊 <b>Статус:</b> ✅ Активна\n"
                elif status == 'upcoming':
                    message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                elif status == 'ended':
                    message += f"📊 <b>Статус:</b> ⏹ Завершена\n"
                
                # === ОПИСАНИЕ (Призовой пул + Участники) ===
                message += "\n💰 <b>ОПИСАНИЕ:</b>\n"
                
                # Призовой пул
                if total_pool and award_token:
                    pool_str = f"{total_pool:,.0f} {award_token}"
                    if total_pool_usd:
                        message += f"   • Призовой пул: {self.escape_html(pool_str)} (~${total_pool_usd:,.0f})\n"
                    else:
                        # USD данные берём только из БД - цены обновляются при парсинге
                        message += f"   • Призовой пул: {self.escape_html(pool_str)}\n"
                
                # Участники
                if participants:
                    message += f"   • Участников: {participants:,}\n"
                
                # Статистика участников за 6ч/12ч/24ч
                participants_stats = promo.get('participants_stats', {})
                has_any_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                
                if has_any_history:
                    for hours in [6, 12, 24]:
                        key = f'{hours}h'
                        if key in participants_stats:
                            stat = participants_stats[key]
                            diff = stat.get('diff', 0)
                            percent = stat.get('percent', 0)
                            sign = '+' if diff > 0 else ''
                            message += f"   • {hours} часов: {sign}{diff:,} ({sign}{percent:.0f}%)\n"
                
                # === ПЕРИОД АКЦИИ ===
                start_dt = get_datetime(join_start)
                end_dt = get_datetime(join_end) or get_datetime(end_time)
                
                if start_dt or end_dt:
                    message += "\n⏰ <b>ПЕРИОД АКЦИИ:</b>\n"
                    
                    if start_dt and end_dt:
                        message += f"   • Период: {start_dt.strftime('%d.%m.%Y %H:%M')} / {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
                    elif end_dt:
                        message += f"   • Конец: {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
                    elif start_dt:
                        message += f"   • Начало: {start_dt.strftime('%d.%m.%Y %H:%M')}\n"
                    
                    # Оставшееся время
                    if end_dt:
                        now_dt = datetime.utcnow()
                        if end_dt > now_dt:
                            remaining = end_dt - now_dt
                            days = remaining.days
                            hours = remaining.seconds // 3600
                            
                            if days > 0:
                                message += f"   • Осталось: {days} дн. {hours} ч.\n"
                            elif hours > 0:
                                minutes = (remaining.seconds % 3600) // 60
                                message += f"   • Осталось: {hours} ч. {minutes} мин.\n"
                            else:
                                minutes = remaining.seconds // 60
                                message += f"   • Осталось: {minutes} мин.\n"
                
                # === ССЫЛКА ===
                if link:
                    message += f"\n🔗 {self.escape_html(link)}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"
            
            # Проверяем лимит Telegram
            if len(message) > 4090:
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования OKX Boost: {e}", exc_info=True)
            return f"🚀 <b>OKX X Launch</b>\n\n❌ Ошибка"

    def format_gate_candy_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        prev_participants: Dict[str, int] = None
    ) -> str:
        """
        Форматирует страницу Gate.io CandyDrop промоакций с полной информацией о наградах
        
        Args:
            promos: Список промоакций
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
            prev_participants: Словарь {promo_id: кол-во участников} с предыдущего обновления
        """
        try:
            from datetime import datetime

            def fmt_number(n):
                """Форматирует число с разделителями"""
                try:
                    return '{:,.0f}'.format(float(str(n).replace(',', '').replace(' ', '')))
                except:
                    return str(n)

            def fmt_conditions(conditions):
                """Форматирует условия участия из списка или строки"""
                if not conditions:
                    return ''
                if isinstance(conditions, list):
                    return ', '.join(conditions)
                return str(conditions)

            def fmt_reward_type(reward_type):
                """Форматирует тип награды"""
                if not reward_type:
                    return ''
                if isinstance(reward_type, list):
                    return ', '.join(reward_type)
                return str(reward_type)

            # Заголовок (время обновления добавляется в handlers.py)
            message = f"⚪️ <b>GATE.IO</b> | 🍬 <b>CANDYDROP</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных промоакций</i>\n"
                return message

            # Словарь предыдущих участников
            prev_participants = prev_participants or {}

            # Форматируем каждую промоакцию
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без названия')
                award_token = promo.get('award_token', '')
                promo_id = promo.get('promo_id', str(promo.get('id', idx)))
                
                # Название акции
                message += f"🪂 <b>{self.escape_html(title)}</b>\n"
                
                # Статус
                status = promo.get('status', '')
                if status:
                    if status.lower() == 'ongoing':
                        message += f"📊 <b>Статус:</b> ✅ Активна\n"
                    elif status.lower() == 'upcoming':
                        message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                
                # Условия участия (сразу после статуса)
                conditions = promo.get('conditions')
                if conditions:
                    message += f"\n📋 <b>УСЛОВИЯ:</b> {self.escape_html(fmt_conditions(conditions))}\n"
                
                # Тип награды
                reward_type = promo.get('reward_type')
                if reward_type:
                    rt_str = fmt_reward_type(reward_type)
                    # Пропускаем если это просто число
                    try:
                        int(str(rt_str))
                    except ValueError:
                        message += f"🎁 <b>ТИП НАГРАДЫ:</b> {self.escape_html(rt_str)}\n"
                
                # Блок НАГРАДЫ
                total_pool = promo.get('total_prize_pool')
                max_reward = promo.get('user_max_rewards')
                
                # USD данные берём только из БД - цены обновляются при парсинге
                total_pool_usd = promo.get('total_prize_pool_usd')
                reward_per_winner_usd = promo.get('reward_per_winner_usd')
                
                # Для max_reward_usd используем reward_per_winner_usd если есть (для Gate.io это то же самое)
                max_reward_usd = reward_per_winner_usd
                
                has_reward_info = total_pool or max_reward
                if has_reward_info:
                    message += "\n💎 <b>НАГРАДЫ:</b>\n"
                    
                    # Общий пул
                    if total_pool:
                        pool_str = f"{fmt_number(total_pool)} {award_token}" if award_token else fmt_number(total_pool)
                        if total_pool_usd:
                            message += f"   • Общий пул: {pool_str} (~${fmt_number(total_pool_usd)})\n"
                        else:
                            message += f"   • Общий пул: {pool_str}\n"
                    
                    # Макс награда на юзера
                    if max_reward:
                        max_str = f"{fmt_number(max_reward)} {award_token}" if award_token else fmt_number(max_reward)
                        if max_reward_usd:
                            message += f"   • Макс. на юзера: {max_str} (~${fmt_number(max_reward_usd)})\n"
                        else:
                            message += f"   • Макс. на юзера: {max_str}\n"
                
                # Участники с полной статистикой
                participants = promo.get('participants_count')
                if participants:
                    message += f"\n👥 <b>УЧАСТНИКИ:</b>\n"
                    message += f"   • Всего: {fmt_number(participants)}\n"
                    
                    # Получаем статистику из истории
                    participants_stats = promo.get('participants_stats', {})
                    
                    # Проверяем есть ли данные хотя бы за один интервал
                    has_any_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                    
                    if has_any_history:
                        # Статистика за 6ч, 12ч, 24ч - показываем только те интервалы, где есть данные
                        for hours in [6, 12, 24]:
                            key = f'{hours}h'
                            if key in participants_stats:
                                stat = participants_stats[key]
                                diff = stat.get('diff', 0)
                                percent = stat.get('percent', 0)
                                sign = '+' if diff > 0 else ''
                                message += f"   • За {hours} ч: {sign}{fmt_number(diff)} ({sign}{percent:.0f}%)\n"
                    
                    # Новых с последнего обновления
                    if 'last_update' in participants_stats:
                        last = participants_stats['last_update']
                        diff = last.get('diff', 0)
                        time_ago = last.get('time_ago', '')
                        if diff > 0:
                            message += f"   • Новых ({time_ago}): +{fmt_number(diff)} 📈\n"
                        elif diff < 0:
                            message += f"   • Изменение ({time_ago}): {fmt_number(diff)} 📉\n"
                    elif prev_participants:
                        # Fallback на старую логику если нет статистики из БД
                        prev_count = prev_participants.get(promo_id)
                        if prev_count is not None:
                            try:
                                current = int(float(str(participants).replace(',', '').replace(' ', '')))
                                prev = int(prev_count)
                                diff = current - prev
                                if diff > 0:
                                    message += f"   • Новых с обновления: +{fmt_number(diff)} 📈\n"
                                elif diff < 0:
                                    message += f"   • Изменение: {fmt_number(diff)} 📉\n"
                            except:
                                pass
                
                # Период (start_time, end_time) - компактный формат
                start_time = promo.get('start_time')
                end_time = promo.get('end_time')
                if start_time or end_time:
                    message += f"\n⏰ <b>ПЕРИОД:</b>\n"
                    
                    # Форматируем даты
                    start_str = ""
                    end_str = ""
                    if start_time:
                        if hasattr(start_time, 'strftime'):
                            start_str = start_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            start_str = str(start_time)
                    if end_time:
                        if hasattr(end_time, 'strftime'):
                            end_str = end_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            end_str = str(end_time)
                    
                    # Объединяем в одну строку
                    if start_str and end_str:
                        message += f"   • Даты: {start_str} / {end_str} UTC\n"
                    elif start_str:
                        message += f"   • Старт: {start_str} UTC\n"
                    elif end_str:
                        message += f"   • Конец: {end_str} UTC\n"
                    
                    # Добавляем "Конец через X дней"
                    if end_time and hasattr(end_time, 'timestamp'):
                        try:
                            from datetime import datetime
                            now = datetime.now()
                            delta = end_time - now
                            if delta.total_seconds() > 0:
                                days = delta.days
                                hours = delta.seconds // 3600
                                if days > 0:
                                    message += f"   • Конец через: {days} дн. {hours} ч.\n"
                                elif hours > 0:
                                    message += f"   • Конец через: {hours} ч.\n"
                                else:
                                    minutes = delta.seconds // 60
                                    message += f"   • Конец через: {minutes} мин.\n"
                        except:
                            pass
                
                # Ссылка на промоакцию
                promo_link = promo.get('link', '')
                if promo_link:
                    message += f"\n🔗 {self.escape_html(promo_link)}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования GateCandy: {e}", exc_info=True)
            return f"🎁 <b>Текущие промоакции</b>\n\n<b>Биржа:</b> GateCandy\n\n❌ Ошибка форматирования данных"

    def format_bitget_candy_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        prev_participants: Dict[str, int] = None
    ) -> str:
        """
        Форматирует страницу Bitget CandyBomb промоакций
        
        Формат данных из API:
        {
            "id": "232994",
            "name": "SKR",                    # Токен
            "desc": "...",                    # Описание  
            "ieoTotal": 666666,               # Общий пул токенов
            "ieoTotalUsdt": 7914.65,          # Пул в USD
            "totalPeople": 2,                 # Участники
            "activityStatus": 1,              # 0=upcoming, 1=active, 5=ended
            "bizLineLabel": "contract",       # spot/contract
            "startTime": "1768960800740",     # ms timestamp
            "endTime": "1769565600740",       # ms timestamp
        }
        """
        try:
            from datetime import datetime

            def fmt_number(n):
                """Форматирует число с разделителями"""
                try:
                    return '{:,.0f}'.format(float(str(n).replace(',', '').replace(' ', '')))
                except:
                    return str(n)

            def fmt_conditions(conditions):
                """Форматирует условия участия (SPOT/CONTRACT -> Spot/Futures)"""
                if not conditions:
                    return ''
                if isinstance(conditions, list):
                    formatted = []
                    for c in conditions:
                        c_upper = str(c).upper()
                        if c_upper == 'SPOT':
                            formatted.append('Spot')
                        elif c_upper == 'CONTRACT':
                            formatted.append('Futures')
                        else:
                            formatted.append(str(c))
                    return ', '.join(formatted)
                return str(conditions)

            def fmt_task_types(task_types):
                """Форматирует типы заданий"""
                if not task_types:
                    return ''
                if isinstance(task_types, list):
                    return ', '.join(task_types)
                return str(task_types)

            # Заголовок
            message = f"🟠 <b>BITGET</b> | 🍬 <b>CANDY BOMB</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных промоакций</i>\n"
                return message

            # Словарь предыдущих участников
            prev_participants = prev_participants or {}

            # Форматируем каждую промоакцию
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без названия')
                award_token = promo.get('award_token', '')
                promo_id = promo.get('promo_id', str(promo.get('id', idx)))
                
                # Название акции - токен (как у Gate: "Win up to X TOKEN")
                token_display = award_token if award_token else title
                total_pool = promo.get('total_prize_pool') or promo.get('total_pool_tokens')
                
                # Формируем заголовок с наградой
                if total_pool and award_token:
                    message += f"🪂 <b>Win up to {fmt_number(total_pool)} {self.escape_html(award_token)}</b>\n"
                elif '🌊' in title:
                    # Извлекаем токен из формата "🌊 TOKEN_NAME (TOKEN) - Статус"
                    token_part = title.split('🌊')[-1].strip()
                    if '-' in token_part:
                        token_display = token_part.split('-')[0].strip()
                    message += f"🪂 <b>{self.escape_html(token_display)}</b>\n"
                else:
                    message += f"🪂 <b>{self.escape_html(token_display)}</b>\n"
                
                # Статус
                status = promo.get('status', '')
                if status:
                    if status.lower() in ['active', 'ongoing']:
                        message += f"📊 <b>Статус:</b> ✅ Активна\n"
                    elif status.lower() == 'upcoming':
                        message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                    elif status.lower() == 'ended':
                        message += f"📊 <b>Статус:</b> ⏹️ Завершена\n"
                
                # Условия участия (SPOT/CONTRACT)
                conditions = promo.get('conditions', [])
                if conditions:
                    message += f"\n📋 <b>УСЛОВИЯ:</b> {self.escape_html(fmt_conditions(conditions))}\n"
                
                # Типы заданий (как reward_type у Gate)
                task_types = promo.get('task_types', [])
                if task_types:
                    message += f"🎁 <b>ТИП НАГРАДЫ:</b> {self.escape_html(fmt_task_types(task_types))}\n"
                
                # Блок НАГРАДЫ
                total_pool_usd = promo.get('total_prize_pool_usd') or promo.get('total_pool_usd')
                
                has_reward_info = total_pool or total_pool_usd
                if has_reward_info:
                    message += "\n💎 <b>НАГРАДЫ:</b>\n"
                    
                    # Общий пул
                    if total_pool:
                        token = award_token or promo.get('token_symbol', '')
                        pool_str = f"{fmt_number(total_pool)} {token}" if token else fmt_number(total_pool)
                        if total_pool_usd:
                            message += f"   • Общий пул: {pool_str} (~${fmt_number(total_pool_usd)})\n"
                        else:
                            message += f"   • Общий пул: {pool_str}\n"
                    elif total_pool_usd:
                        message += f"   • Общий пул: ~${fmt_number(total_pool_usd)}\n"
                
                # Участники
                participants = promo.get('participants_count') or promo.get('total_participants')
                if participants:
                    message += f"\n👥 <b>УЧАСТНИКИ:</b>\n"
                    message += f"   • Всего: {fmt_number(participants)}\n"
                    
                    # Получаем статистику из истории
                    participants_stats = promo.get('participants_stats', {})
                    
                    # Проверяем есть ли данные хотя бы за один интервал
                    has_any_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                    
                    if has_any_history:
                        # Статистика за 6ч, 12ч, 24ч
                        for hours in [6, 12, 24]:
                            key = f'{hours}h'
                            if key in participants_stats:
                                stat = participants_stats[key]
                                diff = stat.get('diff', 0)
                                percent = stat.get('percent', 0)
                                sign = '+' if diff > 0 else ''
                                message += f"   • За {hours} ч: {sign}{fmt_number(diff)} ({sign}{percent:.0f}%)\n"
                    
                    # Новых с последнего обновления
                    if 'last_update' in participants_stats:
                        last = participants_stats['last_update']
                        diff = last.get('diff', 0)
                        time_ago = last.get('time_ago', '')
                        if diff > 0:
                            message += f"   • Новых ({time_ago}): +{fmt_number(diff)} 📈\n"
                        elif diff < 0:
                            message += f"   • Изменение ({time_ago}): {fmt_number(diff)} 📉\n"
                    elif prev_participants:
                        # Fallback на старую логику
                        prev_count = prev_participants.get(promo_id)
                        if prev_count is not None:
                            try:
                                current = int(float(str(participants).replace(',', '').replace(' ', '')))
                                prev = int(prev_count)
                                diff = current - prev
                                if diff > 0:
                                    message += f"   • Новых с обновления: +{fmt_number(diff)} 📈\n"
                                elif diff < 0:
                                    message += f"   • Изменение: {fmt_number(diff)} 📉\n"
                            except:
                                pass
                
                # Период (start_time, end_time) - компактный формат
                start_time = promo.get('start_time')
                end_time = promo.get('end_time')
                if start_time or end_time:
                    message += f"\n⏰ <b>ПЕРИОД:</b>\n"
                    
                    # Форматируем даты
                    start_str = ""
                    end_str = ""
                    if start_time:
                        if hasattr(start_time, 'strftime'):
                            start_str = start_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            start_str = str(start_time)
                    if end_time:
                        if hasattr(end_time, 'strftime'):
                            end_str = end_time.strftime('%d.%m.%Y %H:%M')
                        else:
                            end_str = str(end_time)
                    
                    # Объединяем в одну строку
                    if start_str and end_str:
                        message += f"   • Даты: {start_str} / {end_str} UTC\n"
                    elif start_str:
                        message += f"   • Старт: {start_str} UTC\n"
                    elif end_str:
                        message += f"   • Конец: {end_str} UTC\n"
                    
                    # Добавляем "Конец через X дней"
                    if end_time and hasattr(end_time, 'timestamp'):
                        try:
                            from datetime import datetime
                            now = datetime.now()
                            delta = end_time - now
                            if delta.total_seconds() > 0:
                                days = delta.days
                                hours = delta.seconds // 3600
                                if days > 0:
                                    message += f"   • Конец через: {days} дн. {hours} ч.\n"
                                elif hours > 0:
                                    message += f"   • Конец через: {hours} ч.\n"
                                else:
                                    minutes = delta.seconds // 60
                                    message += f"   • Конец через: {minutes} мин.\n"
                        except:
                            pass
                
                # Ссылка на промоакцию
                promo_link = promo.get('link', '') or promo.get('project_url', '')
                if promo_link:
                    message += f"\n🔗 {self.escape_html(promo_link)}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования BitgetCandy: {e}", exc_info=True)
            return f"🎁 <b>Текущие промоакции</b>\n\n<b>Биржа:</b> BitgetCandy\n\n❌ Ошибка форматирования данных"

    def format_phemex_candy_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        prev_participants: Dict[str, int] = None
    ) -> str:
        """
        Форматирует страницу Phemex Candy Drop промоакций (минималистичный стиль)
        
        Формат данных из API:
        {
            "activityId": 820,
            "activityName": "IMU",
            "status": 0,  // 0=upcoming, 1=active, 2=ended
            "rewardAmount": 500000000000000,  // Scaled (÷10^8)
            "participants": 18639,
            "startTime": 1768903200000,  // ms timestamp
            "endTime": 1769076000000,    // ms timestamp
        }
        """
        try:
            from datetime import datetime

            def fmt_number(n):
                """Форматирует число с разделителями"""
                try:
                    return '{:,.0f}'.format(float(str(n).replace(',', '').replace(' ', '')))
                except:
                    return str(n)

            # Заголовок
            message = f"🚀 <b>PHEMEX CANDYDROP</b>\n\n"
            message += f"🏦 <b>Биржа:</b> Phemex Candydrop\n"
            
            # Время обновления
            now = datetime.now()
            update_time = now.strftime('%d.%m.%Y %H:%M')
            message += f"⏱️ <b>Обновлено:</b> {update_time}\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных промоакций</i>\n"
                return message

            # Форматируем каждую промоакцию
            for idx, promo in enumerate(promos):
                # Получаем данные
                token_symbol = promo.get('token_symbol', 'Unknown')
                token_name = promo.get('token_name', token_symbol)
                status = promo.get('status', '')
                total_pool = promo.get('total_pool_tokens', 0)
                start_time = promo.get('start_time')
                end_time = promo.get('end_time')
                promo_link = promo.get('project_url', '')
                token_price_usd = promo.get('token_price_usd')
                
                # Заголовок токена
                if token_name and token_name != token_symbol:
                    message += f"🪙 <b>{self.escape_html(token_symbol)} ({self.escape_html(token_name)})</b>\n"
                else:
                    message += f"🪙 <b>{self.escape_html(token_symbol)}</b>\n"
                
                # Статус
                if status:
                    if status == 'active':
                        message += f"📊 <b>Статус:</b> ✅ Активный\n"
                    elif status == 'upcoming':
                        message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                    elif status == 'ended':
                        message += f"📊 <b>Статус:</b> ⏹️ Завершён\n"
                
                # Общий пул наград с ценой в USD
                if total_pool > 0:
                    pool_str = f"💰 <b>Пул наград:</b> {fmt_number(total_pool)} {self.escape_html(token_symbol)}"
                    
                    # Добавляем эквивалент в USD если цена известна
                    if token_price_usd and token_price_usd > 0:
                        total_usd = total_pool * token_price_usd
                        pool_str += f" (~${fmt_number(total_usd)})"
                    
                    message += pool_str + "\n"
                
                # Осталось времени (только для активных)
                if status == 'active' and end_time:
                    try:
                        delta = end_time - now
                        if delta.total_seconds() > 0:
                            days = delta.days
                            hours = delta.seconds // 3600
                            if days > 0:
                                message += f"⏰ <b>Осталось:</b> {days} д. {hours} ч.\n"
                            else:
                                message += f"⏰ <b>Осталось:</b> {hours} ч.\n"
                    except:
                        pass
                
                # Период в одну строку
                if start_time and end_time:
                    start_str = start_time.strftime('%d.%m.%Y %H:%M') if hasattr(start_time, 'strftime') else str(start_time)
                    end_str = end_time.strftime('%d.%m.%Y %H:%M') if hasattr(end_time, 'strftime') else str(end_time)
                    message += f"\n📅 <b>Период:</b> {start_str} — {end_str} UTC\n"
                elif start_time:
                    start_str = start_time.strftime('%d.%m.%Y %H:%M') if hasattr(start_time, 'strftime') else str(start_time)
                    message += f"\n📅 <b>Старт:</b> {start_str} UTC\n"
                elif end_time:
                    end_str = end_time.strftime('%d.%m.%Y %H:%M') if hasattr(end_time, 'strftime') else str(end_time)
                    message += f"\n📅 <b>Конец:</b> {end_str} UTC\n"
                
                # Ссылка на страницу
                if promo_link:
                    message += f"\n🔗 {self.escape_html(promo_link)}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования PhemexCandy: {e}", exc_info=True)
            return f"🚀 <b>PHEMEX CANDYDROP</b>\n\n<b>Биржа:</b> Phemex Candydrop\n\n❌ Ошибка форматирования данных"

    def format_mexc_airdrop_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу MEXC Airdrop (EFTD) промоакций - оптимизированный формат
        
        Args:
            promos: Список промоакций (из UniversalParser._parse_mexc_airdrop)
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
        """
        try:
            from datetime import datetime, timedelta

            def fmt_number(n):
                """Форматирует число с разделителями"""
                try:
                    return '{:,.0f}'.format(float(str(n).replace(',', '').replace(' ', '')))
                except:
                    return str(n)

            def fmt_time(dt):
                """Форматирует datetime"""
                if not dt:
                    return ''
                if isinstance(dt, datetime):
                    return dt.strftime("%d.%m %H:%M")
                return str(dt)

            def fmt_remaining(end_dt):
                """Форматирует оставшееся время"""
                if not end_dt or not isinstance(end_dt, datetime):
                    return ''
                now = datetime.utcnow()
                if end_dt <= now:
                    return 'Завершено'
                remaining = end_dt - now
                days = remaining.days
                hours = remaining.seconds // 3600
                if days > 0:
                    return f'{days}д {hours}ч'
                elif hours > 0:
                    minutes = (remaining.seconds % 3600) // 60
                    return f'{hours}ч {minutes}м'
                else:
                    minutes = remaining.seconds // 60
                    return f'{minutes}м'

            # Заголовок (время обновления добавляется в handlers.py)
            message = f"🔵 <b>MEXC</b> | 🪂 <b>AIRDROP</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных аирдропов</i>\n"
                if page_url:
                    message += f"\n🔗 {self.escape_html(page_url)}\n"
                return message

            # Форматируем каждую промоакцию (чистый формат без дерева)
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без назви')
                token = promo.get('award_token', '')
                status = promo.get('status', '')
                
                # Статус-иконка
                if status == 'ongoing':
                    status_icon = "✅"
                elif status == 'upcoming':
                    status_icon = "🔜"
                else:
                    status_icon = "📌"
                
                # Название с токеном
                if token and token not in title:
                    message += f"{status_icon} <b>{self.escape_html(title)}</b> ({token})\n"
                else:
                    message += f"{status_icon} <b>{self.escape_html(title)}</b>\n"
                
                # Только для новых пользователей
                join_user_type = promo.get('join_user_type')
                if join_user_type == 'new_users':
                    message += f"   👤 <i>Тільки для нових користувачів</i>\n"
                
                # Призовой пул (BONUS награда)
                total_pool = promo.get('total_prize_pool')
                reward_currency = promo.get('reward_currency', 'USDT')
                participants = promo.get('participants_count') or 0
                
                if total_pool and float(total_pool) > 0:
                    pool_str = f"{fmt_number(total_pool)} {reward_currency}"
                    message += f"   💰 Пул: <b>{pool_str}</b>\n"
                    
                    # Рассчитываем награду на аккаунт если есть участники
                    if participants > 0:
                        reward_per_account = float(total_pool) / participants
                        if reward_per_account >= 1:
                            message += f"   🎁 На акаунт: ~{reward_per_account:,.2f} {reward_currency}\n"
                        else:
                            message += f"   🎁 На акаунт: ~{reward_per_account:.4f} {reward_currency}\n"
                
                # Дни до выплаты
                settle_days = promo.get('settle_days')
                if settle_days and settle_days > 0:
                    message += f"   📅 Виплата через: {settle_days} днів\n"
                
                # Участники
                if participants > 0:
                    message += f"   👥 Учасників: {fmt_number(participants)}\n"
                    
                    # Статистика из трекера
                    participants_stats = promo.get('participants_stats', {})
                    has_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                    
                    if has_history:
                        stats_parts = []
                        for hours in [6, 12, 24]:
                            key = f'{hours}h'
                            if key in participants_stats:
                                stat = participants_stats[key]
                                diff = stat.get('diff', 0)
                                if diff > 0:
                                    stats_parts.append(f"+{fmt_number(diff)} ({hours}г)")
                        
                        if stats_parts:
                            message += f"   📈 {', '.join(stats_parts)}\n"
                
                # Оставшееся время
                end_time = promo.get('end_time')
                remaining = fmt_remaining(end_time)
                if remaining and remaining != 'Завершено':
                    message += f"   ⏰ Залишилось: {remaining}\n"
                
                # Ссылка на аирдроп
                link = promo.get('link', '')
                if link:
                    message += f"   🔗 {self.escape_html(link)}\n"
                else:
                    message += f"   🔗 https://www.mexc.com/ru-RU/token-airdrop\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n"

            # Ссылка на страницу
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            if page_url:
                message += f"🔗 {self.escape_html(page_url)}\n"
            else:
                message += f"🔗 https://www.mexc.com/ru-RU/token-airdrop\n"

            # Проверяем лимит Telegram
            if len(message) > 4090:
                logger.warning(f"⚠️ MEXC Airdrop: сообщение слишком длинное ({len(message)})")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования MEXC Airdrop: {e}", exc_info=True)
            return f"🪂 <b>MEXC Airdrop</b>\n\n❌ Ошибка форматирования"

    def format_mexc_launchpad_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу MEXC Launchpad (IEO/IDO) - покупка токенов со скидкой
        
        Данные из API: https://www.mexc.com/api/financialactivity/launchpad/list
        
        Структура данных:
        - activityCoin, activityCoinFullName - токен
        - activityStatus - UNDERWAY, FINISHED, NOT_STARTED
        - totalSupply - общее количество токенов
        - launchpadTakingCoins[] - варианты подписки:
            - investCurrency - валюта (USDT, USD1)
            - takingPrice - цена подписки
            - linePrice - рыночная цена  
            - label - скидка (70% Off)
            - supply - выделено токенов
            - takingAmount - собрано
            - joinNum - участников
            - onlyForNewUser - только для новых
        
        Args:
            promos: Список промоакций (raw_data из API)
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
        """
        try:
            from datetime import datetime

            def fmt_number(n, decimals=0):
                """Форматирует число с разделителями"""
                try:
                    num = float(str(n).replace(',', '').replace(' ', ''))
                    if decimals > 0:
                        return f'{num:,.{decimals}f}'
                    return f'{num:,.0f}'
                except:
                    return str(n)

            def fmt_price(price):
                """Форматирует цену (убирает лишние нули)"""
                try:
                    p = float(price)
                    if p < 0.01:
                        return f'{p:.6f}'.rstrip('0').rstrip('.')
                    elif p < 1:
                        return f'{p:.4f}'.rstrip('0').rstrip('.')
                    else:
                        return f'{p:,.2f}'
                except:
                    return str(price)

            def get_remaining_time(end_ts):
                """Рассчитывает оставшееся время"""
                if not end_ts:
                    return None
                try:
                    end_dt = datetime.fromtimestamp(end_ts / 1000) if end_ts > 10**10 else datetime.fromtimestamp(end_ts)
                    now = datetime.now()
                    if end_dt <= now:
                        return None
                    remaining = end_dt - now
                    days = remaining.days
                    hours = remaining.seconds // 3600
                    minutes = (remaining.seconds % 3600) // 60
                    
                    if days > 0:
                        return f'{days} дн. {hours} ч.'
                    elif hours > 0:
                        return f'{hours} ч. {minutes} мин.'
                    else:
                        return f'{minutes} мин.'
                except:
                    return None

            def get_status_emoji(status):
                """Возвращает эмодзи статуса"""
                status_map = {
                    'UNDERWAY': '✅ В процессе',
                    'ONGOING': '✅ В процессе',
                    'NOT_STARTED': '🔜 Скоро',
                    'FINISHED': '⏹ Завершено',
                    'SETTLED': '⏹ Завершено',
                    'CANCELLED': '❌ Отменено'
                }
                return status_map.get(status, f'❓ {status}')

            # Заголовок
            message = f"� <b>MEXC</b> | 🚀 <b>LAUNCHPAD</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных launchpad проектов</i>\n"
                if page_url:
                    message += f"\n🔗 {self.escape_html(page_url)}\n"
                return message

            # Форматируем каждый проект
            for idx, promo in enumerate(promos):
                # Извлекаем raw_data если есть (из БД) или используем сам promo (из API напрямую)
                raw_data = promo.get('raw_data') or promo
                if isinstance(raw_data, str):
                    try:
                        import json
                        raw_data = json.loads(raw_data)
                    except:
                        raw_data = promo
                
                # Основные данные проекта
                token = raw_data.get('activityCoin', promo.get('award_token', ''))
                full_name = raw_data.get('activityCoinFullName', promo.get('title', token))
                status = raw_data.get('activityStatus', promo.get('status', '').upper())
                total_supply = raw_data.get('totalSupply', promo.get('total_prize_pool', ''))
                launchpad_id = raw_data.get('launchpadId', raw_data.get('id', ''))
                
                # === ЗАГОЛОВОК ПРОЕКТА ===
                if full_name and full_name != token:
                    message += f"🪙 <b>{self.escape_html(full_name)} ({token})</b>\n"
                else:
                    message += f"🪙 <b>{token}</b>\n"
                
                # Статус
                message += f"📊 <b>Статус:</b> {get_status_emoji(status)}\n"
                
                # Общее распределение
                if total_supply:
                    message += f"📦 <b>Всего токенов:</b> {fmt_number(total_supply)} {token}\n"
                
                # === ВАРИАНТЫ ПОДПИСКИ ===
                taking_coins = raw_data.get('launchpadTakingCoins', [])
                
                if taking_coins:
                    message += f"\n💰 <b>ВАРИАНТЫ ПОДПИСКИ ({len(taking_coins)}):</b>\n"
                    
                    for tc_idx, tc in enumerate(taking_coins, 1):
                        invest_curr = tc.get('investCurrency', 'USDT')
                        taking_price = tc.get('takingPrice', '0')
                        line_price = tc.get('linePrice')  # Рыночная цена
                        label = tc.get('label', '')  # Скидка (70% Off)
                        supply = tc.get('supply', '0')
                        taking_amount = tc.get('takingAmount', '0')
                        join_num = tc.get('joinNum', 0)
                        only_new = tc.get('onlyForNewUser', False)
                        taking_min = tc.get('takingMin', '')
                        taking_max = tc.get('takingMax', '')
                        
                        # Заголовок варианта
                        message += f"\n   <b>▸ {invest_curr}</b>"
                        if label:
                            message += f" 🔥 <b>{label}</b>"
                        if only_new:
                            message += " 🆕"
                        message += "\n"
                        
                        if only_new:
                            message += f"      <i>👤 Только для новых пользователей</i>\n"
                        
                        # Цена подписки
                        message += f"      • Цена: 1 {token} = {fmt_price(taking_price)} {invest_curr}\n"
                        
                        # Рыночная цена и экономия
                        if line_price:
                            try:
                                market = float(line_price)
                                current = float(taking_price)
                                if market > 0 and current > 0:
                                    savings_pct = ((market - current) / market) * 100
                                    message += f"      • Рынок: {fmt_price(line_price)} {invest_curr} "
                                    message += f"<i>(экономия {savings_pct:.0f}%)</i>\n"
                            except:
                                message += f"      • Рынок: {fmt_price(line_price)} {invest_curr}\n"
                        
                        # Выделено токенов
                        message += f"      • Выделено: {fmt_number(supply)} {token}\n"
                        
                        # Собрано
                        try:
                            amount_num = float(str(taking_amount).replace(',', ''))
                            if amount_num > 0:
                                message += f"      • Собрано: {fmt_number(amount_num, 2)} {invest_curr}\n"
                        except:
                            pass
                        
                        # Лимиты
                        if taking_min and taking_max:
                            message += f"      • Лимит: {fmt_number(taking_min)} - {fmt_number(taking_max)} {invest_curr}\n"
                        
                        # Участники (выделено)
                        if join_num:
                            message += f"      • Участников: <b>{fmt_number(join_num)}</b>\n"
                        
                        # === РАСЧЁТ АЛЛОКАЦИИ И ПРОФИТА ===
                        try:
                            supply_num = float(str(supply).replace(',', ''))
                            amount_num = float(str(taking_amount).replace(',', ''))
                            price_num = float(str(taking_price).replace(',', ''))
                            max_limit = float(str(taking_max).replace(',', '')) if taking_max else 5000
                            min_limit = float(str(taking_min).replace(',', '')) if taking_min else 100
                            
                            # Рыночная цена для расчёта профита
                            market_price = 0
                            try:
                                market_price = float(str(line_price).replace(',', '')) if line_price else 0
                            except:
                                pass
                            
                            if price_num > 0 and supply_num > 0:
                                # Сколько токенов забронировано
                                tokens_booked = amount_num / price_num if amount_num > 0 else 0
                                
                                # Коэффициент переподписки
                                oversubscription = tokens_booked / supply_num if tokens_booked > 0 else 0
                                
                                if oversubscription > 1:
                                    # Переподписка есть - рассчитываем аллокацию
                                    allocation_pct = 100 / oversubscription
                                    
                                    # При максимальном вкладе
                                    max_tokens_requested = max_limit / price_num
                                    tokens_received = max_tokens_requested * (allocation_pct / 100)
                                    usdt_allocated = tokens_received * price_num
                                    
                                    message += f"\n      📊 <b>АЛЛОКАЦИЯ:</b> {allocation_pct:.1f}% ({oversubscription:.1f}x)\n"
                                    
                                    # Профит по рыночной цене
                                    if market_price > price_num:
                                        profit_per_token = market_price - price_num
                                        total_profit = tokens_received * profit_per_token
                                        market_value = tokens_received * market_price
                                        roi = ((market_price - price_num) / price_num) * 100
                                        
                                        message += f"\n      💰 <b>РАСЧЁТ ДОХОДА (депозит {fmt_number(max_limit)} {invest_curr}):</b>\n"
                                        message += f"         📥 Депозит: {fmt_number(max_limit)} {invest_curr}\n"
                                        message += f"         📤 Аллокация: {usdt_allocated:.2f} {invest_curr}\n"
                                        tokens_fmt = f"{tokens_received/1000:.1f}K" if tokens_received >= 1000 else f"{tokens_received:.0f}"
                                        message += f"         🪙 Токены: {tokens_fmt} {token}\n"
                                        message += f"         💵 <b>По рынку: {market_value:.2f} {invest_curr} (+{total_profit:.2f} / +{roi:.0f}%)</b>\n"
                                else:
                                    # Пока недоподписка - 100% аллокация
                                    fill_pct = (tokens_booked / supply_num) * 100 if tokens_booked > 0 else 0
                                    message += f"\n      📊 <b>АЛЛОКАЦИЯ:</b> 100% <i>(заполнено {fill_pct:.0f}%)</i>\n"
                                    
                                    # Показываем потенциальный профит при 100% аллокации
                                    if market_price > price_num:
                                        profit_per_token = market_price - price_num
                                        roi = ((market_price - price_num) / price_num) * 100
                                        
                                        # Примеры расчёта для разных депозитов
                                        example_amounts = []
                                        if min_limit:
                                            example_amounts.append(min_limit)
                                        mid = (min_limit + max_limit) / 2
                                        mid = round(mid / 100) * 100  # округляем
                                        if mid not in example_amounts and mid != max_limit:
                                            example_amounts.append(mid)
                                        example_amounts.append(max_limit)
                                        
                                        message += f"\n      💰 <b>РАСЧЁТ ДОХОДА (100% аллока, ROI +{roi:.0f}%):</b>\n"
                                        
                                        for i, dep_amount in enumerate(example_amounts[:3]):
                                            tokens_get = dep_amount / price_num
                                            market_value = tokens_get * market_price
                                            profit = tokens_get * profit_per_token
                                            tokens_fmt = f"{tokens_get/1000:.1f}K" if tokens_get >= 1000 else f"{tokens_get:.0f}"
                                            
                                            prefix = "└─" if i == len(example_amounts) - 1 else "├─"
                                            star = " ⭐" if i == len(example_amounts) - 1 else ""
                                            message += f"         {prefix} {fmt_number(dep_amount)}$ → {tokens_fmt} {token} → <b>{market_value:.0f}$ (+{profit:.0f}$)</b>{star}\n"
                        except Exception as e:
                            # Не удалось рассчитать - пропускаем
                            logger.debug(f"⚠️ Не удалось рассчитать аллокацию: {e}")
                            pass
                
                # === ПЕРИОД АКЦИИ ===
                start_time = raw_data.get('startTime')
                end_time = raw_data.get('endTime')
                
                if start_time or end_time:
                    message += f"\n⏰ <b>ПЕРИОД:</b>\n"
                    
                    if start_time and end_time:
                        try:
                            start_dt = datetime.fromtimestamp(start_time / 1000) if start_time > 10**10 else datetime.fromtimestamp(start_time)
                            end_dt = datetime.fromtimestamp(end_time / 1000) if end_time > 10**10 else datetime.fromtimestamp(end_time)
                            message += f"   • {start_dt.strftime('%d.%m.%Y %H:%M')} — {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
                        except:
                            pass
                    
                    # Оставшееся время
                    if status in ['UNDERWAY', 'ONGOING', 'NOT_STARTED']:
                        remaining = get_remaining_time(end_time)
                        if remaining:
                            message += f"   • Осталось: <b>{remaining}</b>\n"
                
                # === ССЫЛКИ ===
                official_url = raw_data.get('officialUrl', '')
                twitter_url = raw_data.get('twitterUrl', '')
                
                message += f"\n🔗 <b>ССЫЛКИ:</b>\n"
                
                # Ссылка на MEXC Launchpad
                if launchpad_id:
                    message += f"   • <a href='https://www.mexc.com/ru-RU/launchpad/{launchpad_id}'>Страница на MEXC</a>\n"
                else:
                    message += f"   • https://www.mexc.com/ru-RU/launchpad\n"
                
                if official_url:
                    message += f"   • <a href='{official_url}'>Официальный сайт</a>\n"
                
                if twitter_url:
                    message += f"   • <a href='{twitter_url}'>Twitter/X</a>\n"
                
                # Разделитель между проектами
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"
            
            # Футер
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += f"🔗 <b>Все проекты:</b> https://www.mexc.com/ru-RU/launchpad\n"

            # Проверяем лимит Telegram
            if len(message) > 4090:
                logger.warning(f"⚠️ MEXC Launchpad: сообщение слишком длинное ({len(message)})")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования MEXC Launchpad: {e}", exc_info=True)
            return f"🚀 <b>MEXC Launchpad</b>\n\n❌ Ошибка форматирования"

    async def format_launchpool_page_async(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        special_parser: str = None,
        exchange_name: str = None
    ) -> str:
        """
        Асинхронный универсальный форматтер для всех Launchpool парсеров (Bybit, MEXC, Gate, BingX, Bitget)
        """
        try:
            from datetime import datetime
            
            # Определяем парсер и название биржи
            parser = None
            display_name = exchange_name or "Launchpool"
            exchange_color = '🌊'
            promo_type = 'LAUNCHPOOL'
            
            if special_parser == 'bybit_launchpool':
                from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
                parser = BybitLaunchpoolParser()
                display_name = "BYBIT"
                exchange_color = '🟡'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'mexc_launchpool':
                from parsers.mexc_launchpool_parser import MexcLaunchpoolParser
                parser = MexcLaunchpoolParser()
                display_name = "MEXC"
                exchange_color = '🔵'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'gate_launchpool':
                from parsers.gate_launchpool_parser import GateLaunchpoolParser
                parser = GateLaunchpoolParser()
                display_name = "GATE.IO"
                exchange_color = '⚪️'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'gate_launchpad':
                from parsers.gate_launchpad_parser import GateLaunchpadParser
                parser = GateLaunchpadParser()
                display_name = "GATE.IO"
                exchange_color = '⚪️'
                promo_type = 'LAUNCHPAD'
            elif special_parser == 'bingx_launchpool':
                from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
                parser = BingxLaunchpoolParser()
                display_name = "BINGX"
                exchange_color = '🔵'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'bitget_launchpool':
                from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
                parser = BitgetLaunchpoolParser()
                display_name = "BITGET"
                exchange_color = '🟠'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'bitget_poolx':
                from parsers.bitget_poolx_parser import BitgetPoolxParser
                parser = BitgetPoolxParser()
                display_name = "BITGET"
                exchange_color = '🟠'
                promo_type = 'POOLX'
            elif special_parser == 'phemex_candydrop':
                from parsers.phemex_candydrop_parser import PhemexCandydropParser
                parser = PhemexCandydropParser()
                display_name = "PHEMEX"
                exchange_color = '🟣'
                promo_type = 'CANDYDROP'
            
            if not parser:
                return f"{exchange_color} <b>{display_name}</b> | 🌊 <b>{promo_type}</b>\n\n❌ Парсер не найден"
            
            def fmt_number(n, decimals=0):
                """Форматирует число с разделителями"""
                try:
                    num = float(str(n).replace(',', '').replace(' ', ''))
                    if decimals > 0:
                        return f'{num:,.{decimals}f}'
                    return f'{num:,.0f}'
                except:
                    return str(n)
            
            def fmt_usd(amount):
                """Форматирует USD сумму"""
                try:
                    num = float(amount)
                    if num >= 1_000_000:
                        return f"${num/1_000_000:.2f}M"
                    elif num >= 1_000:
                        return f"${num/1_000:.2f}K"
                    else:
                        return f"${num:.2f}"
                except:
                    return f"${amount}"
            
            # Заголовок - унифицированный формат
            promo_emoji = '🌊' if promo_type == 'LAUNCHPOOL' else ('🚀' if promo_type == 'LAUNCHPAD' else ('🎱' if promo_type == 'POOLX' else '🍬'))
            message = f"{exchange_color} <b>{display_name}</b> | {promo_emoji} <b>{promo_type}</b>\n\n"
            
            # Получаем актуальные данные из API (асинхронно!)
            try:
                # Получаем и active, и upcoming проекты
                projects = await parser.get_projects_async(status_filter=None)  # Все проекты
                # Фильтруем только active и upcoming (исключаем ended)
                projects = [p for p in projects if p.status in ['active', 'upcoming']]
                
                if not projects:
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    message += "📭 <i>Нет активных или предстоящих launchpool проектов</i>\n"
                    return message
                
                # Для Gate.io Launchpad используем специальный форматтер
                if special_parser == 'gate_launchpad':
                    message = f"🚀 <b>GATE.IO LAUNCHPAD</b>\n\n"
                    message += f"<b>🏦 Биржа:</b> Gate.io Launchpad\n"
                    message += f"<b>⏱️ Обновлено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    message += "━" * 32 + "\n"
                    
                    for project in projects:
                        formatted = parser.format_project(project)
                        formatted = formatted.replace('<', '&lt;').replace('>', '&gt;')
                        message += f"\n{formatted}\n"
                    
                    if len(message) > 4090:
                        lines = message[:4000].split('\n')
                        message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
                    
                    return message
                
                # Получаем цены токенов
                token_prices = {}
                try:
                    if self.price_fetcher:
                        tokens_to_fetch = set()
                        for project in projects:
                            tokens_to_fetch.add(project.token_symbol)
                            for pool in project.pools:
                                tokens_to_fetch.add(pool.stake_coin)
                        
                        for token in tokens_to_fetch:
                            try:
                                price = self.price_fetcher.get_token_price(token, parser.EXCHANGE_NAME.lower())
                                if price and price > 0:
                                    token_prices[token] = price
                            except:
                                pass
                except Exception as price_err:
                    logger.warning(f"⚠️ Ошибка получения цен: {price_err}")
                
                # Форматируем каждый проект
                for idx, project in enumerate(projects):
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    message += f"🪙 <b>{project.token_name} ({project.token_symbol})</b>\n"
                    message += f"📊 <b>Статус:</b> {project.get_status_emoji()} {project.get_status_text()}\n"
                    
                    if project.total_pool_tokens > 0:
                        pool_str = f"{fmt_number(project.total_pool_tokens)} {project.token_symbol}"
                        token_price = token_prices.get(project.token_symbol, 0)
                        if token_price > 0:
                            pool_usd = project.total_pool_tokens * token_price
                            pool_str += f" ({fmt_usd(pool_usd)})"
                        message += f"💰 <b>Общий пул наград:</b> {pool_str}\n"
                    elif project.total_pool_usd > 0:
                        message += f"💰 <b>Общий пул наград:</b> {fmt_usd(project.total_pool_usd)}\n"
                    
                    message += f"⏰ <b>Осталось:</b> {project.time_remaining_str}\n"
                    
                    for i, pool in enumerate(project.pools, 1):
                        message += "\n"
                        
                        # Название пула с APR и звездой для лучшего
                        is_best_apr = pool.apr == project.max_apr
                        pool_star = " ⭐" if is_best_apr and len(project.pools) > 1 else ""
                        pool_name = f"📦 <b>ПУЛ #{i}: {pool.stake_coin} | {pool.apr:.0f}%{pool_star}</b>"
                        message += f"{pool_name}\n"
                        
                        stake_price = token_prices.get(pool.stake_coin, 0)
                        if pool.max_stake > 0:
                            max_str = f"{fmt_number(pool.max_stake)} {pool.stake_coin}"
                            if stake_price > 0:
                                max_usd = pool.max_stake * stake_price
                                max_str += f" ({fmt_usd(max_usd)})"
                            message += f"   🔒 Макс. депозит: {max_str}\n"
                        else:
                            message += f"   🔒 Макс. депозит: Без лимита\n"
                        
                        # Расчёт заработка (используем дробные дни для точности)
                        days_left = project.days_left
                        hours_left = project.hours_left
                        if days_left == 0 and hours_left > 0:
                            days_for_calc = hours_left / 24
                            time_label = f"{hours_left}ч"
                        else:
                            days_for_calc = days_left + (hours_left / 24)
                            time_label = f"{days_left}д"
                        
                        if days_for_calc > 0 and pool.apr > 0:
                            message += f"\n   💰 <b>ЗАРАБОТОК ЗА {time_label}:</b>\n"
                            
                            if pool.max_stake > 0:
                                amounts = [pool.max_stake * 0.25, pool.max_stake * 0.5, pool.max_stake]
                                for amt in amounts:
                                    earnings = amt * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = amt == pool.max_stake
                                    star = " ⭐️" if is_max else ""
                                    
                                    if stake_price > 0:
                                        deposit_usd = amt * stake_price
                                        earnings_usd = earnings * stake_price
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin} ({fmt_usd(deposit_usd)}){star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})\n"
                                    else:
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin}{star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}\n"
                            else:
                                for usd in [1000, 2500, 5000]:
                                    earnings_usd = usd * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = usd == 5000
                                    star = " ⭐️" if is_max else ""
                                    message += f"      🔸 Депозит: ${fmt_number(usd)}{star}\n"
                                    if is_max:
                                        message += f"         <b>Доход: ~{fmt_usd(earnings_usd)}</b>\n"
                                    else:
                                        message += f"         Доход: ~{fmt_usd(earnings_usd)}\n"
                    
                    message += f"\n⏰ <b>ПЕРІОД:</b>\n"
                    if project.start_time:
                        message += f"   • Старт: {project.start_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    if project.end_time:
                        message += f"   • Конец: {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    
                    if project.project_url:
                        message += f"\n🔗 <a href='{project.project_url}'>Страница проекта</a>"
                    if project.website:
                        message += f" | <a href='{project.website}'>Сайт</a>"
                    message += "\n"
                
                # Подсчёт по статусам
                active_count = len([p for p in projects if p.status == 'active'])
                upcoming_count = len([p for p in projects if p.status == 'upcoming'])
                
                message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                stats = []
                if active_count > 0:
                    stats.append(f"✅ Активных: {active_count}")
                if upcoming_count > 0:
                    stats.append(f"⏳ Предстоящих: {upcoming_count}")
                message += f"<b>📊 {' | '.join(stats)}</b>\n"
                message += f"<b>⏱️ Обновлено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                
                if len(message) > 4090:
                    lines = message[:4000].split('\n')
                    message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
                
                return message
                
            except Exception as api_err:
                logger.error(f"❌ Ошибка получения данных {display_name}: {api_err}", exc_info=True)
                return f"🌊 <b>{display_name.upper()}</b>\n\n❌ Ошибка получения данных: {str(api_err)[:100]}"
                
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования launchpool: {e}", exc_info=True)
            return f"🌊 <b>LAUNCHPOOL</b>\n\n❌ Ошибка форматирования"

    def format_launchpool_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None,
        special_parser: str = None,
        exchange_name: str = None
    ) -> str:
        """
        Универсальный форматтер для всех Launchpool парсеров (Bybit, MEXC, Gate, etc.)
        
        Args:
            promos: Список промоакций из БД
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
            special_parser: Тип парсера (bybit_launchpool, mexc_launchpool, etc.)
            exchange_name: Название биржи для отображения
        """
        try:
            from datetime import datetime
            
            # Определяем парсер и название биржи
            parser = None
            display_name = exchange_name or "Launchpool"
            exchange_color = '🌊'
            promo_type = 'LAUNCHPOOL'
            
            if special_parser == 'bybit_launchpool':
                from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
                parser = BybitLaunchpoolParser()
                display_name = "BYBIT"
                exchange_color = '🟡'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'mexc_launchpool':
                from parsers.mexc_launchpool_parser import MexcLaunchpoolParser
                parser = MexcLaunchpoolParser()
                display_name = "MEXC"
                exchange_color = '🔵'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'gate_launchpool':
                from parsers.gate_launchpool_parser import GateLaunchpoolParser
                parser = GateLaunchpoolParser()
                display_name = "GATE.IO"
                exchange_color = '⚪️'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'gate_launchpad':
                from parsers.gate_launchpad_parser import GateLaunchpadParser
                parser = GateLaunchpadParser()
                display_name = "GATE.IO"
                exchange_color = '⚪️'
                promo_type = 'LAUNCHPAD'
            elif special_parser == 'bingx_launchpool':
                from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
                parser = BingxLaunchpoolParser()
                display_name = "BINGX"
                exchange_color = '🔵'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'bitget_launchpool':
                from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
                parser = BitgetLaunchpoolParser()
                display_name = "BITGET"
                exchange_color = '🟠'
                promo_type = 'LAUNCHPOOL'
            elif special_parser == 'bitget_poolx':
                from parsers.bitget_poolx_parser import BitgetPoolxParser
                parser = BitgetPoolxParser()
                display_name = "BITGET"
                exchange_color = '🟠'
                promo_type = 'POOLX'
            elif special_parser == 'phemex_candydrop':
                from parsers.phemex_candydrop_parser import PhemexCandydropParser
                parser = PhemexCandydropParser()
                display_name = "PHEMEX"
                exchange_color = '🟣'
                promo_type = 'CANDYDROP'
            
            if not parser:
                return f"{exchange_color} <b>{display_name}</b> | 🌊 <b>{promo_type}</b>\n\n❌ Парсер не найден"
            
            def fmt_number(n, decimals=0):
                """Форматирует число с разделителями"""
                try:
                    num = float(str(n).replace(',', '').replace(' ', ''))
                    if decimals > 0:
                        return f'{num:,.{decimals}f}'
                    return f'{num:,.0f}'
                except:
                    return str(n)
            
            def fmt_usd(amount):
                """Форматирует USD сумму"""
                try:
                    num = float(amount)
                    if num >= 1_000_000:
                        return f"${num/1_000_000:.2f}M"
                    elif num >= 1_000:
                        return f"${num/1_000:.2f}K"
                    else:
                        return f"${num:.2f}"
                except:
                    return f"${amount}"
            
            # Заголовок - унифицированный формат
            promo_emoji = '🌊' if promo_type == 'LAUNCHPOOL' else ('🚀' if promo_type == 'LAUNCHPAD' else ('🎱' if promo_type == 'POOLX' else '🍬'))
            message = f"{exchange_color} <b>{display_name}</b> | {promo_emoji} <b>{promo_type}</b>\n\n"
            
            # Получаем актуальные данные из API
            try:
                projects = parser.get_projects(status_filter='active')
                
                if not projects:
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    message += "📭 <i>Нет активных launchpool проектов</i>\n"
                    return message
                
                # Для Gate.io Launchpad используем специальный форматтер с расчётом аллокации
                if special_parser == 'gate_launchpad':
                    message = f"⚪️ <b>GATE.IO</b> | 🚀 <b>LAUNCHPAD</b>\n\n"
                    message += f"<b>⏱️ Обновлено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    message += "━" * 32 + "\n"
                    
                    for project in projects:
                        formatted = parser.format_project(project)
                        # Экранируем HTML
                        formatted = formatted.replace('<', '&lt;').replace('>', '&gt;')
                        message += f"\n{formatted}\n"
                    
                    # Проверяем лимит Telegram
                    if len(message) > 4090:
                        lines = message[:4000].split('\n')
                        message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
                    
                    return message
                
                # Получаем цены токенов
                token_prices = {}
                try:
                    if self.price_fetcher:
                        tokens_to_fetch = set()
                        for project in projects:
                            tokens_to_fetch.add(project.token_symbol)
                            for pool in project.pools:
                                tokens_to_fetch.add(pool.stake_coin)
                        
                        for token in tokens_to_fetch:
                            try:
                                # Используем exchange из парсера
                                price = self.price_fetcher.get_token_price(token, parser.EXCHANGE_NAME.lower())
                                if price and price > 0:
                                    token_prices[token] = price
                            except:
                                pass
                except Exception as price_err:
                    logger.warning(f"⚠️ Ошибка получения цен: {price_err}")
                
                # Форматируем каждый проект
                for idx, project in enumerate(projects):
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    # Токен
                    message += f"🪙 <b>{project.token_name} ({project.token_symbol})</b>\n"
                    message += f"📊 <b>Статус:</b> {project.get_status_emoji()} {project.get_status_text()}\n"
                    
                    # Общий пул наград с USD
                    if project.total_pool_tokens > 0:
                        pool_str = f"{fmt_number(project.total_pool_tokens)} {project.token_symbol}"
                        token_price = token_prices.get(project.token_symbol, 0)
                        if token_price > 0:
                            pool_usd = project.total_pool_tokens * token_price
                            pool_str += f" ({fmt_usd(pool_usd)})"
                        message += f"💰 <b>Общий пул наград:</b> {pool_str}\n"
                    elif project.total_pool_usd > 0:
                        message += f"💰 <b>Общий пул наград:</b> {fmt_usd(project.total_pool_usd)}\n"
                    
                    message += f"⏰ <b>Осталось:</b> {project.time_remaining_str}\n"
                    
                    # Пулы для стейкинга
                    for i, pool in enumerate(project.pools, 1):
                        message += "\n"
                        
                        # Название пула с APR и звездой для лучшего
                        is_best_apr = pool.apr == project.max_apr
                        pool_star = " ⭐" if is_best_apr and len(project.pools) > 1 else ""
                        pool_name = f"📦 <b>ПУЛ #{i}: {pool.stake_coin} | {pool.apr:.0f}%{pool_star}</b>"
                        message += f"{pool_name}\n"
                        
                        # Макс депозит с USD
                        stake_price = token_prices.get(pool.stake_coin, 0)
                        if pool.max_stake > 0:
                            max_str = f"{fmt_number(pool.max_stake)} {pool.stake_coin}"
                            if stake_price > 0:
                                max_usd = pool.max_stake * stake_price
                                max_str += f" ({fmt_usd(max_usd)})"
                            message += f"   🔒 Макс. депозит: {max_str}\n"
                        else:
                            message += f"   🔒 Макс. депозит: Без лимита\n"
                        
                        # Расчёт заработка (используем дробные дни для точности)
                        days_left = project.days_left
                        hours_left = project.hours_left
                        if days_left == 0 and hours_left > 0:
                            days_for_calc = hours_left / 24
                            time_label = f"{hours_left}ч"
                        else:
                            days_for_calc = days_left + (hours_left / 24)
                            time_label = f"{days_left}д"
                        
                        if days_for_calc > 0 and pool.apr > 0:
                            message += f"\n   💰 <b>ЗАРАБОТОК ЗА {time_label}:</b>\n"
                            
                            if pool.max_stake > 0:
                                amounts = [pool.max_stake * 0.25, pool.max_stake * 0.5, pool.max_stake]
                                for amt in amounts:
                                    earnings = amt * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = amt == pool.max_stake
                                    star = " ⭐️" if is_max else ""
                                    
                                    if stake_price > 0:
                                        deposit_usd = amt * stake_price
                                        earnings_usd = earnings * stake_price
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin} ({fmt_usd(deposit_usd)}){star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})\n"
                                    else:
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin}{star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}\n"
                            else:
                                for usd in [1000, 2500, 5000]:
                                    earnings_usd = usd * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = usd == 5000
                                    star = " ⭐️" if is_max else ""
                                    message += f"      🔸 Депозит: ${fmt_number(usd)}{star}\n"
                                    if is_max:
                                        message += f"         <b>Доход: ~{fmt_usd(earnings_usd)}</b>\n"
                                    else:
                                        message += f"         Доход: ~{fmt_usd(earnings_usd)}\n"
                    
                    # Период
                    message += f"\n⏰ <b>ПЕРИОД:</b>\n"
                    if project.start_time:
                        message += f"   • Старт: {project.start_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    if project.end_time:
                        message += f"   • Конец: {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    
                    # Ссылки
                    if project.project_url:
                        message += f"\n🔗 <a href='{project.project_url}'>Страница проекта</a>"
                    if project.website:
                        message += f" | <a href='{project.website}'>Сайт</a>"
                    message += "\n"
                
            except Exception as api_err:
                logger.warning(f"⚠️ Не удалось загрузить данные из API: {api_err}")
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                for idx, promo in enumerate(promos):
                    title = promo.get('title', 'Без названия')
                    message += f"🪙 <b>{self.escape_html(title)}</b>\n"
                    link = promo.get('link', '')
                    if link:
                        message += f"🔗 {link}\n"
                    if idx < len(promos) - 1:
                        message += "\n"
            
            # Проверяем лимит Telegram
            if len(message) > 4090:
                logger.warning(f"⚠️ {display_name}: сообщение слишком длинное ({len(message)})")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Launchpool: {e}", exc_info=True)
            return f"🌊 <b>LAUNCHPOOL</b>\n\n❌ Ошибка форматирования"

    def format_bybit_launchpool_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу Bybit Launchpool с USD эквивалентами
        """
        try:
            from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
            from datetime import datetime
            
            def fmt_number(n, decimals=0):
                """Форматирует число с разделителями"""
                try:
                    num = float(str(n).replace(',', '').replace(' ', ''))
                    if decimals > 0:
                        return f'{num:,.{decimals}f}'
                    return f'{num:,.0f}'
                except:
                    return str(n)
            
            def fmt_usd(amount):
                """Форматирует USD сумму"""
                try:
                    num = float(amount)
                    if num >= 1_000_000:
                        return f"${num/1_000_000:.2f}M"
                    elif num >= 1_000:
                        return f"${num/1_000:.2f}K"
                    else:
                        return f"${num:.2f}"
                except:
                    return f"${amount}"
            
            # Заголовок
            message = "🟡 <b>BYBIT</b> | 🌊 <b>LAUNCHPOOL</b>\n\n"
            
            if not promos:
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                message += "📭 <i>Нет активных launchpool проектов</i>\n"
                return message
            
            # Получаем актуальные данные из API
            try:
                parser = BybitLaunchpoolParser()
                projects = parser.get_projects(status_filter='active')
                
                if not projects:
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    message += "📭 <i>Нет активных launchpool проектов</i>\n"
                    return message
                
                # Получаем цены токенов
                token_prices = {}
                try:
                    if self.price_fetcher:
                        # Собираем все токены для запроса цен
                        tokens_to_fetch = set()
                        for project in projects:
                            tokens_to_fetch.add(project.token_symbol)
                            for pool in project.pools:
                                tokens_to_fetch.add(pool.stake_coin)
                        
                        # Получаем цены
                        for token in tokens_to_fetch:
                            try:
                                price = self.price_fetcher.get_token_price(token, 'bybit')
                                if price and price > 0:
                                    token_prices[token] = price
                            except:
                                pass
                except Exception as price_err:
                    logger.warning(f"⚠️ Ошибка получения цен: {price_err}")
                
                # Форматируем каждый проект
                for idx, project in enumerate(projects):
                    message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    # Токен
                    message += f"🪙 <b>{project.token_name} ({project.token_symbol})</b>\n"
                    message += f"📊 <b>Статус:</b> {project.get_status_emoji()} {project.get_status_text()}\n"
                    
                    # Общий пул наград с USD
                    if project.total_pool_tokens > 0:
                        pool_str = f"{fmt_number(project.total_pool_tokens)} {project.token_symbol}"
                        token_price = token_prices.get(project.token_symbol, 0)
                        if token_price > 0:
                            pool_usd = project.total_pool_tokens * token_price
                            pool_str += f" ({fmt_usd(pool_usd)})"
                        message += f"💰 <b>Общий пул наград:</b> {pool_str}\n"
                    elif project.total_pool_usd > 0:
                        message += f"💰 <b>Общий пул наград:</b> {fmt_usd(project.total_pool_usd)}\n"
                    
                    message += f"⏰ <b>Осталось:</b> {project.time_remaining_str}\n"
                    
                    # Пулы для стейкинга
                    for i, pool in enumerate(project.pools, 1):
                        message += "\n"
                        
                        # Название пула с APR и звездой для лучшего
                        is_best_apr = pool.apr == project.max_apr
                        star = " ⭐" if is_best_apr and len(project.pools) > 1 else ""
                        pool_name = f"📦 <b>ПУЛ #{i}: {pool.stake_coin} | {pool.apr:.0f}%{star}</b>"
                        message += f"{pool_name}\n"
                        
                        # Макс депозит с USD
                        stake_price = token_prices.get(pool.stake_coin, 0)
                        if pool.max_stake > 0:
                            max_str = f"{fmt_number(pool.max_stake)} {pool.stake_coin}"
                            if stake_price > 0:
                                max_usd = pool.max_stake * stake_price
                                max_str += f" ({fmt_usd(max_usd)})"
                            message += f"   🔒 Макс. депозит: {max_str}\n"
                        else:
                            message += f"   🔒 Макс. депозит: Без лимита\n"
                        
                        # Расчёт заработка (используем дробные дни для точности)
                        days_left = project.days_left
                        hours_left = project.hours_left
                        # Если меньше дня, используем часы переведённые в дни
                        if days_left == 0 and hours_left > 0:
                            days_for_calc = hours_left / 24
                            time_label = f"{hours_left}ч"
                        else:
                            days_for_calc = days_left + (hours_left / 24)
                            time_label = f"{days_left}д"
                        
                        if days_for_calc > 0 and pool.apr > 0:
                            message += f"\n   💰 <b>ЗАРАБОТОК ЗА {time_label}:</b>\n"
                            
                            if pool.max_stake > 0:
                                # Есть лимит - показываем 25%, 50%, 100%
                                amounts = [
                                    pool.max_stake * 0.25,
                                    pool.max_stake * 0.5,
                                    pool.max_stake
                                ]
                                for amt in amounts:
                                    # Используем days_for_calc для точного расчёта
                                    earnings = amt * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = amt == pool.max_stake
                                    star = " ⭐️" if is_max else ""
                                    
                                    # Форматируем депозит с USD
                                    if stake_price > 0:
                                        deposit_usd = amt * stake_price
                                        earnings_usd = earnings * stake_price
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin} ({fmt_usd(deposit_usd)}){star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin} ({fmt_usd(earnings_usd)})\n"
                                    else:
                                        message += f"      🔸 Депозит: {fmt_number(amt)} {pool.stake_coin}{star}\n"
                                        if is_max:
                                            message += f"         <b>Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}</b>\n"
                                        else:
                                            message += f"         Доход: ~{fmt_number(earnings, 0)} {pool.stake_coin}\n"
                            else:
                                # Нет лимита - показываем $1000, $2500, $5000
                                for usd in [1000, 2500, 5000]:
                                    earnings_usd = usd * (pool.apr / 100) * (days_for_calc / 365)
                                    is_max = usd == 5000
                                    star = " ⭐️" if is_max else ""
                                    message += f"      🔸 Депозит: ${fmt_number(usd)}{star}\n"
                                    if is_max:
                                        message += f"         <b>Доход: ~{fmt_usd(earnings_usd)}</b>\n"
                                    else:
                                        message += f"         Доход: ~{fmt_usd(earnings_usd)}\n"
                    
                    # Период
                    message += f"\n⏰ <b>ПЕРИОД:</b>\n"
                    if project.start_time:
                        message += f"   • Старт: {project.start_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    if project.end_time:
                        message += f"   • Конец: {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC\n"
                    
                    # Ссылки
                    if project.project_url:
                        message += f"\n🔗 <a href='{project.project_url}'>Страница проекта</a>"
                    if project.website:
                        message += f" | <a href='{project.website}'>Сайт</a>"
                    message += "\n"
                
            except Exception as api_err:
                logger.warning(f"⚠️ Не удалось загрузить данные из API: {api_err}")
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                # Fallback - показываем из БД
                for idx, promo in enumerate(promos):
                    title = promo.get('title', 'Без названия')
                    message += f"🪙 <b>{self.escape_html(title)}</b>\n"
                    link = promo.get('link', '')
                    if link:
                        message += f"🔗 {link}\n"
                    if idx < len(promos) - 1:
                        message += "\n"
            
            # Проверяем лимит Telegram
            if len(message) > 4090:
                logger.warning(f"⚠️ Bybit Launchpool: сообщение слишком длинное ({len(message)})")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Обрезано</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Bybit Launchpool: {e}", exc_info=True)
            return f"🌊 <b>BYBIT LAUNCHPOOL</b>\n\n❌ Ошибка форматирования"

    def format_weex_airdrop_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу Weex Airdrop Hub промоакций
        
        Args:
            promos: Список промоакций (из WeexParser)
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
        """
        try:
            from datetime import datetime

            def fmt_number(n):
                """Форматирует число с разделителями"""
                try:
                    return '{:,.0f}'.format(float(str(n).replace(',', '').replace(' ', '')))
                except:
                    return str(n)

            def fmt_time(timestamp):
                """Форматирует timestamp в дату"""
                if not timestamp:
                    return ''
                try:
                    # Конвертируем строку в число если это timestamp
                    if isinstance(timestamp, str):
                        # Проверяем, что это числовой timestamp
                        if timestamp.isdigit() or (timestamp.replace('.', '', 1).isdigit() and timestamp.count('.') <= 1):
                            timestamp = float(timestamp)
                        else:
                            return str(timestamp)  # Уже отформатированная дата
                    
                    if isinstance(timestamp, (int, float)):
                        if timestamp > 10**10:
                            timestamp = timestamp / 1000
                        dt = datetime.fromtimestamp(timestamp)
                        return dt.strftime("%d.%m.%Y %H:%M")
                    return str(timestamp)
                except:
                    return str(timestamp)
            
            def calc_days_remaining(end_timestamp):
                """Рассчитывает оставшиеся дни"""
                if not end_timestamp:
                    return None
                try:
                    # Конвертируем строку в число
                    if isinstance(end_timestamp, str) and end_timestamp.isdigit():
                        end_timestamp = float(end_timestamp)
                    
                    if isinstance(end_timestamp, (int, float)):
                        if end_timestamp > 10**10:
                            end_timestamp = end_timestamp / 1000
                        end_dt = datetime.fromtimestamp(end_timestamp)
                        now_dt = datetime.now()
                        
                        if end_dt > now_dt:
                            remaining = end_dt - now_dt
                            days = remaining.days
                            hours = remaining.seconds // 3600
                            
                            if days > 0:
                                return f"{days} дн. {hours} ч."
                            elif hours > 0:
                                minutes = (remaining.seconds % 3600) // 60
                                return f"{hours} ч. {minutes} мин."
                            else:
                                minutes = remaining.seconds // 60
                                return f"{minutes} мин."
                        else:
                            return "Завершено"
                except:
                    pass
                return None

            # Заголовок (время обновления добавляется в handlers.py)
            message = f"🟣 <b>WEEX</b> | 🪂 <b>AIRDROP HUB</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных airdrop</i>\n"
                return message

            # Форматируем каждую промоакцию
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без названия')
                token = promo.get('award_token') or promo.get('token', '')
                promo_id = promo.get('promo_id', '')
                
                # Название airdrop
                message += f"🪂 <b>{self.escape_html(title)}</b>"
                if token and token != title:
                    message += f" ({token})"
                message += "\n"
                
                # Описание проекта
                description = promo.get('description', '')
                if description:
                    # Обрезаем длинные описания
                    desc_short = description[:150] + '...' if len(description) > 150 else description
                    message += f"📝 <i>{self.escape_html(desc_short)}</i>\n"
                
                # Статус
                status = promo.get('status', '')
                if status == 'ongoing':
                    message += f"📊 <b>Статус:</b> ✅ Активен\n"
                elif status == 'upcoming':
                    message += f"📊 <b>Статус:</b> 🔜 Скоро\n"
                
                # Награда (призовой пул)
                reward = promo.get('total_prize_pool') or promo.get('reward')
                if reward:
                    message += f"💰 <b>Награда:</b> {self.escape_html(str(reward))}\n"
                
                # Участники с полной статистикой (как в GateCandy)
                participants = promo.get('participants_count') or promo.get('participants')
                if participants:
                    message += f"\n👥 <b>УЧАСТНИКИ:</b>\n"
                    message += f"   • Всего: {fmt_number(participants)}\n"
                    
                    # Получаем статистику из истории
                    participants_stats = promo.get('participants_stats', {})
                    
                    # Проверяем есть ли данные хотя бы за один интервал
                    has_any_history = any(f'{h}h' in participants_stats for h in [6, 12, 24])
                    
                    if has_any_history:
                        # Статистика за 6ч, 12ч, 24ч - показываем только те интервалы, где есть данные
                        for hours in [6, 12, 24]:
                            key = f'{hours}h'
                            if key in participants_stats:
                                stat = participants_stats[key]
                                diff = stat.get('diff', 0)
                                percent = stat.get('percent', 0)
                                sign = '+' if diff > 0 else ''
                                message += f"   • За {hours} ч: {sign}{fmt_number(diff)} ({sign}{percent:.0f}%)\n"
                    
                    # Новых с последнего обновления
                    if 'last_update' in participants_stats:
                        last = participants_stats['last_update']
                        diff = last.get('diff', 0)
                        time_ago = last.get('time_ago', '')
                        if diff > 0:
                            message += f"   • Новых ({time_ago}): +{fmt_number(diff)} 📈\n"
                        elif diff < 0:
                            message += f"   • Изменение ({time_ago}): {fmt_number(diff)} 📉\n"
                
                # Период акции с оставшимся временем
                start_time = promo.get('start_time') or promo.get('startTime')
                end_time = promo.get('end_time') or promo.get('endTime')
                
                if start_time or end_time:
                    message += "\n📅 <b>ПЕРИОД:</b>\n"
                    
                    if start_time and end_time:
                        message += f"   • {fmt_time(start_time)} — {fmt_time(end_time)}\n"
                    elif start_time:
                        message += f"   • Начало: {fmt_time(start_time)}\n"
                    elif end_time:
                        message += f"   • Конец: {fmt_time(end_time)}\n"
                    
                    # Рассчитываем оставшееся время используя новую функцию
                    if end_time:
                        remaining_str = calc_days_remaining(end_time)
                        if remaining_str:
                            message += f"   • ⏳ Осталось: {remaining_str}\n"
                
                # Ссылка
                url = promo.get('link') or promo.get('url')
                if url:
                    message += f"\n🔗 {url}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Ссылка на страницу
            if page_url:
                message += f"\n\n🌐 <b>Страница:</b> {self.escape_html(page_url)}"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Weex: {e}", exc_info=True)
            return f"🎁 <b>WEEX AIRDROP HUB</b>\n\n<b>Биржа:</b> Weex\n\n❌ Ошибка форматирования данных"

    def format_weex_rewards_page(
        self,
        promos: List[Dict],
        page: int,
        total_pages: int,
        page_url: str = None
    ) -> str:
        """
        Форматирует страницу WEEX Rewards (все активности)
        
        Args:
            promos: Список промоакций (из WeexParser для /rewards)
            page: Номер страницы
            total_pages: Всего страниц
            page_url: URL страницы
        """
        try:
            from datetime import datetime

            def fmt_time(timestamp):
                """Форматирует timestamp в дату"""
                if not timestamp:
                    return ''
                try:
                    # Конвертируем строку в число если это timestamp
                    if isinstance(timestamp, str):
                        if timestamp.isdigit() or (timestamp.replace('.', '', 1).isdigit() and timestamp.count('.') <= 1):
                            timestamp = float(timestamp)
                        else:
                            return str(timestamp)  # Уже отформатированная дата
                    
                    if isinstance(timestamp, (int, float)):
                        if timestamp > 10**10:
                            timestamp = timestamp / 1000
                        dt = datetime.fromtimestamp(timestamp)
                        return dt.strftime("%d.%m.%Y %H:%M")
                    return str(timestamp)
                except:
                    return str(timestamp)

            def calc_days_remaining(end_timestamp):
                """Рассчитывает оставшиеся дни"""
                if not end_timestamp:
                    return None
                try:
                    if isinstance(end_timestamp, str) and end_timestamp.isdigit():
                        end_timestamp = float(end_timestamp)
                    
                    if isinstance(end_timestamp, (int, float)):
                        if end_timestamp > 10**10:
                            end_timestamp = end_timestamp / 1000
                        end_dt = datetime.fromtimestamp(end_timestamp)
                        now_dt = datetime.now()
                        
                        if end_dt > now_dt:
                            remaining = end_dt - now_dt
                            days = remaining.days
                            hours = remaining.seconds // 3600
                            
                            if days > 0:
                                return f"{days} дн. {hours} ч."
                            elif hours > 0:
                                minutes = (remaining.seconds % 3600) // 60
                                return f"{hours} ч. {minutes} мин."
                            else:
                                minutes = remaining.seconds // 60
                                return f"{minutes} мин."
                        else:
                            return "Завершено"
                except:
                    pass
                return None

            # Заголовок (время обновления добавляется в handlers.py)
            message = f"🟣 <b>WEEX</b> | 🎁 <b>REWARDS</b>\n\n"

            # Если промоакций нет
            if not promos:
                message += "📭 <i>Нет активных промоакций</i>\n"
                return message

            # Форматируем каждую промоакцию (компактный вид для 5 на страницу)
            for idx, promo in enumerate(promos):
                title = promo.get('title', 'Без названия')
                description = promo.get('description', '')
                
                # Номер и название промоакции
                message += f"<b>{idx + 1}. {self.escape_html(title)}</b>\n"
                
                # Статус + Тип активности
                status = promo.get('status', '')
                activity_type = promo.get('activityType')
                type_emoji = ''
                type_name = ''
                
                # Определяем тип активности
                if activity_type == 2:
                    type_emoji = '🏆'
                    type_name = 'Trading Competition'
                elif activity_type == 7:
                    type_emoji = '🎁'
                    type_name = 'Promo'
                elif activity_type:
                    type_emoji = '📌'
                    type_name = f'Activity #{activity_type}'
                
                status_text = '✅ Активна' if status == 'ongoing' else '🔜 Скоро' if status == 'upcoming' else ''
                if status_text and type_name:
                    message += f"   {status_text} | {type_emoji} {type_name}\n"
                elif status_text:
                    message += f"   {status_text}\n"
                
                # Описание (краткое)
                if description:
                    # Обрезаем длинные описания
                    desc_short = description[:100] + '...' if len(description) > 100 else description
                    message += f"   📝 {self.escape_html(desc_short)}\n"
                
                # Период акции с оставшимся временем
                start_time = promo.get('startTime')
                end_time = promo.get('endTime')
                
                if start_time or end_time:
                    message += "\n   ⏰ <b>ПЕРИОД АКЦИИ:</b>\n"
                    
                    if start_time and end_time:
                        message += f"      • Период: {fmt_time(start_time)} / {fmt_time(end_time)}\n"
                    elif start_time:
                        message += f"      • Начало: {fmt_time(start_time)}\n"
                    elif end_time:
                        message += f"      • Конец: {fmt_time(end_time)}\n"
                    
                    # Рассчитываем оставшееся время
                    if end_time:
                        try:
                            # Конвертируем timestamp в datetime
                            if isinstance(end_time, (int, float)):
                                end_dt = datetime.fromtimestamp(end_time / 1000 if end_time > 10**10 else end_time)
                                now_dt = datetime.utcnow()
                                
                                if end_dt > now_dt:
                                    remaining = end_dt - now_dt
                                    days = remaining.days
                                    hours = remaining.seconds // 3600
                                    
                                    if days > 0:
                                        message += f"      • Осталось: {days} дн. {hours} ч.\n"
                                    elif hours > 0:
                                        minutes = (remaining.seconds % 3600) // 60
                                        message += f"      • Осталось: {hours} ч. {minutes} мин.\n"
                                    else:
                                        minutes = remaining.seconds // 60
                                        message += f"      • Осталось: {minutes} мин.\n"
                        except Exception as e:
                            logger.debug(f"Ошибка расчета оставшегося времени: {e}")
                
                # Ссылка
                url = promo.get('url')
                if url:
                    message += f"\n   🔗 {url}\n"
                
                # Разделитель между промоакциями
                if idx < len(promos) - 1:
                    message += "\n"

            # Ссылка на страницу
            if page_url:
                message += f"\n\n🌐 <b>Страница:</b> {self.escape_html(page_url)}"

            # Проверяем лимит Telegram (4096 символов)
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования Weex Rewards: {e}", exc_info=True)
            return f"🎁 <b>WEEX REWARDS</b>\n\n<b>Биржа:</b> WEEX\n\n❌ Ошибка форматирования данных"

    def format_new_weex_rewards_notification(
        self,
        promo: Dict,
        link_name: str = None
    ) -> str:
        """
        Форматирует уведомление о новой промоакции WEEX Rewards
        
        Args:
            promo: Данные промоакции
            link_name: Название ссылки (опционально)
        """
        try:
            from datetime import datetime

            def fmt_time(timestamp):
                """Форматирует timestamp в дату"""
                if not timestamp:
                    return None
                try:
                    # Конвертируем строку в число если это timestamp
                    if isinstance(timestamp, str):
                        if timestamp.isdigit() or (timestamp.replace('.', '', 1).isdigit() and timestamp.count('.') <= 1):
                            timestamp = float(timestamp)
                        else:
                            return None
                    
                    if isinstance(timestamp, (int, float)):
                        if timestamp > 10**10:
                            timestamp = timestamp / 1000
                        dt = datetime.fromtimestamp(timestamp)
                        return dt.strftime("%d.%m.%Y")
                    return None
                except:
                    return None

            def calc_duration_days(start_timestamp, end_timestamp):
                """Рассчитывает продолжительность в днях"""
                if not start_timestamp or not end_timestamp:
                    return None
                try:
                    if isinstance(start_timestamp, str) and start_timestamp.isdigit():
                        start_timestamp = float(start_timestamp)
                    if isinstance(end_timestamp, str) and end_timestamp.isdigit():
                        end_timestamp = float(end_timestamp)
                    
                    if isinstance(start_timestamp, (int, float)) and isinstance(end_timestamp, (int, float)):
                        if start_timestamp > 10**10:
                            start_timestamp = start_timestamp / 1000
                        if end_timestamp > 10**10:
                            end_timestamp = end_timestamp / 1000
                        
                        start_dt = datetime.fromtimestamp(start_timestamp)
                        end_dt = datetime.fromtimestamp(end_timestamp)
                        
                        duration = end_dt - start_dt
                        return duration.days
                except:
                    pass
                return None

            title = promo.get('title', 'Без названия')
            description = promo.get('description', '')
            start_time = promo.get('startTime') or promo.get('start_time')
            end_time = promo.get('endTime') or promo.get('end_time')
            url = promo.get('url') or promo.get('link', '')
            promo_id = promo.get('promo_id', '')

            # Форматируем заголовок
            message = "🟣 <b>WEEX | 🎁 REWARDS | 🆕 NEW</b>\n\n"
            
            # Название
            message += f"📛 <b>Название:</b> {self.escape_html(title)}\n"
            
            # Описание
            if description:
                message += f"📝 <b>Описание:</b> {self.escape_html(description)}\n"
            
            # Период
            start_str = fmt_time(start_time)
            end_str = fmt_time(end_time)
            
            if start_str and end_str:
                duration = calc_duration_days(start_time, end_time)
                if duration is not None:
                    message += f"📅 <b>Период:</b> {start_str} - {end_str} ({duration} дней)\n"
                else:
                    message += f"📅 <b>Период:</b> {start_str} - {end_str}\n"
            elif end_str:
                message += f"📅 <b>Период:</b> До {end_str}\n"
            elif start_str:
                message += f"📅 <b>Период:</b> С {start_str}\n"
            
            # Ссылка
            if url:
                message += f"🔗 <b>Ссылка:</b> {url}\n"
            
            # ID
            if promo_id:
                message += f"\n<code>ID: {promo_id}</code>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования уведомления Weex Rewards: {e}", exc_info=True)
            return f"🎉 <b>НОВАЯ ПРОМОАКЦИЯ НА WEEX!</b>\n\n❌ Ошибка форматирования"

    async def notify_account_blocked(
        self,
        chat_id: int,
        account_name: str,
        phone_number: str,
        reason: str,
        new_account_name: Optional[str] = None,
        new_phone_number: Optional[str] = None,
        affected_links: List[str] = None
    ):
        """
        Отправляет уведомление о блокировке Telegram аккаунта и автоматическом переключении

        Args:
            chat_id: ID чата для отправки уведомления
            account_name: Имя заблокированного аккаунта
            phone_number: Номер заблокированного аккаунта
            reason: Причина блокировки (тип ошибки)
            new_account_name: Имя нового аккаунта (если fallback успешен)
            new_phone_number: Номер нового аккаунта
            affected_links: Список названий затронутых ссылок
        """
        try:
            # Формируем сообщение о блокировке
            message = "⚠️ <b>TELEGRAM АККАУНТ ЗАБЛОКИРОВАН!</b>\n\n"

            # Информация о заблокированном аккаунте
            message += f"<b>🚫 Заблокированный аккаунт:</b>\n"
            message += f"├─ Имя: {self.escape_html(account_name)}\n"
            message += f"├─ Номер: +{self.escape_html(phone_number)}\n"
            message += f"└─ Причина: {self.escape_html(reason)}\n\n"

            # Информация о переключении
            if new_account_name:
                message += "✅ <b>АВТОМАТИЧЕСКОЕ ПЕРЕКЛЮЧЕНИЕ УСПЕШНО!</b>\n\n"
                message += f"<b>🔄 Новый аккаунт:</b>\n"
                message += f"├─ Имя: {self.escape_html(new_account_name)}\n"
                message += f"└─ Номер: +{self.escape_html(new_phone_number)}\n\n"
                message += "<i>✓ Парсинг продолжается с новым аккаунтом</i>"
            else:
                message += "❌ <b>НЕТ ДОСТУПНЫХ АККАУНТОВ ДЛЯ ЗАМЕНЫ!</b>\n\n"
                message += "<i>⚠️ Парсинг Telegram ссылок остановлен</i>\n\n"
                message += "Действия для исправления:\n"
                message += "1. Добавьте новый Telegram аккаунт\n"
                message += "2. Или разблокируйте существующий аккаунт\n"
                message += "3. Парсинг возобновится автоматически"

            # Список затронутых ссылок (если есть)
            if affected_links:
                message += "\n\n<b>📋 Затронутые ссылки:</b>\n"
                for link_name in affected_links[:5]:  # Показываем максимум 5 ссылок
                    message += f"  • {self.escape_html(link_name)}\n"

                if len(affected_links) > 5:
                    message += f"  <i>...и еще {len(affected_links) - 5}</i>\n"

            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"
            )

            logger.info(f"📤 Уведомление о блокировке аккаунта отправлено в чат {chat_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о блокировке: {e}")

    def format_new_staking_notification(
        self,
        staking: Dict[str, Any],
        lock_type: str = 'Unknown',
        page_url: str = None
    ) -> str:
        """
        Форматирование умного уведомления о новом стейкинге

        Args:
            staking: Данные стейкинга из парсера
            lock_type: Тип блокировки ('Fixed', 'Flexible', 'Combined', 'Unknown')
            page_url: Ссылка на страницу стейкингов

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # Базовая информация
            coin = self.escape_html(staking.get('coin', 'N/A'))
            reward_coin = self.escape_html(staking.get('reward_coin')) if staking.get('reward_coin') else None
            exchange = self.escape_html(staking.get('exchange', 'N/A'))
            apr = staking.get('apr', 0)
            term_days = staking.get('term_days', 0)
            term_type = self.escape_html(staking.get('type', 'N/A'))
            token_price = staking.get('token_price_usd')
            status = self.escape_html(staking.get('status', 'N/A'))

            # Заголовок в зависимости от типа
            if lock_type == 'Fixed':
                message = "🔒 <b>НОВЫЙ FIXED СТЕЙКИНГ!</b>\n\n"
            elif lock_type == 'Flexible':
                message = "🌊 <b>НОВЫЙ FLEXIBLE СТЕЙКИНГ</b> (стабилизирован)\n\n"
            elif lock_type == 'Combined':
                message = "💎 <b>НОВЫЙ COMBINED СТЕЙКИНГ!</b>\n\n"
            else:
                message = "🆕 <b>НОВЫЙ СТЕЙКИНГ!</b>\n\n"

            # Основная информация
            if reward_coin and reward_coin != coin:
                message += f"<b>💎 Стейкай:</b> {coin}\n"
                message += f"<b>🎁 Награда:</b> {reward_coin}\n"
            else:
                message += f"<b>💎 Монета:</b> {coin}\n"

            message += f"<b>🏦 Биржа:</b> {exchange}\n"
            message += f"<b>💰 APR:</b> {apr}%\n"

            # Период
            if term_days == 0:
                message += f"<b>📅 Период:</b> Flexible (бессрочно)\n"
            else:
                message += f"<b>📅 Период:</b> {term_days} дней\n"

            # Тип
            if term_type:
                message += f"<b>🔧 Тип:</b> {term_type}\n"
            if status:
                message += f"<b>📊 Статус:</b> {status}\n"

            # Заполненность (если есть)
            fill_percentage = staking.get('fill_percentage')
            if fill_percentage is not None:
                message += f"\n<b>📊 Заполненность:</b> "
                if fill_percentage < 30:
                    message += "🟢 "
                elif fill_percentage < 70:
                    message += "🟡 "
                else:
                    message += "🔴 "
                message += f"{fill_percentage:.1f}%\n"

            # Лимиты
            user_limit_tokens = staking.get('user_limit_tokens')
            user_limit_usd = staking.get('user_limit_usd')

            if user_limit_tokens:
                message += f"\n<b>👤 Лимит на пользователя:</b> {user_limit_tokens:,.2f} {coin}"
                if user_limit_usd:
                    message += f" (~${user_limit_usd:,.2f})"
                message += "\n"

            # Цена токена
            if token_price:
                message += f"<b>💵 Цена токена:</b> ${token_price:,.4f}\n"

            # Даты
            start_time = staking.get('start_time')
            end_time = staking.get('end_time')

            if start_time or end_time:
                message += "\n"
            if start_time:
                message += f"<b>⏰ Старт:</b> {self.escape_html(str(start_time))}\n"
            if end_time:
                message += f"<b>🕐 Конец:</b> {self.escape_html(str(end_time))}\n"

            # Ссылка
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования нового стейкинга: {e}", exc_info=True)
            return f"🆕 <b>Новый стейкинг!</b>\n\n<b>Монета:</b> {self.escape_html(staking.get('coin', 'Unknown'))}\n<b>APR:</b> {staking.get('apr', 0)}%"

    def format_apr_change_notification(
        self,
        staking: Dict[str, Any],
        old_apr: float,
        new_apr: float,
        lock_type: str = 'Unknown',
        page_url: str = None
    ) -> str:
        """
        Форматирование уведомления об изменении APR

        Args:
            staking: Данные стейкинга из парсера
            old_apr: Предыдущий APR
            new_apr: Новый APR
            lock_type: Тип блокировки ('Fixed', 'Flexible', 'Combined', 'Unknown')
            page_url: Ссылка на страницу стейкингов

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # Базовая информация
            coin = self.escape_html(staking.get('coin', 'N/A'))
            exchange = self.escape_html(staking.get('exchange', 'N/A'))
            apr_change = new_apr - old_apr

            # Определяем направление изменения
            if apr_change > 0:
                change_emoji = "📈"
                change_text = "УВЕЛИЧЕНИЕ APR"
                change_symbol = "↑"
            else:
                change_emoji = "📉"
                change_text = "СНИЖЕНИЕ APR"
                change_symbol = "↓"

            # Заголовок
            message = f"{change_emoji} <b>{change_text}!</b>\n\n"
            message += f"<b>💎 Монета:</b> {coin}\n"
            message += f"<b>🏦 Биржа:</b> {exchange}\n\n"

            # Изменение APR
            message += f"<b>💰 APR:</b>\n"
            message += f"   Было: {old_apr}%\n"
            message += f"   Стало: <b>{new_apr}%</b> {change_symbol} {abs(apr_change):.2f}%\n"

            # Тип стейкинга
            if lock_type != 'Unknown':
                message += f"\n<b>🔧 Тип:</b> {lock_type}\n"

            # Для Flexible указываем, что APR стабилизирован
            if lock_type == 'Flexible':
                message += "<i>✓ APR стабилизирован в течение 6 часов</i>\n"

            # Период
            term_days = staking.get('term_days', 0)
            if term_days == 0:
                message += f"<b>📅 Период:</b> Flexible (бессрочно)\n"
            else:
                message += f"<b>📅 Период:</b> {term_days} дней\n"

            # Статус
            status = staking.get('status')
            if status:
                message += f"<b>📊 Статус:</b> {self.escape_html(status)}\n"

            # Заполненность (если есть)
            fill_percentage = staking.get('fill_percentage')
            if fill_percentage is not None:
                message += f"\n<b>📊 Заполненность:</b> "
                if fill_percentage < 30:
                    message += "🟢 "
                elif fill_percentage < 70:
                    message += "🟡 "
                else:
                    message += "🔴 "
                message += f"{fill_percentage:.1f}%\n"

            # Ссылка
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования изменения APR: {e}", exc_info=True)
            return f"📈 <b>Изменение APR!</b>\n\n<b>Монета:</b> {self.escape_html(staking.get('coin', 'Unknown'))}\n<b>APR:</b> {old_apr}% → {new_apr}%"