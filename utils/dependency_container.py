import sqlite3
import logging
from typing import Optional

class DependencyContainer:
    _instance: Optional['DependencyContainer'] = None
    
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        
        # Ленивая инициализация менеджеров
        self._proxy_manager = None
        self._user_agent_manager = None
        self._statistics_manager = None
        self._rotation_manager = None
        
    @classmethod
    def get_instance(cls, db_path: str = "data/database.db") -> 'DependencyContainer':
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance
        
    @property
    def proxy_manager(self):
        if self._proxy_manager is None:
            from utils.proxy_manager import ProxyManager
            self._proxy_manager = ProxyManager(self.db_path)
        return self._proxy_manager
        
    @property
    def user_agent_manager(self):
        if self._user_agent_manager is None:
            from utils.user_agent_manager import UserAgentManager
            self._user_agent_manager = UserAgentManager(self.db_path)
        return self._user_agent_manager
        
    @property
    def statistics_manager(self):
        if self._statistics_manager is None:
            from utils.statistics_manager import StatisticsManager
            self._statistics_manager = StatisticsManager(self.db_path)
        return self._statistics_manager
        
    @property
    def rotation_manager(self):
        if self._rotation_manager is None:
            from utils.rotation_manager import RotationManager
            self._rotation_manager = RotationManager(self.db_path)
        return self._rotation_manager

# Глобальный доступ к контейнеру
def get_container() -> DependencyContainer:
    return DependencyContainer.get_instance()