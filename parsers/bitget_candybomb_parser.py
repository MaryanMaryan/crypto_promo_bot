"""
Bitget Candy Bomb Parser

API: https://www.bitget.com/v1/act/candyBombNew/current/list
Примечание: Это airdrop/задания, НЕ стейкинг (отличается от Launchpool/PoolX)

Candy Bomb - это программа airdrop Bitget с заданиями для получения бесплатных токенов

Требует Playwright для обхода защиты Bitget (403 без cookie)
"""

import logging
import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime

from parsers.launchpool_base import (
    LaunchpoolBaseParser, 
    LaunchpoolProject, 
    LaunchpoolPool
)
from utils.browser_pool import get_browser_pool

logger = logging.getLogger(__name__)


class BitgetCandybombParser(LaunchpoolBaseParser):
    """
    Парсер для Bitget Candy Bomb (airdrop/задания)
    
    Структура API ответа /v1/act/candyBombNew/current/list:
    {
        "code": "00000",
        "data": {
            "notStartedActivities": [...],   # Предстоящие
            "processingActivities": [        # Активные
                {
                    "id": "232994",
                    "name": "SKR",
                    "desc": "...",
                    "coinIcon": "https://...",
                    "startTime": "1768960800740",
                    "endTime": "1769565600740",
                    "airDropTime": "1769580000608",
                    "ieoTotal": 666666,
                    "ieoTotalUsdt": 7914.65,
                    "totalPeople": 2,
                    "activityStatus": 1,      # 0=upcoming, 1=active, 5=ended
                    "bizLineLabel": "contract", # spot/contract
                    "rewardCarousels": [...]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "Bitget"
    EXCHANGE_TYPE = "candybomb"
    BASE_URL = "https://www.bitget.com/uk/events/candy-bomb"
    
    API_URLS = {
        'current': 'https://www.bitget.com/v1/act/candyBombNew/current/list',
        'history': 'https://www.bitget.com/v1/act/candyBombNew/history/listV2',
        'panel': 'https://www.bitget.com/v1/act/candyBombNew/panel',
    }
    
    DEFAULT_HEADERS = {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json;charset=UTF-8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'language': 'uk_UA',
        'locale': 'uk_UA',
        'terminaltype': '1',
        'securitynew': 'true',
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
        Candy Bomb требует браузер для обхода защиты (403 без cookies).
        """
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._fetch_via_browser())
                return future.result()
        except RuntimeError:
            return asyncio.run(self._fetch_via_browser())
    
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
                
                api_data = None
                captured_urls = []
                
                async def handle_response(response):
                    nonlocal api_data
                    url = response.url
                    
                    # Логируем API запросы
                    if 'bitget.com' in url and '/v1/' in url:
                        captured_urls.append(url)
                    
                    # Перехватываем candyBomb current/list API
                    if 'candyBombNew/current/list' in url:
                        try:
                            if response.status == 200 and 'json' in response.headers.get('content-type', ''):
                                data = await response.json()
                                self.logger.info(f"📦 Candy Bomb current/list: {str(data)[:200]}")
                                
                                if data.get('code') == '00000' and data.get('data'):
                                    data_content = data.get('data')
                                    
                                    # Объединяем active и upcoming
                                    all_activities = []
                                    processing = data_content.get('processingActivities', [])
                                    not_started = data_content.get('notStartedActivities', [])
                                    
                                    all_activities.extend(processing)
                                    all_activities.extend(not_started)
                                    
                                    if all_activities:
                                        api_data = {'code': '00000', 'data': all_activities}
                                        self.logger.info(f"✅ Перехвачен Candy Bomb API: {len(all_activities)} акций")
                                        
                        except Exception as e:
                            self.logger.debug(f"Пропуск: {e}")
                
                try:
                    page = await context.new_page()
                    page.on('response', handle_response)
                    
                    self.logger.info("🌐 Загружаем страницу Bitget Candy Bomb...")
                    await page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(4)
                    
                    # Прокручиваем для загрузки
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(2)
                    
                    if api_data:
                        return api_data
                    
                    self.logger.info(f"📋 Перехваченные URL: {len(captured_urls)}")
                    for url in captured_urls[:10]:
                        self.logger.debug(f"  - {url[:80]}")
                    
                    return None
                        
                finally:
                    try:
                        await context.close()
                    except Exception as e:
                        self.logger.debug(f"Контекст уже закрыт: {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных Candy Bomb: {e}")
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
                if project:
                    projects.append(project)
            except Exception as e:
                self.logger.error(f"❌ Ошибка парсинга Candy Bomb проекта: {e}")
                continue
        
        return projects

    def _parse_project(self, project_data: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """
        Парсинг одного проекта из API ответа
        """
        try:
            # Базовая информация
            project_id = str(project_data.get('id', ''))
            token_symbol = project_data.get('name', '').upper()
            description = project_data.get('desc', '')
            token_icon = project_data.get('coinIcon', '')
            
            if not project_id or not token_symbol:
                return None
            
            # Время (timestamp в миллисекундах)
            start_time = self.parse_timestamp(project_data.get('startTime'), is_milliseconds=True)
            end_time = self.parse_timestamp(project_data.get('endTime'), is_milliseconds=True)
            airdrop_time = self.parse_timestamp(project_data.get('airDropTime'), is_milliseconds=True)
            
            # Награды
            total_tokens = self.safe_float(project_data.get('ieoTotal', 0))
            total_usd = self.safe_float(project_data.get('ieoTotalUsdt', 0))
            
            # Участники
            total_participants = int(project_data.get('totalPeople', 0))
            
            # Статус: 0=upcoming, 1=active, 5=ended
            activity_status = int(project_data.get('activityStatus', 0))
            
            if activity_status == 0:
                status = "upcoming"
            elif activity_status == 1:
                status = "active"
            elif activity_status >= 5:
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
            
            # Тип линейки бизнеса
            biz_line = project_data.get('bizLineLabel', 'spot')  # spot / contract
            
            # Создаём "виртуальный" пул для награды
            # Candy Bomb не использует стейкинг, но мы форматируем как reward pool
            pools = []
            
            # Награды по типам (rewardCarousels)
            reward_carousels = project_data.get('rewardCarousels', [])
            
            for i, reward in enumerate(reward_carousels):
                coin_name = reward.get('coinName', token_symbol)
                award = self.safe_float(reward.get('award', 0))
                target_type = reward.get('targetType', 0)
                
                # targetType определяет тип задания:
                # 4 = общие задания
                # 39 = для новых пользователей контрактов
                # 99 = реферальный бонус
                task_type = self._get_task_type_name(target_type)
                
                pool = LaunchpoolPool(
                    stake_coin=task_type,  # Используем как название задания
                    pool_reward=award,
                    labels=[biz_line.upper()],
                    extra_data={
                        'reward_coin': coin_name,
                        'target_type': target_type,
                        'is_airdrop': True,
                    }
                )
                pools.append(pool)
            
            # Если нет carousels, создаём общий пул
            if not pools and total_tokens > 0:
                pools.append(LaunchpoolPool(
                    stake_coin="Airdrop",
                    pool_reward=total_tokens,
                    labels=[biz_line.upper()],
                    extra_data={
                        'reward_coin': token_symbol,
                        'is_airdrop': True,
                    }
                ))
            
            # URL проекта
            project_url = f"https://www.bitget.com/uk/events/candy-bomb"
            
            # Проверяем условия участия
            is_new_contract_only = project_data.get('newContractUserLabel', False)
            is_new_user_only = project_data.get('newUserLabel', False)
            signup_condition = project_data.get('signupConditionConfigLabel', False)
            
            # Добавляем метки (на русском)
            condition_labels = []
            if is_new_contract_only:
                condition_labels.append("Новые пользователи фьючерсов")
            if is_new_user_only:
                condition_labels.append("Новые пользователи")
            if signup_condition:
                condition_type = project_data.get('signupConditionType', 0)
                if condition_type == 1:
                    condition_labels.append("Требуется KYC")
                elif condition_type == 2:
                    condition_labels.append("Требуется торговля фьючерсами")
            
            return LaunchpoolProject(
                id=project_id,
                exchange=self.EXCHANGE_NAME,
                type=self.EXCHANGE_TYPE,
                token_symbol=token_symbol,
                token_name=token_symbol,  # Candy Bomb не даёт полное название
                token_icon=token_icon,
                status=status,
                status_text=self._get_status_text(status, condition_labels),
                total_pool_usd=total_usd,
                total_pool_tokens=total_tokens,
                start_time=start_time,
                end_time=end_time,
                pools=pools,
                project_url=project_url,
                description=description[:500] if description else "",
                total_participants=total_participants,
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга Candy Bomb: {e}")
            return None
    
    def _get_task_type_name(self, target_type: int) -> str:
        """Получение названия типа задания на русском"""
        type_names = {
            4: "Общие задания",
            39: "Торговля фьючерсами",
            99: "Реферальный бонус",
        }
        return type_names.get(target_type, f"Задание #{target_type}")
    
    def _get_status_text(self, status: str, condition_labels: List[str]) -> str:
        """Получение текста статуса с условиями"""
        status_map = {
            'active': 'Активный',
            'upcoming': 'Скоро начнётся',
            'ended': 'Завершён',
        }
        base_text = status_map.get(status, 'Неизвестно')
        
        if condition_labels:
            # Переводим условия на русский
            ru_labels = []
            for label in condition_labels:
                label_map = {
                    "Нові користувачі ф'ючерсів": "Новые пользователи фьючерсов",
                    "Нові користувачі": "Новые пользователи",
                    "Потрібна KYC": "Требуется KYC",
                    "Потрібна торгівля ф'ючерсами": "Требуется торговля фьючерсами",
                }
                ru_labels.append(label_map.get(label, label))
            return f"{base_text} ({', '.join(ru_labels)})"
        return base_text
    
    def _get_task_type_name_ru(self, target_type: int) -> str:
        """Получение названия типа задания на русском"""
        type_names = {
            4: "Общие задания",
            39: "Торговля фьючерсами",
            99: "Реферальный бонус",
        }
        return type_names.get(target_type, f"Задание #{target_type}")
    
    def format_project(self, project: LaunchpoolProject) -> str:
        """
        Специальное форматирование для Candy Bomb (airdrop с заданиями).
        Компактный формат на русском языке с HTML разметкой.
        """
        lines = []
        
        # Заголовок в стиле Gate (с выделением)
        lines.append(f"<b>🟠 BITGET | 🍬 CANDY BOMB | {project.token_symbol}</b>")
        lines.append("")
        
        # Статус
        lines.append(f"📊 Статус: {project.get_status_emoji()} {project.status_text or project.get_status_text()}")
        
        # Пул (токены первые, USD в скобках, с выделением)
        if project.total_pool_usd > 0 and project.total_pool_tokens > 0:
            lines.append(f"<b>💰 Пул: {project.total_pool_tokens:,.0f} {project.token_symbol} (${project.total_pool_usd:,.2f})</b>")
        elif project.total_pool_usd > 0:
            lines.append(f"<b>💰 Пул: ${project.total_pool_usd:,.2f}</b>")
        elif project.total_pool_tokens > 0:
            lines.append(f"<b>💰 Пул: {project.total_pool_tokens:,.0f} {project.token_symbol}</b>")
        
        # Участники
        if project.total_participants > 0:
            lines.append(f"👥 Участников: {project.total_participants:,}")
        
        # Осталось времени
        lines.append(f"⏰ Осталось: {project.time_remaining_str}")
        
        # Задания с USD стоимостью
        if project.pools:
            lines.append("")
            lines.append("🎯 Задания:")
            
            # Рассчитываем цену за токен
            token_price = 0.0
            if project.total_pool_usd > 0 and project.total_pool_tokens > 0:
                token_price = project.total_pool_usd / project.total_pool_tokens
            
            for pool in project.pools:
                reward_coin = pool.extra_data.get('reward_coin', project.token_symbol) if pool.extra_data else project.token_symbol
                biz_line = pool.labels[0] if pool.labels else ""
                
                # Переводим название задания на русский
                task_name = pool.stake_coin
                task_map = {
                    "Загальні завдання": "Общие задания",
                    "Торгівля ф'ючерсами": "Торговля фьючерсами",
                    "Реферальний бонус": "Реферальный бонус",
                    "Airdrop": "Airdrop",
                }
                task_name_ru = task_map.get(task_name, task_name)
                
                # Метка SPOT/CONTRACT
                biz_label = f" [{biz_line}]" if biz_line else ""
                
                # Рассчитываем USD стоимость награды
                reward_usd = pool.pool_reward * token_price if token_price > 0 else 0
                usd_str = f" (~${reward_usd:,.2f})" if reward_usd > 0 else ""
                
                lines.append(f"  • {task_name_ru} → {pool.pool_reward:,.0f} {reward_coin}{biz_label}{usd_str}")
        
        # Период (компактно в одну строку)
        if project.start_time and project.end_time:
            lines.append("")
            lines.append(f"📅 {project.start_time.strftime('%d.%m.%Y %H:%M')} — {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC")
        
        # Ссылка (сокращённая)
        lines.append("")
        lines.append(f"🔗 bitget.com/uk/events/candy-bomb")
        
        return "\n".join(lines)
    
    async def get_projects_async(self, status_filter: str = None) -> List[LaunchpoolProject]:
        """
        Асинхронный метод получения проектов
        
        Args:
            status_filter: Фильтр статуса ('active', 'upcoming', 'ended' или None для всех)
        """
        data = await self._fetch_via_browser()
        if data:
            projects = self.parse_projects(data)
            if status_filter:
                projects = [p for p in projects if p.status == status_filter]
            return projects
        return []
    
    def get_projects(self, status_filter: str = None) -> List[LaunchpoolProject]:
        """
        Синхронный метод получения проектов
        
        Args:
            status_filter: Фильтр статуса ('active', 'upcoming', 'ended' или None для всех)
        """
        data = self.fetch_data()
        if data:
            projects = self.parse_projects(data)
            if status_filter:
                projects = [p for p in projects if p.status == status_filter]
            return projects
        return []


# Для тестирования
if __name__ == '__main__':
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    async def test():
        print("="*60)
        print("Testing Bitget Candy Bomb Parser")
        print("="*60)
        
        parser = BitgetCandybombParser()
        projects = await parser.get_projects_async()
        
        print(f"\nНайдено проектів: {len(projects)}\n")
        
        for p in projects:
            print(parser.format_project(p))
            print()
    
    asyncio.run(test())
