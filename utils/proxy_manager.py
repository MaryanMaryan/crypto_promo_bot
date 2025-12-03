# utils/proxy_manager.py
import sqlite3
import requests
import logging
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class ProxyProtocol(Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"

class ProxyStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TESTING = "testing"
    FAILED = "failed"

@dataclass
class ProxyServer:
    id: int
    address: str
    protocol: str
    status: str
    speed_ms: float
    success_count: int
    fail_count: int
    priority: int
    last_used: float
    last_success: float
    last_blocked: float = 0  # Время последней блокировки (403/429)

class ProxyManager:
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.test_endpoints = [
            "https://httpbin.org/ip",
            "https://api.binance.com/api/v3/ping",
            "https://www.google.com/favicon.ico"
        ]
        self._init_database()
        self._ensure_backup_proxies()
        
    def _init_database(self):
        """Инициализация таблицы ProxyServer в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ProxyServer (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        address TEXT UNIQUE NOT NULL,
                        protocol TEXT NOT NULL,
                        status TEXT DEFAULT 'active',
                        speed_ms REAL DEFAULT 0,
                        success_count INTEGER DEFAULT 0,
                        fail_count INTEGER DEFAULT 0,
                        priority INTEGER DEFAULT 5,
                        last_used REAL DEFAULT 0,
                        last_success REAL DEFAULT 0,
                        last_blocked REAL DEFAULT 0
                    )
                ''')

                # Добавляем колонку last_blocked если её нет (для существующих БД)
                try:
                    cursor.execute("SELECT last_blocked FROM ProxyServer LIMIT 1")
                except sqlite3.OperationalError:
                    cursor.execute("ALTER TABLE ProxyServer ADD COLUMN last_blocked REAL DEFAULT 0")
                    self.logger.info("Добавлена колонка last_blocked в таблицу ProxyServer")
                
                # Создаем индексы для оптимизации
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_proxy_status 
                    ON ProxyServer(status)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_proxy_status_success 
                    ON ProxyServer(status, success_count, fail_count)
                ''')
                
                conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка инициализации БД ProxyServer: {e}")
            raise

    def _ensure_backup_proxies(self):
        """Создание резервных прокси если их нет"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM ProxyServer WHERE status = 'active'")
                count = cursor.fetchone()[0]
                
                if count == 0:
                    self.logger.info("Добавление резервных прокси...")
                    # Добавляем несколько бесплатных прокси как fallback
                    backup_proxies = [
                        # Эти прокси будут заменены на реальные при использовании
                    ]
                    
                    for proxy in backup_proxies:
                        try:
                            cursor.execute('''
                                INSERT OR IGNORE INTO ProxyServer 
                                (address, protocol, status, priority)
                                VALUES (?, ?, 'active', 3)
                            ''', (proxy['address'], proxy['protocol']))
                        except:
                            continue
                    
                    conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка создания резервных прокси: {e}")

    def add_proxy(self, address: str, protocol: str, priority: int = 5) -> bool:
        """Добавление нового прокси с тестированием"""
        try:
            # Тестируем прокси перед добавлением
            speed, success = self._test_proxy(address, protocol)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                status = 'active' if success else 'inactive'
                
                # Сначала пробуем добавить, если не существует
                cursor.execute('''
                    INSERT OR IGNORE INTO ProxyServer 
                    (address, protocol, status, speed_ms, success_count, fail_count, priority, last_success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    address, protocol, status, speed, 
                    1 if success else 0, 0 if success else 1,
                    priority, time.time() if success else 0
                ))
                
                # Если прокси уже существует, обновляем только основные поля
                if cursor.rowcount == 0:
                    cursor.execute('''
                        UPDATE ProxyServer 
                        SET protocol = ?, status = ?, priority = ?,
                            speed_ms = CASE WHEN ? > 0 THEN ? ELSE speed_ms END,
                            last_success = CASE WHEN ? = 1 THEN ? ELSE last_success END
                        WHERE address = ?
                    ''', (
                        protocol, status, priority,
                        speed, speed, 
                        1 if success else 0, time.time() if success else 0,
                        address
                    ))
                
                conn.commit()
                self.logger.info(f"Прокси {address} добавлен/обновлен со статусом {status}")
                return success
                
        except Exception as e:
            self.logger.error(f"Ошибка добавления прокси {address}: {e}")
            return False

    def _test_proxy(self, address: str, protocol: str) -> Tuple[float, bool]:
        """Тестирование прокси"""
        proxies = {
            'http': f"{protocol}://{address}",
            'https': f"{protocol}://{address}"
        }
        
        for endpoint in self.test_endpoints:
            try:
                start_time = time.time()
                response = requests.get(
                    endpoint,
                    proxies=proxies,
                    timeout=10,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                response_time = (time.time() - start_time) * 1000
                
                if response.status_code == 200 and response_time < 3000:
                    return response_time, True
                    
            except Exception as e:
                self.logger.debug(f"Прокси {address} не прошел тест {endpoint}: {e}")
                continue
                
        return 0, False

    def get_optimal_proxy(self, exchange: str = None, cooldown_seconds: int = 0) -> Optional[ProxyServer]:
        """Выбор оптимального прокси на основе статистики

        Args:
            exchange: Название биржи (не используется в текущей версии)
            cooldown_seconds: Время в секундах, в течение которого прокси исключается после блокировки (по умолчанию 0 = нет cooldown для ротирующихся прокси)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                current_time = time.time()
                cooldown_threshold = current_time - cooldown_seconds

                # Формула выбора: success_rate * 0.6 + speed_score * 0.3 + priority_score * 0.1
                # Понижен порог до 0.0 чтобы новые прокси тоже проходили
                # ДЛЯ РОТИРУЮЩИХСЯ ПРОКСИ: cooldown_seconds = 0, поэтому все прокси всегда доступны
                query = """
                    SELECT *,
                        (success_count * 1.0 / (success_count + fail_count + 1)) * 0.6 +
                        (1 - (speed_ms / 10000)) * 0.3 +
                        (priority * 0.1) as score
                    FROM ProxyServer
                    WHERE status = 'active'
                    AND (success_count * 1.0 / (success_count + fail_count + 1)) >= 0.0
                    AND (last_blocked = 0 OR last_blocked < ?)
                    ORDER BY score DESC, last_used ASC
                    LIMIT 1
                """

                cursor.execute(query, (cooldown_threshold,))
                result = cursor.fetchone()

                if result:
                    # Обновляем время последнего использования
                    cursor.execute(
                        "UPDATE ProxyServer SET last_used = ? WHERE id = ?",
                        (time.time(), result['id'])
                    )
                    conn.commit()

                    self.logger.info(f"🟢 Выбран прокси ID {result['id']} (ротирующийся)")

                    return ProxyServer(
                        id=result['id'],
                        address=result['address'],
                        protocol=result['protocol'],
                        status=result['status'],
                        speed_ms=result['speed_ms'],
                        success_count=result['success_count'],
                        fail_count=result['fail_count'],
                        priority=result['priority'],
                        last_used=result['last_used'],
                        last_success=result['last_success'],
                        last_blocked=result['last_blocked'] if 'last_blocked' in result.keys() else 0
                    )

                # Fallback: Если нет доступных прокси (что не должно происходить при cooldown=0)
                self.logger.warning(f"⚠️ Нет доступных прокси, выбираем наименее недавно использованный")
                cursor.execute("""
                    SELECT * FROM ProxyServer
                    WHERE status = 'active'
                    ORDER BY last_used ASC, last_success DESC
                    LIMIT 1
                """)
                result = cursor.fetchone()

                if result:
                    cursor.execute(
                        "UPDATE ProxyServer SET last_used = ? WHERE id = ?",
                        (time.time(), result['id'])
                    )
                    conn.commit()

                    return ProxyServer(**dict(result))

                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка получения оптимального прокси: {e}")
            return None

    def update_proxy_stats(self, proxy_id: int, success: bool, response_time: float = 0, response_code: int = None):
        """Обновление статистики прокси после запроса"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if success:
                    # ПРАВИЛЬНЫЙ расчет среднего значения скорости
                    cursor.execute('''
                        UPDATE ProxyServer
                        SET success_count = success_count + 1,
                            speed_ms = (speed_ms * success_count + ?) / (success_count + 1),
                            last_success = ?
                        WHERE id = ?
                    ''', (response_time, time.time(), proxy_id))
                else:
                    # Проверяем, является ли это блокировкой (403/429)
                    is_blocked = response_code in [403, 429] if response_code else False

                    if is_blocked:
                        # Записываем время блокировки
                        cursor.execute('''
                            UPDATE ProxyServer
                            SET fail_count = fail_count + 1,
                                last_blocked = ?
                            WHERE id = ?
                        ''', (time.time(), proxy_id))
                        self.logger.warning(f"🔴 Прокси ID {proxy_id} заблокирован (код {response_code})")
                    else:
                        cursor.execute('''
                            UPDATE ProxyServer
                            SET fail_count = fail_count + 1
                            WHERE id = ?
                        ''', (proxy_id,))
                
                # Проверяем, не нужно ли деактивировать прокси
                cursor.execute('''
                    SELECT success_count, fail_count 
                    FROM ProxyServer WHERE id = ?
                ''', (proxy_id,))
                result = cursor.fetchone()
                if result and result[0] is not None and result[1] is not None:
                    sc, fc = result
                    total = sc + fc
                    if total >= 5 and sc / total < 0.2:  # Меньше 20% успеха
                        cursor.execute('''
                            UPDATE ProxyServer SET status = 'inactive' WHERE id = ?
                        ''', (proxy_id,))
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"Ошибка обновления статистики прокси {proxy_id}: {e}")

    def get_proxy_stats(self) -> Dict:
        """Получение статистики по прокси"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                        COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive,
                        AVG(speed_ms) as avg_speed,
                        SUM(success_count) as total_success,
                        SUM(fail_count) as total_fail
                    FROM ProxyServer
                """)
                
                result = cursor.fetchone()
                if not result:
                    return {}
                    
                total_requests = (result[4] or 0) + (result[5] or 0)
                success_rate = (result[4] or 0) / total_requests if total_requests > 0 else 0
                
                return {
                    'total': result[0] or 0,
                    'active': result[1] or 0,
                    'inactive': result[2] or 0,
                    'avg_speed_ms': round(result[3] or 0, 2),
                    'success_rate': round(success_rate, 3),
                    'total_requests': total_requests
                }
        except Exception as e:
            self.logger.error(f"Ошибка получения статистики прокси: {e}")
            return {}

    def periodic_proxy_test(self):
        """Периодическое тестирование всех прокси"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM ProxyServer WHERE status != 'failed'")
                proxies = cursor.fetchall()
            
            tested_count = 0
            for proxy_row in proxies:
                try:
                    # БЕЗОПАСНАЯ распаковка с проверкой
                    if proxy_row and len(proxy_row) > 0:
                        proxy_dict = dict(proxy_row)
                        proxy = ProxyServer(**proxy_dict)
                        
                        speed, success = self._test_proxy(proxy.address, proxy.protocol)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            if success:
                                cursor.execute('''
                                    UPDATE ProxyServer 
                                    SET status = 'active', speed_ms = ?, last_success = ?,
                                        success_count = success_count + 1
                                    WHERE id = ?
                                ''', (speed, time.time(), proxy.id))
                            else:
                                cursor.execute('''
                                    UPDATE ProxyServer 
                                    SET fail_count = fail_count + 1
                                    WHERE id = ?
                                ''', (proxy.id,))
                                
                                # Проверяем, не нужно ли деактивировать прокси
                                cursor.execute('''
                                    SELECT success_count, fail_count 
                                    FROM ProxyServer WHERE id = ?
                                ''', (proxy.id,))
                                result = cursor.fetchone()
                                if result and result[0] is not None and result[1] is not None:
                                    sc, fc = result
                                    total = sc + fc
                                    if total >= 5 and sc / total < 0.2:
                                        cursor.execute('''
                                            UPDATE ProxyServer SET status = 'inactive' WHERE id = ?
                                        ''', (proxy.id,))
                            
                            conn.commit()
                            tested_count += 1
                            
                except Exception as e:
                    self.logger.error(f"Ошибка тестирования прокси {proxy_row.get('id', 'unknown')}: {e}")
                    continue
                    
            self.logger.info(f"Периодическое тестирование завершено: {tested_count}/{len(proxies)} прокси")
            
        except Exception as e:
            self.logger.error(f"Ошибка периодического тестирования прокси: {e}")

    def get_all_proxies(self, active_only: bool = True) -> List[ProxyServer]:
        """Получение всех прокси-серверов"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                query = "SELECT * FROM ProxyServer"
                if active_only:
                    query += " WHERE status = 'active'"
                query += " ORDER BY priority DESC, success_count DESC"
                
                cursor.execute(query)
                results = cursor.fetchall()
                
                return [ProxyServer(**dict(row)) for row in results]
        except Exception as e:
            self.logger.error(f"Ошибка получения списка прокси: {e}")
            return []

    def get_proxy_by_address(self, address: str) -> Optional[ProxyServer]:
        """Получение прокси по адресу"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM ProxyServer WHERE address = ?", (address,))
                result = cursor.fetchone()
                
                return ProxyServer(**dict(result)) if result else None
        except Exception as e:
            self.logger.error(f"Ошибка получения прокси по адресу {address}: {e}")
            return None

    def get_proxy_by_id(self, proxy_id: int) -> Optional[ProxyServer]:
        """Получение прокси по ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM ProxyServer WHERE id = ?", (proxy_id,))
                result = cursor.fetchone()
                
                return ProxyServer(**dict(result)) if result else None
        except Exception as e:
            self.logger.error(f"Ошибка получения прокси по ID {proxy_id}: {e}")
            return None

    def delete_proxy(self, proxy_id: int) -> bool:
        """Удаление прокси по ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM ProxyServer WHERE id = ?", (proxy_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Ошибка удаления прокси {proxy_id}: {e}")
            return False

    def test_proxy(self, proxy_id: int) -> bool:
        """Тестирование конкретного прокси"""
        try:
            proxy = self.get_proxy_by_id(proxy_id)
            if not proxy:
                self.logger.error(f"Прокси с ID {proxy_id} не найден")
                return False
            
            speed, success = self._test_proxy(proxy.address, proxy.protocol)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if success:
                    cursor.execute('''
                        UPDATE ProxyServer 
                        SET status = 'active', speed_ms = ?, last_success = ?,
                            success_count = success_count + 1
                        WHERE id = ?
                    ''', (speed, time.time(), proxy_id))
                else:
                    cursor.execute('''
                        UPDATE ProxyServer 
                        SET fail_count = fail_count + 1
                        WHERE id = ?
                    ''', (proxy_id,))
                    
                    # Проверяем, не нужно ли деактивировать прокси
                    cursor.execute('''
                        SELECT success_count, fail_count 
                        FROM ProxyServer WHERE id = ?
                    ''', (proxy_id,))
                    result = cursor.fetchone()
                    if result and result[0] is not None and result[1] is not None:
                        sc, fc = result
                        total = sc + fc
                        if total >= 5 and sc / total < 0.2:
                            cursor.execute('''
                                UPDATE ProxyServer SET status = 'inactive' WHERE id = ?
                            ''', (proxy_id,))
                
                conn.commit()
                return success
                
        except Exception as e:
            self.logger.error(f"Ошибка тестирования прокси {proxy_id}: {e}")
            return False


# Глобальный экземпляр менеджера прокси
_proxy_manager = None

def get_proxy_manager():
    """Получить глобальный экземпляр менеджера прокси"""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager