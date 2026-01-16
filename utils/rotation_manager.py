import sqlite3
import logging
import time
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class RotationSettings:
    rotation_interval: int
    auto_optimize: bool
    stats_retention_days: int
    archive_inactive_days: int
    last_rotation: float
    last_cleanup: float

@dataclass
class ActiveCombination:
    proxy: 'ProxyServer'
    user_agent: 'UserAgent'
    exchange: str
    score: float
    last_used: float

class RotationManager:
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        
        # Ленивая загрузка менеджеров
        self._proxy_manager = None
        self._ua_manager = None
        self._stats_manager = None
        
        # Активные комбинации по биржам
        self._active_combinations: Dict[str, ActiveCombination] = {}
        self._combination_cache: Dict[str, Dict] = {}
        self._cache_ttl = 120  # 2 минуты
        
        # Блокировки для потокобезопасности
        self._lock = threading.Lock()
        self._rotation_lock = threading.Lock()
        
        # Инициализация
        self._init_database()
        self._load_settings()
        self._start_rotation_scheduler()

    @property
    def proxy_manager(self):
        if self._proxy_manager is None:
            from utils.proxy_manager import ProxyManager
            self._proxy_manager = ProxyManager()
        return self._proxy_manager
        
    @property
    def ua_manager(self):
        if self._ua_manager is None:
            from utils.user_agent_manager import UserAgentManager
            self._ua_manager = UserAgentManager()
        return self._ua_manager
        
    @property
    def stats_manager(self):
        if self._stats_manager is None:
            from utils.statistics_manager import StatisticsManager
            self._stats_manager = StatisticsManager()
        return self._stats_manager

    def _init_database(self):
        """Инициализация настроек ротации"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS RotationSettings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rotation_interval INTEGER DEFAULT 900,
                        auto_optimize BOOLEAN DEFAULT 1,
                        stats_retention_days INTEGER DEFAULT 30,
                        archive_inactive_days INTEGER DEFAULT 7,
                        last_rotation REAL DEFAULT 0,
                        last_cleanup REAL DEFAULT 0
                    )
                ''')
                
                # Инициализация настроек по умолчанию
                cursor.execute('''
                    INSERT OR IGNORE INTO RotationSettings 
                    (id, rotation_interval, auto_optimize, stats_retention_days, archive_inactive_days)
                    VALUES (1, 900, 1, 30, 7)
                ''')
                conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка инициализации БД ротации: {e}")
            raise

    def _load_settings(self):
        """Загрузка настроек из БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM RotationSettings WHERE id = 1")
                result = cursor.fetchone()
                
                if result:
                    self.settings = RotationSettings(
                        rotation_interval=result['rotation_interval'],
                        auto_optimize=bool(result['auto_optimize']),
                        stats_retention_days=result['stats_retention_days'],
                        archive_inactive_days=result['archive_inactive_days'],
                        last_rotation=result['last_rotation'],
                        last_cleanup=result['last_cleanup']
                    )
                else:
                    self.settings = RotationSettings(
                        rotation_interval=900,
                        auto_optimize=True,
                        stats_retention_days=30,
                        archive_inactive_days=7,
                        last_rotation=0,
                        last_cleanup=0
                    )
        except Exception as e:
            self.logger.error(f"Ошибка загрузки настроек: {e}")
            self.settings = RotationSettings(900, True, 30, 7, 0, 0)

    def _start_rotation_scheduler(self):
        """Запуск планировщика ротации"""
        def rotation_scheduler():
            while True:
                try:
                    time.sleep(60)  # Проверка каждую минуту
                    self._check_and_rotate()
                except Exception as e:
                    self.logger.error(f"Ошибка в планировщике ротации: {e}")

        scheduler_thread = threading.Thread(target=rotation_scheduler, daemon=True)
        scheduler_thread.start()

    def _check_and_rotate(self):
        """Проверка необходимости ротации и выполнение"""
        current_time = time.time()
        
        # Проверяем, нужно ли выполнить ротацию по времени
        if current_time - self.settings.last_rotation >= self.settings.rotation_interval:
            self.logger.info("Запуск плановой ротации...")
            self.rotate_all_combinations()
            
            # Обновляем время последней ротации
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE RotationSettings SET last_rotation = ? WHERE id = 1",
                    (current_time,)
                )
                conn.commit()
            self.settings.last_rotation = current_time

    def get_optimal_combination(self, exchange: str) -> Tuple[Optional['ProxyServer'], Optional['UserAgent']]:
        """Получение оптимальной комбинации для биржи"""
        cache_key = f"combination_{exchange}"
        
        # Проверяем кеш
        if cache_key in self._combination_cache:
            cache_data = self._combination_cache[cache_key]
            if time.time() - cache_data['timestamp'] < self._cache_ttl:
                return cache_data['proxy'], cache_data['user_agent']
        
        try:
            with self._lock:
                # Проверяем активную комбинацию для биржи
                if exchange in self._active_combinations:
                    active_combo = self._active_combinations[exchange]
                    
                    # Проверяем, не устарела ли комбинация
                    if time.time() - active_combo.last_used < 3600:  # 1 час
                        active_combo.last_used = time.time()
                        return active_combo.proxy, active_combo.user_agent

                # Получаем новую оптимальную комбинацию
                proxy = self.proxy_manager.get_optimal_proxy(exchange)
                user_agent = self.ua_manager.get_optimal_user_agent(exchange)
                
                if proxy and user_agent:
                    # Рассчитываем score комбинации
                    score = self._calculate_combination_score(proxy, user_agent, exchange)
                    
                    # Сохраняем как активную комбинацию
                    self._active_combinations[exchange] = ActiveCombination(
                        proxy=proxy,
                        user_agent=user_agent,
                        exchange=exchange,
                        score=score,
                        last_used=time.time()
                    )
                    
                    # Сохраняем в кеш
                    self._combination_cache[cache_key] = {
                        'proxy': proxy,
                        'user_agent': user_agent,
                        'timestamp': time.time()
                    }
                    
                    self.logger.info(f"Новая комбинация для {exchange}: proxy_id={proxy.id}, ua_id={user_agent.id}, score={score:.2f}")
                
                return proxy, user_agent
                
        except Exception as e:
            self.logger.error(f"Ошибка получения комбинации для {exchange}: {e}")
            return None, None

    def _calculate_combination_score(self, proxy: 'ProxyServer', user_agent: 'UserAgent', exchange: str) -> float:
        """Расчет скоринга комбинации"""
        try:
            # Базовые метрики
            proxy_success_rate = proxy.success_count / max(proxy.success_count + proxy.fail_count, 1)
            ua_success_rate = user_agent.success_rate
            
            # Бонус за скорость (чем быстрее - тем лучше)
            speed_score = max(0, 1 - (proxy.speed_ms / 10000))
            
            # Бонус за приоритет прокси
            priority_score = proxy.priority / 10
            
            # Бонус за новизну (первые 5 запросов)
            novelty_bonus = 0
            total_requests = proxy.success_count + proxy.fail_count
            if total_requests < 5:
                novelty_bonus = 0.2 * (5 - total_requests) / 5
            
            # Основная формула
            score = (
                (proxy_success_rate * 0.6) +
                (ua_success_rate * 0.2) +
                (speed_score * 0.1) +
                (priority_score * 0.1) +
                novelty_bonus
            )
            
            return min(score, 1.0)  # Ограничиваем максимальный score
            
        except Exception as e:
            self.logger.error(f"Ошибка расчета скоринга: {e}")
            return 0.5

    def rotate_all_combinations(self):
        """Принудительная ротация всех комбинаций"""
        with self._rotation_lock:
            self.logger.info("Запуск ротации всех комбинаций...")
            
            # Очищаем активные комбинации и кеш
            self._active_combinations.clear()
            self._combination_cache.clear()
            
            # Тестируем прокси
            self.proxy_manager.periodic_proxy_test()
            
            self.logger.info("Ротация всех комбинаций завершена")

    def invalidate_cache_for_exchange(self, exchange: str):
        """Принудительная инвалидация кеша для конкретной биржи (для retry логики)"""
        with self._lock:
            # Удаляем активную комбинацию
            if exchange in self._active_combinations:
                del self._active_combinations[exchange]
                self.logger.info(f"🔄 Удалена активная комбинация для {exchange}")
            
            # Очищаем кеш
            cache_key = f"combination_{exchange}"
            if cache_key in self._combination_cache:
                del self._combination_cache[cache_key]
                self.logger.info(f"🔄 Очищен кеш комбинации для {exchange}")

    def handle_request_result(self, exchange: str, proxy_id: int, user_agent_id: int, 
                            success: bool, response_time_ms: float, response_code: int = None):
        """Обработка результата запроса и обновление статистики"""
        try:
            # Определяем тип результата
            if success:
                request_result = "success"
            elif response_code in [403, 429]:
                request_result = "blocked"
            elif response_code is None:
                request_result = "timeout"
            else:
                request_result = "error"
            
            # Логируем в статистику
            self.stats_manager.log_request(
                proxy_id=proxy_id,
                user_agent_id=user_agent_id,
                exchange=exchange,
                request_result=request_result,
                response_code=response_code,
                response_time_ms=response_time_ms
            )
            
            # Обновляем статистику прокси (передаем response_code для отслеживания блокировок)
            self.proxy_manager.update_proxy_stats(proxy_id, success, response_time_ms, response_code)
            
            # Обновляем статистику User-Agent
            self.ua_manager.update_success_rate(user_agent_id, success)
            
            # Если запрос заблокирован - немедленная ротация для этой биржи
            if request_result == "blocked":
                self.logger.warning(f"Обнаружена блокировка для {exchange}, запуск немедленной ротации...")
                if exchange in self._active_combinations:
                    del self._active_combinations[exchange]
                # Очищаем кеш для этой биржи
                cache_key = f"combination_{exchange}"
                if cache_key in self._combination_cache:
                    del self._combination_cache[cache_key]
                    
        except Exception as e:
            self.logger.error(f"Ошибка обработки результата запроса: {e}")

    def update_settings(self, rotation_interval: int = None, auto_optimize: bool = None,
                      stats_retention_days: int = None, archive_inactive_days: int = None):
        """Обновление настроек ротации"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                update_fields = []
                params = []
                
                if rotation_interval is not None:
                    update_fields.append("rotation_interval = ?")
                    params.append(rotation_interval)
                    self.settings.rotation_interval = rotation_interval
                
                if auto_optimize is not None:
                    update_fields.append("auto_optimize = ?")
                    params.append(1 if auto_optimize else 0)
                    self.settings.auto_optimize = auto_optimize
                
                if stats_retention_days is not None:
                    update_fields.append("stats_retention_days = ?")
                    params.append(stats_retention_days)
                    self.settings.stats_retention_days = stats_retention_days
                
                if archive_inactive_days is not None:
                    update_fields.append("archive_inactive_days = ?")
                    params.append(archive_inactive_days)
                    self.settings.archive_inactive_days = archive_inactive_days
                
                if update_fields:
                    params.append(1)  # для WHERE id = 1
                    cursor.execute(
                        f"UPDATE RotationSettings SET {', '.join(update_fields)} WHERE id = ?",
                        params
                    )
                    conn.commit()
                    
                    self.logger.info("Настройки ротации обновлены")
                    
        except Exception as e:
            self.logger.error(f"Ошибка обновления настроек: {e}")
            raise

    def get_rotation_status(self) -> Dict:
        """Получение статуса ротации"""
        active_exchanges = list(self._active_combinations.keys())
        status = {
            'active_exchanges': active_exchanges,
            'total_active_combinations': len(active_exchanges),
            'rotation_interval': self.settings.rotation_interval,
            'auto_optimize': self.settings.auto_optimize,
            'last_rotation': self.settings.last_rotation,
            'time_until_next_rotation': max(0, self.settings.rotation_interval - (time.time() - self.settings.last_rotation))
        }
        
        # Добавляем информацию о комбинациях
        combinations_info = {}
        for exchange, combo in self._active_combinations.items():
            combinations_info[exchange] = {
                'proxy_id': combo.proxy.id,
                'user_agent_id': combo.user_agent.id,
                'score': round(combo.score, 3),
                'last_used': combo.last_used
            }
        
        status['combinations'] = combinations_info
        return status


# Глобальный экземпляр менеджера ротации
_rotation_manager = None

def get_rotation_manager(db_path: str = "data/database.db") -> RotationManager:
    global _rotation_manager
    if _rotation_manager is None:
        _rotation_manager = RotationManager(db_path)
    return _rotation_manager