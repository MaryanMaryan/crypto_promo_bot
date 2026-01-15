"""
Временно включить DEBUG логирование для отладки фильтра min_apr
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import logging

# Настраиваем логирование на уровень DEBUG
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Устанавливаем DEBUG для всех логгеров
logging.getLogger('bot.parser_service').setLevel(logging.DEBUG)
logging.getLogger('services.stability_tracker_service').setLevel(logging.DEBUG)
logging.getLogger('main').setLevel(logging.DEBUG)

print("✅ DEBUG логирование включено")
print("Теперь запусти бота и выполни принудительную проверку")
