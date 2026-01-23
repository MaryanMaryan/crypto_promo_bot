"""
Скрипт для поиска API endpoints лаунчпадов/лаунчпулов через Playwright
"""
import asyncio
import json
from playwright.async_api import async_playwright
from datetime import datetime

# Биржи для анализа
TARGETS = [
    {
        "name": "Gate.io Launchpool",
        "url": "https://www.gate.com/ru/launchpool",
        "keywords": ["launchpool", "pool", "startup", "api"]
    },
    {
        "name": "Gate.io Launchpad",
        "url": "https://www.gate.com/ru/launchpad",
        "keywords": ["launchpad", "startup", "ieo", "api"]
    },
    {
        "name": "MEXC Launchpool",
        "url": "https://www.mexc.com/ru-RU/launchpool",
        "keywords": ["launchpool", "pool", "mxdefi", "api"]
    },
    {
        "name": "Bybit Launchpool",
        "url": "https://www.bybit.com/en/trade/spot/launchpool",
        "keywords": ["launchpool", "pool", "earn", "api"]
    },
    {
        "name": "BingX Launchpool",
        "url": "https://bingx.com/ru-ru/launchpool",
        "keywords": ["launchpool", "pool", "api"]
    },
    {
        "name": "Bitget Launchpool",
        "url": "https://www.bitget.com/ru/launchpool",
        "keywords": ["launchpool", "pool", "earn", "api"]
    },
]

async def find_apis():
    """Ищем API endpoints для всех бирж"""
    
    results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=False чтобы видеть
        
        for target in TARGETS:
            print(f"\n{'='*60}")
            print(f"🔍 Анализируем: {target['name']}")
            print(f"   URL: {target['url']}")
            print('='*60)
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            api_calls = []
            
            # Перехватываем все network запросы
            async def handle_response(response):
                url = response.url
                content_type = response.headers.get('content-type', '')
                
                # Фильтруем только API/JSON запросы
                if ('application/json' in content_type or 
                    '/api/' in url or 
                    any(kw in url.lower() for kw in target['keywords'])):
                    
                    # Игнорируем статику
                    if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.svg', '.woff']):
                        return
                    
                    try:
                        status = response.status
                        body = None
                        if status == 200 and 'application/json' in content_type:
                            try:
                                body = await response.json()
                            except:
                                pass
                        
                        api_calls.append({
                            "url": url,
                            "status": status,
                            "content_type": content_type,
                            "body_preview": str(body)[:500] if body else None,
                            "has_data": body is not None
                        })
                        
                        # Показываем найденный API
                        print(f"   📡 [{status}] {url[:100]}...")
                        
                    except Exception as e:
                        pass
            
            page.on("response", handle_response)
            
            try:
                # Загружаем страницу
                await page.goto(target['url'], wait_until='networkidle', timeout=30000)
                
                # Ждём дополнительно для динамической загрузки
                await asyncio.sleep(3)
                
                # Скроллим чтобы загрузить больше данных
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"   ❌ Ошибка загрузки: {e}")
            
            await context.close()
            
            # Сохраняем результаты
            results[target['name']] = {
                "url": target['url'],
                "api_calls": api_calls,
                "found_count": len(api_calls)
            }
            
            print(f"\n   ✅ Найдено API запросов: {len(api_calls)}")
        
        await browser.close()
    
    # Сохраняем все результаты
    output_file = "launch_apis_found.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n{'='*60}")
    print(f"📁 Результаты сохранены в: {output_file}")
    print('='*60)
    
    # Красивый вывод
    print("\n\n📊 СВОДКА НАЙДЕННЫХ API:\n")
    for name, data in results.items():
        print(f"\n🏦 {name}")
        print(f"   Страница: {data['url']}")
        print(f"   Найдено запросов: {data['found_count']}")
        
        # Показываем самые релевантные API
        relevant = [c for c in data['api_calls'] if c['has_data']]
        if relevant:
            print("   📡 API с данными:")
            for api in relevant[:5]:  # Топ 5
                print(f"      • {api['url'][:80]}...")

if __name__ == "__main__":
    asyncio.run(find_apis())
