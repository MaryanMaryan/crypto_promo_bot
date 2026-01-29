#!/usr/bin/env python3
"""Проверка и исправление OKX Flash Earn"""
import requests
import sqlite3

print("=" * 60)
print("ПРОВЕРКА И РЕШЕНИЕ OKX FLASH EARN")
print("=" * 60)

# 1. Тест API через разные методы
print("\n📡 Тест API напрямую:")
headers = {
    'accept': 'application/json',
    'x-locale': 'ru_RU',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://www.okx.com/ru/earn/flash-earn',
    'origin': 'https://www.okx.com'
}

try:
    response = requests.get(
        "https://www.okx.com/priapi/v3/stake-earn/projects",
        headers=headers,
        timeout=30
    )
    data = response.json()
    ongoing = data.get('data', {}).get('ongoingProjects', [])
    print(f"  Ongoing projects: {len(ongoing)}")
    if not ongoing:
        print("  ⚠️ API блокируется для этого IP!")
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# 2. Проверяем прокси
print("\n🔌 Проверка прокси:")
try:
    conn = sqlite3.connect('data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT address, protocol, status FROM proxy_servers WHERE status = 'active' LIMIT 10")
    proxies = cursor.fetchall()
    if proxies:
        print(f"  Активных прокси: {len(proxies)}")
        for p in proxies[:5]:
            print(f"    - {p[0]} ({p[1]}) - {p[2]}")
    else:
        print("  ⚠️ Нет активных прокси!")
    conn.close()
except Exception as e:
    print(f"  ❌ Ошибка: {e}")

# 3. Предложения по решению
print("\n" + "=" * 60)
print("💡 РЕШЕНИЯ ПРОБЛЕМЫ:")
print("=" * 60)
print("""
1. ПРОКСИ (рекомендуется):
   - Добавить резидентный прокси из Украины/России
   - OKX блокирует IP дата-центров в ЕС

2. БРАУЗЕРНЫЙ ПАРСИНГ:
   - Создать специальный парсер для OKX Flash Earn
   - Использовать Playwright с перехватом API
   
3. VPN НА СЕРВЕРЕ:
   - Настроить VPN клиент на сервере
   - Подключаться через страну без блокировки
""")
