"""
Тест: Проверка названий монет в парсере Bybit
"""
import sys
import io

# Настройка UTF-8 для Windows консоли
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import logging
from parsers.staking_parser import StakingParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_bybit_coin_names():
    """Тест: Проверка что названия монет теперь правильные"""

    print("="*80)
    print("🔍 ТЕСТ: Названия монет Bybit (BTC, ETH, а не COIN_1, COIN_2)")
    print("="*80)
    print()

    parser = StakingParser(
        api_url="https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list",
        exchange_name="Bybit"
    )

    print("📡 Парсинг Bybit стейкингов...\n")

    stakings = parser.parse()

    if not stakings:
        print("❌ Не удалось получить данные от Bybit")
        return

    print(f"✅ Получено: {len(stakings)} стейкингов\n")

    # Группируем по монетам
    coins_count = {}
    coin_products_examples = {}

    for staking in stakings:
        coin = staking['coin']
        coins_count[coin] = coins_count.get(coin, 0) + 1

        # Сохраняем пример для каждой монеты
        if coin not in coin_products_examples:
            coin_products_examples[coin] = staking

    print("="*80)
    print(f"📊 СТАТИСТИКА ПО МОНЕТАМ")
    print("="*80)
    print(f"Уникальных монет: {len(coins_count)}\n")

    # Сортируем по количеству продуктов
    sorted_coins = sorted(coins_count.items(), key=lambda x: x[1], reverse=True)

    print("📋 ТОП-20 монет с наибольшим количеством продуктов:")
    print(f"{'Монета':<15} {'Продуктов':<10} {'Тип монеты'}")
    print("-"*80)

    for i, (coin, count) in enumerate(sorted_coins[:20], 1):
        coin_type = "✅ Реальное название" if not coin.startswith("COIN_") else "❌ Неизвестная (COIN_ID)"
        print(f"{coin:<15} {count:<10} {coin_type}")

    # Показываем примеры
    print(f"\n{'='*80}")
    print(f"📖 ПРИМЕРЫ СТЕЙКИНГОВ (первые 5)")
    print("="*80)

    for i, staking in enumerate(stakings[:5], 1):
        coin = staking['coin']
        apr = staking['apr']
        staking_type = staking['type']
        status = staking['status']

        print(f"\n{i}. {coin}")
        print(f"   APR: {apr}%")
        print(f"   Тип: {staking_type}")
        print(f"   Статус: {status}")

    # Статистика известных vs неизвестных
    known_coins = [c for c in coins_count.keys() if not c.startswith("COIN_")]
    unknown_coins = [c for c in coins_count.keys() if c.startswith("COIN_")]

    print(f"\n{'='*80}")
    print(f"📈 ИТОГОВАЯ СТАТИСТИКА")
    print("="*80)
    print(f"✅ Известных монет (реальные названия): {len(known_coins)} ({len(known_coins)/len(coins_count)*100:.1f}%)")
    print(f"❌ Неизвестных монет (COIN_ID):         {len(unknown_coins)} ({len(unknown_coins)/len(coins_count)*100:.1f}%)")
    print()

    if unknown_coins:
        print(f"⚠️ Неизвестные монеты (нужно добавить в маппинг):")
        print(f"{unknown_coins[:20]}...")
    else:
        print(f"🎉 Все монеты имеют правильные названия!")

if __name__ == "__main__":
    test_bybit_coin_names()
