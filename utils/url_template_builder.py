"""
URL TEMPLATE BUILDER
Автоматическое обучение и генерация ссылок на промоакции

Система работает так:
1. Получает пример URL промоакции от пользователя
2. Запрашивает API и парсит промоакции
3. Автоматически находит соответствия между данными API и URL
4. Создает и сохраняет шаблон
5. Использует шаблон для генерации ссылок на новые промоакции
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, parse_qs, urlencode
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Путь к файлу с шаблонами
TEMPLATES_FILE = os.path.join(os.path.dirname(__file__), '..', 'config', 'url_templates.json')


class URLTemplateAnalyzer:
    """Анализирует пример URL и создает шаблон для генерации ссылок"""

    def __init__(self, example_url: str, api_data: List[Dict[str, Any]]):
        """
        Args:
            example_url: Пример ссылки на промоакцию
            api_data: Список промоакций из API
        """
        self.example_url = example_url
        self.api_data = api_data
        self.parsed_url = urlparse(example_url)

    def analyze(self) -> Optional[Dict[str, Any]]:
        """
        Анализирует URL и создает шаблон

        Returns:
            Словарь с шаблоном или None если не удалось создать
        """
        try:
            logger.info(f"🔍 Анализ URL: {self.example_url}")

            # Шаг 1: Разбиваем URL на части
            url_parts = self._parse_url_parts()
            logger.debug(f"URL части: {url_parts}")

            # Шаг 2: Находим промоакцию в API данных, которая соответствует этому URL
            matching_promo = self._find_matching_promo(url_parts)

            if not matching_promo:
                logger.warning(f"⚠️ Не удалось найти соответствующую промоакцию в API")
                return None

            logger.info(f"✅ Найдена соответствующая промоакция в API")

            # Шаг 3: Сопоставляем части URL с полями API
            template = self._create_template(url_parts, matching_promo)

            if template:
                # Шаг 4: Валидация шаблона - проверяем что он генерирует правильный URL
                if self._validate_template(template, matching_promo):
                    logger.info(f"✅ Шаблон успешно создан и валидирован: {template['pattern']}")
                    return template
                else:
                    logger.error(f"❌ Шаблон не прошел валидацию - сгенерированный URL не совпадает с примером")
                    return None

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка анализа URL: {e}", exc_info=True)
            return None

    def _parse_url_parts(self) -> Dict[str, Any]:
        """Разбирает URL на составные части"""
        path = self.parsed_url.path
        query_params = parse_qs(self.parsed_url.query)

        # Разбиваем путь на сегменты
        path_segments = [s for s in path.split('/') if s]

        return {
            'scheme': self.parsed_url.scheme,
            'domain': self.parsed_url.netloc,
            'path': path,
            'path_segments': path_segments,
            'query_params': query_params,
            'full_url': self.example_url
        }

    def _find_matching_promo(self, url_parts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Ищет промоакцию в API данных, которая соответствует URL

        Использует несколько стратегий:
        1. Поиск по ID в URL
        2. Поиск по имени/названию
        3. Нечеткое сопоставление
        """
        path_segments = url_parts['path_segments']
        query_params = url_parts['query_params']

        # Извлекаем все значения из URL (path segments + query params)
        url_values = set(path_segments)
        for param_values in query_params.values():
            url_values.update(param_values)

        best_match = None
        best_score = 0

        for promo in self.api_data:
            score = self._calculate_match_score(promo, url_values)

            if score > best_score:
                best_score = score
                best_match = promo

        # Требуем минимальный уровень совпадения
        if best_score >= 2:  # Минимум 2 совпадающих поля
            logger.debug(f"Найдено совпадение с score={best_score}: {best_match}")
            return best_match

        return None

    def _calculate_match_score(self, promo: Dict[str, Any], url_values: set) -> int:
        """Вычисляет степень совпадения между промоакцией и URL"""
        score = 0

        # Проверяем все значения в промоакции
        for key, value in promo.items():
            if value is None:
                continue

            value_str = str(value).lower()

            # Точное совпадение
            for url_value in url_values:
                url_value_lower = url_value.lower()

                if value_str == url_value_lower:
                    score += 3  # Точное совпадение - высокий балл
                elif value_str in url_value_lower or url_value_lower in value_str:
                    score += 2  # Частичное совпадение
                elif self._similarity(value_str, url_value_lower) > 0.8:
                    score += 1  # Похожие строки

        return score

    def _similarity(self, a: str, b: str) -> float:
        """Вычисляет сходство двух строк (0.0 - 1.0)"""
        return SequenceMatcher(None, a, b).ratio()

    def _create_template(self, url_parts: Dict[str, Any], promo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Создает шаблон на основе URL и промоакции

        Returns:
            {
                'pattern': '/ru-RU/launchpad/{projectName}/{projectId}',
                'pattern_type': 'path',  # или 'query'
                'base_url': 'https://www.mexc.com',
                'fields': {
                    'projectName': ['projectName', 'name', 'coinName'],
                    'projectId': ['projectId', 'id', '_id']
                },
                'static_segments': ['ru-RU', 'launchpad']
            }
        """
        try:
            # Определяем, где находятся динамические части: в path или в query
            if url_parts['query_params']:
                # Если есть query параметры, создаем шаблон с query
                return self._create_query_template(url_parts, promo)
            else:
                # Иначе создаем шаблон для path
                return self._create_path_template(url_parts, promo)

        except Exception as e:
            logger.error(f"❌ Ошибка создания шаблона: {e}", exc_info=True)
            return None

    def _create_path_template(self, url_parts: Dict[str, Any], promo: Dict[str, Any]) -> Dict[str, Any]:
        """Создает шаблон для URL с динамическими частями в path"""
        path_segments = url_parts['path_segments']
        pattern_parts = []
        fields = {}
        static_segments = []

        for segment in path_segments:
            # Пробуем найти соответствующее поле в промоакции
            field_info = self._find_matching_field(segment, promo)

            if field_info:
                # Это динамическая часть
                field_name, api_fields = field_info
                pattern_parts.append(f"{{{field_name}}}")
                fields[field_name] = api_fields
            else:
                # Это статическая часть
                pattern_parts.append(segment)
                static_segments.append(segment)

        pattern = '/' + '/'.join(pattern_parts)
        base_url = f"{url_parts['scheme']}://{url_parts['domain']}"

        return {
            'pattern': pattern,
            'pattern_type': 'path',
            'base_url': base_url,
            'fields': fields,
            'static_segments': static_segments
        }

    def _create_query_template(self, url_parts: Dict[str, Any], promo: Dict[str, Any]) -> Dict[str, Any]:
        """Создает шаблон для URL с динамическими частями в query параметрах"""
        query_params = url_parts['query_params']
        fields = {}
        static_path = url_parts['path']

        for param_name, param_values in query_params.items():
            param_value = param_values[0] if param_values else ''

            # Пробуем найти соответствующее поле в промоакции
            field_info = self._find_matching_field(param_value, promo)

            if field_info:
                field_name, api_fields = field_info
                fields[param_name] = api_fields

        # Создаем паттерн query string
        query_pattern = '&'.join([f"{k}={{{k}}}" for k in fields.keys()])
        pattern = f"{static_path}?{query_pattern}"
        base_url = f"{url_parts['scheme']}://{url_parts['domain']}"

        return {
            'pattern': pattern,
            'pattern_type': 'query',
            'base_url': base_url,
            'fields': fields,
            'static_segments': []
        }

    def _find_matching_field(self, url_value: str, promo: Dict[str, Any]) -> Optional[Tuple[str, List[str]]]:
        """
        Находит поле в промоакции, которое соответствует значению из URL

        Returns:
            (field_name, [list_of_alternative_field_names]) или None
        """
        url_value_lower = url_value.lower()

        # Список полей с похожими значениями
        candidates = []

        for key, value in promo.items():
            if value is None:
                continue

            value_str = str(value).lower()

            # Точное совпадение или частичное вхождение
            if value_str == url_value_lower:
                # Точное совпадение - высокий приоритет
                candidates.append((key, 3))
            elif value_str in url_value_lower or url_value_lower in value_str:
                candidates.append((key, 2))
            elif self._similarity(value_str, url_value_lower) > 0.8:
                candidates.append((key, 1))

        if not candidates:
            return None

        # Выбираем кандидата с максимальным приоритетом
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_field = candidates[0][0]

        # Создаем список альтернативных имен полей (для гибкости)
        alternative_names = self._generate_alternative_field_names(best_field)

        return (best_field, alternative_names)

    def _generate_alternative_field_names(self, field_name: str) -> List[str]:
        """
        Генерирует список альтернативных имен для поля

        Например, для 'projectId' создаст ['projectId', 'id', '_id', 'project_id']
        """
        alternatives = [field_name]

        # Добавляем общие варианты для ID
        if 'id' in field_name.lower():
            alternatives.extend(['id', '_id'])

        # Добавляем варианты с подчеркиваниями
        snake_case = re.sub(r'([A-Z])', r'_\1', field_name).lower().lstrip('_')
        if snake_case not in alternatives:
            alternatives.append(snake_case)

        # Добавляем варианты без префиксов
        if '_' in field_name:
            base_name = field_name.split('_')[-1]
            if base_name not in alternatives:
                alternatives.append(base_name)

        # Для name/title полей добавляем популярные варианты
        if 'name' in field_name.lower():
            alternatives.extend(['name', 'title', 'projectName', 'tokenName', 'coinName'])

        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        result = []
        for alt in alternatives:
            if alt not in seen:
                seen.add(alt)
                result.append(alt)

        return result

    def _validate_template(self, template: Dict[str, Any], promo: Dict[str, Any]) -> bool:
        """
        Валидирует шаблон, проверяя что он генерирует правильный URL

        Args:
            template: Созданный шаблон
            promo: Промоакция, для которой создан шаблон

        Returns:
            True если шаблон генерирует URL совпадающий с примером, False иначе
        """
        try:
            # Создаем временный builder для проверки
            test_builder = URLTemplateBuilder()

            # Подставляем значения из промоакции в шаблон
            pattern = template['pattern']
            base_url = template['base_url']
            fields = template['fields']

            # Собираем значения для всех полей
            field_values = {}
            for field_name, alternative_names in fields.items():
                value = test_builder._get_field_value(promo, alternative_names)
                if value is None:
                    logger.warning(f"⚠️ Поле {field_name} не найдено в данных промоакции")
                    return False
                field_values[field_name] = value

            # Генерируем URL
            generated_path = pattern
            for field_name, value in field_values.items():
                generated_path = generated_path.replace(f"{{{field_name}}}", str(value))

            generated_url = base_url + generated_path

            # Нормализуем URL для сравнения (убираем query params и fragment)
            example_parsed = urlparse(self.example_url)
            generated_parsed = urlparse(generated_url)

            example_normalized = f"{example_parsed.scheme}://{example_parsed.netloc}{example_parsed.path}"
            generated_normalized = f"{generated_parsed.scheme}://{generated_parsed.netloc}{generated_parsed.path}"

            # Убираем trailing slash для сравнения
            example_normalized = example_normalized.rstrip('/')
            generated_normalized = generated_normalized.rstrip('/')

            # Сравниваем
            if example_normalized.lower() == generated_normalized.lower():
                logger.info(f"✅ Валидация успешна:")
                logger.info(f"   Пример:      {example_normalized}")
                logger.info(f"   Сгенерирован: {generated_normalized}")
                return True
            else:
                logger.error(f"❌ Валидация не прошла:")
                logger.error(f"   Ожидалось:   {example_normalized}")
                logger.error(f"   Получено:     {generated_normalized}")
                logger.error(f"   Разница в пути может указывать на неправильное определение статических сегментов")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка валидации шаблона: {e}", exc_info=True)
            return False


class URLTemplateBuilder:
    """Генерирует URL для промоакций на основе сохраненных шаблонов"""

    def __init__(self):
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[str, Any]:
        """Загружает шаблоны из JSON файла"""
        try:
            if os.path.exists(TEMPLATES_FILE):
                with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки шаблонов: {e}")
            return {}

    def _save_templates(self):
        """Сохраняет шаблоны в JSON файл"""
        try:
            os.makedirs(os.path.dirname(TEMPLATES_FILE), exist_ok=True)
            with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.templates, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Шаблоны сохранены в {TEMPLATES_FILE}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения шаблонов: {e}")

    def add_template(self, exchange: str, template_type: str, template: Dict[str, Any]):
        """
        Добавляет новый шаблон

        Args:
            exchange: Название биржи (mexc, bybit, binance)
            template_type: Тип промоакции (launchpad, token-airdrop, token-splash)
            template: Шаблон URL
        """
        if exchange not in self.templates:
            self.templates[exchange] = {}

        self.templates[exchange][template_type] = template
        self._save_templates()

        logger.info(f"✅ Шаблон добавлен: {exchange} / {template_type}")

    def build_url(self, exchange: str, promo: Dict[str, Any]) -> Optional[str]:
        """
        Генерирует URL для промоакции

        Args:
            exchange: Название биржи
            promo: Данные промоакции из API

        Returns:
            URL промоакции или None
        """
        try:
            # Если в промоакции уже есть ссылка, используем её
            if promo.get('link') or promo.get('url'):
                return promo.get('link') or promo.get('url')

            # Получаем шаблоны для биржи
            exchange_templates = self.templates.get(exchange.lower(), {})

            if not exchange_templates:
                logger.debug(f"⚠️ Нет шаблонов для биржи {exchange}")
                return None

            # Пробуем каждый шаблон
            for template_type, template in exchange_templates.items():
                url = self._try_build_url(template, promo)
                if url:
                    logger.debug(f"✅ URL построен по шаблону {template_type}: {url}")
                    return url

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка генерации URL: {e}", exc_info=True)
            return None

    def _try_build_url(self, template: Dict[str, Any], promo: Dict[str, Any]) -> Optional[str]:
        """Пытается построить URL по шаблону"""
        try:
            pattern = template['pattern']
            base_url = template['base_url']
            fields = template['fields']

            # Собираем значения для всех полей шаблона
            field_values = {}

            for field_name, alternative_names in fields.items():
                value = self._get_field_value(promo, alternative_names)
                if value is None:
                    # Не хватает обязательного поля
                    return None
                field_values[field_name] = value

            # Подставляем значения в шаблон
            url = pattern
            for field_name, value in field_values.items():
                url = url.replace(f"{{{field_name}}}", str(value))

            full_url = base_url + url

            return full_url

        except Exception as e:
            logger.debug(f"Не удалось построить URL по шаблону: {e}")
            return None

    def _get_field_value(self, promo: Dict[str, Any], field_names: List[str]) -> Optional[str]:
        """Получает значение поля из промоакции, пробуя разные варианты имен"""
        for field_name in field_names:
            # Прямой поиск
            if field_name in promo:
                value = promo[field_name]
                if value is not None:
                    return str(value)

            # Поиск без учета регистра
            field_name_lower = field_name.lower()
            for key, value in promo.items():
                if key.lower() == field_name_lower and value is not None:
                    return str(value)

        return None

    def get_template_info(self, exchange: str) -> Dict[str, Any]:
        """Возвращает информацию о шаблонах для биржи"""
        return self.templates.get(exchange.lower(), {})


# Глобальный экземпляр builder'а
_builder_instance = None

def get_url_builder() -> URLTemplateBuilder:
    """Возвращает глобальный экземпляр URLTemplateBuilder (singleton)"""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = URLTemplateBuilder()
    return _builder_instance
