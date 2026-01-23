"""
Bitget PoolX Parser

API: https://www.bitget.com/v1/finance/poolx/product/page/list/new
Примечание: Требует Playwright для обхода Cloudflare защиты

PoolX - это программа стейкинга Bitget, аналогичная Launchpool
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
from utils.browser_pool import get_browser_pool

logger = logging.getLogger(__name__)


class BitgetPoolxParser(LaunchpoolBaseParser):
    """
    Парсер для Bitget PoolX (стейкинг)
    
    Структура API ответа:
    {
        "code": "200",
        "data": {
            "items": [
                {
                    "id": "1395379598615986176",
                    "productCoinName": "FUN",
                    "startTime": "1768449600000",
                    "endTime": "1769004000000",
                    "totalRewards": "8331000",
                    "period": 6,
                    "status": 2,  # 1=waiting, 2=running, 3=claim, 4=finished
                    "productSubList": [
                        {
                            "productSubCoinName": "BTC",
                            "settleCoinName": "FUN",
                            "apr": "2.68",
                            "userMaxAmount": "50.000000",
                            "totalStakedAmount": "7982.148847"
                        }
                    ]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "Bitget"
    EXCHANGE_TYPE = "poolx"
    BASE_URL = "https://www.bitget.com/uk/events/poolx"
    
    API_URLS = {
        'list': 'https://www.bitget.com/v1/finance/poolx/product/page/list/new',
        'count': 'https://www.bitget.com/v1/finance/poolx/product/count'
    }
    
    def __init__(self, url: str = None):
        """
        Args:
            url: URL страницы (опционально, для совместимости с ParserService)
        """
        super().__init__()
        self.url = url
        self._pool = get_browser_pool()
    
    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """
        Реализация абстрактного метода.
        Bitget требует браузер для получения данных.
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._fetch_via_network_intercept())
                return future.result()
        except RuntimeError:
            return asyncio.run(self._fetch_via_network_intercept())
    
    async def _fetch_via_network_intercept(self) -> Optional[Dict[str, Any]]:
        """Получение данных через перехват API ответа"""
        try:
            if not self._pool.is_running:
                self.logger.warning("⚠️ Пул браузеров не запущен, запускаем...")
                await self._pool.start()
            
            async with self._pool.acquire() as browser:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                api_data = None
                captured_urls = []
                
                async def handle_response(response):
                    nonlocal api_data
                    url = response.url
                    
                    # Логируем API запросы
                    if 'bitget.com' in url and '/v1/' in url:
                        captured_urls.append(url)
                    
                    # Перехватываем poolx API - только product/page/list
                    if 'finance/poolx/product/page/list' in url.lower() or 'finance/poolx/product/list' in url.lower():
                        try:
                            if response.status == 200 and 'json' in response.headers.get('content-type', ''):
                                data = await response.json()
                                self.logger.info(f"📦 PoolX Product List: {str(data)[:200]}")
                                
                                if data.get('code') == '200' and data.get('data'):
                                    data_content = data.get('data')
                                    
                                    # Формат с items (основной)
                                    if isinstance(data_content, dict) and data_content.get('items'):
                                        items = data_content['items']
                                        if items:
                                            # Конвертируем в стандартный формат
                                            api_data = {'code': '00000', 'data': items}
                                            self.logger.info(f"✅ Перехвачен PoolX API: {len(items)} проектов")
                                        
                        except Exception as e:
                            self.logger.debug(f"Пропуск: {e}")
                
                try:
                    page = await context.new_page()
                    page.on('response', handle_response)
                    
                    self.logger.info("🌐 Загружаем страницу Bitget PoolX...")
                    await page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(4)
                    
                    # Прокручиваем для загрузки
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(2)
                    
                    if api_data:
                        return api_data
                    
                    self.logger.info(f"📋 Перехваченные URL: {len(captured_urls)}")
                    for url in captured_urls:
                        self.logger.debug(f"  - {url[:80]}")
                    
                    return None
                        
                finally:
                    await context.close()
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных PoolX: {e}")
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """
        Реализация абстрактного метода парсинга.
        """
        projects = []
        if not data or data.get('code') != '00000':
            return projects
        
        project_list = data.get('data', [])
        for project_data in project_list:
            try:
                project = self._parse_project(project_data)
                projects.append(project)
            except Exception as e:
                self.logger.error(f"❌ Ошибка парсинга проекта PoolX: {e}")
                continue
        
        return projects

    def _parse_project(self, project_data: Dict[str, Any]) -> LaunchpoolProject:
        """
        Парсинг одного проекта из API ответа
        """
        try:
            # Базовая информация
            project_id = project_data.get('id', '')
            token_symbol = project_data.get('productCoinName', '').upper()
            token_icon = project_data.get('productCoinImgUrl', '')
            
            # Периоды (timestamp в миллисекундах)
            start_time = self._parse_timestamp_ms(project_data.get('startTime'))
            end_time = self._parse_timestamp_ms(project_data.get('endTime'))
            
            # Награды
            total_reward = self._safe_float(project_data.get('totalRewards', 0))
            
            # Статус: 1=waiting, 2=running, 3=claiming, 4=finished
            status_code = int(project_data.get('status', 0))
            self.logger.debug(f"PoolX status code: {status_code} for {token_symbol}")
            
            if status_code == 1:
                status = "upcoming"
            elif status_code in [2, 3]:  # running или claiming - считаем активным
                status = "active"
            elif status_code == 4:
                status = "ended"
            else:
                # Определяем по времени
                now = datetime.now()
                if start_time and start_time > now:
                    status = "upcoming"
                elif end_time and end_time < now:
                    status = "ended"
                else:
                    status = "active"
            
            # Ссылки
            website = project_data.get('website', '')
            
            # Парсим пулы
            pools = []
            total_participants = 0
            for pool_data in project_data.get('productSubList', []):
                pool = self._parse_pool(pool_data)
                if pool:
                    pools.append(pool)
                    total_participants += pool.participants
            
            return LaunchpoolProject(
                id=str(project_id),
                exchange=self.EXCHANGE_NAME,
                type=self.EXCHANGE_TYPE,
                token_symbol=token_symbol,
                token_name=token_symbol,  # PoolX не предоставляет полное имя
                token_icon=token_icon,
                total_pool_tokens=total_reward,
                start_time=start_time,
                end_time=end_time,
                status=status,
                project_url=f"https://www.bitget.com/events/poolx/{project_id}",
                website=website,
                pools=pools,
                total_participants=total_participants,
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга проекта PoolX: {e}")
            self.logger.error(f"Данные проекта: {project_data}")
            raise
    
    def _safe_float(self, value, default=0.0) -> float:
        """Безопасное преобразование в float"""
        if value is None or value == '':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _parse_pool(self, pool_data: Dict[str, Any]) -> Optional[LaunchpoolPool]:
        """
        Парсинг одного пула стейкинга
        """
        stake_token = pool_data.get('productSubCoinName', '').upper()
        if not stake_token:
            return None
        
        # APR
        apr = self._safe_float(pool_data.get('apr', 0))
        
        # Лимиты депозита
        min_stake = self._safe_float(pool_data.get('minAmount', 0))
        max_stake = self._safe_float(pool_data.get('userMaxAmount', 0))
        
        # Награды
        pool_reward = self._safe_float(pool_data.get('totalRewards', 0))
        
        # Всего застейкано
        total_staked = self._safe_float(pool_data.get('totalStakedAmount', 0))
        
        # Участники
        participants = int(self._safe_float(pool_data.get('userCount', 0)))
        
        # Иконка
        stake_coin_icon = pool_data.get('productSubCoinImgUrl', '')
        
        return LaunchpoolPool(
            stake_coin=stake_token,
            stake_coin_icon=stake_coin_icon,
            apr=apr,
            min_stake=min_stake,
            max_stake=max_stake,
            total_staked=total_staked,
            pool_reward=pool_reward,
            participants=participants,
        )

    def _parse_timestamp_ms(self, timestamp_str: str) -> datetime:
        """
        Парсинг timestamp в миллисекундах (строка)
        """
        if not timestamp_str:
            return datetime.now()
        
        try:
            timestamp = int(timestamp_str) / 1000
            return datetime.fromtimestamp(timestamp)
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга timestamp '{timestamp_str}': {e}")
            return datetime.now()

    def get_projects(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Получение списка проектов (синхронная обёртка)
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, 
                    self.get_projects_async(status_filter)
                )
                return future.result()
        except RuntimeError:
            return asyncio.run(self.get_projects_async(status_filter))

    async def get_projects_async(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Получение списка проектов (асинхронная версия)
        """
        try:
            projects = []
            
            self.logger.info("📡 Получение проектов Bitget PoolX...")
            data = await self._fetch_via_network_intercept()
            
            if not data or data.get('code') != '00000':
                self.logger.error(f"❌ Ошибка PoolX API: {data.get('msg') if data else 'Нет данных'}")
                return []
            
            project_list = data.get('data', [])
            self.logger.info(f"✅ Получено проектов PoolX: {len(project_list)}")
            
            for project_data in project_list:
                try:
                    project = self._parse_project(project_data)
                    
                    if not status_filter or project.status == status_filter:
                        projects.append(project)
                        
                except Exception as e:
                    self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                    continue
            
            self.logger.info(f"✅ Всего проектов Bitget PoolX: {len(projects)}")
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения проектов Bitget PoolX: {e}")
            return []


def test_parser():
    """Тестирование парсера"""
    import asyncio
    
    async def run_test():
        parser = BitgetPoolxParser()
        
        print("\n" + "="*60)
        print("🧪 ТЕСТ Bitget PoolX Parser")
        print("="*60)
        
        print("\n📊 Получение проектов...")
        projects = await parser.get_projects_async()
        
        print(f"\n✅ Найдено проектов: {len(projects)}")
        
        for project in projects:
            print(f"\n{'='*50}")
            print(f"🪙 {project.token_symbol}")
            print(f"   ID: {project.id}")
            print(f"   Статус: {project.status}")
            print(f"   Награды: {project.total_pool_tokens:,.0f} {project.token_symbol}")
            print(f"   Период: {project.start_time} - {project.end_time}")
            print(f"   Пулы:")
            for pool in project.pools:
                print(f"      • Стейк {pool.stake_coin}: APR {pool.apr}%, max {pool.max_stake}")
    
    asyncio.run(run_test())


if __name__ == '__main__':
    test_parser()
