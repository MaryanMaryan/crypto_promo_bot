"""
Скрипт для отправки тестовых уведомлений о стейкинге
Отправляет реальные уведомления о существующих стейкингах с Bybit и KuCoin
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

async def send_test_staking_notifications():
    """Отправляет тестовые уведомления о стейкинге"""

    # Импортируем конфигурацию
    from config import BOT_TOKEN, ADMIN_CHAT_ID

    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ УВЕДОМЛЕНИЙ О СТЕЙКИНГЕ")
    print("=" * 80)

    # Создаем бота
    bot = Bot(token=BOT_TOKEN)
    notification_service = NotificationService(bot)

    try:
        # 1. BYBIT СТЕЙКИНГ
        print("\n1️⃣ Получение стейкинга с Bybit...")
        bybit_parser = StakingParser(
            api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
            exchange_name="Bybit"
        )

        bybit_stakings = bybit_parser.parse()

        if bybit_stakings:
            # Фильтруем активные стейкинги с разумным APR
            active_bybit = [
                s for s in bybit_stakings
                if s.get('status') == 'Active' and s.get('apr', 0) > 0
            ]

            if active_bybit:
                # Сортируем по APR и берём один с высоким APR
                active_bybit.sort(key=lambda x: x.get('apr', 0), reverse=True)
                test_staking = active_bybit[0]

                print(f"   ✅ Найден стейкинг: {test_staking['coin']} с APR {test_staking['apr']}%")

                # Формируем и отправляем уведомление
                message = notification_service.format_new_staking(
                    test_staking,
                    page_url="https://www.bybit.com/en/earn/easy-earn"
                )

                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                print(f"   📤 Уведомление о Bybit стейкинге отправлено!")
            else:
                print("   ⚠️ Нет активных стейкингов на Bybit")
        else:
            print("   ❌ Не удалось получить данные с Bybit")

        # Небольшая пауза между сообщениями
        await asyncio.sleep(1)

        # 2. KUCOIN СТЕЙКИНГ
        print("\n2️⃣ Получение стейкинга с KuCoin...")
        kucoin_parser = StakingParser(
            api_url="https://www.kucoin.com/_pxapi/pool-staking/v4/low-risk/products?new_listed=1",
            exchange_name="Kucoin"
        )

        kucoin_stakings = kucoin_parser.parse()

        if kucoin_stakings:
            # Фильтруем активные стейкинги с разумным APR
            active_kucoin = [
                s for s in kucoin_stakings
                if s.get('status') == 'ONGOING' and s.get('apr', 0) > 0
            ]

            if active_kucoin:
                # Сортируем по APR и берём один с высоким APR
                active_kucoin.sort(key=lambda x: x.get('apr', 0), reverse=True)
                test_staking = active_kucoin[0]

                print(f"   ✅ Найден стейкинг: {test_staking['coin']} с APR {test_staking['apr']}%")

                # Формируем и отправляем уведомление
                message = notification_service.format_new_staking(
                    test_staking,
                    page_url="https://www.kucoin.com/earn/finance"
                )

                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                print(f"   📤 Уведомление о KuCoin стейкинге отправлено!")
            else:
                print("   ⚠️ Нет активных стейкингов на KuCoin")
        else:
            print("   ❌ Не удалось получить данные с KuCoin")

        print("\n" + "=" * 80)
        print("✅ ТЕСТ ЗАВЕРШЕН!")
        print("=" * 80)

    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомлений: {e}", exc_info=True)

    finally:
        # Закрываем сессию бота
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_test_staking_notifications())
