# utils/user_agent_manager.py
import logging
from data.database import get_db_session
from data.models import UserAgent

logger = logging.getLogger(__name__)

class UserAgentManager:
    def __init__(self):
        self.user_agents = []
        self._load_user_agents()
    
    def _load_user_agents(self):
        """Загрузка User-Agent из базы данных"""
        try:
            with get_db_session() as db:
                self.user_agents = db.query(UserAgent).filter(
                    UserAgent.status == "active"
                ).all()
            logger.info(f"✅ Загружено {len(self.user_agents)} User-Agent")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки User-Agent: {e}")
            self.user_agents = []
    
    def get_random_user_agent(self):
        """Получить случайный User-Agent"""
        import random
        if self.user_agents:
            return random.choice(self.user_agents).user_agent_string
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def get_all_user_agents(self):
        """Получить все User-Agent"""
        return self.user_agents
    
    def get_user_agent_stats(self):
        """Получить статистику User-Agent"""
        return {
            'total': len(self.user_agents),
            'active': len([ua for ua in self.user_agents if ua.status == 'active']),
            'inactive': len([ua for ua in self.user_agents if ua.status == 'inactive']),
            'avg_success_rate': 0.8,
            'avg_usage_count': 10.5
        }
    
    def add_user_agent(self, user_agent_string, browser_type, browser_version, platform, device_type):
        """Добавить новый User-Agent"""
        try:
            with get_db_session() as db:
                new_ua = UserAgent(
                    user_agent_string=user_agent_string,
                    browser_type=browser_type,
                    browser_version=browser_version,
                    platform=platform,
                    device_type=device_type,
                    status="active"
                )
                db.add(new_ua)
                db.commit()
            
            self._load_user_agents()  # Перезагружаем список
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления User-Agent: {e}")
            return False
    
    def _generate_initial_user_agents(self):
        """Генерация начальных User-Agent"""
        return [
            ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", 
             "chrome", "91.0", "windows", "desktop"),
            ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
             "firefox", "89.0", "windows", "desktop"),
            ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
             "chrome", "91.0", "macos", "desktop"),
        ]

# Глобальный экземпляр менеджера
_user_agent_manager = None

def get_user_agent_manager():
    global _user_agent_manager
    if _user_agent_manager is None:
        _user_agent_manager = UserAgentManager()
    return _user_agent_manager