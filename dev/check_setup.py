#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт проверки корректности установки и конфигурации
"""
import sys
import os
from pathlib import Path

# Устанавливаем UTF-8 для Windows консоли
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

def check_env_file():
    """Проверка наличия .env файла"""
    env_path = Path('.env')
    if not env_path.exists():
        print("❌ .env файл не найден!")
        print("💡 Создайте .env на основе .env.example:")
        print("   cp .env.example .env")
        return False
    print("✅ .env файл найден")
    return True

def check_env_variables():
    """Проверка переменных окружения"""
    try:
        import config

        # Проверка BOT_TOKEN
        if not config.BOT_TOKEN:
            print("❌ BOT_TOKEN не установлен в .env")
            return False
        if len(config.BOT_TOKEN) < 20:
            print("⚠️ BOT_TOKEN выглядит некорректно (слишком короткий)")
            return False
        print(f"✅ BOT_TOKEN установлен: {config.BOT_TOKEN[:15]}...")

        # Проверка ADMIN_CHAT_ID
        if not config.ADMIN_CHAT_ID:
            print("❌ ADMIN_CHAT_ID не установлен в .env")
            return False
        print(f"✅ ADMIN_CHAT_ID установлен: {config.ADMIN_CHAT_ID}")

        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки конфигурации: {e}")
        return False

def check_dependencies():
    """Проверка установки зависимостей"""
    required = {
        'aiogram': 'aiogram',
        'playwright': 'playwright',
        'playwright_stealth': 'playwright-stealth',
        'bs4': 'beautifulsoup4',
        'sqlalchemy': 'sqlalchemy',
        'dotenv': 'python-dotenv',
        'requests': 'requests',
        'apscheduler': 'apscheduler'
    }

    missing = []
    for import_name, package_name in required.items():
        try:
            __import__(import_name)
            print(f"✅ {package_name} установлен")
        except ImportError:
            print(f"❌ {package_name} НЕ установлен")
            missing.append(package_name)

    if missing:
        print(f"\n❌ Отсутствуют зависимости: {', '.join(missing)}")
        print("💡 Установите: pip install -r requirements.txt")
        return False

    return True

def check_playwright_browsers():
    """Проверка установки браузеров Playwright"""
    try:
        from utils.playwright_checker import check_browsers_installed

        if check_browsers_installed():
            print("✅ Браузеры Playwright установлены")
            return True
        else:
            print("❌ Браузеры Playwright НЕ установлены")
            print("💡 Установите: playwright install chromium")
            return False
    except Exception as e:
        print(f"⚠️ Не удалось проверить браузеры: {e}")
        return False

def main():
    """Основная функция проверки"""
    print("=" * 60)
    print("🔍 ПРОВЕРКА УСТАНОВКИ CRYPTO PROMO BOT")
    print("=" * 60)

    checks = [
        ("Проверка .env файла", check_env_file),
        ("Проверка зависимостей", check_dependencies),
        ("Проверка переменных окружения", check_env_variables),
        ("Проверка браузеров Playwright", check_playwright_browsers),
    ]

    results = []
    for name, check_func in checks:
        print(f"\n{'=' * 60}")
        print(f"📋 {name}")
        print(f"{'=' * 60}")
        results.append(check_func())

    print(f"\n{'=' * 60}")
    print("📊 ИТОГИ ПРОВЕРКИ")
    print(f"{'=' * 60}")

    if all(results):
        print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
        print("🚀 Бот готов к запуску: python main.py")
        return 0
    else:
        print("❌ ОБНАРУЖЕНЫ ПРОБЛЕМЫ!")
        print("📖 Подробные инструкции: SETUP.md")
        return 1

if __name__ == '__main__':
    sys.exit(main())
