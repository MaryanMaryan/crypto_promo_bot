"""
Проверка сырых данных через тот же метод что и парсер
"""
import sys
sys.path.insert(0, '.')

from parsers.staking_parser import StakingParser

# Патчим _parse_bybit чтобы увидеть сырые данные
original_parse = StakingParser._parse_bybit

def debug_parse(self, data, has_auth=False):
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print("=== СЫРЫЕ ДАННЫЕ API BYBIT ===\n")
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        coin_name = cp.get('coin_name', 'N/A')
        
        for sp in cp.get('saving_products', []):
            apy = sp.get('apy', '0%')
            apy_float = float(apy.replace('%', ''))
            
            if apy_float >= 100:
                print(f"=== Product {sp.get('product_id')} ===")
                print(f"  coin_id: {coin_id}, coin_name: {coin_name}")
                print(f"  APY: {apy}")
                print(f"  product_max_share: {sp.get('product_max_share')}")
                print(f"  total_deposit_share: {sp.get('total_deposit_share')}")
                print(f"  min_deposit_share: {sp.get('min_deposit_share')}")
                print(f"  max_deposit_share: {sp.get('max_deposit_share')}")
                print(f"  user_max_subscribe: {sp.get('user_max_subscribe')}")
                print(f"  staking_term: {sp.get('staking_term')}")
                print()
    
    return original_parse(self, data, has_auth)

StakingParser._parse_bybit = debug_parse

# Запускаем парсер
parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)

stakings = parser.parse()
print(f"\n=== Итого: {len(stakings)} стейкингов ===")
