"""
Gate.io Launchpool Parser

API: https://www.gate.com/apiw/v2/earn/launch-pool/project-list?page=1&pageSize=10&status=0

Примечание: Gate.io API может блокировать прямые запросы.
Если простые HTTP запросы не работают, используем async браузер.
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from parsers.launchpool_base import (
    LaunchpoolBaseParser, 
    LaunchpoolProject, 
    LaunchpoolPool
)

logger = logging.getLogger(__name__)


class GateLaunchpoolParser(LaunchpoolBaseParser):
    """
    Парсер для Gate.io Launchpool
    
    Структура API ответа:
    {
        "code": 200,
        "message": "success",
        "data": {
            "ing_count": 2,
            "not_start_count": 0,
            "finish_count": 354,
            "total": 356,
            "list": [
                {
                    "pid": 491,
                    "coin": "FOGO",
                    "coin_icon": "https://...",
                    "desc": "Description...",
                    "name": "FOGO Token",
                    "total_amount_u": "123456.78",
                    "start_timest": 1768878000,
                    "end_timest": 1769680800,
                    "labels_config": {"website": "https://...", "twitter": "..."},
                    "reward_pools": [
                        {
                            "rid": 123,
                            "coin": "BTC",
                            "coin_icon": "https://...",
                            "maybe_year_rate": "50.00",  # APR%
                            "personal_min_amount": "0.001",
                            "personal_max_amount": "1.0",
                            "order_count": 500,  # участники
                            "total_amount": "100.5",  # застейкано
                            "pool_amount": "50000"  # пул наград
                        }
                    ]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "Gate.io"
    EXCHANGE_TYPE = "launchpool"
    BASE_URL = "https://www.gate.com/ru/launchpool"
    API_URL = "https://www.gate.com/apiw/v2/earn/launch-pool/project-list?page=1&pageSize=50&status=0"
    
    def __init__(self, url: str = None):
        """
        Args:
            url: URL страницы (опционально, для совместимости с ParserService)
        """
        super().__init__()
        self.url = url
        self._use_browser = False  # Попытаемся сначала без браузера
        
        # Заголовки для Gate.io (из браузера)
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.gate.com',
            'Referer': 'https://www.gate.com/ru/launchpool',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
        })
    
    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Получение данных с Gate.io API"""
        
        # Сначала пробуем обычный HTTP запрос
        data = self._fetch_via_http()
        if data:
            return data
        
        # Если не получилось - пробуем через браузер
        self.logger.info("⚠️ HTTP запрос не удался, пробуем через браузер...")
        try:
            return asyncio.get_event_loop().run_until_complete(self._fetch_via_browser())
        except RuntimeError:
            # Если event loop уже запущен
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._fetch_via_browser())
            finally:
                loop.close()
    
    def _fetch_via_http(self) -> Optional[Dict[str, Any]]:
        """Попытка получить данные через HTTP"""
        try:
            self.logger.info(f"🌐 Запрос к Gate.io Launchpool API...")
            
            response = self.session.get(self.API_URL, timeout=15)
            
            # Проверяем что это JSON
            if 'application/json' not in response.headers.get('content-type', ''):
                self.logger.warning(f"⚠️ Gate.io вернул не JSON: {response.status_code}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # Проверяем успешность
            if data.get('code') != 200:
                self.logger.error(f"❌ Gate.io API error: {data.get('message')}")
                return None
            
            result = data.get('data', {})
            projects_count = len(result.get('list', []))
            self.logger.info(f"✅ Получено {projects_count} проектов от Gate.io Launchpool (HTTP)")
            
            return data
            
        except Exception as e:
            self.logger.warning(f"⚠️ HTTP запрос к Gate.io не удался: {e}")
            return None
    
    async def _fetch_via_browser(self) -> Optional[Dict[str, Any]]:
        """Получение данных через Playwright браузер"""
        try:
            from playwright.async_api import async_playwright
            
            self.logger.info(f"🌐 Запрос к Gate.io через браузер...")
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                api_data = None
                
                async def handle_response(response):
                    nonlocal api_data
                    if 'launch-pool/project-list' in response.url:
                        try:
                            if response.status == 200:
                                api_data = await response.json()
                                self.logger.info(f"✅ Перехвачен API ответ Gate.io")
                        except:
                            pass
                
                page.on('response', handle_response)
                
                await page.goto(self.BASE_URL, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(3000)  # Ждём загрузки API
                
                await browser.close()
                
                if api_data:
                    result = api_data.get('data', {})
                    projects_count = len(result.get('list', []))
                    self.logger.info(f"✅ Получено {projects_count} проектов от Gate.io (браузер)")
                    return api_data
                else:
                    self.logger.error("❌ Не удалось получить данные через браузер")
                    return None
                    
        except ImportError:
            self.logger.error("❌ Playwright не установлен. pip install playwright && playwright install chromium")
            return None
        except Exception as e:
            self.logger.error(f"❌ Ошибка браузера Gate.io: {e}")
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """Парсинг данных Gate.io в LaunchpoolProject"""
        projects = []
        
        try:
            result = data.get('data', {})
            items = result.get('list', [])
            
            for item in items:
                try:
                    project = self._parse_single_project(item)
                    if project:
                        projects.append(project)
                except Exception as e:
                    self.logger.error(f"❌ Ошибка парсинга проекта Gate.io: {e}")
                    continue
            
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга Gate.io данных: {e}")
            return []
    
    def _parse_single_project(self, item: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """Парсинг одного проекта"""
        
        # Базовая информация
        pid = str(item.get('pid', ''))
        token_symbol = item.get('coin', '')
        token_name = item.get('name', '') or token_symbol
        
        if not token_symbol:
            return None
        
        # Время (в секундах, не миллисекундах!)
        start_ts = item.get('start_timest')
        end_ts = item.get('end_timest')
        start_time = self.parse_timestamp(start_ts, is_milliseconds=False) if start_ts else None
        end_time = self.parse_timestamp(end_ts, is_milliseconds=False) if end_ts else None
        
        # Если время в прошлом или нет времени - пробуем миллисекунды
        if start_time and start_time.year < 2024:
            start_time = self.parse_timestamp(start_ts, is_milliseconds=True)
        if end_time and end_time.year < 2024:
            end_time = self.parse_timestamp(end_ts, is_milliseconds=True)
        
        # Определяем статус по времени
        now = datetime.utcnow()
        if start_time and start_time > now:
            status = 'upcoming'
        elif end_time and end_time < now:
            status = 'ended'
        else:
            status = 'active'
        
        # Общий пул в USD
        total_pool_usd = self.safe_float(item.get('total_amount_u', 0))
        
        # Пулы для стейкинга
        pools = []
        reward_pools = item.get('reward_pools', [])
        total_participants = 0
        
        for pool_data in reward_pools:
            pool = self._parse_pool(pool_data)
            if pool:
                pools.append(pool)
                total_participants += pool.participants
        
        # Ссылки
        labels_config = item.get('labels_config', {})
        website = ''
        twitter = ''
        
        if isinstance(labels_config, dict):
            website = labels_config.get('website', '') or labels_config.get('official_website', '')
            twitter = labels_config.get('twitter', '') or labels_config.get('twitter_url', '')
        elif isinstance(labels_config, list):
            for label in labels_config:
                if isinstance(label, dict):
                    if label.get('type') == 'website':
                        website = label.get('url', '')
                    elif label.get('type') == 'twitter':
                        twitter = label.get('url', '')
        
        # Создаём проект
        project = LaunchpoolProject(
            id=pid,
            exchange=self.EXCHANGE_NAME,
            type=self.EXCHANGE_TYPE,
            token_symbol=token_symbol,
            token_name=token_name,
            token_icon=item.get('coin_icon', ''),
            status=status,
            total_pool_usd=total_pool_usd,
            start_time=start_time,
            end_time=end_time,
            pools=pools,
            project_url=f"https://www.gate.com/ru/launchpool/{token_symbol}",
            website=website,
            twitter=twitter,
            description=item.get('desc', ''),
            total_participants=total_participants,
        )
        
        return project
    
    def _parse_pool(self, pool_data: Dict[str, Any]) -> Optional[LaunchpoolPool]:
        """Парсинг одного пула"""
        stake_coin = pool_data.get('coin', '')
        if not stake_coin:
            return None
        
        # APR в Gate.io приходит как строка процентов (например "50.00" = 50%)
        apr_raw = self.safe_float(pool_data.get('maybe_year_rate', 0))
        apr = apr_raw  # Уже в процентах
        
        # Лимиты
        min_stake = self.safe_float(pool_data.get('personal_min_amount'))
        max_stake = self.safe_float(pool_data.get('personal_max_amount'))
        
        # Участники
        participants = self.safe_int(pool_data.get('order_count', 0))
        
        # Застейкано
        total_staked = self.safe_float(pool_data.get('total_amount', 0))
        
        # Награды в пуле
        pool_reward = self.safe_float(pool_data.get('pool_amount', 0))
        
        # Метки
        labels = []
        reward_pool_type = pool_data.get('reward_pool_type', 0)
        if reward_pool_type == 1:
            labels.append('🆕')  # Для новых пользователей
        
        pool = LaunchpoolPool(
            stake_coin=stake_coin,
            stake_coin_icon=pool_data.get('coin_icon', ''),
            apr=apr,
            min_stake=min_stake,
            max_stake=max_stake,
            total_staked=total_staked,
            pool_reward=pool_reward,
            participants=participants,
            is_new_user_only=(reward_pool_type == 1),
            labels=labels,
        )
        
        return pool
    
    def _map_status(self, status_code: Any) -> str:
        """Маппинг статуса Gate.io"""
        # Gate.io status=0 в API возвращает все проекты
        # Реальный статус определяется по start_time и end_time в _parse_single_project
        return 'active'


# Для тестирования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    parser = GateLaunchpoolParser()
    projects = parser.get_projects(status_filter='active')
    
    print(f"\n{'='*60}")
    print(f"Найдено проектов: {len(projects)}")
    print('='*60)
    
    for project in projects[:3]:
        print(parser.format_project(project))
        print("\n" + "="*60 + "\n")
