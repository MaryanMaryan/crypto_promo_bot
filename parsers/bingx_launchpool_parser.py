"""
BingX Launchpool Parser

API: https://api-app.qq-os.com/api/spot-launchpool/v1/project/process-list
Примечание: Требует Playwright для синхронизации timestamp с сервером
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


class BingxLaunchpoolParser(LaunchpoolBaseParser):
    """
    Парсер для BingX Launchpool
    
    Структура API ответа:
    {
        "code": 0,
        "msg": "success",
        "data": {
            "data": [
                {
                    "projectName": "Athena",
                    "tokenName": "ENA",
                    "startTime": "2024-04-02T00:00:00.000Z",
                    "endTime": "2024-04-16T00:00:00.000Z",
                    "totalRewardNumber": "17550000",
                    "totalRewardValue": 17550000,
                    "estimatedApr": "100",
                    "poolList": [
                        {
                            "assetName": "USDT",
                            "userDepositNumberLimit": "100000",
                            "userDepositNumberMinimum": "10",
                            "rewardNumber": "17550000",
                            "userNumber": 12345
                        }
                    ],
                    "labelList": [
                        {"name": "twitter", "value": "https://twitter.com/..."},
                        {"name": "website", "value": "https://..."}
                    ]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "BingX"
    EXCHANGE_TYPE = "launchpool"
    BASE_URL = "https://bingx.com/ru-ru/launchpool"
    
    API_URLS = {
        'process': 'https://api-app.qq-os.com/api/spot-launchpool/v1/project/process-list',
        'completed': 'https://api-app.qq-os.com/api/spot-launchpool/v1/project/completed-list?pageSize=100',
        'entrance': 'https://api-app.qq-os.com/api/spot-launchpool/v2/entrance'
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
        BingX требует браузер для получения данных, поэтому используем async версию.
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._fetch_active_data())
                return future.result()
        except RuntimeError:
            return asyncio.run(self._fetch_active_data())
    
    async def _fetch_active_data(self) -> Optional[Dict[str, Any]]:
        """Получение данных активных проектов через перехват API"""
        return await self._fetch_via_network_intercept()
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """
        Реализация абстрактного метода парсинга.
        """
        projects = []
        if not data or data.get('code') != 0:
            return projects
        
        project_list = data.get('data', {}).get('data', [])
        for project_data in project_list:
            try:
                project = self._parse_project(project_data)
                projects.append(project)
            except Exception as e:
                self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                continue
        
        return projects
    
    async def _fetch_via_network_intercept(self) -> Optional[Dict[str, Any]]:
        """
        Получение данных через перехват API ответа (обход timestamp защиты)
        """
        try:
            if not self._pool.is_running:
                self.logger.warning("⚠️ Пул браузеров не запущен, запускаем...")
                await self._pool.start()
            
            async with self._pool.acquire() as browser:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                api_data = None
                
                async def handle_response(response):
                    nonlocal api_data
                    # Перехватываем ответ API launchpool
                    if 'spot-launchpool' in response.url and 'process-list' in response.url:
                        try:
                            if response.status == 200:
                                data = await response.json()
                                if data.get('code') == 0:
                                    api_data = data
                                    self.logger.info(f"✅ Перехвачен API ответ BingX")
                        except:
                            pass
                
                try:
                    page = await context.new_page()
                    page.on('response', handle_response)
                    
                    # Переходим на страницу launchpool - это триггерит API запрос
                    self.logger.info("🌐 Загружаем страницу BingX Launchpool...")
                    await page.goto('https://bingx.com/ru-ru/launchpool/', wait_until='networkidle')
                    await asyncio.sleep(3)  # Даём время на загрузку API
                    
                    if api_data:
                        return api_data
                    else:
                        self.logger.warning("⚠️ API данные не были перехвачены")
                        return None
                        
                finally:
                    await context.close()
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных: {e}")
            return None

    async def _fetch_api_with_browser(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Получение данных через браузер для обхода timestamp защиты
        (Legacy метод - может не работать из-за timestamp проверки)
        """
        try:
            # Проверяем, запущен ли пул
            if not self._pool.is_running:
                self.logger.warning("⚠️ Пул браузеров не запущен, запускаем...")
                await self._pool.start()

            # Получаем браузер из пула
            async with self._pool.acquire() as browser:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                try:
                    page = await context.new_page()
                    
                    # Переходим на главную страницу для получения cookies и timestamp
                    self.logger.info("🌐 Загружаем главную страницу BingX...")
                    await page.goto('https://bingx.com/ru-ru/launchpool/', wait_until='networkidle')
                    await asyncio.sleep(2)  # Даем время на инициализацию
                    
                    # Теперь делаем API запрос
                    self.logger.info(f"📡 Запрос к API: {url}")
                    response = await page.goto(url, wait_until='networkidle')
                    
                    if response.status != 200:
                        self.logger.error(f"❌ Ошибка HTTP: {response.status}")
                        return None
                    
                    content = await response.text()
                    
                    # Парсим JSON
                    import json
                    data = json.loads(content)
                    
                    self.logger.info(f"✅ Данные получены успешно")
                    return data
                    
                finally:
                    await context.close()
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных через браузер: {e}")
            return None

    def _parse_project(self, project_data: Dict[str, Any]) -> LaunchpoolProject:
        """
        Парсинг одного проекта из API ответа
        """
        try:
            # Базовая информация
            token_symbol = project_data.get('tokenName', '').upper()
            project_name = project_data.get('projectName', '')
            project_id = project_data.get('projectId', '') or token_symbol
            
            # Периоды (ISO строки)
            start_time = self._parse_iso_time(project_data.get('startTime'))
            end_time = self._parse_iso_time(project_data.get('endTime'))
            
            # Награды
            total_reward = float(project_data.get('totalRewardNumber', 0))
            total_reward_value = float(project_data.get('totalRewardValue', 0))
            
            # Определяем статус
            now = datetime.now()
            if now < start_time:
                status = "upcoming"
            elif start_time <= now <= end_time:
                status = "active"
            else:
                status = "ended"
            
            # Ссылки из labelList
            labels = {label['name']: label['value'] for label in project_data.get('labelList', [])}
            website = labels.get('website', '')
            twitter = labels.get('twitter', '')
            
            # Парсим пулы
            pools = []
            total_participants = 0
            for pool_data in project_data.get('poolList', []):
                pool = self._parse_pool(pool_data, token_symbol)
                if pool:
                    pools.append(pool)
                    total_participants += pool.participants
            
            return LaunchpoolProject(
                id=str(project_id),
                exchange=self.EXCHANGE_NAME,
                type=self.EXCHANGE_TYPE,
                token_symbol=token_symbol,
                token_name=project_name,
                total_pool_tokens=total_reward,
                total_pool_usd=total_reward_value,
                start_time=start_time,
                end_time=end_time,
                status=status,
                project_url=f"https://bingx.com/ru-ru/launchpool/{token_symbol}",
                website=website,
                twitter=twitter,
                pools=pools,
                total_participants=total_participants,
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
            self.logger.error(f"Данные проекта: {project_data}")
            raise

    def _parse_pool(self, pool_data: Dict[str, Any], reward_token: str) -> Optional[LaunchpoolPool]:
        """
        Парсинг одного пула стейкинга
        """
        stake_token = pool_data.get('assetName', '').upper()
        if not stake_token:
            return None
        
        # APR (уже в процентах)
        apr = float(pool_data.get('estimatedApr', 0))
        
        # Лимиты депозита
        min_stake = float(pool_data.get('userDepositNumberMinimum', 0))
        max_stake = float(pool_data.get('userDepositNumberLimit', 0))
        
        # Награды
        pool_reward = float(pool_data.get('rewardNumber', 0))
        
        # Участники
        participants = int(pool_data.get('userNumber', 0))
        
        return LaunchpoolPool(
            stake_coin=stake_token,
            apr=apr,
            min_stake=min_stake,
            max_stake=max_stake,
            pool_reward=pool_reward,
            participants=participants,
        )

    def _parse_iso_time(self, time_str: str) -> datetime:
        """
        Парсинг ISO времени (2024-04-02T00:00:00.000Z)
        """
        if not time_str:
            return datetime.now()
        
        try:
            # Убираем миллисекунды и Z
            time_str = time_str.replace('.000Z', '').replace('Z', '')
            return datetime.fromisoformat(time_str)
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга времени '{time_str}': {e}")
            return datetime.now()

    def get_projects(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Получение списка проектов (синхронная обёртка)
        
        Args:
            status_filter: 'active', 'ended', 'upcoming' или None (все)
        """
        try:
            loop = asyncio.get_running_loop()
            # Если уже есть running loop, создаем task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, 
                    self.get_projects_async(status_filter)
                )
                return future.result()
        except RuntimeError:
            # Нет running loop, можно использовать asyncio.run
            return asyncio.run(self.get_projects_async(status_filter))

    async def get_projects_async(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Получение списка проектов (асинхронная версия)
        
        Args:
            status_filter: 'active', 'ended', 'upcoming' или None (все)
        """
        try:
            projects = []
            
            # Получаем активные проекты через перехват API
            if not status_filter or status_filter in ['active', 'upcoming']:
                self.logger.info("📡 Получение активных проектов BingX...")
                data = await self._fetch_via_network_intercept()
                
                if data and data.get('code') == 0:
                    project_list = data.get('data', {}).get('data', [])
                    self.logger.info(f"✅ Получено активных проектов: {len(project_list)}")
                    
                    for project_data in project_list:
                        try:
                            project = self._parse_project(project_data)
                            
                            # Фильтруем по статусу если нужно
                            if not status_filter or project.status == status_filter:
                                projects.append(project)
                                
                        except Exception as e:
                            self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                            continue
                else:
                    self.logger.warning("⚠️ Не удалось получить данные BingX (возможно нет активных проектов)")
            
            self.logger.info(f"✅ Всего проектов BingX: {len(projects)}")
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения проектов BingX: {e}")
            return []


def test_parser():
    """Тестирование парсера"""
    import asyncio
    
    async def run_test():
        parser = BingxLaunchpoolParser()
        
        print("\n" + "="*60)
        print("🧪 ТЕСТ BingX Launchpool Parser")
        print("="*60)
        
        # Получаем активные проекты
        print("\n📊 Получение активных проектов...")
        projects = await parser.get_projects_async(status_filter='active')
        
        print(f"\n✅ Найдено проектов: {len(projects)}")
        
        if projects:
            print("\n" + "="*60)
            print("📋 ПЕРВЫЙ ПРОЕКТ (ФОРМАТИРОВАННЫЙ):")
            print("="*60)
            print(parser.format_project(projects[0]))
        else:
            print("\n⚠️ Активных проектов не найдено")
            
            # Пробуем получить все проекты
            print("\n📊 Получение всех проектов...")
            all_projects = await parser.get_projects_async()
            print(f"\n✅ Всего проектов: {len(all_projects)}")
            
            if all_projects:
                print("\n" + "="*60)
                print("📋 ПЕРВЫЙ ПРОЕКТ (ФОРМАТИРОВАННЫЙ):")
                print("="*60)
                print(parser.format_project(all_projects[0]))
    
    asyncio.run(run_test())


if __name__ == '__main__':
    test_parser()
