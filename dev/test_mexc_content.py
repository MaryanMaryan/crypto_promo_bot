from playwright.sync_api import sync_playwright

proxy_address = "res.proxy-seller.io:10001"
username = "0980b764e6ffcd74"
password = "0NLOnydG"

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled'],
        proxy={
            'server': f'http://{proxy_address}',
            'username': username,
            'password': password
        }
    )

    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    )

    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)

    page = context.new_page()
    response = page.goto('https://www.mexc.com/launchpad', wait_until='domcontentloaded', timeout=30000)

    print(f"Status: {response.status}")

    # Ждем JS
    page.wait_for_timeout(5000)

    content = page.content()

    # Ищем ключевые слова
    keywords = {
        'captcha': content.lower().count('captcha'),
        'challenge': content.lower().count('challenge'),
        'cloudflare': content.lower().count('cloudflare'),
        'access denied': content.lower().count('access denied'),
        'launchpad': content.lower().count('launchpad'),
        'project': content.lower().count('project'),
    }

    print("\nKeyword counts:")
    for kw, count in keywords.items():
        print(f"  {kw}: {count}")

    # Сохраняем HTML для анализа
    with open('mexc_output.html', 'w', encoding='utf-8') as f:
        f.write(content)

    print("\nHTML saved to mexc_output.html")
    print(f"Total length: {len(content)} chars")

    # Проверяем заголовок страницы
    title = page.title()
    print(f"Page title: {title}")

    browser.close()
