import logging
from aiogram import Bot
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    def format_promo_message(self, promo: Dict[str, Any]) -> str:
        """Форматирует сообщение о промоакции в красивый HTML"""
        try:
            message = "🎉 <b>НОВАЯ ПРОМОАКЦИЯ!</b>\n\n"

            # Биржа
            message += f"<b>🏢 Биржа:</b> {promo.get('exchange', 'Unknown')}\n"

            # Название
            if promo.get('title'):
                message += f"<b>📌 Название:</b> {promo['title']}\n"

            # Описание (обрезаем если слишком длинное)
            if promo.get('description'):
                desc = promo['description']
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                message += f"<b>📝 Описание:</b> {desc}\n"

            # Призовой фонд
            if promo.get('total_prize_pool'):
                message += f"<b>💰 Призовой фонд:</b> {promo['total_prize_pool']}\n"

            # Токен награды
            if promo.get('award_token'):
                message += f"<b>🎯 Токен награды:</b> {promo['award_token']}\n"

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

    async def send_bulk_notifications(self, chat_id: int, promos: List[Dict[str, Any]]):
        """Отправляет уведомления о нескольких промоакциях"""
        if not promos:
            return

        logger.info(f"📨 Отправка {len(promos)} уведомлений в чат {chat_id}")

        for i, promo in enumerate(promos, 1):
            await self.send_promo_notification(chat_id, promo)
            # Небольшая задержка между сообщениями чтобы не спамить
            if i < len(promos):
                import asyncio
                await asyncio.sleep(0.5)

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