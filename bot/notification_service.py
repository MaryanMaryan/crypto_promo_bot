import logging
import html
from aiogram import Bot
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    @staticmethod
    def escape_html(text: Any) -> str:
        """Безопасное экранирование HTML-символов"""
        if text is None:
            return 'N/A'
        return html.escape(str(text))

    def format_promo_message(self, promo: Dict[str, Any]) -> str:
        """Форматирует сообщение о промоакции в красивый HTML"""
        try:
            message = "🎉 <b>НОВАЯ ПРОМОАКЦИЯ!</b>\n\n"

            # Биржа
            message += f"<b>🏢 Биржа:</b> {self.escape_html(promo.get('exchange', 'Unknown'))}\n"

            # Название
            if promo.get('title'):
                message += f"<b>📌 Название:</b> {self.escape_html(promo['title'])}\n"

            # Описание (обрезаем если слишком длинное)
            if promo.get('description'):
                desc = str(promo['description'])
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                message += f"<b>📝 Описание:</b> {self.escape_html(desc)}\n"

            # Призовой фонд
            if promo.get('total_prize_pool'):
                message += f"<b>💰 Призовой фонд:</b> {self.escape_html(promo['total_prize_pool'])}\n"

            # Токен награды
            if promo.get('award_token'):
                message += f"<b>🎯 Токен награды:</b> {self.escape_html(promo['award_token'])}\n"

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
                message += f"\n<b>📈 Заполненность:</b> {fill_percentage:.2f}%\n"

                # Прогресс бар
                filled_blocks = int(fill_percentage / 5)  # 20 блоков = 100%
                empty_blocks = 20 - filled_blocks
                progress_bar = "▓" * filled_blocks + "░" * empty_blocks
                message += f"{progress_bar}\n"

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

            # Ссылка
            if page_url:
                message += f"\n<b>🔗 Ссылка:</b> {self.escape_html(page_url)}"

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