from playwright.sync_api import sync_playwright
import time

proxy_address = "res.proxy-seller.io:10001"
username = "0980b764e6ffcd74"
password = "0NLOnydG"

sites = [
    "https://www.mexc.com/launchpad",
    "https://www.bybit.com/trade/spot/token-splash"
]

for site in sites:
    print(f"\n{'='*60}")
    print(f"Тестирование: {site}")
    print(f"{'='*60}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ],
                proxy={
                    'server': f'http://{proxy_address}',
                    'username': username,
                    'password': password
                }
            )

            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='de-DE',
                timezone_id='Europe/Berlin',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            )

            # Антидетект скрипты
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            print(f"Загрузка...")
            start = time.time()

            try:
                response = page.goto(site, wait_until='domcontentloaded', timeout=30000)
                elapsed = (time.time() - start) * 1000

                print(f"Status: {response.status if response else 'N/A'}")
                print(f"Time: {elapsed:.0f}ms")

                # Ждем JS
                page.wait_for_timeout(5000)

                content = page.content()
                print(f"Content length: {len(content)} chars")

                # Проверяем блокировки
                blocking_keywords = ['captcha', 'Access Denied', 'Cloudflare', 'blocked', 'rate limit']
                found_blocks = [kw for kw in blocking_keywords if kw.lower() in content.lower()]

                if found_blocks:
                    print(f"WARNING: Blocks found: {found_blocks}")
                else:
                    print(f"OK: No blocks detected")

                browser.close()

            except Exception as e:
                print(f"ERROR: Page load failed: {e}")
                browser.close()

    except Exception as e:
        print(f"ERROR: Browser failed: {e}")

print("\n" + "="*60)
print("Тесты завершены")
