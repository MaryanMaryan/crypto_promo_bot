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

try:
    from .browser_parser import BrowserParser
except ImportError:
    pass

try:
    from .async_browser_parser import AsyncBrowserParser
except ImportError:
    pass

try:
    from .bitget_poolx_parser import BitgetPoolxParser
except ImportError:
    pass

try:
    from .bitget_candybomb_parser import BitgetCandybombParser
except ImportError:
    pass

__all__ = ['BaseParser', 'UniversalParser', 'UniversalFallbackParser', 'WeexParser', 'BrowserParser', 'AsyncBrowserParser', 'BitgetPoolxParser', 'BitgetCandybombParser']