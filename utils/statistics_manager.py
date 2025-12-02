import sqlite3
import logging
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
from enum import Enum

class RequestResult(Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ERROR = "error"
    PROXY_ERROR = "proxy_error"

@dataclass
class RotationStats:
    id: int
    proxy_id: int
    user_agent_id: int
    exchange: str
    request_result: str
    response_code: int
    response_time_ms: float
    timestamp: float

@dataclass
class AggregatedStats:
    id: int
    date: str
    exchange: str
    total_requests: int
    successful_requests: int
    blocked_requests: int
    average_response_time: float
    best_proxy_id: int
    best_user_agent_id: int

class StatisticsManager:
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_database()
        self._cache = {}
        self._cache_ttl = 300  # 5 минут
        self._batch_size = 10
        self._batch_buffer = []
        self._lock = threading.Lock()
        
        # Запуск фоновых задач
        self._start_background_tasks()

    def _init_database(self):
        """Инициализация таблиц статистики в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Таблица детальной статистики по запросам
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS RotationStats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        proxy_id INTEGER NOT NULL,
                        user_agent_id INTEGER NOT NULL,
                        exchange TEXT NOT NULL,
                        request_result TEXT NOT NULL,
                        response_code INTEGER,
                        response_time_ms REAL NOT NULL,
                        timestamp REAL NOT NULL,
                        FOREIGN KEY (proxy_id) REFERENCES ProxyServer (id),
                        FOREIGN KEY (user_agent_id) REFERENCES UserAgent (id)
                    )
                ''')
                
                # Таблица агрегированной дневной статистики
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS AggregatedStats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        exchange TEXT NOT NULL,
                        total_requests INTEGER DEFAULT 0,
                        successful_requests INTEGER DEFAULT 0,
                        blocked_requests INTEGER DEFAULT 0,
                        average_response_time REAL DEFAULT 0,
                        best_proxy_id INTEGER,
                        best_user_agent_id INTEGER,
                        UNIQUE(date, exchange)
                    )
                ''')
                
                # Создаем индексы для оптимизации
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_rotation_stats_timestamp 
                    ON RotationStats(timestamp)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_rotation_stats_exchange_timestamp 
                    ON RotationStats(exchange, timestamp)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_aggregated_stats_date 
                    ON AggregatedStats(date)
                ''')
                
                conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка инициализации БД статистики: {e}")
            raise

    def _start_background_tasks(self):
        """Запуск фоновых задач для агрегации и очистки"""
        def background_aggregator():
            while True:
                try:
                    time.sleep(3600)  # Каждый час
                    self._aggregate_daily_stats()
                    self._cleanup_old_data()
                except Exception as e:
                    self.logger.error(f"Ошибка в фоновом агрегаторе: {e}")

        aggregator_thread = threading.Thread(target=background_aggregator, daemon=True)
        aggregator_thread.start()

    def log_request(self, proxy_id: int, user_agent_id: int, exchange: str, 
                   request_result: str, response_code: int, response_time_ms: float):
        """Логирование статистики запроса"""
        try:
            stats_record = (
                proxy_id, user_agent_id, exchange, request_result, 
                response_code, response_time_ms, time.time()
            )
            
            with self._lock:
                self._batch_buffer.append(stats_record)
                
                # Пакетная вставка при достижении размера батча
                if len(self._batch_buffer) >= self._batch_size:
                    self._flush_batch_buffer()
                    
        except Exception as e:
            self.logger.error(f"Ошибка логирования запроса: {e}")

    def _flush_batch_buffer(self):
        """Пакетная вставка накопленных данных"""
        if not self._batch_buffer:
            return
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany('''
                    INSERT INTO RotationStats 
                    (proxy_id, user_agent_id, exchange, request_result, response_code, response_time_ms, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', self._batch_buffer)
                conn.commit()
                
                self._batch_buffer.clear()
                self._cache.clear()  # Инвалидируем кеш
                
        except Exception as e:
            self.logger.error(f"Ошибка пакетной вставки статистики: {e}")

    def _aggregate_daily_stats(self):
        """Агрегация дневной статистики"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Получаем все уникальные биржи за сегодня
                cursor.execute('''
                    SELECT DISTINCT exchange FROM RotationStats 
                    WHERE DATE(datetime(timestamp, 'unixepoch')) = ?
                ''', (today,))
                exchanges = [row['exchange'] for row in cursor.fetchall()]
                
                for exchange in exchanges:
                    # Агрегируем статистику по бирже
                    cursor.execute('''
                        SELECT 
                            COUNT(*) as total_requests,
                            SUM(CASE WHEN request_result = 'success' THEN 1 ELSE 0 END) as successful_requests,
                            SUM(CASE WHEN request_result = 'blocked' THEN 1 ELSE 0 END) as blocked_requests,
                            AVG(response_time_ms) as average_response_time,
                            proxy_id,
                            COUNT(*) as proxy_count
                        FROM RotationStats 
                        WHERE exchange = ? AND DATE(datetime(timestamp, 'unixepoch')) = ?
                        GROUP BY proxy_id
                        ORDER BY proxy_count DESC, average_response_time ASC
                        LIMIT 1
                    ''', (exchange, today))
                    best_proxy = cursor.fetchone()
                    
                    cursor.execute('''
                        SELECT 
                            user_agent_id,
                            COUNT(*) as ua_count
                        FROM RotationStats 
                        WHERE exchange = ? AND DATE(datetime(timestamp, 'unixepoch')) = ?
                        GROUP BY user_agent_id
                        ORDER BY ua_count DESC
                        LIMIT 1
                    ''', (exchange, today))
                    best_ua = cursor.fetchone()
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO AggregatedStats 
                        (date, exchange, total_requests, successful_requests, blocked_requests, 
                         average_response_time, best_proxy_id, best_user_agent_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        today, exchange,
                        best_proxy['total_requests'] if best_proxy else 0,
                        best_proxy['successful_requests'] if best_proxy else 0,
                        best_proxy['blocked_requests'] if best_proxy else 0,
                        best_proxy['average_response_time'] if best_proxy else 0,
                        best_proxy['proxy_id'] if best_proxy else None,
                        best_ua['user_agent_id'] if best_ua else None
                    ))
                
                conn.commit()
                self.logger.info(f"Агрегация статистики завершена для {len(exchanges)} бирж")
                
        except Exception as e:
            self.logger.error(f"Ошибка агрегации дневной статистики: {e}")

    def _cleanup_old_data(self):
        """Очистка старых данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Используем значение по умолчанию для retention_days
                retention_days = 30
                cutoff_time = time.time() - (retention_days * 24 * 3600)
                
                # Удаляем старые записи статистики
                cursor.execute("DELETE FROM RotationStats WHERE timestamp < ?", (cutoff_time,))
                deleted_count = cursor.rowcount
                
                conn.commit()
                self.logger.info(f"Очистка статистики: удалено {deleted_count} записей")
                
        except Exception as e:
            self.logger.error(f"Ошибка очистки старых данных: {e}")

    def get_exchange_stats(self, exchange: str, hours: int = 24) -> Dict:
        """Получение статистики по бирже за указанный период"""
        cache_key = f"exchange_stats_{exchange}_{hours}"
        if cache_key in self._cache and time.time() - self._cache[cache_key]['timestamp'] < self._cache_ttl:
            return self._cache[cache_key]['data']
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cutoff_time = time.time() - (hours * 3600)
                
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_requests,
                        SUM(CASE WHEN request_result = 'success' THEN 1 ELSE 0 END) as successful_requests,
                        SUM(CASE WHEN request_result = 'blocked' THEN 1 ELSE 0 END) as blocked_requests,
                        AVG(response_time_ms) as average_response_time
                    FROM RotationStats 
                    WHERE exchange = ? AND timestamp > ?
                ''', (exchange, cutoff_time))
                
                result = cursor.fetchone()
                
                stats = {
                    'total_requests': result['total_requests'] or 0,
                    'successful_requests': result['successful_requests'] or 0,
                    'blocked_requests': result['blocked_requests'] or 0,
                    'success_rate': round((result['successful_requests'] or 0) / max(result['total_requests'] or 1, 1) * 100, 2),
                    'average_response_time': round(result['average_response_time'] or 0, 2)
                }
                
                self._cache[cache_key] = {
                    'data': stats,
                    'timestamp': time.time()
                }
                
                return stats
                
        except Exception as e:
            self.logger.error(f"Ошибка получения статистики по бирже {exchange}: {e}")
            return {}

    def get_best_combinations(self, exchange: str, limit: int = 5) -> List[Dict]:
        """Получение лучших комбинаций прокси + User-Agent для биржи"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT 
                        proxy_id,
                        user_agent_id,
                        COUNT(*) as request_count,
                        SUM(CASE WHEN request_result = 'success' THEN 1 ELSE 0 END) as success_count,
                        AVG(response_time_ms) as avg_response_time
                    FROM RotationStats 
                    WHERE exchange = ? AND timestamp > ?
                    GROUP BY proxy_id, user_agent_id
                    HAVING request_count >= 3
                    ORDER BY (success_count * 1.0 / request_count) DESC, avg_response_time ASC
                    LIMIT ?
                ''', (exchange, time.time() - (24 * 3600), limit))
                
                results = cursor.fetchall()
                combinations = []
                
                for row in results:
                    success_rate = (row['success_count'] / row['request_count']) * 100
                    combinations.append({
                        'proxy_id': row['proxy_id'],
                        'user_agent_id': row['user_agent_id'],
                        'success_rate': round(success_rate, 2),
                        'avg_response_time': round(row['avg_response_time'], 2),
                        'request_count': row['request_count']
                    })
                
                return combinations
                
        except Exception as e:
            self.logger.error(f"Ошибка получения лучших комбинаций для {exchange}: {e}")
            return []

    def get_overall_stats(self) -> Dict:
        """Получение общей статистики системы"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Статистика за последние 24 часа
                cutoff_time = time.time() - (24 * 3600)
                
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_requests,
                        SUM(CASE WHEN request_result = 'success' THEN 1 ELSE 0 END) as successful_requests,
                        SUM(CASE WHEN request_result = 'blocked' THEN 1 ELSE 0 END) as blocked_requests
                    FROM RotationStats 
                    WHERE timestamp > ?
                ''', (cutoff_time,))
                
                result = cursor.fetchone()
                
                return {
                    'last_24h_requests': result[0] or 0,
                    'last_24h_success': result[1] or 0,
                    'last_24h_blocked': result[2] or 0,
                    'last_24h_success_rate': round((result[1] or 0) / max(result[0] or 1, 1) * 100, 2),
                    'total_combinations_tested': self._get_total_combinations_count()
                }
        except Exception as e:
            self.logger.error(f"Ошибка получения общей статистики: {e}")
            return {}

    def _get_total_combinations_count(self) -> int:
        """Получение общего количества протестированных комбинаций"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(DISTINCT proxy_id || '-' || user_agent_id) 
                    FROM RotationStats
                ''')
                return cursor.fetchone()[0] or 0
        except:
            return 0


# Синглтон экземпляр
_statistics_manager_instance = None

def get_statistics_manager(db_path: str = "data/database.db") -> StatisticsManager:
    """Функция для получения синглтон экземпляра StatisticsManager"""
    global _statistics_manager_instance
    if _statistics_manager_instance is None:
        _statistics_manager_instance = StatisticsManager(db_path)
    return _statistics_manager_instance