# parsers/weex_parser.py
"""
WEEX PARSER
Специальный парсер для Weex, использующий Playwright с перехватом API ответов.
Weex блокирует прямые API запросы через Cloudflare, поэтому нужно:
1. Загрузить HTML страницу для получения cookies
2. Перехватить API ответы при загрузке страницы
"""

import logging
import time
import hashlib
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, Response
from playwright_stealth import Stealth

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class WeexParser(BaseParser):
    """
    Парсер для Weex с перехватом API ответов через Playwright.
    Поддерживает:
    - token-airdrop (Airdrop Hub)
    - trade-to-earn (Mining activities)
    - rewards (All promotions/activities page)
    """

    # API endpoints для разных типов страниц
    API_ENDPOINTS = {
        'token-airdrop': 'spotMerge/detail',
        'trade-to-earn': 'activity/mining',
        'events': 'activity',
        'rewards': 'welfare/popular',
    }

    def __init__(self, url: str):
        super().__init__(url)
        self.exchange = 'weex'
        self._captured_data = {}

    def get_promotions(self) -> List[Dict[str, Any]]:
        """Основной метод парсинга Weex через Playwright с перехватом API"""
        try:
            logger.info(f"🌐 WeexParser: Начало парсинга")
            logger.info(f"   URL: {self.url}")

            # Определяем тип страницы
            page_type = self._detect_page_type()
            logger.info(f"   Тип страницы: {page_type}")

            # Получаем данные через Playwright
            raw_data = self._fetch_with_intercept(page_type)

            if not raw_data:
                logger.warning(f"⚠️ Не удалось получить данные с Weex")
                return []

            # Парсим данные в зависимости от типа
            if page_type == 'token-airdrop':
                promotions = self._parse_airdrop_data(raw_data)
            elif page_type == 'trade-to-earn':
                promotions = self._parse_mining_data(raw_data)
            elif page_type == 'rewards':
                promotions = self._parse_rewards_data(raw_data)
            else:
                promotions = self._parse_generic_data(raw_data)

            logger.info(f"✅ WeexParser: Найдено {len(promotions)} промоакций")
            return promotions

        except Exception as e:
            logger.error(f"❌ Ошибка WeexParser: {e}", exc_info=True)
            return []

    def _detect_page_type(self) -> str:
        """Определяет тип страницы по URL"""
        url_lower = self.url.lower()
        if '/rewards' in url_lower:
            return 'rewards'
        elif 'token-airdrop' in url_lower or 'airdrop' in url_lower:
            return 'token-airdrop'
        elif 'trade-to-earn' in url_lower or 'mining' in url_lower:
            return 'trade-to-earn'
        elif 'events' in url_lower or 'activity' in url_lower:
            return 'events'
        return 'token-airdrop'  # Default

    def _fetch_with_intercept(self, page_type: str) -> Optional[Dict]:
        """Загружает страницу и перехватывает API ответы"""
        playwright = None
        captured_data = {}
        
        try:
            playwright = sync_playwright().start()
            
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )

            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
            )

            page = context.new_page()

            # Применяем stealth
            stealth = Stealth()
            stealth.apply_stealth_sync(page)

            # Перехватчик ответов
            def handle_response(response: Response):
                url = response.url
                if response.status == 200 and 'application/json' in response.headers.get('content-type', ''):
                    try:
                        # Перехватываем нужные API ответы
                        target_endpoint = self.API_ENDPOINTS.get(page_type, '')
                        # Для rewards проверяем welfare/popular
                        if page_type == 'rewards':
                            if 'welfare/popular' in url:
                                data = response.json()
                                captured_data['popular'] = data
                                logger.debug(f"📦 Перехвачен API ответ: welfare/popular")
                        elif target_endpoint and target_endpoint in url:
                            data = response.json()
                            endpoint_key = url.split('?')[0].split('/')[-1]
                            captured_data[endpoint_key] = data
                            logger.debug(f"📦 Перехвачен API ответ: {endpoint_key}")
                    except Exception as e:
                        logger.debug(f"Не удалось распарсить JSON: {e}")

            page.on('response', handle_response)

            # Загружаем страницу
            logger.info(f"🔄 Загрузка страницы: {self.url}")
            start_time = time.time()
            page.goto(self.url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(5000)  # Ждём API запросы
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Страница загружена за {elapsed:.1f} сек")
            logger.info(f"📦 Перехвачено {len(captured_data)} API ответов")

            # Закрываем браузер
            context.close()
            browser.close()
            playwright.stop()
            playwright = None

            return captured_data

        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке страницы: {e}")
            return None
        finally:
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass

    def _parse_airdrop_data(self, raw_data: Dict) -> List[Dict[str, Any]]:
        """Парсит данные Airdrop Hub"""
        promotions = []
        now = int(time.time() * 1000)

        # Получаем данные из spotMerge/detail
        detail_data = raw_data.get('detail', {})
        if not detail_data:
            # Пробуем найти в любом ключе
            for key, value in raw_data.items():
                if isinstance(value, dict) and value.get('code') == '00000':
                    detail_data = value
                    break

        if not detail_data or detail_data.get('code') != '00000':
            logger.warning(f"⚠️ Некорректный ответ API: {detail_data.get('code') if detail_data else 'empty'}")
            return []

        data = detail_data.get('data', {})
        airdrops = data.get('singleInfoList', [])

        logger.info(f"📋 Найдено {len(airdrops)} airdrop событий в API")

        for airdrop in airdrops:
            try:
                end_time = airdrop.get('endTime', 0)
                start_time = airdrop.get('startTime', 0)
                
                # Пропускаем завершённые
                if end_time and end_time < now:
                    continue

                # Определяем статус
                if start_time > now:
                    status = 'upcoming'
                else:
                    status = 'ongoing'

                # Извлекаем токен из названия
                project_title = airdrop.get('projectTitle', '')
                token = project_title.split()[0] if project_title else ''
                
                # Очищаем название
                title = project_title.replace(' new user airdrop!', '').strip()
                if not title:
                    title = token

                # Создаём уникальный ID
                raw_id = airdrop.get('id') or airdrop.get('activityId') or airdrop.get('showUrl', '')
                promo_id = f"weex_airdrop_{raw_id}"

                # Формируем URL
                show_url = airdrop.get('showUrl', '')
                full_url = f"https://www.weex.com/token-airdrop/{show_url}" if show_url else ''

                promotion = {
                    'promo_id': promo_id,
                    'title': title,
                    'token': token,
                    'reward': airdrop.get('totalPrizePool', ''),
                    'participants': airdrop.get('applyNum', 0),
                    'startTime': start_time,
                    'endTime': end_time,
                    'url': full_url,
                    'status': status,
                    'type': 'airdrop',
                    'exchange': 'weex',
                    'icon': airdrop.get('projectIconUrl', ''),
                    'activityId': airdrop.get('activityId'),
                }

                promotions.append(promotion)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга airdrop: {e}")
                continue

        logger.info(f"✅ Отфильтровано {len(promotions)} активных airdrop")
        return promotions

    def _parse_mining_data(self, raw_data: Dict) -> List[Dict[str, Any]]:
        """Парсит данные Trade-to-Earn (Mining)"""
        promotions = []
        now = int(time.time() * 1000)

        # Ищем baseInfo данные
        base_info = None
        for key, value in raw_data.items():
            if isinstance(value, dict) and 'baseInfo' in key.lower():
                base_info = value.get('data', {})
                break

        if not base_info:
            logger.warning(f"⚠️ Не найдены данные mining")
            return []

        try:
            activity_id = base_info.get('activityId')
            end_time = base_info.get('endTime', 0)
            start_time = base_info.get('startTime', 0) if base_info.get('startTime') else now

            if end_time and end_time < now:
                return []

            status = 'upcoming' if start_time > now else 'ongoing'

            # Получаем информацию о наградах
            mining_info = base_info.get('mining', {})
            reward_rates = mining_info.get('miningRewardRate', [])
            max_rate = max([r.get('initialRatio', 0) for r in reward_rates]) if reward_rates else 0

            promotion = {
                'promo_id': f"weex_mining_{activity_id}",
                'title': 'Trade to Earn',
                'token': 'WXT',
                'reward': f'Up to {max_rate}% rebate' if max_rate else 'WXT Rewards',
                'startTime': start_time,
                'endTime': end_time,
                'url': 'https://www.weex.com/events/futures-trading/trade-to-earn',
                'status': status,
                'type': 'mining',
                'exchange': 'weex',
                'activityId': activity_id,
            }

            promotions.append(promotion)

        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга mining: {e}")

        return promotions

    def _parse_rewards_data(self, raw_data: Dict) -> List[Dict[str, Any]]:
        """Парсит данные страницы /rewards (welfare/popular API)"""
        promotions = []
        now = int(time.time() * 1000)

        # Ищем данные popular API
        popular_data = None
        for key, value in raw_data.items():
            if isinstance(value, dict) and value.get('code') == '00000' and value.get('data'):
                data = value.get('data')
                if isinstance(data, list) and len(data) > 0:
                    # Проверяем что это данные популярных активностей
                    first_item = data[0]
                    if 'activityUrl' in first_item or 'showUrl' in first_item or 'popularActivityType' in first_item:
                        popular_data = data
                        break

        if not popular_data:
            logger.warning(f"⚠️ Не найдены данные rewards/popular")
            return []

        logger.info(f"📋 Найдено {len(popular_data)} активностей в rewards API")

        for item in popular_data:
            try:
                # Получаем название и описание
                title = item.get('title', '')
                sub_title = item.get('subTitle', '')
                
                # Очищаем HTML теги из названия и описания
                title = self._clean_html(title)
                sub_title = self._clean_html(sub_title)
                
                if not title:
                    continue

                # Время начала и конца
                start_time = item.get('startTime')
                end_time = item.get('endTime')
                
                # Конвертируем строки в числа если нужно
                if isinstance(start_time, str):
                    start_time = int(start_time) if start_time.isdigit() else 0
                if isinstance(end_time, str):
                    end_time = int(end_time) if end_time.isdigit() else 0

                # Пропускаем завершённые (end_time < now)
                if end_time and end_time < now:
                    continue

                # Определяем статус
                if start_time and start_time > now:
                    status = 'upcoming'
                else:
                    status = 'ongoing'

                # Формируем URL
                activity_url = item.get('activityUrl', '')
                show_url = item.get('showUrl', '')
                
                if activity_url:
                    # Если URL уже полный
                    if activity_url.startswith('http'):
                        full_url = activity_url
                    else:
                        full_url = f"https://www.weex.com{activity_url}"
                elif show_url:
                    # Формируем URL на основе типа активности
                    activity_type = item.get('activityType')
                    popular_type = item.get('popularActivityType')
                    
                    if activity_type == 2:  # Trading competition
                        full_url = f"https://www.weex.com/events/trading-competition/{show_url}"
                    elif activity_type == 7 or popular_type == 4:  # Promo
                        full_url = f"https://www.weex.com/events/promo/{show_url}"
                    else:
                        full_url = f"https://www.weex.com/events/promo/{show_url}"
                else:
                    full_url = 'https://www.weex.com/rewards'

                # Создаём уникальный ID
                activity_id = item.get('activityId')
                if activity_id:
                    promo_id = f"weex_rewards_{activity_id}"
                else:
                    promo_id = f"weex_rewards_{hashlib.md5(title.encode()).hexdigest()[:12]}"

                promotion = {
                    'promo_id': promo_id,
                    'title': title,
                    'description': sub_title,
                    'startTime': start_time,
                    'endTime': end_time,
                    'url': full_url,
                    'status': status,
                    'type': 'rewards',
                    'exchange': 'weex',
                    'activityId': activity_id,
                    'activityType': item.get('activityType'),
                    'popularActivityType': item.get('popularActivityType'),
                }

                promotions.append(promotion)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга rewards item: {e}")
                continue

        logger.info(f"✅ Отфильтровано {len(promotions)} активных rewards")
        return promotions

    def _clean_html(self, text: str) -> str:
        """Очищает HTML теги из текста"""
        if not text:
            return ''
        import re
        # Удаляем HTML теги
        clean = re.sub(r'<[^>]+>', '', str(text))
        # Удаляем лишние пробелы
        clean = ' '.join(clean.split())
        return clean.strip()

    def _parse_generic_data(self, raw_data: Dict) -> List[Dict[str, Any]]:
        """Парсит generic данные активностей"""
        promotions = []
        
        for key, value in raw_data.items():
            if isinstance(value, dict) and value.get('data'):
                data = value.get('data')
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            promo = self._convert_to_promotion(item)
                            if promo:
                                promotions.append(promo)
        
        return promotions

    def _convert_to_promotion(self, item: Dict) -> Optional[Dict]:
        """Конвертирует сырой объект в промоакцию"""
        try:
            title = item.get('title') or item.get('name') or item.get('projectTitle', '')
            if not title:
                return None

            raw_id = item.get('id') or item.get('activityId')
            if raw_id:
                promo_id = f"weex_activity_{raw_id}"
            else:
                promo_id = f"weex_activity_{hashlib.md5(title.encode()).hexdigest()[:12]}"

            return {
                'promo_id': promo_id,
                'title': title,
                'token': item.get('token', ''),
                'reward': item.get('totalPrizePool', item.get('reward', '')),
                'startTime': item.get('startTime'),
                'endTime': item.get('endTime'),
                'status': 'ongoing',
                'type': 'activity',
                'exchange': 'weex',
            }
        except:
            return None

    def get_strategy_info(self) -> Dict[str, Any]:
        """Возвращает информацию о стратегии парсинга"""
        return {
            'strategy_used': 'weex_playwright_intercept',
            'parser_type': 'WeexParser',
            'exchange': 'weex',
            'method': 'playwright_api_intercept',
            'description': 'Загрузка HTML страницы с перехватом API ответов через Playwright'
        }

    def get_error_stats(self) -> Dict[str, Any]:
        """Возвращает статистику ошибок"""
        return {
            'total_errors': 0,
            'errors': []
        }
