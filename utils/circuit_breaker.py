# utils/circuit_breaker.py
"""
CIRCUIT BREAKER - Предохранитель для бирж

Проблема: Если биржа лежит — тратим время на таймауты
Решение: После N неудач — пропускать биржу на M минут

Паттерн Circuit Breaker:
- CLOSED: Нормальная работа, запросы проходят
- OPEN: Биржа заблокирована, запросы отклоняются
- HALF_OPEN: Пробуем один запрос для проверки восстановления
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, Callable, TypeVar
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Состояния Circuit Breaker"""
    CLOSED = "closed"      # Нормальная работа
    OPEN = "open"          # Заблокирован (биржа недоступна)
    HALF_OPEN = "half_open"  # Пробный запрос


@dataclass
class CircuitStats:
    """Статистика Circuit Breaker для одной биржи"""
    exchange: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    opened_at: Optional[float] = None  # Когда открылся (заблокировался)
    total_requests: int = 0
    total_failures: int = 0
    total_blocked: int = 0  # Сколько запросов было отклонено
    
    @property
    def failure_rate(self) -> float:
        """Процент неудач"""
        if self.total_requests == 0:
            return 0.0
        return (self.total_failures / self.total_requests) * 100
    
    @property
    def time_in_open_state(self) -> Optional[float]:
        """Сколько секунд в состоянии OPEN"""
        if self.opened_at and self.state == CircuitState.OPEN:
            return time.time() - self.opened_at
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'exchange': self.exchange,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'total_requests': self.total_requests,
            'total_failures': self.total_failures,
            'total_blocked': self.total_blocked,
            'failure_rate': round(self.failure_rate, 2),
            'last_failure': datetime.fromtimestamp(self.last_failure_time).isoformat() if self.last_failure_time else None,
            'last_success': datetime.fromtimestamp(self.last_success_time).isoformat() if self.last_success_time else None,
        }


