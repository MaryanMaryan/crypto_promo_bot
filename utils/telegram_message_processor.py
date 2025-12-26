import re
from typing import Dict, List, Optional
from datetime import datetime

class TelegramMessageProcessor:
    """Процессор для анализа и обработки сообщений из Telegram"""

    # Паттерны для различных типов данных
    PRIZE_PATTERNS = [
        r'\$[\d,]+',  # $10,000
        r'[\d,]+\s*USD[T]?',  # 10000 USDT
        r'[\d,]+\s*[A-Z]{3,4}',  # 1000 BTC
    ]

    DATE_PATTERNS = [
        r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}',  # 01.01.2025
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}',  # Jan 15
        r'\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)',  # 15 января
    ]

    PROMO_TYPES = {
        'airdrop': ['airdrop', 'air drop', 'раздача', 'бесплатно'],
        'staking': ['staking', 'stake', 'стейкинг', 'locked', 'earn'],
        'trading': ['trading', 'trade', 'трейдинг', 'volume', 'объем'],
        'campaign': ['campaign', 'competition', 'contest', 'кампания', 'конкурс'],
        'launchpool': ['launchpool', 'launch pool', 'лаунчпул', 'farming'],
    }

    @staticmethod
    def extract_prize_pool(text: str) -> Optional[str]:
        """Извлечение призового фонда"""
        for pattern in TelegramMessageProcessor.PRIZE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def extract_period(text: str) -> Optional[str]:
        """Извлечение периода проведения акции"""
        dates = []
        for pattern in TelegramMessageProcessor.DATE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)

        if dates:
            return ' - '.join(dates[:2]) if len(dates) >= 2 else dates[0]
        return None

    @staticmethod
    def detect_promo_type(text: str, keywords: List[str]) -> str:
        """Определение типа промоакции"""
        text_lower = text.lower()

        # Проверяем каждый тип
        for promo_type, terms in TelegramMessageProcessor.PROMO_TYPES.items():
            for term in terms:
                if term in text_lower:
                    return promo_type

        # Если не определено, возвращаем тип по ключевому слову
        if keywords:
            keyword_lower = keywords[0].lower()
            for promo_type, terms in TelegramMessageProcessor.PROMO_TYPES.items():
                if keyword_lower in terms:
                    return promo_type

        return 'general'

    @staticmethod
    def extract_requirements(text: str) -> List[str]:
        """Извлечение требований для участия"""
        requirements = []

        # Ищем списки с маркерами
        list_pattern = r'[•\-\*]\s*(.+)'
        matches = re.findall(list_pattern, text)

        if matches:
            requirements = [m.strip() for m in matches[:5]]  # Максимум 5 пунктов

        return requirements

    @staticmethod
    def create_summary(text: str, max_length: int = 300) -> str:
        """Создание краткого содержания сообщения"""
        # Убираем лишние пробелы и переносы
        clean_text = ' '.join(text.split())

        if len(clean_text) <= max_length:
            return clean_text

        # Обрезаем по словам
        summary = clean_text[:max_length]
        last_space = summary.rfind(' ')

        if last_space > 0:
            summary = summary[:last_space]

        return summary + '...'

    @staticmethod
    def analyze_message(text: str, matched_keywords: List[str]) -> Dict:
        """Полный анализ сообщения"""
        return {
            'prize_pool': TelegramMessageProcessor.extract_prize_pool(text),
            'period': TelegramMessageProcessor.extract_period(text),
            'promo_type': TelegramMessageProcessor.detect_promo_type(text, matched_keywords),
            'requirements': TelegramMessageProcessor.extract_requirements(text),
            'summary': TelegramMessageProcessor.create_summary(text)
        }
