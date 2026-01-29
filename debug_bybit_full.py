"""
Проверка сырых данных API Bybit - все поля
"""
import asyncio
import sys
sys.path.insert(0, '.')

from parsers.browser_parser import BrowserParser

async def debug_bybit():
    """Получим ПОЛНЫЕ сырые данные API"""
    url = "https://www.bybit.com/x-api/s1/byfi/get-easy-earn-product-list?language=en-US&operationType=1&clientType=PC"
    browser = BrowserParser(url)
    
    print("Запрос к API Bybit...")
    raw_data = await browser.fetch_json(url)
    
    if not raw_data or 'result' not in raw_data:
        print("Не удалось получить данные")
        return
    
    result = raw_data.get('result', {})
    coin_products = result.get('coin_products', [])
    
    print(f"\n=== Найдено {len(coin_products)} групп продуктов ===\n")
    
    # Показываем ВСЕ поля первой группы
    if coin_products:
        first = coin_products[0]
        print("=== СТРУКТУРА ГРУППЫ (первый элемент) ===")
        for key, value in first.items():
            if key == 'saving_products':
                print(f"  {key}: [{len(value)} продуктов]")
            else:
                print(f"  {key}: {value}")
        
        # Показываем ВСЕ поля первого продукта
        if first.get('saving_products'):
            sp = first['saving_products'][0]
            print("\n=== СТРУКТУРА ПРОДУКТА (первый продукт первой группы) ===")
            for key, value in sp.items():
                print(f"  {key}: {value}")
    
    # Теперь проверяем USDT стейкинги (coin=5 с высоким APR)
    print("\n\n=== USDT СТЕЙКИНГИ (проверка единиц) ===\n")
    
    for cp in coin_products:
        coin_id = cp.get('coin')
        
        for sp in cp.get('saving_products', []):
            apy_str = sp.get('apy', '0%')
            apy = float(apy_str.replace('%', '')) if apy_str else 0
            
            # Только высокий APR (вероятно USDT)
            if apy >= 400:
                max_share = sp.get('product_max_share', '0')
                deposited = sp.get('total_deposit_share', '0')
                min_subscribe = sp.get('min_subscribe')
                max_subscribe = sp.get('max_subscribe')
                precision = sp.get('precision')
                coin_precision = sp.get('coin_precision')
                tag = sp.get('tag', '')
                
                max_share_f = float(max_share)
                deposited_f = float(deposited)
                
                print(f"Product ID: {sp.get('product_id')}")
                print(f"  coin_id: {coin_id}")
                print(f"  tag: {tag}")
                print(f"  APY: {apy}%")
                print(f"  staking_term: {sp.get('staking_term')} days")
                print(f"  precision: {precision}")
                print(f"  coin_precision: {coin_precision}")
                print(f"  min_subscribe: {min_subscribe}")
                print(f"  max_subscribe: {max_subscribe}")
                print(f"  --")
                print(f"  product_max_share RAW: {max_share}")
                print(f"  total_deposit_share RAW: {deposited}")
                print(f"  --")
                print(f"  Если делить на 10^6: {max_share_f / 10**6:,.2f}")
                print(f"  Если делить на 10^8: {max_share_f / 10**8:,.2f}")
                print(f"  Если целые: {max_share_f:,.0f}")
                available = max_share_f - deposited_f
                print(f"  Доступно: {available:,.0f}")
                print()

if __name__ == "__main__":
    asyncio.run(debug_bybit())
