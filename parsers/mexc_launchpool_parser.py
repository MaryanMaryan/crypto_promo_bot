"""
MEXC Launchpool Parser

API: https://www.mexc.com/api/operateactivity/launchpool/list?activityCoin=
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from parsers.launchpool_base import (
    LaunchpoolBaseParser, 
    LaunchpoolProject, 
    LaunchpoolPool
)

logger = logging.getLogger(__name__)


class MexcLaunchpoolParser(LaunchpoolBaseParser):
    """
    Парсер для MEXC Launchpool
    
    Структура API ответа:
    {
        "code": 0,
        "data": [
            {
                "id": 12345,
                "activityName": "PROJECT Token",
                "activityCoin": "PRJ",
                "activityStatus": "UNDERWAY",  # UNDERWAY, FINISHED, WAITING
                "startTime": 1768878000000,
                "endTime": 1769680800000,
                "officialUrl": "https://...",
                "launchpoolDetailList": [
                    {
                        "id": 123,
                        "pledgeCurrency": "MX",  # токен для стейкинга
                        "apr": 0.2409,  # APR как доля (0.2409 = 24.09%)
                        "pledgeMax": 10000,
                        "pledgeMin": 100,
                        "joinType": "ALL_USER",  # ALL_USER, NEW_USER
                        "participantsNumber": 1500,
                        "totalPledge": 500000,
                        "poolReward": 100000,
                        ...
                    }
                ]
            }
        ]
    }
    """
    
    EXCHANGE_NAME = "MEXC"
    EXCHANGE_TYPE = "launchpool"
    BASE_URL = "https://www.mexc.com/ru-RU/launchpool"
    API_URL = "https://www.mexc.com/api/operateactivity/launchpool/list?activityCoin="
    OVERVIEW_API_URL = "https://www.mexc.com/api/operateactivity/launchpool/overview"
    
    def __init__(self, url: str = None):
        """
        Args:
            url: URL страницы (опционально, для совместимости с ParserService)
        """
        super().__init__()
        self.url = url  # Сохраняем для совместимости
        # Заголовки для MEXC
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.mexc.com',
            'Referer': 'https://www.mexc.com/ru-RU/launchpool',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
    
    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Получение данных с MEXC API"""
        try:
            self.logger.info(f"🌐 Запрос к MEXC Launchpool API...")
            
            response = self.session.get(self.API_URL, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            # Проверяем успешность
            if data.get('code') != 0:
                self.logger.error(f"❌ MEXC API error: {data.get('msg')}")
                return None
            
            projects_count = len(data.get('data', []))
            self.logger.info(f"✅ Получено {projects_count} проектов от MEXC Launchpool")
            
            return data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запроса к MEXC: {e}")
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """Парсинг данных MEXC в LaunchpoolProject"""
        projects = []
        
        try:
            items = data.get('data', [])
            
            for item in items:
                try:
                    project = self._parse_single_project(item)
                    if project:
                        projects.append(project)
                except Exception as e:
                    self.logger.error(f"❌ Ошибка парсинга проекта: {e}")
                    continue
            
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга MEXC данных: {e}")
            return []
    
    def _parse_single_project(self, item: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """Парсинг одного проекта"""
        
        # Базовая информация
        project_id = str(item.get('id', ''))
        token_symbol = item.get('activityCoin', '')
        token_name = item.get('activityName', token_symbol)
        
        if not token_symbol:
            return None
        
        # Статус
        activity_status = item.get('activityStatus', '')
        status = self._map_status(activity_status)
        
        # Время
        start_time = self.parse_timestamp(item.get('startTime'))
        end_time = self.parse_timestamp(item.get('endTime'))
        
        # Пулы
        pools = []
        detail_list = item.get('launchpoolDetailList', [])
        total_participants = 0
        total_pool_tokens = 0.0
        
        for pool_data in detail_list:
            pool = self._parse_pool(pool_data, token_symbol)
            if pool:
                pools.append(pool)
                total_participants += pool.participants
                total_pool_tokens += pool.pool_reward
        
        # Ссылки
        official_url = item.get('officialUrl', '')
        twitter = item.get('twitterUrl', '')
        
        # Создаём проект
        project = LaunchpoolProject(
            id=project_id,
            exchange=self.EXCHANGE_NAME,
            type=self.EXCHANGE_TYPE,
            token_symbol=token_symbol,
            token_name=token_name,
            token_icon=item.get('activityCoinLogo', ''),
            status=status,
            total_pool_tokens=total_pool_tokens,
            start_time=start_time,
            end_time=end_time,
            pools=pools,
            project_url=f"https://www.mexc.com/ru-RU/launchpool/{token_symbol}",
            website=official_url,
            twitter=twitter,
            description=item.get('description', ''),
            total_participants=total_participants,
        )
        
        return project
    
    def _parse_pool(self, pool_data: Dict[str, Any], reward_token: str) -> Optional[LaunchpoolPool]:
        """Парсинг одного пула"""
        stake_coin = pool_data.get('pledgeCurrency', '')
        if not stake_coin:
            return None
        
        # APR в MEXC приходит как доля (0.2409 = 24.09%), конвертируем в проценты
        apr_raw = self.safe_float(pool_data.get('apr', 0))
        # Если APR < 10, значит это доля, умножаем на 100
        if apr_raw < 10:
            apr = apr_raw * 100
        else:
            apr = apr_raw
        
        # Определяем метки
        labels = []
        join_type = pool_data.get('joinType', '')
        is_new_user_only = join_type == 'NEW_USER'
        
        if is_new_user_only:
            labels.append("🆕")
        
        # Добавляем 🔥 для высокого APR
        if apr > 100:
            labels.append("🔥")
        
        pool = LaunchpoolPool(
            stake_coin=stake_coin,
            stake_coin_icon=pool_data.get('pledgeCurrencyLogo', ''),
            apr=apr,
            min_stake=self.safe_float(pool_data.get('pledgeMin')),
            max_stake=self.safe_float(pool_data.get('pledgeMax')),
            max_stake_vip=self.safe_float(pool_data.get('vipPledgeMax')),
            total_staked=self.safe_float(pool_data.get('totalPledge')),
            pool_reward=self.safe_float(pool_data.get('poolReward')),
            participants=self.safe_int(pool_data.get('participantsNumber')),
            is_new_user_only=is_new_user_only,
            labels=labels,
        )
        
        return pool
    
    def _map_status(self, activity_status: str) -> str:
        """Маппинг статуса MEXC"""
        status_map = {
            'UNDERWAY': 'active',
            'WAITING': 'upcoming',
            'FINISHED': 'ended',
            'ENDED': 'ended',
        }
        return status_map.get(activity_status.upper(), 'unknown')
    
    def get_active_projects(self) -> List[LaunchpoolProject]:
        """Получить только активные проекты"""
        return self.get_projects(status_filter='active')
    
    def get_upcoming_projects(self) -> List[LaunchpoolProject]:
        """Получить предстоящие проекты"""
        return self.get_projects(status_filter='upcoming')


# === Тестирование ===

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = MexcLaunchpoolParser()
    
    # Получаем все проекты
    projects = parser.get_projects()
    
    print(f"\n{'='*60}")
    print(f"🏦 MEXC Launchpool - Найдено проектов: {len(projects)}")
    print('='*60)
    
    # Статистика по статусам
    active = [p for p in projects if p.status == 'active']
    upcoming = [p for p in projects if p.status == 'upcoming']
    ended = [p for p in projects if p.status == 'ended']
    
    print(f"\n📊 Статистика:")
    print(f"   ✅ Активных: {len(active)}")
    print(f"   🟡 Предстоящих: {len(upcoming)}")
    print(f"   ⏹️ Завершённых: {len(ended)}")
    
    # Выводим активные проекты
    if active:
        print("\n" + "="*60)
        print("📊 АКТИВНЫЕ ПРОЕКТЫ:")
        print("="*60)
        for project in active:
            print(parser.format_project(project))
            print()
    elif projects:
        print("\n⚠️ Нет активных проектов")
        print("\n📊 Первый проект:")
        print(parser.format_project(projects[0]))
    else:
        print("\n❌ Проекты не найдены")
