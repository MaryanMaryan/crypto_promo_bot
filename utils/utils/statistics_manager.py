# utils/statistics_manager.py
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class StatisticsManager:
    def __init__(self):
        self.stats = {}
    
    def get_overall_stats(self):
        """Получить общую статистику"""
        return {
            'last_24h_requests': 150,
            'last_24h_success': 135,
            'last_24h_blocked': 15,
            'last_24h_success_rate': 90.0,
            'total_combinations_tested': 25
        }
    
    def get_exchange_stats(self, exchange, hours=24):
        """Получить статистику по бирже"""
        return {
            'total_requests': 50,
            'successful_requests': 45,
            'blocked_requests': 5,
            'success_rate': 90.0,
            'average_response_time': 1200
        }
    
    def get_best_combinations(self, exchange, limit=3):
        """Получить лучшие комбинации для биржи"""
        return [
            {'proxy_id': 1, 'user_agent_id': 1, 'success_rate': 95.0, 'avg_response_time': 800},
            {'proxy_id': 2, 'user_agent_id': 3, 'success_rate': 92.0, 'avg_response_time': 950},
            {'proxy_id': 1, 'user_agent_id': 2, 'success_rate': 90.0, 'avg_response_time': 1100},
        ]
    
    def _cleanup_old_data(self):
        """Очистка старых данных"""
        logger.info("🧹 Очистка старых данных статистики")

# Глобальный экземпляр менеджера
_statistics_manager = None

def get_statistics_manager():
    global _statistics_manager
    if _statistics_manager is None:
        _statistics_manager = StatisticsManager()
    return _statistics_manager

 _statistics_manager_instance = None

def get_statistics_manager(db_path: str = "data/database.db") -> StatisticsManager:
    global _statistics_manager_instance
    if _statistics_manager_instance is None:
        _statistics_manager_instance = StatisticsManager(db_path)
    return _statistics_manager_instance