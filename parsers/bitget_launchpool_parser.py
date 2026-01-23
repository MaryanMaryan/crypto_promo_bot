"""
Bitget Launchpool Parser

API: https://www.bitget.com/v1/finance/launchpool/product/list/new
Примечание: Требует Playwright для обхода Cloudflare защиты
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


class BitgetLaunchpoolParser(LaunchpoolBaseParser):
    """
    Парсер для Bitget Launchpool
    
    Структура API ответа:
    {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "id": "1234567890",
                "productName": "Athena",
                "productCoinName": "ENA",
                "startTime": "1711929600000",
                "endTime": "1713139200000",
                "totalRewards": "17550000",
                "farmingPeriod": "14",
                "status": 2,  # 1=waiting, 2=running, 4=finished
                "productSubList": [
                    {
                        "productSubCoinName": "USDT",
                        "apr": "100.5",
                        "userMaxAmount": "100000",
                        "vipUserMaxAmount": "200000",
                        "minAmount": "10",
                        "totalAmount": "17550000",
                        "participants": 12345
                    }
                ],
                "website": "https://...",
                "twitter": "https://twitter.com/..."
            }
        ]
    }
    """
    
    EXCHANGE_NAME = "Bitget"
    EXCHANGE_TYPE = "launchpool"
    BASE_URL = "https://www.bitget.com/ru/events/launchpool"
    
    API_URLS = {
        'list': 'https://www.bitget.com/v1/finance/launchpool/product/list/new',
        'count': 'https://www.bitget.com/v1/finance/launchpool/product/count'
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
        """Получение данных через перехват API ответа или HTML парсинг"""
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
                    
                    # Логируем все API запросы для диагностики
                    if 'bitget.com' in url and ('/v1/' in url or '/api/' in url):
                        captured_urls.append(url)
                        self.logger.info(f"📡 API: {url[:80]}... - {response.status}")
                    
                    # Перехватываем launchpool API
                    if any(x in url.lower() for x in ['launchpool', 'launch-pool', 'poolmining']):
                        try:
                            if response.status == 200 and 'json' in response.headers.get('content-type', ''):
                                data = await response.json()
                                self.logger.info(f"📦 JSON data: {str(data)[:200]}")
                                # Bitget использует code '200' вместо '00000'
                                if data.get('code') in ['00000', '200'] and data.get('data'):
                                    # Проверяем формат данных
                                    data_content = data.get('data')
                                    if isinstance(data_content, list) and len(data_content) > 0:
                                        api_data = data
                                        self.logger.info(f"✅ Перехвачен API Bitget (список)")
                                    elif isinstance(data_content, dict) and data_content.get('items'):
                                        # Конвертируем в формат со списком
                                        api_data = {'code': '00000', 'data': data_content['items']}
                                        self.logger.info(f"✅ Перехвачен API Bitget (items)")
                        except Exception as e:
                            self.logger.debug(f"Пропуск: {e}")
                
                try:
                    page = await context.new_page()
                    page.on('response', handle_response)
                    
                    self.logger.info("🌐 Загружаем страницу Bitget Launchpool...")
                    await page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(3)
                    
                    # Кликаем на вкладку "Скоро" / "Coming Soon" / "Upcoming" для загрузки upcoming проектов
                    try:
                        # Ищем таб с upcoming проектами
                        upcoming_tab = await page.query_selector('text=/Coming|Скоро|Upcoming|Незабаром/i')
                        if upcoming_tab:
                            self.logger.info("🔘 Кликаем на вкладку Upcoming...")
                            await upcoming_tab.click()
                            await asyncio.sleep(2)
                    except Exception as e:
                        self.logger.debug(f"Не удалось кликнуть на таб: {e}")
                    
                    # Также кликаем на таб "Текущие" / "Ongoing"
                    try:
                        ongoing_tab = await page.query_selector('text=/Ongoing|Current|Текущие|Активн/i')
                        if ongoing_tab:
                            self.logger.info("🔘 Кликаем на вкладку Ongoing...")
                            await ongoing_tab.click()
                            await asyncio.sleep(2)
                    except:
                        pass
                    
                    await asyncio.sleep(2)
                    
                    if api_data:
                        return api_data
                    
                    self.logger.info(f"📋 Перехваченные URL: {len(captured_urls)}")
                    
                    # Если API не перехвачен - пробуем парсить HTML
                    self.logger.info("🔍 Пробуем парсить HTML...")
                    
                    html_content = await page.content()
                    projects = await self._parse_html_projects(page)
                    
                    if projects:
                        # Возвращаем в формате API
                        return {'code': '00000', 'data': projects}
                    
                    return None
                        
                finally:
                    try:
                        await context.close()
                    except Exception as e:
                        self.logger.debug(f"Контекст уже закрыт: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных: {e}")
            return None
    
    async def _parse_html_projects(self, page) -> List[Dict]:
        """Парсинг проектов из HTML страницы"""
        projects = []
        
        try:
            # Ищем карточки проектов
            cards = await page.query_selector_all('[class*="launchpool"] [class*="card"], [class*="project-card"], [class*="pool-item"]')
            
            if not cards:
                # Альтернативные селекторы
                cards = await page.query_selector_all('div[class*="event"] > div, div[class*="list"] > div')
            
            self.logger.info(f"📦 Найдено карточек: {len(cards)}")
            
            for card in cards:
                try:
                    # Извлекаем данные из карточки
                    text = await card.inner_text()
                    
                    # Ищем токен (обычно в крупном шрифте)
                    token_el = await card.query_selector('h2, h3, [class*="title"], [class*="name"], [class*="symbol"]')
                    token_name = await token_el.inner_text() if token_el else ''
                    
                    # Проверяем статус
                    status_el = await card.query_selector('[class*="status"], [class*="tag"], [class*="badge"]')
                    status_text = await status_el.inner_text() if status_el else ''
                    
                    if any(x in status_text.lower() for x in ['coming', 'soon', 'незабаром', 'скоро', 'upcoming']):
                        status = 'upcoming'
                        status_code = 1
                    elif any(x in status_text.lower() for x in ['live', 'active', 'ongoing', 'триває']):
                        status = 'active'
                        status_code = 2
                    else:
                        status = 'ended'
                        status_code = 4
                    
                    if token_name and len(token_name) < 30:
                        projects.append({
                            'id': token_name.upper().replace(' ', '_'),
                            'productCoinName': token_name.upper().split()[0] if token_name else '',
                            'productName': token_name,
                            'status': status_code,
                            'startTime': None,
                            'endTime': None,
                            'totalRewards': 0,
                            'productSubList': []
                        })
                        self.logger.info(f"✅ Найден проект: {token_name} [{status}]")
                        
                except Exception as e:
                    self.logger.debug(f"Ошибка парсинга карточки: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка HTML парсинга: {e}")
        
        return projects
    
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
                self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                continue
        
        return projects

    async def _fetch_api_with_browser(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Legacy метод - может не работать из-за Cloudflare
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
                    
                    # Переходим на главную страницу для прохождения Cloudflare
                    self.logger.info("🌐 Загружаем главную страницу Bitget...")
                    await page.goto('https://www.bitget.com/ru/events/launchpool', wait_until='networkidle')
                    await asyncio.sleep(3)  # Даем время на инициализацию и Cloudflare
                    
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
                    try:
                        await context.close()
                    except Exception as e:
                        self.logger.debug(f"Контекст уже закрыт: {e}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных через браузер: {e}")
            return None

    def _parse_project(self, project_data: Dict[str, Any]) -> LaunchpoolProject:
        """
        Парсинг одного проекта из API ответа
        """
        try:
            # Базовая информация
            project_id = project_data.get('id', '')
            token_symbol = project_data.get('productCoinName', '').upper()
            project_name = project_data.get('productName', '')
            
            # Периоды (timestamp в миллисекундах)
            start_time = self._parse_timestamp_ms(project_data.get('startTime'))
            end_time = self._parse_timestamp_ms(project_data.get('endTime'))
            
            # Награды (могут быть строкой или числом)
            total_reward = self._safe_float(project_data.get('totalRewards', 0))
            
            # Статус: 1=waiting, 2=running, 4=finished, 7=upcoming (новый формат)
            status_code = int(project_data.get('status', 0))
            if status_code in [1, 7]:  # 7 = upcoming в новом API
                status = "upcoming"
            elif status_code == 2:
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
            twitter = project_data.get('twitter', '')
            
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
                token_name=project_name,
                total_pool_tokens=total_reward,
                start_time=start_time,
                end_time=end_time,
                status=status,
                project_url=f"https://www.bitget.com/ru/events/launchpool/{token_symbol}",
                website=website,
                twitter=twitter,
                pools=pools,
                total_participants=total_participants,
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
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
        
        # APR/APY (может быть 'apy' или 'apr' в зависимости от API)
        apr = self._safe_float(pool_data.get('apy') or pool_data.get('apr', 0))
        
        # Лимиты депозита (используем _safe_float для безопасного преобразования)
        min_stake = self._safe_float(pool_data.get('minAmount', 0))
        max_stake = self._safe_float(pool_data.get('userMaxAmount', 0))
        max_stake_vip = self._safe_float(pool_data.get('vipUserMaxAmount', 0))
        
        # Награды
        pool_reward = self._safe_float(pool_data.get('totalRewards') or pool_data.get('totalAmount', 0))
        
        # Участники (может отсутствовать)
        participants = int(self._safe_float(pool_data.get('participants', 0)))
        
        # Метки
        labels = []
        if max_stake_vip > max_stake:
            labels.append(f"VIP: {max_stake_vip:,.0f}")
        
        return LaunchpoolPool(
            stake_coin=stake_token,
            apr=apr,
            min_stake=min_stake,
            max_stake=max_stake,
            max_stake_vip=max_stake_vip,
            pool_reward=pool_reward,
            participants=participants,
            labels=labels,
        )

    def _parse_timestamp_ms(self, timestamp_str: str) -> datetime:
        """
        Парсинг timestamp в миллисекундах (строка)
        """
        if not timestamp_str:
            return datetime.now()
        
        try:
            timestamp = int(timestamp_str) / 1000  # Конвертируем ms в seconds
            return datetime.fromtimestamp(timestamp)
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга timestamp '{timestamp_str}': {e}")
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
            
            self.logger.info("📡 Получение проектов Bitget...")
            data = await self._fetch_via_network_intercept()
            
            if not data or data.get('code') != '00000':
                self.logger.error(f"❌ Ошибка API: {data.get('msg') if data else 'Нет данных'}")
                return []
            
            project_list = data.get('data', [])
            self.logger.info(f"✅ Получено проектов: {len(project_list)}")
            
            for project_data in project_list:
                try:
                    project = self._parse_project(project_data)
                    
                    # Фильтруем по статусу если нужно
                    if not status_filter or project.status == status_filter:
                        projects.append(project)
                        
                except Exception as e:
                    self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                    continue
            
            self.logger.info(f"✅ Всего проектов Bitget: {len(projects)}")
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения проектов Bitget: {e}")
            return []


def test_parser():
    """Тестирование парсера"""
    import asyncio
    
    async def run_test():
        parser = BitgetLaunchpoolParser()
        
        print("\n" + "="*60)
        print("🧪 ТЕСТ Bitget Launchpool Parser")
        print("="*60)
        
        # Получаем активные проекты
        print("\n📊 Получение активных проектов...")
        projects = await parser.get_projects_async(status_filter='active')
        
        print(f"\n✅ Найдено активных проектов: {len(projects)}")
        
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
