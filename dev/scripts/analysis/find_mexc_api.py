"""
MEXC Airdrop API Finder
Использует Playwright для перехвата network запросов и поиска API промоакций
"""
import asyncio
import json
import sys
from playwright.async_api import async_playwright

# Фикс кодировки для Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def find_mexc_api():
    """Найти API endpoints для промоакций MEXC"""
    
    # Список для хранения найденных API запросов
    api_requests = []
    
    async with async_playwright() as p:
        # Запускаем браузер
        print("🚀 Запуск браузера...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = await context.new_page()
        
        # Обработчик для перехвата network запросов
        async def handle_request(request):
            url = request.url
            method = request.method
            
            # Интересуют API запросы (обычно /api/, /bapi/, содержат json)
            if any(keyword in url.lower() for keyword in ['/api/', '/bapi/', 'airdrop', 'token', 'campaign', 'activity']):
                if method in ['GET', 'POST']:
                    print(f"\n📡 Найден API запрос:")
                    print(f"   Method: {method}")
                    print(f"   URL: {url}")
                    
                    # Сохраняем информацию
                    api_requests.append({
                        'method': method,
                        'url': url,
                        'headers': dict(request.headers),
                        'post_data': request.post_data if method == 'POST' else None
                    })
        
        # Обработчик для перехвата ответов
        async def handle_response(response):
            url = response.url
            
            # Ищем JSON ответы с данными о промоакциях
            if any(keyword in url.lower() for keyword in ['/api/', '/bapi/', 'airdrop', 'token', 'campaign', 'activity']):
                try:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        data = await response.json()
                        
                        print(f"\n✅ Получен JSON ответ:")
                        print(f"   URL: {url}")
                        print(f"   Status: {response.status}")
                        print(f"   Data keys: {list(data.keys()) if isinstance(data, dict) else 'array'}")
                        
                        # Сохраняем ответ
                        for req in api_requests:
                            if req['url'] == url:
                                req['response'] = data
                                req['status'] = response.status
                                break
                except Exception as e:
                    print(f"   ⚠️ Не удалось распарсить JSON: {e}")
        
        # Подключаем обработчики
        page.on('request', handle_request)
        page.on('response', handle_response)
        
        # Открываем страницу с аирдропами
        print(f"\n🌐 Открываем страницу: https://www.mexc.com/ru-RU/token-airdrop")
        try:
            await page.goto('https://www.mexc.com/ru-RU/token-airdrop', wait_until='domcontentloaded', timeout=15000)
        except Exception as e:
            print(f"   ⚠️ Timeout при загрузке, но продолжаем (это нормально): {e}")
        
        # Ждем дополнительное время для загрузки всех данных
        print("\n⏳ Ожидание загрузки данных (8 секунд)...")
        await asyncio.sleep(8)
        
        # Прокручиваем страницу для загрузки lazy-loaded контента
        print("\n📜 Прокрутка страницы...")
        for i in range(3):
            await page.evaluate('window.scrollBy(0, 1000)')
            await asyncio.sleep(1)
        
        await asyncio.sleep(2)
        
        # Закрываем браузер
        await browser.close()
    
    # Выводим результаты
    print("\n" + "="*80)
    print("📊 РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("="*80)
    
    if not api_requests:
        print("\n❌ API запросы не найдены")
        return
    
    print(f"\n✅ Найдено API запросов: {len(api_requests)}")
    
    # Сортируем по релевантности (содержат ли airdrop, token и т.д.)
    relevant = []
    other = []
    
    for req in api_requests:
        url_lower = req['url'].lower()
        if any(kw in url_lower for kw in ['airdrop', 'token', 'campaign', 'activity', 'event']):
            relevant.append(req)
        else:
            other.append(req)
    
    # Выводим релевантные запросы
    if relevant:
        print(f"\n🎯 РЕЛЕВАНТНЫЕ API ENDPOINTS ({len(relevant)}):")
        print("-" * 80)
        
        for i, req in enumerate(relevant, 1):
            print(f"\n{i}. {req['method']} {req['url']}")
            
            if 'response' in req:
                print(f"   Status: {req['status']}")
                data = req['response']
                
                # Анализируем структуру данных
                if isinstance(data, dict):
                    print(f"   Response keys: {list(data.keys())}")
                    
                    # Пытаемся найти список промоакций
                    for key in ['data', 'result', 'list', 'items', 'campaigns', 'airdrops']:
                        if key in data:
                            items = data[key]
                            if isinstance(items, list):
                                print(f"   ✨ Найден список в '{key}': {len(items)} элементов")
                                if items:
                                    print(f"   Пример элемента: {list(items[0].keys()) if isinstance(items[0], dict) else items[0]}")
                            elif isinstance(items, dict):
                                print(f"   ✨ Найден объект в '{key}': {list(items.keys())}")
                elif isinstance(data, list):
                    print(f"   Response: массив из {len(data)} элементов")
                    if data:
                        print(f"   Пример элемента: {list(data[0].keys()) if isinstance(data[0], dict) else data[0]}")
            
            if req['post_data']:
                print(f"   POST data: {req['post_data'][:200]}...")
    
    # Выводим остальные запросы
    if other:
        print(f"\n\n📋 ДРУГИЕ API ENDPOINTS ({len(other)}):")
        print("-" * 80)
        for i, req in enumerate(other, 1):
            print(f"{i}. {req['method']} {req['url']}")
    
    # Сохраняем результаты в файл
    output_file = 'mexc_api_analysis.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(api_requests, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n💾 Полные результаты сохранены в: {output_file}")
    print("\n" + "="*80)

if __name__ == '__main__':
    asyncio.run(find_mexc_api())
