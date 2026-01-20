"""
Модуль кэширования для отзывчивого UI

Предоставляет:
- TTL-кэш для часто запрашиваемых данных
- Автоматическая инвалидация по времени
- Thread-safe операции
- Декораторы для автоматического кэширования

Использование:
    from utils.cache import async_cache, cache_manager
    
    # Декоратор для функций
    @async_cache(ttl=30)
    async def get_links():
        ...
    
    # Ручное управление
    cache_manager.set("key", data, ttl=60)
    data = cache_manager.get("key")
    cache_manager.invalidate("key")
"""

import asyncio
import time
import logging
import functools
from typing import Any, Optional, Dict, Callable, TypeVar, ParamSpec
from dataclasses import dataclass, field
import threading
from collections import OrderedDict

import config

logger = logging.getLogger(__name__)

# Type hints для декораторов
P = ParamSpec('P')
T = TypeVar('T')


@dataclass
class CacheEntry:
    """Запись в кэше с TTL"""
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.time)
    hits: int = 0
    
    def is_expired(self) -> bool:
        """Проверить истёк ли срок жизни записи"""
        return time.time() >= self.expires_at
    
    def remaining_ttl(self) -> float:
        """Оставшееся время жизни в секундах"""
        return max(0, self.expires_at - time.time())


class CacheManager:
    """
    Thread-safe TTL кэш с LRU-подобной логикой
    
    Features:
    - Автоматическое удаление просроченных записей
    - Максимальный размер кэша
    - Статистика использования
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 30.0):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._max_size = max_size
        self._default_ttl = default_ttl
        
        # Статистика
        self._hits = 0
        self._misses = 0
        
        logger.info(f"🗄️ CacheManager инициализирован (max_size={max_size}, default_ttl={default_ttl}s)")
    
    def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из кэша
        
        Args:
            key: Ключ записи
            
        Returns:
            Значение или None если не найдено/истекло
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                # Удаляем просроченную запись
                del self._cache[key]
                self._misses += 1
                logger.debug(f"🕐 Кэш истёк: {key}")
                return None
            
            # Обновляем статистику и перемещаем в конец (LRU)
            entry.hits += 1
            self._hits += 1
            self._cache.move_to_end(key)
            
            logger.debug(f"✅ Кэш хит: {key} (осталось {entry.remaining_ttl():.1f}s)")
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        Сохранить значение в кэш
        
        Args:
            key: Ключ записи
            value: Значение для сохранения
            ttl: Время жизни в секундах (по умолчанию default_ttl)
        """
        if ttl is None:
            ttl = self._default_ttl
        
        with self._lock:
            now = time.time()
            
            # Если ключ уже существует, обновляем
            if key in self._cache:
                del self._cache[key]
            
            # Проверяем размер и удаляем старые записи если нужно
            while len(self._cache) >= self._max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"🗑️ Удалена старая запись: {oldest_key}")
            
            # Добавляем новую запись
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=now + ttl,
                created_at=now
            )
            
            logger.debug(f"💾 Кэш записан: {key} (TTL={ttl}s)")
    
    def invalidate(self, key: str) -> bool:
        """
        Удалить запись из кэша
        
        Args:
            key: Ключ для удаления
            
        Returns:
            True если запись была удалена
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"🗑️ Кэш инвалидирован: {key}")
                return True
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Удалить все записи, ключи которых содержат pattern
        
        Args:
            pattern: Подстрока для поиска в ключах
            
        Returns:
            Количество удалённых записей
        """
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
            
            if keys_to_delete:
                logger.debug(f"🗑️ Инвалидированы записи с паттерном '{pattern}': {len(keys_to_delete)}")
            
            return len(keys_to_delete)
    
    def clear(self) -> int:
        """
        Очистить весь кэш
        
        Returns:
            Количество удалённых записей
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"🧹 Кэш очищен: {count} записей")
            return count
    
    def cleanup_expired(self) -> int:
        """
        Удалить все просроченные записи
        
        Returns:
            Количество удалённых записей
        """
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items()
                if v.expires_at <= now
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.debug(f"🧹 Удалено просроченных записей: {len(expired_keys)}")
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику кэша"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "default_ttl": self._default_ttl
            }
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


# Глобальный менеджер кэша
_cache_manager: Optional[CacheManager] = None
_cache_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """
    Получить глобальный экземпляр CacheManager (singleton)
    """
    global _cache_manager
    
    if _cache_manager is None:
        with _cache_lock:
            if _cache_manager is None:
                # Читаем настройки из конфига
                max_size = getattr(config, 'CACHE_MAX_SIZE', 1000)
                default_ttl = getattr(config, 'CACHE_DEFAULT_TTL', 30.0)
                
                _cache_manager = CacheManager(
                    max_size=max_size,
                    default_ttl=default_ttl
                )
    
    return _cache_manager


# Алиас для удобства
cache_manager = property(lambda self: get_cache_manager())


def async_cache(
    ttl: Optional[float] = None,
    key_prefix: str = "",
    key_builder: Optional[Callable[..., str]] = None
):
    """
    Декоратор для кэширования результатов async функций
    
    Args:
        ttl: Время жизни кэша в секундах (None = default из config)
        key_prefix: Префикс для ключа кэша
        key_builder: Функция для генерации ключа из аргументов
        
    Usage:
        @async_cache(ttl=30)
        async def get_links():
            ...
            
        @async_cache(key_builder=lambda user_id: f"user_{user_id}")
        async def get_user_data(user_id: int):
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            cache = get_cache_manager()
            
            # Строим ключ
            if key_builder:
                cache_key = key_prefix + key_builder(*args, **kwargs)
            else:
                # Генерируем ключ из имени функции и аргументов
                args_str = "_".join(str(a) for a in args)
                kwargs_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"{key_prefix}{func.__name__}_{args_str}_{kwargs_str}"
            
            # Пробуем получить из кэша
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            
            # Выполняем функцию
            result = await func(*args, **kwargs)
            
            # Сохраняем в кэш
            actual_ttl = ttl if ttl is not None else getattr(config, 'CACHE_DEFAULT_TTL', 30.0)
            cache.set(cache_key, result, ttl=actual_ttl)
            
            return result
        
        # Добавляем методы для управления кэшем
        wrapper.cache_invalidate = lambda *args, **kwargs: get_cache_manager().invalidate(
            f"{key_prefix}{func.__name__}_{('_'.join(str(a) for a in args))}_{('_'.join(f'{k}={v}' for k, v in sorted(kwargs.items())))}"
        )
        wrapper.cache_clear_all = lambda: get_cache_manager().invalidate_pattern(f"{key_prefix}{func.__name__}")
        
        return wrapper
    return decorator


