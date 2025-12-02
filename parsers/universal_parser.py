import json
import logging
import hashlib
import requests
from typing import List, Dict, Any
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

class UniversalParser(BaseParser):
    def __init__(self, url: str):
        super().__init__(url)  # ✅ Передаем url в родительский класс

    def extract_promo_id(self, obj: Dict) -> str:
        """Создает стабильный уникальный ID для промоакции"""
        try:
            exchange_name = self._extract_domain_name(self.url).lower()
            
            # Приоритетная система для ID
            id_candidates = [
                obj.get('id'),
                obj.get('promoId'),
                obj.get('campaignId'),
                obj.get('activityId'),
                obj.get('code'),
                obj.get('promoCode'),
                obj.get('projectId'),
                obj.get('eventId')
            ]
            
            # Ищем первый непустой ID
            for candidate in id_candidates:
                if candidate and str(candidate).strip():
                    return f"{exchange_name}_{candidate}"
            
            # Если ID не найдены, создаем составной ключ
            title = self._get_value(obj, ['name', 'title', 'campaignName', 'activityName']) or ""
            token = self._get_value(obj, ['token', 'currency', 'awardToken', 'symbol']) or ""
            start_time = self._get_value(obj, ['startTime', 'start', 'startDate', 'beginTime']) or ""
            
            if title and token:
                stable_key = f"{title}_{token}_{start_time}"
                content_hash = hashlib.md5(stable_key.encode('utf-8')).hexdigest()[:12]
                return f"{exchange_name}_{content_hash}"

            # Крайний случай - хэш всего объекта
            fallback_hash = hashlib.md5(str(obj).encode('utf-8')).hexdigest()[:12]
            return f"{exchange_name}_fallback_{fallback_hash}"

        except Exception as e:
            logger.error(f"❌ Ошибка создания ID: {e}")
            return f"{self._extract_domain_name(self.url).lower()}_error_{hash(str(obj))}"

    def get_promotions(self) -> List[Dict[str, Any]]:
        """Получает промоакции из любого JSON API"""
        try:
            logger.info(f"🔍 UniversalParser (API): Начало парсинга")
            logger.info(f"   URL: {self.url}")

            # Увеличиваем таймаут до 30 секунд и добавляем retry стратегию
            logger.debug(f"📡 Отправка GET запроса к API...")
            response = self.session.get(
                self.url,
                timeout=(10, 30),  # (connect_timeout, read_timeout)
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                }
            )

            logger.info(f"✅ Ответ получен: статус {response.status_code}")
            response.raise_for_status()

            logger.debug(f"📦 Парсинг JSON ответа...")
            data = response.json()
            logger.info(f"✅ JSON успешно распарсен")

            # Автоматически находим промоакции в JSON
            logger.info(f"🔍 Поиск объектов-промоакций в JSON структуре...")
            all_items = self._find_all_objects(data)
            logger.info(f"📊 Найдено {len(all_items)} потенциальных объектов-промоакций")

            promotions = []

            for i, item in enumerate(all_items, 1):
                logger.debug(f"🔍 [{i}/{len(all_items)}] Обработка объекта...")
                promo = self._create_promo_from_object(item)
                if promo:
                    logger.debug(f"   ✅ Создана промоакция: {promo.get('title', 'Без названия')}")
                    promotions.append(promo)
                else:
                    logger.debug(f"   ⏭️ Объект не прошел валидацию")

            logger.info(f"✅ UniversalParser (API): Найдено {len(promotions)} валидных промоакций")
            for i, promo in enumerate(promotions[:10], 1):
                logger.info(f"   {i}. {promo.get('title', 'Без названия')} (ID: {promo.get('promo_id', 'N/A')})")
            if len(promotions) > 10:
                logger.info(f"   ... и еще {len(promotions) - 10} промоакций")

            return promotions

        except requests.exceptions.Timeout:
            logger.error(f"⏰ ТАЙМАУТ при запросе к API: {self.url}")
            logger.error(f"   Проверьте доступность API или увеличьте таймаут")
            return []
        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔌 ОШИБКА СОЕДИНЕНИЯ с API: {self.url}")
            logger.error(f"   Детали: {e}")
            return []
        except requests.exceptions.HTTPError as e:
            logger.error(f"🌐 HTTP ОШИБКА при запросе к API: {e.response.status_code}")
            logger.error(f"   URL: {self.url}")
            logger.error(f"   Ответ сервера: {e.response.text[:200]}...")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"❌ ОШИБКА ПАРСИНГА JSON от API: {self.url}")
            logger.error(f"   Детали: {e}")
            logger.error(f"   Возможно, API вернул HTML вместо JSON")
            return []
        except Exception as e:
            logger.error(f"❌ НЕОЖИДАННАЯ ОШИБКА при парсинге API: {self.url}")
            logger.error(f"   Детали: {e}", exc_info=True)
            return []

    def _find_all_objects(self, data: Any, depth: int = 0) -> List[Dict]:
        """Рекурсивно находит все объекты в JSON структуре"""
        objects = []

        if depth > 5:  # Защита от бесконечной рекурсии
            return objects

        if isinstance(data, dict):
            # Если у объекта есть поля похожие на промоакцию - добавляем
            if self._has_promo_fields(data):
                objects.append(data)

            # Рекурсивно проверяем все значения
            for value in data.values():
                objects.extend(self._find_all_objects(value, depth + 1))

        elif isinstance(data, list):
            # Обрабатываем каждый элемент массива
            for item in data:
                objects.extend(self._find_all_objects(item, depth + 1))

        return objects

    def _has_promo_fields(self, obj: Dict) -> bool:
        """Проверяет, похож ли объект на промоакцию"""
        promo_keywords = [
            'name', 'title', 'description', 'reward', 'prize', 'token',
            'start', 'end', 'url', 'link', 'id', 'code', 'campaign',
            'promotion', 'activity', 'event', 'launchpad', 'staking'
        ]

        # Считаем сколько промо-ключей есть в объекте
        promo_keys_count = sum(1 for key in obj.keys() if any(kw in key.lower() for kw in promo_keywords))

        # Если есть хотя бы 3 промо-ключа, считаем это промоакцией
        return promo_keys_count >= 3

    def _create_promo_from_object(self, obj: Dict) -> Dict[str, Any]:
        """Создает стандартизированную промоакцию из любого объекта"""
        try:
            # Автоматически определяем название из домена URL
            exchange_name = self._extract_domain_name(self.url)

            promo_data = {
                'exchange': exchange_name,
                'promo_id': self.extract_promo_id(obj),
                'title': self._get_value(obj, ['name', 'title', 'campaignName', 'activityName', 'projectName']),
                'description': self._get_value(obj, ['description', 'desc', 'details', 'info', 'introduction']),
                'total_prize_pool': self._get_value(obj, ['totalPrizePool', 'reward', 'prize', 'amount', 'prizePool', 'totalReward']),
                'award_token': self._get_value(obj, ['awardToken', 'token', 'coin', 'symbol', 'currency', 'rewardToken']),
                'participants_count': self._get_value(obj, ['participants', 'users', 'joiners', 'totalUsers']),
                'start_time': self._get_value(obj, ['startTime', 'start', 'startDate', 'beginTime', 'openTime']),
                'end_time': self._get_value(obj, ['endTime', 'end', 'endDate', 'expireTime', 'closeTime']),
                'link': self._get_value(obj, ['campaignUrl', 'url', 'link', 'detailUrl', 'jumpUrl', 'joinUrl']),
                'icon': self._get_value(obj, ['tokenIcon', 'iconUrl', 'icon', 'imageUrl', 'logo']),
                'raw_data': obj  # Сохраняем исходные данные
            }

            # Очищаем None значения
            promo_data = {k: v for k, v in promo_data.items() if v is not None}

            # Если нет хотя бы title или description - не считаем промоакцией
            if not promo_data.get('title') and not promo_data.get('description'):
                return None

            return promo_data

        except Exception as e:
            logger.warning(f"Не удалось создать промоакцию из объекта: {e}")
            return None

    def _get_value(self, obj: Dict, keys: List[str]) -> Any:
        """Получает значение по первому найденному ключу (регистронезависимо)"""
        obj_lower = {k.lower(): v for k, v in obj.items()}

        for key in keys:
            key_lower = key.lower()
            if key_lower in obj_lower:
                return obj_lower[key_lower]
        return None

    def _extract_domain_name(self, url: str) -> str:
        """Извлекает название из домена URL (универсально для любой биржи)"""
        import re
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # Убираем www и извлекаем основное название
            domain = domain.replace('www.', '')
            main_name = domain.split('.')[-2]  # Берем предпоследнюю часть

            # Красивое форматирование
            if main_name == 'bybit':
                return 'Bybit'
            elif main_name == 'binance':
                return 'Binance'
            elif main_name == 'gate':
                return 'Gate.io'
            elif main_name == 'mexc':
                return 'MEXC'
            else:
                return main_name.title()

        except:
            return 'Unknown'