import logging
import html
import re
from aiogram import Bot
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, bot: Bot, price_fetcher=None):
        self.bot = bot
        self.price_fetcher = price_fetcher

        # Если price_fetcher не передан, создаем его
        if self.price_fetcher is None:
            try:
                from utils.price_fetcher import get_price_fetcher
                self.price_fetcher = get_price_fetcher()
            except Exception as e:
                logger.warning(f"⚠️ Не удалось инициализировать price_fetcher: {e}")
                self.price_fetcher = None

    @staticmethod
    def escape_html(text: Any) -> str:
        """Безопасное экранирование HTML-символов"""
        if text is None:
            return 'N/A'
        return html.escape(str(text))

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
            message = "🎉 <b>НОВАЯ ПРОМОАКЦИЯ!</b>\n\n"

            # Биржа
            message += f"<b>🏢 Биржа:</b> {self.escape_html(promo.get('exchange', 'Unknown'))}\n"

            # Название
            if promo.get('title'):
                message += f"<b>📌 Название:</b> {self.escape_html(promo['title'])}\n"
            
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

            # Призовой фонд с парсингом токенов и ценами (ТОЛЬКО если это НЕ Telegram сообщение)
            if promo.get('total_prize_pool') and not is_telegram_message:
                prize_pool_text = str(promo['total_prize_pool'])
                tokens = self.parse_token_amounts(prize_pool_text)

                if tokens:
                    # Если нашли токены, показываем их с ценами
                    message += f"<b>💰 Призовой фонд:</b>\n"
                    for amount, token_symbol, price_usd in tokens:
                        formatted_value = self.format_token_value(amount, token_symbol, price_usd)
                        message += f"   • {formatted_value}\n"
                else:
                    # Если токены не найдены, показываем как есть
                    message += f"<b>💰 Призовой фонд:</b> {self.escape_html(prize_pool_text)}\n"

            # Токен награды с парсингом и ценой
            if promo.get('award_token'):
                award_token_text = str(promo['award_token'])
                tokens = self.parse_token_amounts(award_token_text)

                if tokens:
                    # Если нашли токены, показываем их с ценами
                    message += f"<b>🎯 Награды:</b>\n"
                    for amount, token_symbol, price_usd in tokens:
                        formatted_value = self.format_token_value(amount, token_symbol, price_usd)
                        message += f"   • {formatted_value}\n"
                else:
                    # Если токены не найдены, показываем как есть
                    message += f"<b>🎯 Токен награды:</b> {self.escape_html(award_token_text)}\n"

            # Количество участников/мест
            if promo.get('participants_count'):
                message += f"<b>👥 Участники:</b> {promo['participants_count']}\n"

            # Период действия
            if promo.get('start_time') and promo.get('end_time'):
                message += f"<b>📅 Период:</b> {promo['start_time']} - {promo['end_time']}\n"
            elif promo.get('start_time'):
                message += f"<b>📅 Начало:</b> {promo['start_time']}\n"
            elif promo.get('end_time'):
                message += f"<b>📅 Окончание:</b> {promo['end_time']}\n"

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
        Форматирование уведомления о новом проекте OKX (все пулы в одном сообщении)

        Args:
            stakings: Список пулов проекта
            page_url: Ссылка на страницу

        Returns:
            Отформатированное HTML сообщение
        """
        if not stakings:
            return ""

        # Берём общие данные из первого пула
        first = stakings[0]
        reward_coin = self.escape_html(first.get('reward_coin') or first.get('coin'))
        exchange = self.escape_html(first.get('exchange', 'OKX'))
        end_time = first.get('end_time')
        start_time = first.get('start_time')
        reward_amount = first.get('reward_amount')
        term_days = first.get('term_days', 0)
        term_type = self.escape_html(first.get('type', 'N/A'))
        status = self.escape_html(first.get('status', 'Active'))

        # Формируем сообщение
        message = f"🆕 <b>НОВЫЙ СТЕЙКИНГ!</b>\n\n"

        # Собираем все стейкаемые монеты
        stake_coins = [self.escape_html(pool.get('coin', 'N/A')) for pool in stakings]
        message += f"<b>💎 Стейкай:</b> {', '.join(stake_coins)}\n"

        # Награда с количеством на пул и стоимостью в USD
        reward_price = first.get('reward_token_price_usd')
        if reward_amount:
            message += f"<b>🎁 Награда:</b> {reward_coin} ({reward_amount} на пул"

            # Добавляем стоимость в USD если известна цена
            if reward_price:
                try:
                    # Убираем запятые из числа и конвертируем
                    clean_amount = reward_amount.replace(',', '')
                    total_reward_usd = float(clean_amount) * reward_price
                    message += f", ~${total_reward_usd:,.2f}"
                except (ValueError, AttributeError):
                    pass

            message += ")\n"
        else:
            message += f"<b>🎁 Награда:</b> {reward_coin}\n"

        message += f"<b>🏦 Биржа:</b> {exchange}\n"

        # APR для каждого пула
        apr_parts = []
        for pool in stakings:
            coin = self.escape_html(pool.get('coin', 'N/A'))
            apr = pool.get('apr', 0)
            apr_parts.append(f"{coin}: {apr:.2f}%")
        message += f"<b>💰 APR:</b> {' | '.join(apr_parts)}\n"

        # Период
        if term_days == 0:
            message += f"<b>📅 Период:</b> Flexible (бессрочно)\n"
        else:
            message += f"<b>📅 Период:</b> {term_days} дней\n"

        # Тип и статус
        if term_type:
            message += f"<b>🔧 Тип:</b> {term_type}\n"
        if status:
            message += f"<b>📊 Статус:</b> {status}\n"

        # Лимиты на человека для каждого пула
        message += f"\n<b>👤 ЛИМИТЫ НА ЧЕЛОВЕКА:</b>\n"
        for i, pool in enumerate(stakings):
            coin = self.escape_html(pool.get('coin', 'N/A'))
            user_limit = pool.get('user_limit_tokens')
            token_price = pool.get('token_price_usd')

            if user_limit:
                # Определяем символ для форматирования
                if i == len(stakings) - 1:
                    symbol = "└─"
                else:
                    symbol = "├─"

                limit_str = f"{symbol} {coin}: {user_limit:,.2f}"

                # USD эквивалент
                if token_price:
                    limit_usd = user_limit * token_price
                    limit_str += f" (~${limit_usd:,.2f})"

                message += limit_str + "\n"

        # Даты
        if start_time or end_time:
            message += "\n"

        if start_time:
            try:
                from datetime import datetime
                start_dt = datetime.fromtimestamp(start_time / 1000)
                message += f"<b>⏰ Старт:</b> {start_dt.strftime('%d.%m.%Y, %H:%M')}\n"
            except:
                message += f"<b>⏰ Старт:</b> Информация недоступна\n"

        if end_time:
            try:
                from datetime import datetime
                end_dt = datetime.fromtimestamp(end_time / 1000)
                message += f"<b>🕐 Конец:</b> {end_dt.strftime('%d.%m.%Y, %H:%M')}\n"
            except:
                message += f"<b>🕐 Конец:</b> Информация недоступна\n"

        # Ссылка
        if page_url:
            message += f"\n<b>🔗 Ссылка:</b> {page_url}"

        return message

    def format_new_staking(self, staking: Dict[str, Any], page_url: str = None) -> str:
        """
        Форматирование уведомления о новом стейкинге

        Args:
            staking: Данные стейкинга из парсера
            page_url: Ссылка на страницу стейкингов

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            # Базовая информация (с экранированием HTML)
            coin = self.escape_html(staking.get('coin', 'N/A'))
            reward_coin = self.escape_html(staking.get('reward_coin')) if staking.get('reward_coin') else None
            exchange = self.escape_html(staking.get('exchange', 'N/A'))
            apr = staking.get('apr', 0)
            term_days = staking.get('term_days', 0)
            term_type = self.escape_html(staking.get('type', 'N/A'))
            token_price = staking.get('token_price_usd')
            status = self.escape_html(staking.get('status', 'N/A'))
            category = self.escape_html(staking.get('category_text', staking.get('category')))

            # Лимиты
            user_limit_tokens = staking.get('user_limit_tokens')
            user_limit_usd = staking.get('user_limit_usd')
            total_places = staking.get('total_places')

            # Заполненность
            fill_percentage = staking.get('fill_percentage')

            # Даты
            start_time = staking.get('start_time')
            end_time = staking.get('end_time')

            # Формируем сообщение
            message = "🆕 <b>НОВЫЙ СТЕЙКИНГ!</b>\n\n"

            # Основная информация
            if reward_coin and reward_coin != coin:
                message += f"<b>💎 Стейкай:</b> {coin}\n"
                message += f"<b>🎁 Награда:</b> {reward_coin}\n"
            else:
                message += f"<b>💎 Монета:</b> {coin}\n"

            message += f"<b>🏦 Биржа:</b> {exchange}\n"
            message += f"<b>💰 APR:</b> {apr}%\n"

            # Пометки для VIP, New User и Regional
            is_vip = staking.get('is_vip', False)
            is_new_user = staking.get('is_new_user', False)
            regional_tag = staking.get('regional_tag')
            regional_countries = staking.get('regional_countries')

            if is_vip:
                message += f"<b>👑 VIP:</b> Только для VIP пользователей\n"

            if is_new_user:
                message += f"<b>🎁 NEW USER:</b> Только для новых пользователей\n"

            if regional_tag:
                # Региональное предложение
                region_name = regional_tag
                if regional_tag == 'CIS':
                    region_name = 'СНГ (CIS)'
                message += f"<b>🌍 REGIONAL:</b> {region_name}"
                if regional_countries:
                    message += f" ({regional_countries})"
                message += "\n"

            # Период
            if term_days == 0:
                message += f"<b>📅 Период:</b> Flexible (бессрочно)\n"
            else:
                message += f"<b>📅 Период:</b> {term_days} дней\n"

            # Тип и статус
            if term_type:
                message += f"<b>🔧 Тип:</b> {term_type}\n"
            if status:
                message += f"<b>📊 Статус:</b> {status}\n"
            if category:
                message += f"<b>🏷️ Категория:</b> {category}\n"

            # Цена токена
            if token_price:
                message += f"<b>💵 Цена токена:</b> ${token_price:.4f}\n"

            # Заполненность (если доступна)
            if fill_percentage is not None:
                # Прогресс бар (20 блоков = 100%)
                filled_blocks = int(fill_percentage / 5)
                empty_blocks = 20 - filled_blocks
                progress_bar = "▓" * filled_blocks + "░" * empty_blocks

                # Динамика изменений (если доступна)
                fill_change = staking.get('_fill_change')  # Изменение за последний час
                if fill_change is not None and fill_change != 0:
                    change_sign = "↑" if fill_change > 0 else "↓"
                    message += f"\n<b>📈 Заполненность:</b>\n{progress_bar} {fill_percentage:.2f}% ({change_sign} {abs(fill_change):.2f}% за час)\n"
                else:
                    message += f"\n<b>📈 Заполненность:</b>\n{progress_bar} {fill_percentage:.2f}%\n"

            # Лимиты
            if user_limit_tokens or user_limit_usd or total_places:
                message += "\n<b>👤 ЛИМИТ НА ЧЕЛОВЕКА:</b>\n"

                if user_limit_tokens:
                    message += f"├─ Макс. сумма: {user_limit_tokens:,.2f} {coin}\n"

                if user_limit_usd:
                    message += f"├─ Примерно: ${user_limit_usd:,.2f}\n"
                elif user_limit_tokens and token_price:
                    # Рассчитываем USD эквивалент
                    usd_value = user_limit_tokens * token_price
                    message += f"├─ Примерно: ${usd_value:,.2f}\n"

                if total_places:
                    message += f"└─ Всего мест: {total_places}\n"
            elif exchange == 'Kucoin':
                # KuCoin не предоставляет данные о лимитах в публичном API
                message += f"\n<i>ℹ️ Данные о лимитах доступны только на сайте биржи</i>\n"

            # Даты (с экранированием)
            if start_time or end_time:
                message += "\n"
                if start_time:
                    message += f"<b>⏰ Старт:</b> {self.escape_html(start_time)}\n"
                if end_time:
                    message += f"<b>🕐 Конец:</b> {self.escape_html(end_time)}\n"

            # УМНЫЕ УВЕДОМЛЕНИЯ: Информация о типе уведомления
            notification_type = staking.get('_notification_type', 'new')
            lock_type = staking.get('_lock_type', staking.get('lock_type', 'Unknown'))
            notification_reason = staking.get('_notification_reason', '')

            if notification_type == 'new':
                # Новый стейкинг
                if lock_type == 'Fixed':
                    message += f"\n\n⏱️ <b>Уведомление:</b> Новый Fixed стейкинг (отправлено сразу)"
                elif lock_type == 'Combined':
                    message += f"\n\n⏱️ <b>Уведомление:</b> Новый Combined стейкинг (содержит Fixed+Flexible, отправлено сразу)"
                elif lock_type == 'Flexible':
                    # Flexible стейкинг стабилизировался
                    stability_hours = staking.get('_stability_hours', 6)
                    message += f"\n\n⏱️ <b>Уведомление:</b> Flexible стейкинг стабилизирован ({stability_hours} часов без изменений APR)"
            elif notification_type == 'apr_change':
                # Изменение APR
                old_apr = staking.get('_previous_apr', 0)
                new_apr = staking.get('apr', 0)
                change = new_apr - old_apr
                change_percent = (change / old_apr * 100) if old_apr > 0 else 0

                message += f"\n\n📈 <b>ИЗМЕНЕНИЕ APR!</b>\n"
                message += f"📊 <b>Старый APR:</b> {old_apr}%\n"
                message += f"📊 <b>Новый APR:</b> {new_apr}%\n"
                message += f"🔺 <b>Изменение:</b> {'+' if change > 0 else ''}{change:.1f}% (↑ {abs(change_percent):.1f}%)\n\n"
                message += f"⏱️ <b>Уведомление:</b> Изменение APR ≥ {staking.get('_apr_threshold', 5)}% ({lock_type} стейкинг)"

            # Ссылка
            if page_url:
                message += f"\n\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

            # ВАЖНО: Telegram имеет лимит 4096 символов
            # Если сообщение слишком длинное, обрезаем его безопасно на границе строки
            if len(message) > 4090:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(message)} символов), обрезаем")
                lines = message[:4000].split('\n')
                message = '\n'.join(lines[:-1]) + "\n\n<i>⚠️ Сообщение обрезано из-за лимита длины</i>"

            return message

        except Exception as e:
            logger.error(f"❌ Ошибка форматирования стейкинга: {e}")
            return f"🆕 <b>Новый стейкинг!</b>\n\n<b>Монета:</b> {self.escape_html(staking.get('coin', 'Unknown'))}\n<b>APR:</b> {staking.get('apr', 0)}%"

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

    def format_current_stakings_page(
        self,
        stakings_with_deltas: List[Dict],
        page: int,
        total_pages: int,
        exchange_name: str,
        min_apr: float = None,
        page_url: str = None
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

        Returns:
            Отформатированное HTML сообщение
        """
        try:
            from datetime import datetime

            # Заголовок
            now = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
            message = f"📈 <b>ТЕКУЩИЕ СТЕЙКИНГИ</b>\n\n"
            message += f"<b>🏦 Биржа:</b> {self.escape_html(exchange_name)}\n"

            if min_apr is not None:
                message += f"<b>🔍 Фильтр APR:</b> ≥ {min_apr}%\n"

            message += f"<b>🕐 Обновлено:</b> {now}\n\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Если стейкингов нет
            if not stakings_with_deltas:
                message += "📭 <i>Нет стейкингов, соответствующих фильтру</i>\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

                # Пагинация
                message += f"📄 Страница {page} из {total_pages}\n"

                if page_url:
                    message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

                return message

            # Форматируем каждый стейкинг
            for idx, item in enumerate(stakings_with_deltas):
                staking = item['staking']
                deltas = item['deltas']
                alerts = item.get('alerts', [])

                # ЗАГОЛОВОК: Монета | APR | Срок
                coin = self.escape_html(staking['coin'] or 'N/A')
                apr = staking['apr'] or 0
                term_days = staking.get('term_days', 0)
                product_type = staking.get('type', '')

                # Проверяем, это объединенный продукт Fixed/Flexible?
                if product_type == 'Fixed/Flexible':
                    # Для объединенного продукта показываем оба APR
                    category_text = staking.get('category_text', '')
                    if category_text:
                        # category_text уже содержит "Fixed: X% | Flexible: Y%"
                        message += f"💰 <b>{coin}</b> | {apr:.1f}% APR max\n"
                        message += f"   📊 {self.escape_html(category_text)}\n"
                    else:
                        message += f"💰 <b>{coin}</b> | {apr:.1f}% APR | {product_type}\n"
                else:
                    # Обычный продукт - форматируем срок
                    if term_days == 0:
                        term_text = "Flexible"
                    elif term_days == 1:
                        term_text = "1 день"
                    elif term_days < 5:
                        term_text = f"{term_days} дня"
                    elif term_days < 21:
                        term_text = f"{term_days} дней"
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
                    message += f"📊 <b>Статус:</b> {status_emoji} {self.escape_html(status)}\n"

                # КАТЕГОРИЯ И ТИП (для KuCoin и других бирж)
                category = staking.get('category')
                product_type_raw = staking.get('type')
                category_text = staking.get('category_text')

                # Формируем текст категории
                if category or category_text or product_type_raw:
                    category_parts = []

                    # Категория (ACTIVITY = Акция, DEMAND = Сбережения)
                    if category:
                        if category == 'ACTIVITY':
                            category_parts.append('🎯 Акция')
                        elif category == 'DEMAND':
                            category_parts.append('💰 Сбережения')
                        elif category_text:
                            category_parts.append(f'📂 {self.escape_html(category_text)}')
                        else:
                            category_parts.append(f'📂 {self.escape_html(category)}')

                    # Тип продукта (MULTI_TIME = Срочный, SAVING = Гибкий)
                    if product_type_raw:
                        if product_type_raw == 'MULTI_TIME':
                            category_parts.append('⏱ Срочный')
                        elif product_type_raw == 'SAVING':
                            category_parts.append('🔄 Гибкий')
                        else:
                            category_parts.append(f'🔖 {self.escape_html(product_type_raw)}')

                    if category_parts:
                        message += f"🏷 <b>Тип:</b> {' | '.join(category_parts)}\n"

                # ВИЗУАЛЬНАЯ ШКАЛА ЗАПОЛНЕННОСТИ
                fill_percentage = staking.get('fill_percentage')
                fill_delta = deltas.get('fill_delta')

                if fill_percentage is not None:
                    # Создаем визуальную шкалу (20 блоков)
                    filled_blocks = int(fill_percentage / 5)  # 100% / 5 = 20 блоков
                    empty_blocks = 20 - filled_blocks
                    bar = "▓" * filled_blocks + "░" * empty_blocks

                    # Показываем дельту рядом с процентами
                    if deltas.get('has_previous', False) and fill_delta is not None and abs(fill_delta) >= 0.01:
                        if fill_delta > 0:
                            message += f"{bar} {fill_percentage:.2f}% (↑ +{fill_delta:.2f}% за час)\n"
                        else:
                            message += f"{bar} {fill_percentage:.2f}% (↓ {fill_delta:.2f}% за час)\n"
                    else:
                        message += f"{bar} {fill_percentage:.2f}%\n"

                # ЛИМИТЫ И ЗАПОЛНЕННОСТЬ
                max_capacity = staking.get('max_capacity')
                current_deposit = staking.get('current_deposit')
                token_price = staking.get('token_price_usd')

                if max_capacity and max_capacity > 0 and current_deposit is not None:
                    message += "\n💎 <b>ЛИМИТЫ И ЗАПОЛНЕННОСТЬ:</b>\n"

                    # Форматируем большие числа
                    def format_number(num):
                        if num >= 1_000_000_000:
                            return f"{num:,.2f}"
                        else:
                            return f"{num:,.2f}"

                    # Общий пул
                    if token_price:
                        pool_usd = max_capacity * token_price
                        message += f"   • Общий пул: {format_number(max_capacity)} {coin} (${pool_usd:,.0f})\n"
                    else:
                        message += f"   • Общий пул: {format_number(max_capacity)} {coin}\n"

                    # Занято
                    message += f"   • Занято: {format_number(current_deposit)} {coin} ({fill_percentage:.2f}%)\n"

                    # Осталось
                    available = max_capacity - current_deposit
                    if token_price:
                        available_usd = available * token_price
                        message += f"   • Осталось: <b>{format_number(available)} {coin}</b> (~${available_usd:,.0f})\n"
                    else:
                        message += f"   • Осталось: <b>{format_number(available)} {coin}</b>\n"

                    # Лимит на аккаунт (только если есть данные)
                    user_limit = staking.get('user_limit_tokens')
                    if user_limit and user_limit > 0:
                        if token_price:
                            limit_usd = user_limit * token_price
                            message += f"   • Лимит/аккаунт: {format_number(user_limit)} {coin} (~${limit_usd:,.0f})\n"
                        else:
                            message += f"   • Лимит/аккаунт: {format_number(user_limit)} {coin}\n"

                # ПЕРИОД СТЕЙКИНГА
                start_time = staking.get('start_time')
                end_time = staking.get('end_time')

                if start_time or end_time:
                    message += "\n⏰ <b>ПЕРИОД СТЕЙКИНГА:</b>\n"
                    if start_time:
                        message += f"   • Начало: {self.escape_html(start_time)}\n"
                    if end_time:
                        message += f"   • Конец: {self.escape_html(end_time)}\n"
                    if term_days and term_days > 0:
                        message += f"   • Длительность: {term_days} дней\n"

                # ТЕГИ (если есть)
                category_text = staking.get('category_text')
                if category_text:
                    message += f"\n🏷 <b>Теги:</b> {self.escape_html(category_text)}\n"

                # Разделитель между стейкингами (кроме последнего)
                if idx < len(stakings_with_deltas) - 1:
                    message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                else:
                    message += "\n"

            # Пагинация
            message += f"📄 Страница {page} из {total_pages}\n"

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