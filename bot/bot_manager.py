"""
Менеджер для управления глобальным экземпляром бота
Решает проблему циклического импорта
"""
import logging

logger = logging.getLogger(__name__)

class BotManager:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance
    
    @classmethod
    def set_instance(cls, instance):
        cls._instance = instance
        logger.info("✅ BotManager: экземпляр бота установлен")

bot_manager = BotManager()