def sync_cache(
    ttl: Optional[float] = None,
    key_prefix: str = "",
    key_builder: Optional[Callable[..., str]] = None
):
    """
    Декоратор для кэширования результатов синхронных функций
    
    Аналогичен async_cache, но для обычных функций
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            cache = get_cache_manager()
            
            # Строим ключ
            if key_builder:
                cache_key = key_prefix + key_builder(*args, **kwargs)
            else:
                args_str = "_".join(str(a) for a in args)
                kwargs_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"{key_prefix}{func.__name__}_{args_str}_{kwargs_str}"
            
            # Пробуем получить из кэша
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Сохраняем в кэш
            actual_ttl = ttl if ttl is not None else getattr(config, 'CACHE_DEFAULT_TTL', 30.0)
            cache.set(cache_key, result, ttl=actual_ttl)
            
            return result
        
        wrapper.cache_invalidate = lambda *args, **kwargs: get_cache_manager().invalidate(
            f"{key_prefix}{func.__name__}_{('_'.join(str(a) for a in args))}_{('_'.join(f'{k}={v}' for k, v in sorted(kwargs.items())))}"
        )
        wrapper.cache_clear_all = lambda: get_cache_manager().invalidate_pattern(f"{key_prefix}{func.__name__}")
        
        return wrapper
    return decorator


# =============================================================================
# ПРЕДОПРЕДЕЛЁННЫЕ КЛЮЧИ КЭША ДЛЯ HANDLERS
# =============================================================================

class CacheKeys:
    """Константы ключей кэша для единообразия"""
    
    # Ссылки
    LINKS_ALL = "links:all"
    LINKS_BY_CATEGORY = "links:category:{category}"
    LINK_BY_ID = "links:id:{link_id}"
    
    # Текущие промо/стейкинги
    CURRENT_PROMOS = "promos:current:{link_id}"
    CURRENT_STAKINGS = "stakings:current:{link_id}"
    
    # Статистика
    STATS_OVERVIEW = "stats:overview"
    
    @classmethod
    def links_by_category(cls, category: str) -> str:
        return cls.LINKS_BY_CATEGORY.format(category=category)
    
    @classmethod
    def link_by_id(cls, link_id: int) -> str:
        return cls.LINK_BY_ID.format(link_id=link_id)
    
    @classmethod
    def current_promos(cls, link_id: int) -> str:
        return cls.CURRENT_PROMOS.format(link_id=link_id)
    
    @classmethod
    def current_stakings(cls, link_id: int) -> str:
        return cls.CURRENT_STAKINGS.format(link_id=link_id)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def invalidate_links_cache():
    """Инвалидировать весь кэш ссылок (вызывать при изменениях)"""
    cache = get_cache_manager()
    cache.invalidate_pattern("links:")
    logger.info("🗑️ Кэш ссылок инвалидирован")


def invalidate_promos_cache(link_id: Optional[int] = None):
    """
    Инвалидировать кэш промоакций
    
    Args:
        link_id: ID ссылки для инвалидации (None = все)
    """
    cache = get_cache_manager()
    if link_id:
        cache.invalidate(CacheKeys.current_promos(link_id))
    else:
        cache.invalidate_pattern("promos:")
    logger.info(f"🗑️ Кэш промо инвалидирован (link_id={link_id})")


def invalidate_stakings_cache(link_id: Optional[int] = None):
    """
    Инвалидировать кэш стейкингов
    
    Args:
        link_id: ID ссылки для инвалидации (None = все)
    """
    cache = get_cache_manager()
    if link_id:
        cache.invalidate(CacheKeys.current_stakings(link_id))
    else:
        cache.invalidate_pattern("stakings:")
    logger.info(f"🗑️ Кэш стейкингов инвалидирован (link_id={link_id})")
