from playwright.sync_api import sync_playwright
import time

proxy_address = "res.proxy-seller.io:10001"
username = "0980b764e6ffcd74"
password = "0NLOnydG"

print("Test 1: Playwright с HTTP прокси")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={
                'server': f'http://{proxy_address}',
                'username': username,
                'password': password
            }
        )

        context = browser.new_context()
        page = context.new_page()

        print("Загрузка https://httpbin.org/ip...")
        response = page.goto('https://httpbin.org/ip', timeout=15000)
        print(f"Status: {response.status}")

        content = page.content()
        print(f"Content length: {len(content)}")
        print(f"Content preview: {content[:200]}")

        browser.close()
        print("OK: Test 1 passed")
except Exception as e:
    print(f"ERROR Test 1: {e}")

print("\n" + "="*50 + "\n")

print("Test 2: Playwright БЕЗ прокси (direct)")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("Загрузка https://httpbin.org/ip...")
        response = page.goto('https://httpbin.org/ip', timeout=15000)
        print(f"Status: {response.status}")

        content = page.content()
        print(f"Content length: {len(content)}")

        browser.close()
        print("OK: Test 2 passed")
except Exception as e:
    print(f"ERROR Test 2: {e}")