class CircuitBreaker:
    """
    Circuit Breaker для защиты от недоступных бирж.
    
    Использование:
        breaker = CircuitBreaker()
        
        # Проверка перед запросом
        if breaker.can_execute("binance"):
            try:
                result = await parse_exchange("binance")
                breaker.record_success("binance")
            except Exception as e:
                breaker.record_failure("binance", str(e))
        else:
            logger.info("Binance временно заблокирован")
    """
    
    def __init__(
        self,
        failure_threshold: int = None,
        recovery_timeout: int = None,
        half_open_max_calls: int = None,
        success_threshold: int = None
    ):
        """
        Args:
            failure_threshold: Количество неудач для открытия (блокировки)
            recovery_timeout: Секунды ожидания перед пробным запросом
            half_open_max_calls: Макс. запросов в состоянии HALF_OPEN
            success_threshold: Успехов для закрытия (разблокировки)
        """
        self.failure_threshold = failure_threshold or getattr(config, 'CIRCUIT_BREAKER_FAILURE_THRESHOLD', 3)
        self.recovery_timeout = recovery_timeout or getattr(config, 'CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 300)  # 5 минут
        self.half_open_max_calls = half_open_max_calls or getattr(config, 'CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS', 1)
        self.success_threshold = success_threshold or getattr(config, 'CIRCUIT_BREAKER_SUCCESS_THRESHOLD', 2)
        
        self._circuits: Dict[str, CircuitStats] = {}
        self._lock = asyncio.Lock()
        self._half_open_calls: Dict[str, int] = {}  # Счётчик вызовов в HALF_OPEN
        
        logger.info(
            f"🔌 CircuitBreaker инициализирован: "
            f"threshold={self.failure_threshold}, "
            f"recovery={self.recovery_timeout}s, "
            f"success_threshold={self.success_threshold}"
        )
    
    def _get_circuit(self, exchange: str) -> CircuitStats:
        """Получает или создаёт Circuit для биржи"""
        exchange = exchange.lower().strip()
        if exchange not in self._circuits:
            self._circuits[exchange] = CircuitStats(exchange=exchange)
        return self._circuits[exchange]
    
    def _normalize_exchange(self, exchange: str) -> str:
        """Нормализует название биржи"""
        if not exchange:
            return "unknown"
        return exchange.lower().strip()
    
    def can_execute(self, exchange: str) -> bool:
        """
        Проверяет, можно ли выполнять запрос к бирже.
        
        Returns:
            True если запрос можно выполнять, False если биржа заблокирована
        """
        exchange = self._normalize_exchange(exchange)
        circuit = self._get_circuit(exchange)
        
        if circuit.state == CircuitState.CLOSED:
            return True
        
        elif circuit.state == CircuitState.OPEN:
            # Проверяем, не пора ли попробовать восстановление
            if circuit.opened_at:
                elapsed = time.time() - circuit.opened_at
                if elapsed >= self.recovery_timeout:
                    # Переходим в HALF_OPEN для пробного запроса
                    self._transition_to_half_open(circuit)
                    return True
            
            # Биржа всё ещё заблокирована
            circuit.total_blocked += 1
            remaining = self.recovery_timeout - (time.time() - circuit.opened_at) if circuit.opened_at else 0
            logger.debug(f"⏸️ {exchange}: запрос заблокирован (осталось {remaining:.0f}с)")
            return False
        
        elif circuit.state == CircuitState.HALF_OPEN:
            # В HALF_OPEN разрешаем ограниченное количество запросов
            current_calls = self._half_open_calls.get(exchange, 0)
            if current_calls < self.half_open_max_calls:
                self._half_open_calls[exchange] = current_calls + 1
                return True
            
            logger.debug(f"⏸️ {exchange}: лимит HALF_OPEN достигнут")
            return False
        
        return False
    
    def record_success(self, exchange: str):
        """Записывает успешный запрос"""
        exchange = self._normalize_exchange(exchange)
        circuit = self._get_circuit(exchange)
        
        circuit.success_count += 1
        circuit.total_requests += 1
        circuit.last_success_time = time.time()
        
        if circuit.state == CircuitState.HALF_OPEN:
            # Проверяем, достигли ли порога успехов
            if circuit.success_count >= self.success_threshold:
                self._transition_to_closed(circuit)
                logger.info(f"✅ {exchange}: Circuit ЗАКРЫТ (биржа восстановилась)")
            else:
                logger.info(f"🔄 {exchange}: успех в HALF_OPEN ({circuit.success_count}/{self.success_threshold})")
        
        elif circuit.state == CircuitState.CLOSED:
            # Сбрасываем счётчик неудач при успехе
            circuit.failure_count = 0
    
    def record_failure(self, exchange: str, error: Optional[str] = None):
        """Записывает неудачный запрос"""
        exchange = self._normalize_exchange(exchange)
        circuit = self._get_circuit(exchange)
        
        circuit.failure_count += 1
        circuit.total_requests += 1
        circuit.total_failures += 1
        circuit.last_failure_time = time.time()
        
        if circuit.state == CircuitState.HALF_OPEN:
            # Неудача в HALF_OPEN — возвращаемся в OPEN
            self._transition_to_open(circuit)
            logger.warning(f"❌ {exchange}: Circuit ОТКРЫТ снова (ошибка в HALF_OPEN)")
        
        elif circuit.state == CircuitState.CLOSED:
            if circuit.failure_count >= self.failure_threshold:
                self._transition_to_open(circuit)
                logger.warning(
                    f"🔴 {exchange}: Circuit ОТКРЫТ ({circuit.failure_count} неудач подряд). "
                    f"Блокировка на {self.recovery_timeout}с. Ошибка: {error or 'N/A'}"
                )
            else:
                logger.debug(
                    f"⚠️ {exchange}: неудача {circuit.failure_count}/{self.failure_threshold}"
                )
    
    def _transition_to_open(self, circuit: CircuitStats):
        """Переводит в состояние OPEN (блокировка)"""
        circuit.state = CircuitState.OPEN
        circuit.opened_at = time.time()
        circuit.success_count = 0
        self._half_open_calls.pop(circuit.exchange, None)
    
    def _transition_to_half_open(self, circuit: CircuitStats):
        """Переводит в состояние HALF_OPEN (пробный запрос)"""
        circuit.state = CircuitState.HALF_OPEN
        circuit.success_count = 0
        circuit.failure_count = 0
        self._half_open_calls[circuit.exchange] = 0
        logger.info(f"🔄 {circuit.exchange}: Circuit в HALF_OPEN (пробный запрос)")
    
    def _transition_to_closed(self, circuit: CircuitStats):
        """Переводит в состояние CLOSED (нормальная работа)"""
        circuit.state = CircuitState.CLOSED
        circuit.failure_count = 0
        circuit.opened_at = None
        self._half_open_calls.pop(circuit.exchange, None)
    
    def reset(self, exchange: str):
        """Сбрасывает Circuit для биржи в начальное состояние"""
        exchange = self._normalize_exchange(exchange)
        if exchange in self._circuits:
            circuit = self._circuits[exchange]
            self._transition_to_closed(circuit)
            circuit.success_count = 0
            circuit.total_blocked = 0
            logger.info(f"🔄 {exchange}: Circuit сброшен")
    
    def reset_all(self):
        """Сбрасывает все Circuits"""
        for exchange in list(self._circuits.keys()):
            self.reset(exchange)
        logger.info("🔄 Все Circuits сброшены")
    
    def force_open(self, exchange: str, duration: int = None):
        """Принудительно блокирует биржу"""
        exchange = self._normalize_exchange(exchange)
        circuit = self._get_circuit(exchange)
        self._transition_to_open(circuit)
        logger.warning(f"🔴 {exchange}: Circuit принудительно ОТКРЫТ")
    
    def get_state(self, exchange: str) -> CircuitState:
        """Возвращает текущее состояние Circuit для биржи"""
        exchange = self._normalize_exchange(exchange)
        return self._get_circuit(exchange).state
    
    def is_open(self, exchange: str) -> bool:
        """Проверяет, заблокирована ли биржа"""
        return self.get_state(exchange) == CircuitState.OPEN
    
    def get_stats(self, exchange: str = None) -> Dict[str, Any]:
        """Возвращает статистику"""
        if exchange:
            exchange = self._normalize_exchange(exchange)
            circuit = self._circuits.get(exchange)
            return circuit.to_dict() if circuit else {}
        
        # Все биржи
        return {
            'circuits': {ex: c.to_dict() for ex, c in self._circuits.items()},
            'total_blocked': sum(c.total_blocked for c in self._circuits.values()),
            'open_circuits': [ex for ex, c in self._circuits.items() if c.state == CircuitState.OPEN],
        }
    
    def get_blocked_exchanges(self) -> list:
        """Возвращает список заблокированных бирж"""
        return [
            exchange for exchange, circuit in self._circuits.items()
            if circuit.state == CircuitState.OPEN
        ]
    
    def get_status_message(self) -> str:
        """Формирует сообщение о статусе всех Circuits"""
        if not self._circuits:
            return "🔌 Circuit Breaker: нет данных"
        
        lines = ["🔌 <b>Circuit Breaker Status:</b>"]
        
        for exchange, circuit in sorted(self._circuits.items()):
            if circuit.state == CircuitState.CLOSED:
                status = "🟢 OK"
            elif circuit.state == CircuitState.OPEN:
                remaining = self.recovery_timeout - (time.time() - circuit.opened_at) if circuit.opened_at else 0
                status = f"🔴 Blocked ({remaining:.0f}s)"
            else:
                status = "🟡 Testing"
            
            lines.append(
                f"  • <code>{exchange}</code>: {status} "
                f"(fails: {circuit.failure_count}, rate: {circuit.failure_rate:.1f}%)"
            )
        
        blocked = self.get_blocked_exchanges()
        if blocked:
            lines.append(f"\n⚠️ Заблокировано: {', '.join(blocked)}")
        
        return "\n".join(lines)


# Глобальный экземпляр
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    """Возвращает глобальный Circuit Breaker"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


def init_circuit_breaker(**kwargs) -> CircuitBreaker:
    """Инициализирует глобальный Circuit Breaker"""
    global _circuit_breaker
    _circuit_breaker = CircuitBreaker(**kwargs)
    return _circuit_breaker


# Декоратор для автоматического использования Circuit Breaker
def with_circuit_breaker(exchange_param: str = 'exchange'):
    """
    Декоратор для автоматического использования Circuit Breaker.
    
    Использование:
        @with_circuit_breaker('exchange')
        async def parse_exchange(exchange: str, url: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            breaker = get_circuit_breaker()
            
            # Извлекаем exchange из аргументов
            exchange = kwargs.get(exchange_param)
            if exchange is None and args:
                # Пытаемся найти в позиционных аргументах
                import inspect
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if exchange_param in params:
                    idx = params.index(exchange_param)
                    if idx < len(args):
                        exchange = args[idx]
            
            if not exchange:
                # Если exchange не найден — выполняем без Circuit Breaker
                return await func(*args, **kwargs)
            
            if not breaker.can_execute(exchange):
                # Биржа заблокирована
                raise CircuitOpenError(f"Circuit is OPEN for {exchange}")
            
            try:
                result = await func(*args, **kwargs)
                breaker.record_success(exchange)
                return result
            except Exception as e:
                breaker.record_failure(exchange, str(e))
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            breaker = get_circuit_breaker()
            
            exchange = kwargs.get(exchange_param)
            if not exchange:
                return func(*args, **kwargs)
            
            if not breaker.can_execute(exchange):
                raise CircuitOpenError(f"Circuit is OPEN for {exchange}")
            
            try:
                result = func(*args, **kwargs)
                breaker.record_success(exchange)
                return result
            except Exception as e:
                breaker.record_failure(exchange, str(e))
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class CircuitOpenError(Exception):
    """Исключение, когда Circuit открыт (биржа заблокирована)"""
    pass
