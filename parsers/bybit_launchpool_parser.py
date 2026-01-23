"""
Bybit Launchpool Parser

API: https://www.bybit.com/x-api/spot/api/launchpool/v1/home
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from utils.price_fetcher import get_price_fetcher
from parsers.launchpool_base import (
    LaunchpoolBaseParser, 
    LaunchpoolProject, 
    LaunchpoolPool
)

logger = logging.getLogger(__name__)


class BybitLaunchpoolParser(LaunchpoolBaseParser):
    """
    Парсер для Bybit Launchpool
    
    Структура API ответа:
    {
        "ret_code": 0,
        "result": {
            "totalPrizePool": "67688456",
            "totalUsers": 5733278,
            "totalProjects": 63,
            "list": [
                {
                    "code": "20260119073908",
                    "returnCoin": "ELSA",
                    "returnCoinIcon": "https://...",
                    "desc": "...",
                    "website": "https://...",
                    "whitepaper": "https://...",
                    "totalPoolAmount": "3000000.00000000",
                    "aprHigh": "800",
                    "stakeBeginTime": 1768878000000,
                    "stakeEndTime": 1769680800000,
                    "feTimeStatus": 1,  # 1=активный
                    "stakePoolList": [
                        {
                            "stakePoolCode": "202601190739081",
                            "stakeCoin": "ELSA",
                            "stakeCoinIcon": "https://...",
                            "poolAmount": "1000000.00000000",
                            "minStakeAmount": "400.00000000",
                            "maxStakeAmount": "20000.00000000",
                            "apr": "800",
                            "totalUser": 436,
                            "totalAmount": "2151928.0661",
                            ...
                        }
                    ]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "Bybit"
    EXCHANGE_TYPE = "launchpool"
    BASE_URL = "https://www.bybit.com/en/trade/spot/launchpool"
    API_URL = "https://www.bybit.com/x-api/spot/api/launchpool/v1/home"
    HISTORY_API_URL = "https://www.bybit.com/x-api/spot/api/launchpool/v1/history"
    
    def __init__(self, url: str = None):
        """
        Args:
            url: URL страницы (опционально, для совместимости с ParserService)
        """
        super().__init__()
        self.url = url  # Сохраняем для совместимости
        self.price_fetcher = get_price_fetcher()
        # Улучшенные заголовки для Bybit (обход защиты)
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.bybit.com',
            'Referer': 'https://www.bybit.com/en/trade/spot/launchpool',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
    
    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Получение данных с Bybit API"""
        try:
            self.logger.info(f"🌐 Запрос к Bybit Launchpool API...")
            
            response = self.session.get(self.API_URL, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            # Проверяем успешность
            if data.get('ret_code') != 0:
                self.logger.error(f"❌ Bybit API error: {data.get('ret_msg')}")
                return None
            
            result = data.get('result', {})
            projects_count = len(result.get('list', []))
            self.logger.info(f"✅ Получено {projects_count} проектов от Bybit")
            
            return data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запроса к Bybit: {e}")
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """Парсинг данных Bybit в LaunchpoolProject"""
        projects = []
        
        try:
            result = data.get('result', {})
            items = result.get('list', [])
            
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
            self.logger.error(f"❌ Ошибка парсинга Bybit данных: {e}")
            return []
    
    def _parse_single_project(self, item: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """Парсинг одного проекта"""
        
        # Базовая информация
        code = item.get('code', '')
        token_symbol = item.get('returnCoin', '')
        
        if not token_symbol:
            return None
        
        # Статус
        fe_status = item.get('feTimeStatus', 0)
        status = self._map_status(fe_status)
        
        # Время
        start_time = self.parse_timestamp(item.get('stakeBeginTime'))
        end_time = self.parse_timestamp(item.get('stakeEndTime'))
        
        # Пулы
        pools = []
        stake_pool_list = item.get('stakePoolList', [])
        total_participants = 0
        
        for pool_data in stake_pool_list:
            pool = self._parse_pool(pool_data)
            if pool:
                pools.append(pool)
                total_participants += pool.participants
        
        # Получаем цену токена награды для расчёта USD
        total_pool_tokens = self.safe_float(item.get('totalPoolAmount'))
        total_pool_usd = 0.0
        
        if total_pool_tokens > 0:
            try:
                token_price = self.price_fetcher.get_token_price(token_symbol, preferred_exchange='bybit')
                if token_price:
                    total_pool_usd = total_pool_tokens * token_price
                    self.logger.debug(f"💰 {token_symbol}: ${token_price:.6f} × {total_pool_tokens:.0f} = ${total_pool_usd:.2f}")
            except Exception as e:
                self.logger.debug(f"⚠️ Не удалось получить цену {token_symbol}: {e}")
        
        # Создаём проект
        project = LaunchpoolProject(
            id=code,
            exchange=self.EXCHANGE_NAME,
            type=self.EXCHANGE_TYPE,
            token_symbol=token_symbol,
            token_name=token_symbol,  # Bybit не даёт полное имя
            token_icon=item.get('returnCoinIcon', ''),
            status=status,
            total_pool_tokens=total_pool_tokens,
            total_pool_usd=total_pool_usd,
            start_time=start_time,
            end_time=end_time,
            pools=pools,
            project_url=f"https://www.bybit.com/en/trade/spot/launchpool/{code}",
            website=item.get('website', ''),
            whitepaper=item.get('whitepaper', ''),
            description=item.get('desc', ''),
            total_participants=total_participants,
        )
        
        return project
    
    def _parse_pool(self, pool_data: Dict[str, Any]) -> Optional[LaunchpoolPool]:
        """Парсинг одного пула"""
        stake_coin = pool_data.get('stakeCoin', '')
        if not stake_coin:
            return None
        
        # Определяем метки
        labels = []
        pool_tag = pool_data.get('poolTag', 0)
        if pool_tag == 1:
            labels.append("🔥")
        
        if pool_data.get('useNewUserFunction'):
            labels.append("🆕")
        
        pool = LaunchpoolPool(
            stake_coin=stake_coin,
            stake_coin_icon=pool_data.get('stakeCoinIcon', ''),
            apr=self.safe_float(pool_data.get('apr')),
            min_stake=self.safe_float(pool_data.get('minStakeAmount')),
            max_stake=self.safe_float(pool_data.get('maxStakeAmount')),
            max_stake_vip=self.safe_float(pool_data.get('maxVipAmount')),
            total_staked=self.safe_float(pool_data.get('totalAmount')),
            pool_reward=self.safe_float(pool_data.get('poolAmount')),
            participants=self.safe_int(pool_data.get('totalUser')),
            is_new_user_only=bool(pool_data.get('useNewUserFunction')),
            labels=labels,
        )
        
        return pool
    
    def _map_status(self, fe_status: int) -> str:
        """Маппинг статуса Bybit"""
        # feTimeStatus: 0=upcoming, 1=active, 2=ended
        status_map = {
            0: 'upcoming',
            1: 'active',
            2: 'ended',
        }
        return status_map.get(fe_status, 'unknown')
    
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
    
    parser = BybitLaunchpoolParser()
    
    # Получаем все проекты
    projects = parser.get_projects()
    
    print(f"\n{'='*60}")
    print(f"Найдено проектов: {len(projects)}")
    print('='*60)
    
    # Выводим первый активный проект
    active = [p for p in projects if p.status == 'active']
    if active:
        print("\n📊 Пример форматирования:")
        print(parser.format_project(active[0]))
    else:
        print("\n⚠️ Нет активных проектов")
        if projects:
            print("\n📊 Первый проект:")
            print(parser.format_project(projects[0]))
