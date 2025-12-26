"""
Утилита для проверки и автоматической установки Playwright браузеров
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

def is_playwright_installed() -> bool:
    """Проверяет, установлен ли пакет playwright"""
    try:
        import playwright
        return True
    except ImportError:
        return False

def check_browsers_installed() -> bool:
    """Проверяет, установлены ли браузеры Playwright через директорию установки"""
    try:
        # Определяем директорию кэша браузеров Playwright
        if sys.platform == 'win32':
            # Windows: %USERPROFILE%\AppData\Local\ms-playwright
            cache_dir = Path.home() / 'AppData' / 'Local' / 'ms-playwright'
        elif sys.platform == 'darwin':
            # macOS: ~/Library/Caches/ms-playwright
            cache_dir = Path.home() / 'Library' / 'Caches' / 'ms-playwright'
        else:
            # Linux: ~/.cache/ms-playwright
            cache_dir = Path.home() / '.cache' / 'ms-playwright'

        # Проверяем наличие директории с браузерами
        if not cache_dir.exists():
            logger.warning(f"⚠️ Директория браузеров Playwright не найдена: {cache_dir}")
            return False

        # Проверяем наличие chromium (ищем папки типа chromium-1234)
        chromium_dirs = list(cache_dir.glob('chromium-*'))
        if chromium_dirs:
            logger.info(f"✅ Playwright Chromium найден: {chromium_dirs[0]}")
            return True
        else:
            logger.warning(f"⚠️ Chromium не найден в {cache_dir}")
            return False

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке браузеров: {e}")
        return False

def install_playwright_browsers(force: bool = False) -> bool:
    """
    Устанавливает браузеры Playwright

    Args:
        force: Принудительная переустановка даже если браузеры уже установлены

    Returns:
        True если установка прошла успешно, False в противном случае
    """
    try:
        if not force and check_browsers_installed():
            logger.info("✅ Браузеры Playwright уже установлены")
            return True

        logger.info("📥 Установка браузеров Playwright...")
        logger.info("⏳ Это может занять несколько минут...")

        # Запускаем playwright install chromium
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=600  # 10 минут таймаут
        )

        if result.returncode == 0:
            logger.info("✅ Браузеры Playwright успешно установлены")
            logger.debug(f"Вывод установки:\n{result.stdout}")
            return True
        else:
            logger.error(f"❌ Ошибка установки браузеров Playwright")
            logger.error(f"Код возврата: {result.returncode}")
            logger.error(f"Stdout: {result.stdout}")
            logger.error(f"Stderr: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("❌ Таймаут установки браузеров Playwright (>10 минут)")
        return False
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при установке: {e}", exc_info=True)
        return False

def ensure_playwright_ready() -> bool:
    """
    Проверяет готовность Playwright и автоматически устанавливает браузеры если нужно

    Returns:
        True если Playwright готов к использованию, False в противном случае
    """
    # Шаг 1: Проверка установки пакета
    if not is_playwright_installed():
        logger.error("❌ Пакет playwright не установлен!")
        logger.error("💡 Установите: pip install playwright==1.56.0")
        return False

    logger.info("✅ Пакет playwright установлен")

    # Шаг 2: Проверка установки браузеров
    if not check_browsers_installed():
        logger.warning("⚠️ Браузеры Playwright не установлены")
        logger.info("🔧 Запуск автоматической установки...")

        if install_playwright_browsers():
            logger.info("✅ Playwright полностью готов к работе")
            return True
        else:
            logger.error("❌ Не удалось установить браузеры Playwright")
            logger.error("💡 Попробуйте вручную: playwright install chromium")
            return False

    logger.info("✅ Playwright полностью готов к работе")
    return True

# Публичный API
__all__ = [
    'ensure_playwright_ready',
    'check_browsers_installed',
    'install_playwright_browsers'
]
