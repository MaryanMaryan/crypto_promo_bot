"""
Проверка min/max subscribe для определения decimals
"""
import sys
sys.path.insert(0, '.')

from parsers.staking_parser import StakingParser

# Патчим _parse_bybit
original_parse = StakingParser._parse_bybit

def debug_parse(self, data, has_auth=False):
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print("\n=== ПРОВЕРКА min/max для определения decimals ===\n")
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        
        for sp in cp.get('saving_products', []):
            apy_str = sp.get('apy', '0%')
            apy = float(apy_str.replace('%', '')) if apy_str else 0
            
            # Показываем все продукты с данными о min/max
            max_share = float(sp.get('product_max_share', 0))
            term = sp.get('staking_term')
            
            # Для USDT стейкингов
            if coin_id == 5 and apy >= 100:
                tag = sp.get('tag', '')
                
                print(f"=== Product {sp.get('product_id')} (USDT-like, coin=5) ===")
                print(f"  APY: {apy}% | Term: {term} days")
                print(f"  tag: '{tag}'")
                print(f"  max_share: {max_share:,.0f}")
                
                # Ищем поля с подсказкой о min/max
                for key in ['min_subscribe', 'max_subscribe', 'min_deposit_share', 'max_deposit_share', 
                            'user_max_subscribe', 'per_order_limit', 'min_share', 'coin_precision']:
                    val = sp.get(key)
                    if val is not None:
                        print(f"  {key}: {val}")
                
                # Если max_share ~ 6 billion и реально это 6000 USDT
                # То decimals = 6 (10^6 = 1,000,000)
                print(f"  ---")
                print(f"  Если decimals=6: {max_share / 10**6:,.2f} USDT")
                print(f"  Если decimals=8: {max_share / 10**8:,.4f} USDT")
                print()
    
    return original_parse(self, data, has_auth)

StakingParser._parse_bybit = debug_parse

print("Запуск...")
parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)

stakings = parser.parse()
