"""
Проверка исправления min_apr фильтра
Показывает, что будет передано в parse_staking_link()
"""

import sys
import os

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data.database import get_db_session
from data.models import ApiLink


def verify_fix():
    """Проверка, что min_apr корректно читается из БД"""
    print("=" * 80)
    print("✅ ПРОВЕРКА ИСПРАВЛЕНИЯ min_apr")
    print("=" * 80)

    with get_db_session() as db:
        # Получаем Gate.io ссылку
        gate_link = db.query(ApiLink).filter(
            ApiLink.name.like('%Gate%'),
            ApiLink.category == 'staking'
        ).first()

        if not gate_link:
            print("❌ Gate.io ссылка не найдена")
            return

        print("\n📌 GATE.IO ССЫЛКА:")
        print(f"   ID: {gate_link.id}")
        print(f"   Название: {gate_link.name}")
        print(f"   min_apr: {gate_link.min_apr}%")
        print(f"   Категория: {gate_link.category}")
        print(f"   Активна: {gate_link.is_active}")

        # Симулируем формирование link_data как в main.py
        print("\n🔍 СИМУЛЯЦИЯ ФОРМИРОВАНИЯ link_data (как в main.py):")
        link_data = {
            'id': gate_link.id,
            'name': gate_link.name,
            'url': gate_link.url,
            'check_interval': gate_link.check_interval,
            'last_checked': gate_link.last_checked,
            'exchange': gate_link.exchange or 'Unknown',
            'category': gate_link.category or 'launches',
            'api_url': gate_link.api_url,
            'page_url': gate_link.page_url,
            'min_apr': gate_link.min_apr
        }

        print(f"\n📦 link_data:")
        for key, value in link_data.items():
            if key in ['min_apr', 'id', 'name', 'category']:
                print(f"   {key}: {value}")

        # Получаем min_apr как в main.py
        min_apr = link_data.get('min_apr')

        print(f"\n🎯 РЕЗУЛЬТАТ:")
        print(f"   min_apr передаётся в parse_staking_link(): {min_apr}")

        if min_apr is None:
            print(f"\n   ❌ ПРОБЛЕМА: min_apr = None (фильтр не будет работать)")
        elif min_apr == 100.0:
            print(f"\n   ✅ ОТЛИЧНО: min_apr = 100.0 (фильтр будет работать корректно)")
        else:
            print(f"\n   ⚠️ min_apr = {min_apr}% (необычное значение)")

    print("\n" + "=" * 80)
    print("✅ ПРОВЕРКА ЗАВЕРШЕНА")
    print("=" * 80)
    print("\n📋 ИНСТРУКЦИЯ:")
    print("   1. Если min_apr = None → исправление НЕ сработало")
    print("   2. Если min_apr = 100.0 → исправление СРАБОТАЛО")
    print("   3. Перезапусти бота и проверь снова")


if __name__ == "__main__":
    try:
        verify_fix()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
