"""
Проверка decimals для разных токенов
"""
import sys
sys.path.insert(0, '.')

from parsers.staking_parser import StakingParser

original_parse = StakingParser._parse_bybit

def debug_parse(self, data, has_auth=False):
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print("\n=== АНАЛИЗ DECIMALS ПО ТОКЕНАМ ===\n")
    
    # Известные decimals для токенов
    KNOWN_DECIMALS = {
        'USDT': 6,  # TRC20/ERC20
        'USDC': 6,
        'BTC': 8,
        'ETH': 18,
        'BNB': 18,
    }
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        
        for sp in cp.get('saving_products', []):
            apy_str = sp.get('apy', '0%')
            apy = float(apy_str.replace('%', '')) if apy_str else 0
            
            if apy >= 100:
                tag = sp.get('tag', '')
                max_share = float(sp.get('product_max_share', 0))
                
                # Определяем токен
                if coin_id == 5 and apy >= 100:
                    symbol = 'USDT'
                elif tag and '_' in tag:
                    symbol = tag.split('_')[0].upper()
                else:
                    symbol = f"COIN_{coin_id}"
                
                print(f"=== {symbol} (coin_id={coin_id}) | {apy}% APR ===")
                print(f"  RAW: {max_share:,.0f}")
                print(f"  /10^3 = {max_share/1000:,.0f}")
                print(f"  /10^6 = {max_share/1_000_000:,.0f}")
                print(f"  /10^8 = {max_share/100_000_000:,.2f}")
                print(f"  /10^12 = {max_share/1_000_000_000_000:,.4f}")
                print()
    
    return original_parse(self, data, has_auth)

StakingParser._parse_bybit = debug_parse

parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)
parser.parse()
