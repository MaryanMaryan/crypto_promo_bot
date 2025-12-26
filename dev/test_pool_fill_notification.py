"""
Скрипт для тестирования уведомлений о заполненности пулов
"""
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot
from parsers.staking_parser import StakingParser
from bot.notification_service import NotificationService

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def send_pool_fill_notification():
    """Отправляет уведомление о заполненности пулов"""

    # Импортируем конфигурацию
    from config import BOT_TOKEN, ADMIN_CHAT_ID

    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ УВЕДОМЛЕНИЙ О ЗАПОЛНЕННОСТИ ПУЛОВ")
    print("=" * 80)

    # Создаем бота
    bot = Bot(token=BOT_TOKEN)
    notification_service = NotificationService(bot)

    try:
        # Получаем данные о пулах Bybit
        print("\n📡 Получение данных о пулах Bybit...")
        bybit_parser = StakingParser(
            api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
            exchange_name="Bybit"
        )

        pools = bybit_parser.get_pool_fills()

        if pools:
            print(f"   ✅ Найдено {len(pools)} пулов с данными о заполненности")

            # Фильтруем топ-10 по APR
            pools.sort(key=lambda x: x.get('apr', 0), reverse=True)
            top_pools = pools[:10]

            # Формируем отчет
            message = notification_service.format_pools_report(
                pools=top_pools,
                exchange_name="Bybit",
                page_url="https://www.bybit.com/en/earn/easy-earn"
            )

            # Отправляем
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

            print(f"   📤 Отчёт о заполненности отправлен!")
            print(f"\n   Топ-5 пулов:")
            for i, pool in enumerate(top_pools[:5], 1):
                print(f"   {i}. {pool['coin']:8s} | {pool['apr']:7.2f}% APR | Заполнено: {pool.get('fill_percentage', 0):.2f}%")

        else:
            print("   ⚠️ Нет данных о заполненности пулов")

        print("\n" + "=" * 80)
        print("✅ ТЕСТ ЗАВЕРШЕН!")
        print("=" * 80)

    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления: {e}", exc_info=True)

    finally:
        # Закрываем сессию бота
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_pool_fill_notification())
