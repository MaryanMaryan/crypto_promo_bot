"""
Phemex Candy Drop Parser

API: https://api10.phemex.com/phemex-activity/public/md/candydrop/activities
URL: https://phemex.com/events/candy-drop

Candy Drop - это программа airdrop Phemex с токенами за участие

API endpoints:
- ?status=0 - Upcoming (предстоящие)
- ?status=1 - Active (активные)
- ?status=2 - Ended (завершённые)

ВАЖНО: API защищён 403, требуется Playwright для получения данных
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


class PhemexCandydropParser(LaunchpoolBaseParser):
    """
    Парсер для Phemex Candy Drop (airdrop/токен раздачи)
    
    Структура API ответа:
    {
        "code": 0,
        "msg": "OK",
        "data": [
            {
                "activityId": 820,
                "types": [3],
                "activityName": "IMU",
                "description": "IMU",
                "status": 0,  // 0=upcoming, 1=active, 2=ended
                "rewardAmount": 500000000000000,  // Scaled (÷10^8)
                "currencyType": "1117",
                "participants": 18639,
                "startTime": 1768903200000,
                "endTime": 1769076000000,
                "signBeginTime": 1768903200000,
                "signEndTime": 1768903200000
            }
        ]
    }
    """
    
    EXCHANGE_NAME = "Phemex"
    EXCHANGE_TYPE = "candydrop"
    BASE_URL = "https://phemex.com/events/candy-drop"
    
    API_URLS = {
        'upcoming': 'https://api10.phemex.com/phemex-activity/public/md/candydrop/activities?status=0',
        'active': 'https://api10.phemex.com/phemex-activity/public/md/candydrop/activities?status=1',
        'ended': 'https://api10.phemex.com/phemex-activity/public/md/candydrop/activities?status=2',
    }
    
    REWARD_SCALE = 100000000  # 10^8 для конвертации reward
    
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
        Phemex API возвращает 403, требуется браузер.
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._fetch_via_browser())
                return future.result()
        except RuntimeError:
            return asyncio.run(self._fetch_via_browser())
    
    async def get_projects_async(self, status_filter: Optional[str] = None) -> List[LaunchpoolProject]:
        """
        Async метод получения проектов
        
        Args:
            status_filter: 'active', 'upcoming', 'ended' или None (все)
        """
        data = await self._fetch_via_browser()
        if not data:
            self.logger.warning("⚠️ Нет данных от Phemex Candy Drop API")
            return []
        
        projects = self.parse_projects(data)
        
        if status_filter:
            projects = [p for p in projects if p.status == status_filter]
        
        return projects
    
    async def _fetch_via_browser(self) -> Optional[Dict[str, Any]]:
        """Получение данных через браузер с перехватом API ответов"""
        try:
            if not self._pool.is_running:
                self.logger.warning("⚠️ Пул браузеров не запущен, запускаем...")
                await self._pool.start()
            
            async with self._pool.acquire() as browser:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                all_activities = {
                    'upcoming': [],
                    'active': [],
                    'ended': []
                }
                captured_urls = []
                
                async def handle_response(response):
                    url = response.url
                    
                    # Логируем Phemex API запросы
                    if 'phemex.com' in url and '/phemex-activity/' in url:
                        captured_urls.append(url)
                    
                    # Перехватываем candydrop/activities API
                    if 'candydrop/activities' in url:
                        try:
                            if response.status == 200:
                                data = await response.json()
                                
                                if data.get('code') == 0 and data.get('data'):
                                    activities = data.get('data', [])
                                    
                                    # Определяем тип по URL
                                    if 'status=0' in url:
                                        all_activities['upcoming'].extend(activities)
                                        self.logger.info(f"✅ Upcoming: {len(activities)} акций")
                                    elif 'status=1' in url:
                                        all_activities['active'].extend(activities)
                                        self.logger.info(f"✅ Active: {len(activities)} акций")
                                    elif 'status=2' in url:
                                        all_activities['ended'].extend(activities)
                                        self.logger.info(f"✅ Ended: {len(activities)} акций")
                                        
                        except Exception as e:
                            self.logger.debug(f"Пропуск ответа: {e}")
                
                try:
                    page = await context.new_page()
                    page.on('response', handle_response)
                    
                    self.logger.info("🌐 Загружаем страницу Phemex Candy Drop...")
                    await page.goto(self.BASE_URL, wait_until='networkidle', timeout=45000)
                    await asyncio.sleep(3)
                    
                    # Прокручиваем для загрузки всех данных
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(2)
                    
                    # Собираем все активности
                    combined = []
                    combined.extend(all_activities['active'])
                    combined.extend(all_activities['upcoming'])
                    # Ended добавляем ограниченно (последние 5)
                    combined.extend(all_activities['ended'][:5])
                    
                    total = len(combined)
                    self.logger.info(f"📊 Phemex Candy Drop: всего {total} акций")
                    self.logger.info(f"  - Active: {len(all_activities['active'])}")
                    self.logger.info(f"  - Upcoming: {len(all_activities['upcoming'])}")
                    self.logger.info(f"  - Ended: {len(all_activities['ended'])}")
                    
                    if combined:
                        return {'code': 0, 'data': combined}
                    
                    self.logger.warning(f"⚠️ Данные не перехвачены. Captured URLs: {len(captured_urls)}")
                    for url in captured_urls[:10]:
                        self.logger.debug(f"  - {url[:80]}")
                    
                    return None
                        
                finally:
                    try:
                        await context.close()
                    except Exception as e:
                        self.logger.debug(f"Контекст уже закрыт: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных Phemex Candy Drop: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """
        Реализация абстрактного метода парсинга.
        """
        projects = []
        if not data or data.get('code') != 0:
            return projects
        
        project_list = data.get('data', [])
        for project_data in project_list:
            try:
                project = self._parse_project(project_data)
                if project:
                    projects.append(project)
            except Exception as e:
                self.logger.error(f"❌ Ошибка парсинга Phemex Candy Drop проекта: {e}")
                continue
        
        return projects

    def _parse_project(self, project_data: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """
        Парсинг одного проекта из API ответа
        """
        try:
            activity_id = str(project_data.get('activityId', ''))
            name = project_data.get('activityName', '').upper()
            description = project_data.get('description', name)
            
            if not activity_id or not name:
                return None
            
            # Статус: 0=upcoming, 1=active, 2=ended
            api_status = project_data.get('status', 0)
            status_map = {
                0: 'upcoming',
                1: 'active',
                2: 'ended'
            }
            status = status_map.get(api_status, 'unknown')
            
            # Время
            start_time = None
            end_time = None
            
            start_ts = project_data.get('startTime')
            if start_ts:
                start_time = datetime.fromtimestamp(start_ts / 1000)
            
            end_ts = project_data.get('endTime')
            if end_ts:
                # endTime может быть в секундах или миллисекундах
                if end_ts > 10000000000:  # миллисекунды
                    end_time = datetime.fromtimestamp(end_ts / 1000)
                else:  # секунды
                    end_time = datetime.fromtimestamp(end_ts)
            
            # Корректируем статус на основе времени (API иногда возвращает неправильный статус)
            now = datetime.now()
            if start_time and end_time:
                if now < start_time:
                    status = 'upcoming'
                elif start_time <= now <= end_time:
                    status = 'active'
                elif now > end_time:
                    status = 'ended'
            
            # Награды
            reward_amount = project_data.get('rewardAmount', 0)
            reward_tokens = reward_amount / self.REWARD_SCALE if reward_amount else 0
            
            # Участники
            participants = project_data.get('participants', 0)
            
            # Ссылка на проект
            project_url = f"{self.BASE_URL}#{activity_id}"
            
            # Создаём фиктивный пул для совместимости
            pool = LaunchpoolPool(
                stake_coin="USDT",
                pool_reward=reward_tokens,
                participants=participants
            )
            
            project = LaunchpoolProject(
                id=activity_id,
                exchange=self.EXCHANGE_NAME,
                type=self.EXCHANGE_TYPE,
                token_symbol=name,
                token_name=description,
                status=status,
                total_pool_tokens=reward_tokens,
                start_time=start_time,
                end_time=end_time,
                pools=[pool],
                project_url=project_url,
                total_participants=participants,
                description=description
            )
            
            return project
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга проекта Phemex: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None

    def _format_promo_text(self, project: LaunchpoolProject) -> str:
        """
        Форматирование текста промо для уведомлений
        """
        lines = []
        
        # Заголовок
        emoji = project.get_status_emoji()
        lines.append(f"{emoji} *{project.token_symbol}* — Phemex Candy Drop")
        lines.append("")
        
        # Описание
        if project.description and project.description != project.token_symbol:
            lines.append(f"📝 {project.description}")
            lines.append("")
        
        # Награды
        if project.total_pool_tokens > 0:
            lines.append(f"🎁 Пул: *{project.total_pool_tokens:,.0f}* {project.token_symbol}")
        
        # Участники
        if project.total_participants > 0:
            lines.append(f"👥 Участников: *{project.total_participants:,}*")
        
        # Статус
        lines.append(f"📊 Статус: *{project.get_status_text()}*")
        
        # Время
        if project.end_time:
            if project.status == 'active':
                lines.append(f"⏱️ Осталось: *{project.time_remaining_str}*")
            elif project.status == 'upcoming' and project.start_time:
                time_to_start = project.start_time - datetime.now()
                days = time_to_start.days
                hours = time_to_start.seconds // 3600
                if days > 0:
                    lines.append(f"🕐 Начало через: *{days} д. {hours} ч.*")
                elif hours > 0:
                    lines.append(f"🕐 Начало через: *{hours} ч.*")
        
        lines.append("")
        lines.append(f"[🔗 Участвовать]({project.project_url})")
        
        return "\n".join(lines)


# Для тестирования
async def test_parser():
    """Тест парсера"""
    logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')
    
    from utils.browser_pool import get_browser_pool
    pool = get_browser_pool()
    await pool.start()
    
    try:
        parser = PhemexCandydropParser()
        projects = await parser.get_projects_async()
        
        print(f"\n{'='*60}")
        print(f"Phemex Candy Drop: найдено {len(projects)} проектов")
        print('='*60)
        
        for project in projects:
            print(f"\n🎁 {project.token_symbol} ({project.status})")
            print(f"   Описание: {project.description}")
            print(f"   Пул: {project.total_pool_tokens:,.0f} токенов")
            print(f"   Участников: {project.total_participants:,}")
            if project.start_time:
                print(f"   Начало: {project.start_time.strftime('%Y-%m-%d %H:%M')}")
            if project.end_time:
                print(f"   Конец: {project.end_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"   URL: {project.project_url}")
            
    finally:
        await pool.shutdown()


if __name__ == '__main__':
    asyncio.run(test_parser())
