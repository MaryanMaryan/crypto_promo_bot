"""
Скрипт для отправки тестовых уведомлений о найденных постах
"""
import asyncio
from aiogram import Bot
import config

# Примеры найденных постов
test_messages = [
    {
        'channel': '@WEEXNews',
        'link_name': 'WeexTS',
        'message_id': 8714,
        'date': '2026-01-05 11:05:13',
        'keywords': ['Airdrop', 'Trading Campaign', 'claim', 'Event Details', 'worth of'],
        'text': '''📣 #WEEX Exclusive Airdrop Alert!

New users can claim up to $50,000 worth of $DEPINSIM in the Trading Campaign!

📅05/01/2026, 14:00 - 12/01/2026, 14:00 (UTC+1)

🔗 Event Details: https://app.sensor.weex.tech:8106/t/ZLa
📝Register: https://bit.ly/44qKAwK

🚀 Join now and grab your rewards!'''
    },
    {
        'channel': '@MEXC_ENchannel',
        'link_name': 'MexcAirdrop',
        'message_id': 24938,
        'date': '2026-01-05 09:45:41',
        'keywords': ['MEXC New Kickstarter'],
        'text': '''MEXC New Kickstarter!

‣ $QIE @qieblockchain
‣ Trading: Jan 6, 2026, 10:00 (UTC)

Details: https://www.mexc.com/announcements/article/17827791532723'''
    }
]

async def send_notifications():
    """Отправка тестовых уведомлений"""
    bot = Bot(token=config.BOT_TOKEN)

    print("\n🤖 ОТПРАВКА ТЕСТОВЫХ УВЕДОМЛЕНИЙ\n")
    print(f"📤 Отправляю {len(test_messages)} уведомлений пользователю {config.ADMIN_CHAT_ID}\n")

    for i, msg in enumerate(test_messages, 1):
        print(f"{'='*80}")
        print(f"📨 Отправка уведомления {i}/{len(test_messages)}")
        print(f"{'='*80}")

        # Формируем сообщение
        keywords_str = ", ".join([f"<code>{kw}</code>" for kw in msg['keywords']])
        message_link = f"https://t.me/{msg['channel'].replace('@', '')}/{msg['message_id']}"

        notification = f"""🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ - Найдена промоакция!</b>

📢 <b>Канал:</b> {msg['channel']} ({msg['link_name']})
📅 <b>Дата:</b> {msg['date']}
🔗 <b>Ссылка:</b> {message_link}

🔑 <b>Совпавшие ключевые слова:</b> {keywords_str}

📝 <b>Текст сообщения:</b>
{'-'*50}
{msg['text']}
{'-'*50}

💡 <i>Это тестовое уведомление для демонстрации работы парсинга Telegram каналов.</i>
"""

        try:
            await bot.send_message(
                config.ADMIN_CHAT_ID,
                notification,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            print(f"✅ Уведомление {i} отправлено успешно!\n")
            await asyncio.sleep(2)  # Пауза между сообщениями

        except Exception as e:
            print(f"❌ Ошибка отправки уведомления {i}: {e}\n")

    print(f"{'='*80}")
    print(f"✅ Отправка завершена! Проверьте бота.")
    print(f"{'='*80}\n")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_notifications())
