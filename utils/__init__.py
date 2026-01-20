# utils/__init__.py
from .proxy_manager import ProxyManager, get_proxy_manager
from .user_agent_manager import UserAgentManager, get_user_agent_manager
from .statistics_manager import StatisticsManager, get_statistics_manager
from .rotation_manager import RotationManager, get_rotation_manager

# Фаза 4: Отзывчивый UI
from .cache import CacheManager, get_cache_manager, async_cache, sync_cache, invalidate_links_cache
from .loading_indicator import LoadingContext, with_loading, LoadingTexts, show_temporary_message

__all__ = [
    'ProxyManager', 'get_proxy_manager',
    'UserAgentManager', 'get_user_agent_manager', 
    'StatisticsManager', 'get_statistics_manager',
    'RotationManager', 'get_rotation_manager',
    # Фаза 4
    'CacheManager', 'get_cache_manager', 'async_cache', 'sync_cache', 'invalidate_links_cache',
    'LoadingContext', 'with_loading', 'LoadingTexts', 'show_temporary_message'
]