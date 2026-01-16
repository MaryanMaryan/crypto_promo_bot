from .base_parser import BaseParser

# Условный импорт чтобы избежать циклических зависимостей
try:
    from .universal_parser import UniversalParser
except ImportError:
    pass

try:
    from .universal_fallback_parser import UniversalFallbackParser
except ImportError:
    pass

try:
    from .weex_parser import WeexParser
except ImportError:
    pass

__all__ = ['BaseParser', 'UniversalParser', 'UniversalFallbackParser', 'WeexParser']