"""
Проверка сырых данных API Bybit для проверки единиц измерения
"""
import sys
sys.path.insert(0, '.')

from parsers.staking_parser import StakingParser

# Патчим _parse_bybit чтобы увидеть ВСЕ сырые поля
original_parse = StakingParser._parse_bybit

def debug_parse(self, data, has_auth=False):
    result = data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print("\n=== СЫРЫЕ ДАННЫЕ API BYBIT ===\n")
    
    # Сначала покажем структуру первого продукта целиком
    if coin_products:
        first_cp = coin_products[0]
        print("=== СТРУКТУРА ГРУППЫ ===")
        for key, value in first_cp.items():
            if key == 'saving_products':
                print(f"  {key}: [{len(value)} продуктов]")
            else:
                print(f"  {key}: {value}")
        
        if first_cp.get('saving_products'):
            first_sp = first_cp['saving_products'][0]
            print("\n=== ВСЕ ПОЛЯ ПРОДУКТА ===")
            for key, value in sorted(first_sp.items()):
                print(f"  {key}: {value}")
    
    print("\n\n=== ПРОВЕРКА ЕДИНИЦ (USDT стейкинги) ===\n")
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        
        for sp in cp.get('saving_products', []):
            apy_str = sp.get('apy', '0%')
            apy = float(apy_str.replace('%', '')) if apy_str else 0
            
            # Только высокий APR
            if apy >= 400:
                max_share = sp.get('product_max_share', '0')
                deposited = sp.get('total_deposit_share', '0')
                min_sub = sp.get('min_subscribe')
                max_sub = sp.get('max_subscribe')
                precision = sp.get('precision')
                coin_prec = sp.get('coin_precision')
                tag = sp.get('tag', '')
                
                max_share_f = float(max_share)
                deposited_f = float(deposited)
                available = max_share_f - deposited_f
                
                print(f"Product {sp.get('product_id')} | {apy}% APR | {sp.get('staking_term')} дней")
                print(f"  coin_id: {coin_id}, tag: {tag}")
                print(f"  precision: {precision}, coin_precision: {coin_prec}")
                print(f"  min_subscribe: {min_sub}, max_subscribe: {max_sub}")
                print(f"  ---")
                print(f"  product_max_share: {max_share_f:,.0f}")
                print(f"  total_deposit_share: {deposited_f:,.0f}")
                print(f"  available: {available:,.0f}")
                print(f"  ---")
                print(f"  Если это USDT (целые): ${max_share_f:,.0f}")
                print(f"  Если это USDT / 10^6: ${max_share_f / 10**6:,.2f}")
                print(f"  Если это USDT / 10^8: ${max_share_f / 10**8:,.4f}")
                print()
    
    # Вызываем оригинал
    return original_parse(self, data, has_auth)

# Патчим
StakingParser._parse_bybit = debug_parse

# Запускаем парсер
print("Запуск парсера...")
parser = StakingParser(
    api_url='https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list',
    exchange_name='BybitEARN'
)

stakings = parser.parse()
print(f"\n=== Итого спарсено: {len(stakings)} стейкингов ===")
