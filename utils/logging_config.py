# utils/logging_config.py
"""
Централизованная настройка логирования для Crypto Promo Bot.

Возможности:
- Уровень логирования из config.LOG_LEVEL
- Запись в файл с ротацией (по размеру)
- Консольный вывод с цветами (опционально)
- Фильтрация шумных логгеров

Использование:
    from utils.logging_config import setup_logging
    
    # В начале main.py:
    setup_logging()
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

import config


def setup_logging(
    log_level: Optional[str] = None,
    log_to_file: Optional[bool] = None,
    log_file_path: Optional[str] = None,
) -> None:
    """
    Настраивает логирование для всего приложения.
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR). 
                   По умолчанию из config.LOG_LEVEL
        log_to_file: Писать ли в файл. По умолчанию из config.LOG_TO_FILE
        log_file_path: Путь к файлу логов. По умолчанию из config.LOG_FILE_PATH
    """
    # Получаем настройки из config или аргументов
    level_name = log_level or config.LOG_LEVEL
    level = getattr(logging, level_name.upper(), logging.INFO)
    
    write_to_file = log_to_file if log_to_file is not None else config.LOG_TO_FILE
    file_path = log_file_path or config.LOG_FILE_PATH
    
    # Формат логов
    log_format = config.LOG_FORMAT
    
    # Создаём root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Очищаем существующие handlers (чтобы не дублировать)
    root_logger.handlers.clear()
    
    # Консольный handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)
    
    # Файловый handler (с ротацией)
    if write_to_file:
        try:
            # Создаём директорию для логов если не существует
            log_path = Path(file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Ротация: maxBytes = 10MB по умолчанию, backupCount = 5
            max_bytes = config.LOG_MAX_SIZE_MB * 1024 * 1024
            backup_count = config.LOG_BACKUP_COUNT
            
            file_handler = RotatingFileHandler(
                filename=file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(log_format))
            root_logger.addHandler(file_handler)
            
            logging.info(f"📝 Логирование в файл: {file_path} (макс. {config.LOG_MAX_SIZE_MB}MB, {backup_count} бэкапов)")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось настроить логирование в файл: {e}")
    
    # Уменьшаем verbosity сторонних библиотек
    _configure_third_party_loggers(level)
    
    logging.info(f"📊 Уровень логирования: {level_name}")


def _configure_third_party_loggers(app_level: int) -> None:
    """
    Настраивает уровни логирования для сторонних библиотек.
    Это уменьшает спам от urllib3, httpx, aiogram и других.
    """
    # Библиотеки, которые логируют слишком много на INFO
    quiet_loggers = [
        'urllib3',
        'httpx',
        'httpcore',
        'aiohttp',
        'apscheduler',
        'playwright',
        'sqlalchemy.engine',
        'telethon',
    ]
    
    # Устанавливаем WARNING для шумных логгеров (если мы не в DEBUG)
    if app_level > logging.DEBUG:
        for logger_name in quiet_loggers:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # asyncio - підвищуємо до ERROR для Windows subprocess cleanup warnings
    import sys
    if sys.platform == 'win32':
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        logging.info("🪟 Windows: asyncio logger встановлено на ERROR (subprocess cleanup)")
    else:
        if app_level > logging.DEBUG:
            logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    # aiogram — оставляем INFO для важных событий
    if app_level >= logging.INFO:
        logging.getLogger('aiogram').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Получить logger с заданным именем.
    Удобная обёртка для logging.getLogger().
    
    Пример:
        logger = get_logger(__name__)
        logger.info("Сообщение")
    """
    return logging.getLogger(name)


def set_log_level(level: str) -> None:
    """
    Изменить уровень логирования в runtime.
    
    Args:
        level: DEBUG, INFO, WARNING, ERROR
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(numeric_level)
    
    for handler in logging.getLogger().handlers:
        handler.setLevel(numeric_level)
    
    logging.info(f"📊 Уровень логирования изменён на: {level}")
