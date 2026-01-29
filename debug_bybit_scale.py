"""
Проверяем что реально показывает Bybit на сайте
Сравниваем с API данными
"""
import sys
sys.path.insert(0, '.')

from parsers.staking_parser import StakingParser

# Патчим _parse_bybit
original_parse = StakingParser._parse_bybit

def debug_parse(self, data, has_auth=False):
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print("\n=== АНАЛИЗ МАСШТАБА ДАННЫХ ===\n")
    print("Вопрос: какой реальный размер пула?\n")
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        
        for sp in cp.get('saving_products', []):
            apy_str = sp.get('apy', '0%')
            apy = float(apy_str.replace('%', '')) if apy_str else 0
            
            # Только высокий APR
            if apy >= 400 and coin_id == 5:
                max_share = float(sp.get('product_max_share', 0))
                deposited = float(sp.get('total_deposit_share', 0))
                term = sp.get('staking_term')
                
                print(f"=== Product {sp.get('product_id')} | {apy}% APR | {term} дней ===")
                print(f"  RAW max_share: {max_share:,.0f}")
                print(f"  RAW deposited: {deposited:,.0f}")
                print()
                print("  Варианты интерпретации:")
                print(f"    Если целые токены:    {max_share:>20,.0f} USDT")
                print(f"    Если decimals=2:      {max_share/100:>20,.2f} USDT")
                print(f"    Если decimals=3:      {max_share/1000:>20,.2f} USDT")
                print(f"    Если decimals=6:      {max_share/1_000_000:>20,.2f} USDT")
                print(f"    Если decimals=8:      {max_share/100_000_000:>20,.4f} USDT")
                print()
                
                # Если лимит $300 и ~20000 аккаунтов = 6M USDT
                # Тогда 6,083,000,000 должно быть ~6M
                # 6,083,000,000 / 6,000,000 = 1013.83 ≈ 1000
                # То есть decimals = 3? Или данные уже в тысячах?
                
                print(f"  Логический анализ (лимит $300, ~20000 мест):")
                expected_pool = 300 * 20000  # 6M USDT
                ratio = max_share / expected_pool if expected_pool > 0 else 0
                print(f"    Ожидаемый пул: ~${expected_pool:,.0f}")
                print(f"    Соотношение RAW/ожидаемый: {ratio:,.2f}")
                print(f"    Если ratio ~1000, то decimals=3")
                print(f"    Если ratio ~1000000, то decimals=6")
                print()
    
    return original_parse(self, data, has_auth)

StakingParser._parse_bybit = debug_parse

print("Запуск...")
parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)
stakings = parser.parse()
