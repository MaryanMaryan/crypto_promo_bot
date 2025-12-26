import json
import logging
import hashlib
import requests
from typing import List, Dict, Any
from .base_parser import BaseParser
from utils.url_template_builder import get_url_builder

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

            # УЛУЧШЕННЫЙ fallback: хэш СТАБИЛЬНЫХ полей (не всего объекта)
            # Собираем только стабильные поля для хэширования
            stable_fields = {}

            # Приоритетные поля для хэша
            stable_field_keys = [
                'name', 'title', 'token', 'currency', 'symbol',
                'description', 'desc', 'amount', 'reward',
                'url', 'link', 'startTime', 'endTime'
            ]

            for key in stable_field_keys:
                value = self._get_value(obj, [key])
                if value and str(value).strip():
                    stable_fields[key] = str(value).strip()

            # Если есть хоть какие-то стабильные поля - используем их
            if stable_fields:
                # Сортируем ключи для стабильности
                sorted_items = sorted(stable_fields.items())
                stable_string = "_".join([f"{k}:{v}" for k, v in sorted_items])
                fallback_hash = hashlib.md5(stable_string.encode('utf-8')).hexdigest()[:12]

                logger.debug(f"🔑 Создан улучшенный fallback ID из полей: {list(stable_fields.keys())}")
                return f"{exchange_name}_fallback_{fallback_hash}"

            # Если вообще нет стабильных полей - возвращаем None
            # Такой объект не должен становиться промоакцией
            logger.warning(
                f"⚠️ Объект не содержит стабильных полей для создания ID. "
                f"Доступные ключи: {list(obj.keys())[:10]}"
            )
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка создания ID: {e}")
            return f"{self._extract_domain_name(self.url).lower()}_error_{hash(str(obj))}"

    def get_promotions(self) -> List[Dict[str, Any]]:
        """Получает промоакции из любого JSON API"""
        try:
            logger.info(f"🔍 UniversalParser (API): Начало парсинга")
            logger.info(f"   URL: {self.url}")

            # Используем make_request из BaseParser для поддержки прокси и ротации
            logger.debug(f"📡 Отправка GET запроса к API через систему ротации...")

            # Улучшенные реалистичные headers для обхода защиты
            # Имитируем запрос от реального браузера (на основе успешных запросов)
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Connection': 'keep-alive',
                'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'priority': 'u=0, i',
                'cache-control': 'max-age=0',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
            }

            response = self.make_request(self.url, headers=headers, timeout=(10, 30))

            if not response:
                logger.error(f"❌ Не удалось получить ответ от API")
                return []

            logger.info(f"✅ Ответ получен: статус {response.status_code}")
            response.raise_for_status()

            logger.debug(f"📦 Парсинг JSON ответа...")
            data = response.json()
            logger.info(f"✅ JSON успешно распарсен")

            # Используем публичный метод для парсинга JSON
            return self.parse_json_data(data)

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

    def parse_json_data(self, data: Any) -> List[Dict[str, Any]]:
        """Публичный метод для парсинга готового JSON данных (для использования в browser_parser)"""
        try:
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

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга JSON данных: {e}", exc_info=True)
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
        if not isinstance(obj, dict):
            return False

        # РАСШИРЕННЫЙ список ключевых слов для разных бирж
        promo_keywords = [
            # Общие поля
            'name', 'title', 'description', 'reward', 'prize', 'token',
            'start', 'end', 'url', 'link', 'id', 'code', 'campaign',
            'promotion', 'activity', 'event', 'launchpad', 'staking',
            'coin', 'symbol', 'amount', 'pool', 'time', 'date',
            # Специфичные поля Gate.io
            'currency', 'participants', 'icon', 'status', 'phase',
            'registered', 'rewards', 'exchange', 'lottery', 'rule',
            # Дополнительные поля для других бирж
            'airdrop', 'candydrop', 'trading', 'snapshot', 'allocation'
        ]

        # Считаем сколько промо-ключей есть в объекте
        promo_keys_count = sum(1 for key in obj.keys() if any(kw in key.lower() for kw in promo_keywords))

        # Если есть хотя бы 2 промо-ключа, считаем это промоакцией
        return promo_keys_count >= 2

    def _create_promo_from_object(self, obj: Dict) -> Dict[str, Any]:
        """Создает стандартизированную промоакцию из любого объекта"""
        try:
            # Автоматически определяем название из домена URL
            exchange_name = self._extract_domain_name(self.url)

            # ФИЛЬТР ДЛЯ MEXC: пропускаем подпромоакции из массива eftdVOS
            # Основные промоакции MEXC всегда имеют activityCurrency или activityCurrencyFullName
            if exchange_name == 'MEXC':
                has_activity_currency = self._get_value(obj, ['activityCurrency', 'activityCurrencyFullName'])
                if not has_activity_currency:
                    logger.debug("⏭️ Пропускаем MEXC подпромоакцию (нет activityCurrency)")
                    return None

            # ВАЖНО: Сначала создаем promo_id
            promo_id = self.extract_promo_id(obj)

            # Если не удалось создать стабильный ID - не создаем промоакцию
            if not promo_id:
                logger.debug("⏭️ Пропускаем объект: не удалось создать стабильный promo_id")
                return None

            # Универсальный маппинг полей для всех бирж
            promo_data = {
                'exchange': exchange_name,
                'promo_id': promo_id,
                # Title: ищем в максимально широком списке (Bybit, MEXC, Binance, Gate.io и др.)
                'title': self._get_value(obj, [
                    'name', 'title', 'campaignName', 'activityName', 'projectName',
                    'activityCurrencyFullName',  # MEXC: полное название токена промоакции
                    'tokenFullName', 'activityCoinFullName', 'coinFullName',  # Полные названия токенов
                    'eventName', 'promotionName', 'launchpadName'
                ]),
                # Description
                'description': self._get_value(obj, [
                    'description', 'desc', 'details', 'info', 'introduction',
                    'content', 'remark', 'note', 'summary'
                ]),
                # Prize pool
                'total_prize_pool': self._get_value(obj, [
                    'totalPrizePool', 'reward', 'prize', 'amount', 'prizePool', 'totalReward',
                    'rewardAmount', 'totalAmount', 'poolSize'
                ]),
                # Award token: расширенный список для разных бирж
                'award_token': self._get_value(obj, [
                    'activityCurrency',  # MEXC: символ токена промоакции
                    'token', 'coin', 'symbol', 'currency',  # Общие
                    'activityCoin', 'awardToken', 'rewardToken',  # MEXC, Binance
                    'tradeCoin', 'targetCoin', 'assetSymbol',  # Gate.io, OKX
                    'currencyId', 'coinSymbol', 'tokenSymbol'  # Другие биржи
                ]),
                # Participants
                'participants_count': self._get_value(obj, [
                    'participants', 'users', 'joiners', 'totalUsers',
                    'participantCount', 'userCount', 'joinedUsers'
                ]),
                # Time
                'start_time': self._get_value(obj, [
                    'startTime', 'start', 'startDate', 'beginTime', 'openTime',
                    'startTimestamp', 'beginTimestamp'
                ]),
                'end_time': self._get_value(obj, [
                    'endTime', 'end', 'endDate', 'expireTime', 'closeTime',
                    'endTimestamp', 'expireTimestamp'
                ]),
                # Links
                'link': self._get_value(obj, [
                    'url', 'link', 'detailUrl', 'jumpUrl', 'joinUrl',
                    'campaignUrl', 'activityUrl', 'projectUrl', 'href'
                ]),
                # Icon/Image
                'icon': self._get_value(obj, [
                    'icon', 'iconUrl', 'imageUrl', 'logo', 'logoUrl',
                    'tokenIcon', 'coinIcon', 'img', 'image', 'thumbnail'
                ]),
                # Дополнительные поля для генерации URL
                'navName': self._get_value(obj, [
                    'navName', 'slug', 'projectSlug', 'projectCode', 'code'
                ]),
                'homeName': self._get_value(obj, [
                    'homeName', 'shortName', 'projectShortName'
                ]),
                'raw_data': obj  # Сохраняем исходные данные
            }

            # Очищаем None значения
            promo_data = {k: v for k, v in promo_data.items() if v is not None}

            # Минимальная валидация: должен быть хотя бы title или любое поле кроме raw_data
            fields_count = len([k for k in promo_data.keys() if k not in ['raw_data', 'exchange', 'promo_id']])

            if fields_count < 1:
                return None

            # Если нет title - пытаемся создать его из других полей
            if not promo_data.get('title'):
                # Приоритет 1: токен + биржа
                if promo_data.get('award_token'):
                    token = promo_data['award_token']
                    exchange = promo_data.get('exchange', 'Promotion')
                    promo_data['title'] = f"{token} {exchange} Promotion"

                # Приоритет 2: описание (первые 50 символов)
                elif promo_data.get('description'):
                    desc = promo_data['description']
                    promo_data['title'] = desc[:50] + ('...' if len(desc) > 50 else '')

                # Приоритет 3: название биржи + ID
                else:
                    exchange = promo_data.get('exchange', 'Unknown')
                    promo_id = promo_data.get('promo_id', 'N/A')
                    promo_data['title'] = f"{exchange} Promo {promo_id}"

            # ========================================================================
            # НОРМАЛИЗАЦИЯ СЛОЖНЫХ ПОЛЕЙ ДЛЯ БД
            # ========================================================================
            # Преобразуем словари в простые типы для совместимости с SQLite

            # Нормализация total_prize_pool
            if promo_data.get('total_prize_pool') and isinstance(promo_data['total_prize_pool'], dict):
                prize_pool = promo_data['total_prize_pool']
                # Пытаемся извлечь значение из словаря
                if 'amount' in prize_pool:
                    amount = prize_pool['amount']
                    token = prize_pool.get('token', '')
                    # Форматируем как "4000000 MLC"
                    promo_data['total_prize_pool'] = f"{amount} {token}".strip()
                else:
                    # Если нет amount, конвертируем весь словарь в JSON строку
                    promo_data['total_prize_pool'] = json.dumps(prize_pool, ensure_ascii=False)

            # Нормализация award_token
            if promo_data.get('award_token') and isinstance(promo_data['award_token'], dict):
                token_data = promo_data['award_token']
                # Пытаемся извлечь токен из словаря
                promo_data['award_token'] = (
                    token_data.get('token') or
                    token_data.get('symbol') or
                    token_data.get('currency') or
                    json.dumps(token_data, ensure_ascii=False)
                )

            # Нормализация participants_count
            if promo_data.get('participants_count') and isinstance(promo_data['participants_count'], dict):
                participants = promo_data['participants_count']
                # Пытаемся извлечь число из словаря
                promo_data['participants_count'] = (
                    participants.get('count') or
                    participants.get('total') or
                    participants.get('participants') or
                    str(participants)
                )

            # ========================================================================
            # АВТОМАТИЧЕСКАЯ ГЕНЕРАЦИЯ ССЫЛОК
            # ========================================================================
            # Если в API нет ссылки, пытаемся сгенерировать её используя шаблоны
            if not promo_data.get('link'):
                try:
                    url_builder = get_url_builder()
                    generated_link = url_builder.build_url(exchange_name, obj)

                    if generated_link:
                        promo_data['link'] = generated_link
                        logger.debug(f"✅ Ссылка сгенерирована автоматически: {generated_link}")
                    else:
                        logger.debug(f"⚠️ Не удалось сгенерировать ссылку для {exchange_name}")
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка генерации ссылки: {e}")

            return promo_data

        except Exception as e:
            logger.warning(f"Не удалось создать промоакцию из объекта: {e}")
            return None

    def _get_value(self, obj: Dict, keys: List[str]) -> Any:
        """Получает значение по первому найденному ключу (регистронезависимо)

        Пропускает ключи с None или пустыми значениями, чтобы найти первое валидное значение.
        """
        obj_lower = {k.lower(): v for k, v in obj.items()}

        for key in keys:
            key_lower = key.lower()
            if key_lower in obj_lower:
                value = obj_lower[key_lower]
                # Пропускаем None и пустые строки, ищем первое валидное значение
                if value is not None and str(value).strip():
                    return value
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