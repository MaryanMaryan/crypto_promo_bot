"""
Исследуем API Bybit Token Splash для поиска калькулятора наград
"""
import asyncio
import sys
sys.path.insert(0, '.')

async def find_calculator_api():
    """Ищем API калькулятора через Playwright - перехватываем сетевые запросы"""
    from playwright.async_api import async_playwright
    
    # URL страницы Token Splash
    url = "https://www.bybit.com/en/trade/spot/token-splash/detail?code=20260123095342"
    
    captured_requests = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Перехватываем ВСЕ API запросы
        async def capture_request(route, request):
            url = request.url
            if 'api' in url.lower() or 'x-api' in url.lower():
                captured_requests.append({
                    'url': url,
                    'method': request.method
                })
            await route.continue_()
        
        await page.route("**/*", capture_request)
        
        print(f"🔍 Загружаем страницу: {url}")
        await page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Ждём загрузки
        await asyncio.sleep(3)
        
        # Пробуем найти и кликнуть калькулятор
        try:
            calculator_btn = await page.query_selector('text=Rewards Calculator')
            if calculator_btn:
                print("✅ Найдена кнопка калькулятора, кликаем...")
                await calculator_btn.click()
                await asyncio.sleep(2)
        except Exception as e:
            print(f"⚠️ Не удалось найти кнопку калькулятора: {e}")
        
        await browser.close()
    
    print("\n" + "=" * 70)
    print("📡 ПЕРЕХВАЧЕННЫЕ API ЗАПРОСЫ:")
    print("=" * 70)
    
    for req in captured_requests:
        print(f"  {req['method']} {req['url']}")
    
    # Ищем интересные endpoints
    print("\n" + "=" * 70)
    print("🔍 ИНТЕРЕСНЫЕ ENDPOINTS (volume, trade, calculator):")
    print("=" * 70)
    
    keywords = ['volume', 'trade', 'calculator', 'reward', 'estimate', 'total']
    for req in captured_requests:
        url_lower = req['url'].lower()
        if any(kw in url_lower for kw in keywords):
            print(f"  ⭐ {req['url']}")

if __name__ == "__main__":
    asyncio.run(find_calculator_api())
