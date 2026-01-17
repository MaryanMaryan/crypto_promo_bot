"""
Отладка: проверка условий для Binance
"""

import logging
from parsers.staking_parser import StakingParser

logging.basicConfig(level=logging.INFO, format='%(message)s')

# Получаем реальные данные
API_URL = 'https://www.binance.com/bapi/earn/v1/friendly/finance-earn/homepage/overview?pageSize=100'
parser = StakingParser(api_url=API_URL, exchange_name='Binance')
stakings = parser.parse()

# Берем первый стейкинг
if stakings:
    s = stakings[0]
    
    print('='*70)
    print('DEBUG: Проверка условий')
    print('='*70)
    print()
    
    # Значения для проверки
    exchange_name = "BinanceEarn"
    product_type = s.get('type', '')
    
    print(f"exchange_name: '{exchange_name}'")
    print(f"staking['exchange']: '{s.get('exchange')}'")
    print(f"staking['type']: '{product_type}'")
    print(f"staking['product_type']: '{s.get('product_type')}'")
    print()
    
    # Проверяем условия
    print('УСЛОВИЯ:')
    print(f"1. product_type == 'Fixed/Flexible': {product_type == 'Fixed/Flexible'}")
    print(f"2. 'binance' in exchange_name.lower(): {'binance' in exchange_name.lower()}")
    print(f"3. staking['exchange'].lower() == 'binance': {s.get('exchange', '').lower() == 'binance'}")
    print()
    
    # Какое условие сработает?
    if product_type == 'Fixed/Flexible':
        print('✅ СРАБОТАЕТ: Fixed/Flexible секция (Gate.io)')
    elif 'binance' in exchange_name.lower() or s.get('exchange', '').lower() == 'binance':
        print('✅ СРАБОТАЕТ: Binance секция')
    else:
        print('✅ СРАБОТАЕТ: Обычная секция (MEXC, Bybit и др.)')
