# utils/managers.py
from .dependency_container import get_container

class Managers:
    def __init__(self):
        self._container = get_container()
    
    @property
    def proxy(self):
        return self._container.proxy_manager
    
    @property
    def user_agent(self):
        return self._container.user_agent_manager
    
    @property
    def statistics(self):
        return self._container.statistics_manager
    
    @property
    def rotation(self):
        return self._container.rotation_manager

# Глобальный экземпляр для удобного доступа
managers = Managers()