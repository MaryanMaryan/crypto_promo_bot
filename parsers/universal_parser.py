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
        """Получает промоакции из любого JSON API с retry логикой при блокировках"""
        import time as time_module
        max_retries = 3
        retry_delay = 2  # секунд между попытками
        
        # Извлекаем exchange из URL для инвалидации кеша
        exchange = self._extract_exchange_from_url(self.url)
        
        # Сначала пробуем с прокси
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"🔍 UniversalParser (API): Попытка {attempt}/{max_retries} (с прокси)")
                logger.info(f"   URL: {self.url}")

                # При повторных попытках принудительно инвалидируем кеш прокси
                if attempt > 1:
                    logger.info(f"🔄 Инвалидация кеша прокси для {exchange} перед попыткой {attempt}")
                    self.rotation_manager.invalidate_cache_for_exchange(exchange)

                headers = self._build_headers(exchange)
                response = self.make_request(self.url, headers=headers, timeout=(10, 30))

                if response and response.status_code == 200:
                    logger.info(f"✅ Ответ получен: статус {response.status_code}")
                    data = response.json()
                    logger.info(f"✅ JSON успешно распарсен")
                    return self.parse_json_data(data)
                
                # Неуспешный ответ - retry
                if response:
                    logger.warning(f"⚠️ Код ответа: {response.status_code}")
                else:
                    logger.error(f"❌ Не удалось получить ответ от API")
                
                if attempt < max_retries:
                    logger.info(f"🔄 Повторная попытка через {retry_delay} сек...")
                    time_module.sleep(retry_delay)
                    retry_delay *= 1.5

            except Exception as e:
                logger.error(f"❌ Ошибка при попытке {attempt}: {e}")
                if attempt < max_retries:
                    time_module.sleep(retry_delay)
                    retry_delay *= 1.5

        # Все попытки с прокси неудачны - пробуем FALLBACK без прокси
        logger.info(f"🔄 Все {max_retries} попыток с прокси неудачны, ждём 3 сек и пробуем БЕЗ прокси...")
        import time as time_module
        time_module.sleep(3)  # Пауза перед fallback для сброса rate limiting
        
        try:
            headers = self._build_headers(exchange)
            logger.info(f"📡 FALLBACK: Прямой запрос без прокси...")
            response = requests.get(self.url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"✅ FALLBACK успешен: статус {response.status_code}")
                data = response.json()
                return self.parse_json_data(data)
            else:
                logger.error(f"❌ FALLBACK неудачен: код {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"❌ FALLBACK ошибка: {e}")
            return []

    def _build_headers(self, exchange: str) -> dict:
        """Строит headers для запроса в зависимости от биржи"""
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'cache-control': 'no-cache',
        }
        
        # Для Gate.io/Gate.com НЕ добавляем User-Agent (они блокируют с UA)
        if exchange != 'gate':
            headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            headers['sec-ch-ua'] = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
            headers['sec-ch-ua-mobile'] = '?0'
            headers['sec-ch-ua-platform'] = '"Windows"'
        
        # Специальные заголовки для Bybit (Akamai WAF требует sec-fetch-*)
        if exchange == 'bybit':
            headers.update({
                'Referer': 'https://www.bybit.com/en/trade/spot/token-splash',
                'Origin': 'https://www.bybit.com',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
            })
        
        # Специальные заголовки для MEXC Launchpad
        if exchange == 'mexc':
            headers.update({
                'Referer': 'https://www.mexc.com/ru-RU/launchpad',
                'Origin': 'https://www.mexc.com',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
            })
        
        return headers

    def parse_json_data(self, data: Any) -> List[Dict[str, Any]]:
        """Публичный метод для парсинга готового JSON данных (для использования в browser_parser)"""
        try:
            # Проверяем, является ли это OKX Boost API
            if self._is_okx_boost_data(data):
                logger.info(f"🎯 Обнаружен OKX Boost API, используем специализированный парсер")
                return self._parse_okx_boost(data)
            
            # Проверяем, является ли это MEXC Launchpad API
            if self._is_mexc_launchpad_data(data):
                logger.info(f"🎯 Обнаружен MEXC Launchpad API, используем специализированный парсер")
                return self._parse_mexc_launchpad(data)
            
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
                    'rewardAmount', 'totalAmount', 'poolSize',
                    'total_rewards'  # Gate.io CandyDrop
                ]),
                # Prize pool USD (Gate.io CandyDrop и др.)
                'total_prize_pool_usd': self._get_value(obj, [
                    'total_rewards_usdt', 'totalRewardsUsdt', 'prizePoolUsdt', 
                    'totalAmountUsdt', 'poolValueUsd'
                ]),
                # Max reward per user (Gate.io CandyDrop и др.)
                'user_max_rewards': self._get_value(obj, [
                    'user_max_rewards', 'userMaxRewards', 'maxRewardPerUser',
                    'perUserMaxReward', 'maxPrize'
                ]),
                'user_max_rewards_usd': self._get_value(obj, [
                    'user_max_rewards_usdt', 'userMaxRewardsUsdt', 'maxRewardPerUserUsdt'
                ]),
                # Exchange rate (Gate.io CandyDrop)
                'exchange_rate': self._get_value(obj, [
                    'exchange_rate', 'exchangeRate', 'price', 'tokenPrice', 'rate'
                ]),
                # Conditions/Rules (Gate.io CandyDrop rule_name)
                'conditions': self._get_value(obj, [
                    'rule_name', 'ruleName', 'rules', 'conditions', 'requirements',
                    'participationRules', 'eligibility'
                ]),
                # Phase/Wave number (Gate.io CandyDrop)
                'phase': self._get_value(obj, [
                    'phase', 'wave', 'round', 'batch', 'period'
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
                # Time (расширенный поиск для Bybit)
                'start_time': self._get_value(obj, [
                    'startTime', 'start', 'startDate', 'beginTime', 'openTime',
                    'startTimestamp', 'beginTimestamp',
                    'depositStart', 'applyStart'  # Bybit Token Splash
                ]),
                'end_time': self._get_value(obj, [
                    'endTime', 'end', 'endDate', 'expireTime', 'closeTime',
                    'endTimestamp', 'expireTimestamp',
                    'depositEnd', 'applyEnd'  # Bybit Token Splash
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
                # НОВЫЕ ПОЛЯ ДЛЯ ДЕТАЛЬНОЙ ИНФОРМАЦИИ (Bybit и др.)
                'winners_count': self._get_value(obj, [
                    'winnersCount', 'winners', 'prizeCount', 'rewardCount',
                    'totalWinners', 'luckyCount', 'winnerCount'
                ]),
                'reward_per_winner': self._get_value(obj, [
                    'rewardPerWinner', 'prizePerUser', 'amountPerWinner',
                    'rewardAmount', 'perUserReward', 'unitPrize'
                ]),
                'status': self._get_value(obj, [
                    'status', 'state', 'taskStatus', 'projectStatus',
                    'activityStatus', 'activity_status', 'campaignStatus'  # activity_status для Gate.io CandyDrop
                ]),
                'reward_type': self._get_value(obj, [
                    'rewardType', 'prizeType', 'awardType', 'distributionType',
                    'reward_type'  # Gate.io CandyDrop (это массив!)
                ]),
                'task_type': self._get_value(obj, [
                    'taskType', 'activityType', 'campaignType', 'type'
                ]),
                'publish_time': self._get_value(obj, [
                    'publishTime', 'announceTime', 'resultTime', 'drawTime'
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
            elif main_name == 'okx' or main_name == 'web3':
                return 'OKX'
            else:
                return main_name.title()

        except:
            return 'Unknown'

    def _is_okx_boost_data(self, data: Any) -> bool:
        """Проверяет, является ли это данными OKX Boost API"""
        if not isinstance(data, dict):
            return False
        
        # OKX Boost API имеет структуру: {"code": 0, "data": {"pools": [...]}}
        if 'code' in data and 'data' in data:
            inner_data = data.get('data', {})
            if isinstance(inner_data, dict) and 'pools' in inner_data:
                pools = inner_data.get('pools', [])
                if pools and isinstance(pools, list) and len(pools) > 0:
                    first_pool = pools[0]
                    # Проверяем характерные поля OKX Boost
                    return (
                        'navName' in first_pool and 
                        'homeName' in first_pool and 
                        'times' in first_pool
                    )
        return False

    def _parse_okx_boost(self, data: dict) -> List[Dict[str, Any]]:
        """
        Специализированный парсер для OKX Boost (X Launch) API
        
        Структура API:
        {
            "code": 0,
            "data": {
                "pools": [
                    {
                        "id": 438,
                        "name": "Sport.Fun X Launch",
                        "homeName": "Sport.Fun",
                        "navName": "sportfun",
                        "participants": 20420,
                        "reward": {"amount": 4000000, "chainId": 8453, "token": "FUN"},
                        "status": 2,  // 2=активный, 4=скоро, 5=завершен
                        "times": {...},
                        "tokenDesc": "...",
                        "tokenLogo": "..."
                    }
                ]
            }
        }
        """
        promotions = []
        
        try:
            pools = data.get('data', {}).get('pools', [])
            logger.info(f"📊 OKX Boost: найдено {len(pools)} launchpool'ов")
            
            for pool in pools:
                try:
                    pool_id = pool.get('id')
                    status = pool.get('status', 0)
                    
                    # Определяем статус
                    # status: 2=ongoing (активный), 4=upcoming (скоро), 5=ended (завершен)
                    if status == 2:
                        status_str = 'ongoing'
                    elif status == 4:
                        status_str = 'upcoming'
                    elif status == 5:
                        status_str = 'ended'
                    else:
                        status_str = 'unknown'
                    
                    # Данные о награде
                    reward = pool.get('reward', {})
                    reward_amount = reward.get('amount', 0)
                    reward_token = reward.get('token', '')
                    chain_id = reward.get('chainId', 0)
                    
                    # Определяем сеть по chainId
                    chain_names = {
                        1: 'Ethereum',
                        56: 'BNB Chain',
                        137: 'Polygon',
                        8453: 'Base',
                        42161: 'Arbitrum',
                        784: 'Sui',
                        501: 'Solana',
                        9745: 'Plasma',
                        59144: 'Linea'
                    }
                    chain_name = chain_names.get(chain_id, f'Chain {chain_id}')
                    
                    # Временные метки
                    times = pool.get('times', {})
                    join_start = times.get('joinStartTime')
                    join_end = times.get('joinEndTime')
                    claim_start = times.get('claimStartTime')
                    claim_end = times.get('claimEndTime')
                    end_time = times.get('endTime')
                    
                    # Генерация ссылки
                    nav_name = pool.get('navName', '')
                    link = f"https://web3.okx.com/ua/boost/x-launch/{nav_name}" if nav_name else None
                    
                    promo = {
                        'exchange': 'OKX',
                        'promo_id': f"okx_boost_{pool_id}",
                        'title': pool.get('name', ''),
                        'home_name': pool.get('homeName', ''),
                        'description': pool.get('tokenDesc', ''),
                        'award_token': reward_token,
                        'total_prize_pool': reward_amount,
                        'total_prize_pool_formatted': f"{reward_amount:,.0f} {reward_token}",
                        'chain_id': chain_id,
                        'chain_name': chain_name,
                        'participants_count': pool.get('participants', 0),
                        'status': status_str,
                        'status_code': status,
                        # Временные метки для OKX Boost
                        'join_start_time': join_start,
                        'join_end_time': join_end,
                        'claim_start_time': claim_start,
                        'claim_end_time': claim_end,
                        'start_time': join_start,  # Для совместимости
                        'end_time': end_time,
                        # Ссылки и изображения
                        'link': link,
                        'nav_name': nav_name,
                        'icon': pool.get('tokenLogo', ''),
                        'banner': pool.get('banner', ''),
                        'pc_banner': pool.get('pcBanner', ''),
                        # Тип промоакции
                        'promo_type': 'okx_boost',
                        'reward_mode': pool.get('rewardMode', 0),
                        # Сырые данные для отладки
                        'raw_data': pool
                    }
                    
                    promotions.append(promo)
                    logger.debug(f"   ✅ {promo['title']} ({status_str}) - {reward_amount:,.0f} {reward_token}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка парсинга OKX Boost pool: {e}")
                    continue
            
            # Сортируем: сначала активные, потом upcoming, потом ended
            status_order = {'ongoing': 0, 'upcoming': 1, 'ended': 2, 'unknown': 3}
            promotions.sort(key=lambda x: status_order.get(x.get('status', 'unknown'), 3))
            
            logger.info(f"✅ OKX Boost: успешно распарсено {len(promotions)} launchpool'ов")
            
            # Логируем статистику по статусам
            ongoing = sum(1 for p in promotions if p.get('status') == 'ongoing')
            upcoming = sum(1 for p in promotions if p.get('status') == 'upcoming')
            ended = sum(1 for p in promotions if p.get('status') == 'ended')
            logger.info(f"   📊 Активных: {ongoing}, Скоро: {upcoming}, Завершенных: {ended}")
            
            return promotions
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга OKX Boost: {e}", exc_info=True)
            return []

    def _is_mexc_launchpad_data(self, data: Any) -> bool:
        """Проверяет, является ли это данными MEXC Launchpad API"""
        if not isinstance(data, dict):
            return False
        
        # MEXC Launchpad API имеет структуру: {"code": 0, "data": {"launchpads": [...]}}
        if 'code' in data and 'data' in data:
            inner_data = data.get('data', {})
            if isinstance(inner_data, dict) and 'launchpads' in inner_data:
                launchpads = inner_data.get('launchpads', [])
                if launchpads and isinstance(launchpads, list) and len(launchpads) > 0:
                    first = launchpads[0]
                    # Проверяем характерные поля MEXC Launchpad
                    return (
                        'activityCoin' in first and 
                        'launchpadTakingCoins' in first and
                        'activityStatus' in first
                    )
        return False

    def _parse_mexc_launchpad(self, data: dict) -> List[Dict[str, Any]]:
        """
        Специализированный парсер для MEXC Launchpad API
        
        Структура API:
        {
            "code": 0,
            "data": {
                "launchpads": [
                    {
                        "id": 42,
                        "activityCoin": "LIT",
                        "activityCoinFullName": "Lighter",
                        "activityStatus": "FINISHED",  // FINISHED, ONGOING, NOT_STARTED
                        "totalSupply": "17500",
                        "startTime": 1766577600000,
                        "endTime": 1767175200000,
                        "launchpadTakingCoins": [
                            {
                                "joinNum": 529,  // Участники
                                "takingPrice": "1.6",
                                "supply": "12500",
                                ...
                            }
                        ]
                    }
                ]
            }
        }
        """
        from datetime import datetime
        promotions = []
        
        try:
            launchpads = data.get('data', {}).get('launchpads', [])
            logger.info(f"📊 MEXC Launchpad: найдено {len(launchpads)} проектов")
            
            for lp in launchpads:
                try:
                    lp_id = lp.get('id') or lp.get('launchpadId')
                    activity_status = lp.get('activityStatus', 'UNKNOWN')
                    
                    # Определяем статус
                    status_map = {
                        'ONGOING': 'ongoing',
                        'NOT_STARTED': 'upcoming',
                        'FINISHED': 'ended',
                        'SUBSCRIBE': 'ongoing',  # Подписка открыта
                        'SETTLED': 'ended',
                        'CANCELLED': 'ended'
                    }
                    status_str = status_map.get(activity_status, 'unknown')
                    
                    # Название токена
                    token = lp.get('activityCoin', '')
                    token_full_name = lp.get('activityCoinFullName', token)
                    
                    # Собираем участников из всех takingCoins
                    taking_coins = lp.get('launchpadTakingCoins', [])
                    total_participants = 0
                    total_supply_value = 0
                    min_price = None
                    max_discount = None
                    
                    for tc in taking_coins:
                        join_num = tc.get('joinNum', 0)
                        if join_num:
                            total_participants += int(join_num)
                        
                        # Ищем максимальную скидку
                        label = tc.get('label', '')
                        if label and 'Off' in label:
                            try:
                                discount = int(label.replace('% Off', '').replace('%', '').strip())
                                if max_discount is None or discount > max_discount:
                                    max_discount = discount
                            except:
                                pass
                        
                        # Минимальная цена покупки
                        taking_price = tc.get('takingPrice')
                        if taking_price:
                            try:
                                price = float(taking_price)
                                if min_price is None or price < min_price:
                                    min_price = price
                            except:
                                pass
                        
                        # Supply
                        supply = tc.get('supply')
                        if supply:
                            try:
                                total_supply_value += float(supply)
                            except:
                                pass
                    
                    # Общий supply из основного поля
                    total_supply = lp.get('totalSupply', total_supply_value)
                    
                    # Временные метки (в миллисекундах)
                    start_time = lp.get('startTime')
                    end_time = lp.get('endTime')
                    
                    # Конвертируем в datetime
                    start_dt = None
                    end_dt = None
                    if start_time:
                        try:
                            start_dt = datetime.fromtimestamp(start_time / 1000)
                        except:
                            pass
                    if end_time:
                        try:
                            end_dt = datetime.fromtimestamp(end_time / 1000)
                        except:
                            pass
                    
                    # Ссылки на проект
                    official_url = lp.get('officialUrl', '')
                    twitter_url = lp.get('twitterUrl', '')
                    
                    # Генерация ссылки на MEXC Launchpad
                    link = f"https://www.mexc.com/ru-RU/launchpad/{lp_id}" if lp_id else "https://www.mexc.com/ru-RU/launchpad"
                    
                    # Рыночная цена для сравнения
                    market_price = None
                    if taking_coins and taking_coins[0].get('marketPrice'):
                        try:
                            market_price = float(taking_coins[0]['marketPrice'])
                        except:
                            pass
                    
                    # Описание со скидкой
                    description = ''
                    if max_discount:
                        description = f"До {max_discount}% скидки от рыночной цены"
                    if min_price and market_price and market_price > 0:
                        if not description:
                            discount_calc = ((market_price - min_price) / market_price) * 100
                            description = f"Цена от ${min_price} (рынок: ${market_price})"
                    
                    promo = {
                        'exchange': 'MEXC',
                        'promo_id': f"mexc_launchpad_{lp_id}",
                        'title': f"{token_full_name} ({token})" if token_full_name != token else token,
                        'description': description or lp.get('introduction', ''),
                        'award_token': token,
                        'total_prize_pool': total_supply,
                        'participants_count': total_participants,
                        'status': status_str,
                        'activity_status': activity_status,  # Оригинальный статус
                        'start_time': start_dt,
                        'end_time': end_dt,
                        'start_timestamp': start_time,
                        'end_timestamp': end_time,
                        'link': link,
                        'icon': lp.get('logoUrl', ''),
                        'official_url': official_url,
                        'twitter_url': twitter_url,
                        # Дополнительные данные
                        'min_price': min_price,
                        'market_price': market_price,
                        'max_discount': max_discount,
                        'promo_type': 'mexc_launchpad',
                        'is_ipo': lp.get('ipo', False),
                        'taking_coins_count': len(taking_coins),
                        'raw_data': lp
                    }
                    
                    promotions.append(promo)
                    logger.debug(f"   ✅ {promo['title']} ({status_str}) - {total_participants} участников")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка парсинга MEXC Launchpad: {e}")
                    continue
            
            # Сортируем: сначала активные, потом upcoming, потом ended
            status_order = {'ongoing': 0, 'upcoming': 1, 'ended': 2, 'unknown': 3}
            promotions.sort(key=lambda x: status_order.get(x.get('status', 'unknown'), 3))
            
            logger.info(f"✅ MEXC Launchpad: успешно распарсено {len(promotions)} проектов")
            
            # Логируем статистику по статусам
            ongoing = sum(1 for p in promotions if p.get('status') == 'ongoing')
            upcoming = sum(1 for p in promotions if p.get('status') == 'upcoming')
            ended = sum(1 for p in promotions if p.get('status') == 'ended')
            logger.info(f"   📊 Активных: {ongoing}, Скоро: {upcoming}, Завершенных: {ended}")
            
            return promotions
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга MEXC Launchpad: {e}", exc_info=True)
            return []