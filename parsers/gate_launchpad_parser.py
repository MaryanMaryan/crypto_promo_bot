"""
Gate.io Launchpad Parser

API: https://www.gate.com/apiw/v2/launch/launchpad/list_v2?page=1&size=10&project_status=IN_PROCESS

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


class GateLaunchpadParser(LaunchpoolBaseParser):
    """
    Парсер для Gate.io Launchpad
    
    Структура API ответа list_v2:
    {
        "code": 200,
        "message": "Успешно",
        "data": {
            "page": 1,
            "total_page": 1,
            "total_count": 6,
            "preheat_total": 0,
            "underway_total": 1,
            "finish_total": 5,
            "list": [
                {
                    "id": 2374,
                    "name": "Immunefi",
                    "curr_type": "IMU",
                    "icon": "https://...",
                    "status": "UNDERWAY",  # UNDERWAY, PREHEAT, FINISH
                    "status_text": "В процессе",
                    "show_total_allocation": "3 000 000",
                    "subscribe_start_time": 1768878000,
                    "subscribe_end_time": 1769680800,
                    "products": [
                        {
                            "id": 123,
                            "type": "USD1",  # тип подписки (USD1, GUSD, GT)
                            "show_subscription_price": "0.15",
                            "participants": 500,
                            "raise_amount_target": "450000",
                            "raise_amount_current": "300000"
                        }
                    ]
                }
            ]
        }
    }
    """
    
    EXCHANGE_NAME = "Gate.io"
    EXCHANGE_TYPE = "launchpad"
    BASE_URL = "https://www.gate.com/ru/launchpad"
    API_URL = "https://www.gate.com/apiw/v2/launch/launchpad/list_v2?page=1&size=50&project_status=IN_PROCESS"
    
    def __init__(self, url: str = None):
        """
        Args:
            url: URL страницы (опционально, для совместимости с ParserService)
        """
        super().__init__()
        self.url = url
        
        # Заголовки для Gate.io (из браузера)
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.gate.com',
            'Referer': 'https://www.gate.com/ru/launchpad',
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
        """Получение данных с Gate.io Launchpad API"""
        
        # Сначала пробуем обычный HTTP запрос
        data = self._fetch_via_http()
        if data:
            return data
        
        # Если не получилось - пробуем через браузер
        self.logger.info("⚠️ HTTP запрос не удался, пробуем через браузер...")
        try:
            return asyncio.get_event_loop().run_until_complete(self._fetch_via_browser())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._fetch_via_browser())
            finally:
                loop.close()
    
    def _fetch_via_http(self) -> Optional[Dict[str, Any]]:
        """Попытка получить данные через HTTP"""
        try:
            self.logger.info(f"🌐 Запрос к Gate.io Launchpad API...")
            
            response = self.session.get(self.API_URL, timeout=15)
            
            if 'application/json' not in response.headers.get('content-type', ''):
                self.logger.warning(f"⚠️ Gate.io Launchpad вернул не JSON: {response.status_code}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') != 200:
                self.logger.error(f"❌ Gate.io Launchpad API error: {data.get('message')}")
                return None
            
            result = data.get('data', {})
            projects_count = len(result.get('list', []))
            self.logger.info(f"✅ Получено {projects_count} проектов от Gate.io Launchpad (HTTP)")
            
            return data
            
        except Exception as e:
            self.logger.warning(f"⚠️ HTTP запрос к Gate.io Launchpad не удался: {e}")
            return None
    
    async def _fetch_via_browser(self) -> Optional[Dict[str, Any]]:
        """Получение данных через Playwright браузер"""
        try:
            from playwright.async_api import async_playwright
            
            self.logger.info(f"🌐 Запрос к Gate.io Launchpad через браузер...")
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                api_data = None
                
                async def handle_response(response):
                    nonlocal api_data
                    if 'launchpad/list_v2' in response.url and 'IN_PROCESS' in response.url:
                        try:
                            if response.status == 200:
                                api_data = await response.json()
                                self.logger.info(f"✅ Перехвачен Launchpad API ответ Gate.io")
                        except:
                            pass
                
                page.on('response', handle_response)
                
                await page.goto(self.BASE_URL, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(3000)
                
                await browser.close()
                
                if api_data:
                    result = api_data.get('data', {})
                    projects_count = len(result.get('list', []))
                    self.logger.info(f"✅ Получено {projects_count} проектов от Gate.io Launchpad (браузер)")
                    return api_data
                else:
                    self.logger.error("❌ Не удалось получить данные Launchpad через браузер")
                    return None
                    
        except ImportError:
            self.logger.error("❌ Playwright не установлен. pip install playwright && playwright install chromium")
            return None
        except Exception as e:
            self.logger.error(f"❌ Ошибка браузера Gate.io Launchpad: {e}")
            return None
    
    def parse_projects(self, data: Dict[str, Any]) -> List[LaunchpoolProject]:
        """Парсинг данных Gate.io Launchpad в LaunchpoolProject"""
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
                    self.logger.error(f"❌ Ошибка парсинга проекта Gate.io Launchpad: {e}")
                    continue
            
            return projects
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга Gate.io Launchpad данных: {e}")
            return []
    
    def _parse_single_project(self, item: Dict[str, Any]) -> Optional[LaunchpoolProject]:
        """Парсинг одного проекта Launchpad"""
        
        # Базовая информация
        project_id = str(item.get('id', ''))
        token_symbol = item.get('curr_type', '')
        token_name = item.get('name', '') or token_symbol
        
        if not token_symbol:
            return None
        
        # Статус
        status_raw = item.get('status', '').upper()
        status = self._map_status(status_raw)
        status_text = item.get('status_text', '')
        
        # Время
        start_ts = item.get('subscribe_start_time') or item.get('open_timest_unix')
        end_ts = item.get('subscribe_end_time') or item.get('close_timest_unix')
        
        # Gate.io использует секунды в unix timestamp
        start_time = self.parse_timestamp(start_ts, is_milliseconds=False) if start_ts else None
        end_time = self.parse_timestamp(end_ts, is_milliseconds=False) if end_ts else None
        
        # Проверка на миллисекунды
        if start_time and start_time.year < 2024:
            start_time = self.parse_timestamp(start_ts, is_milliseconds=True)
        if end_time and end_time.year < 2024:
            end_time = self.parse_timestamp(end_ts, is_milliseconds=True)
        
        # Общее количество токенов
        total_allocation_str = item.get('show_total_allocation', '0')
        total_tokens = self._parse_number(total_allocation_str)
        
        # Продукты подписки как пулы
        pools = []
        products = item.get('products', [])
        total_participants = 0
        
        for product in products:
            pool = self._parse_product_as_pool(product, token_symbol)
            if pool:
                pools.append(pool)
                total_participants += pool.participants
        
        # Ссылки
        website = item.get('website', '') or item.get('official_website', '')
        twitter = item.get('twitter', '') or item.get('twitter_url', '')
        
        # Создаём проект
        project = LaunchpoolProject(
            id=project_id,
            exchange=self.EXCHANGE_NAME,
            type=self.EXCHANGE_TYPE,
            token_symbol=token_symbol,
            token_name=token_name,
            token_icon=item.get('icon', ''),
            status=status,
            status_text=status_text,
            total_pool_tokens=total_tokens,
            start_time=start_time,
            end_time=end_time,
            pools=pools,
            project_url=f"https://www.gate.com/ru/launchpad/{project_id}",
            website=website,
            twitter=twitter,
            description=item.get('desc', '') or item.get('description', ''),
            total_participants=total_participants,
        )
        
        return project
    
    def _parse_product_as_pool(self, product: Dict[str, Any], reward_token: str) -> Optional[LaunchpoolPool]:
        """
        Парсинг продукта подписки как пула.
        В Launchpad продукты это разные способы подписки (USD1, GUSD, GT).
        """
        product_type = product.get('type', '') or product.get('subscribe_type', '')
        if not product_type:
            product_type = 'USDT'  # По умолчанию
        
        # Цена токена для подписки
        price = self.safe_float(product.get('show_subscription_price', 0)) or self.safe_float(product.get('product_unit_price', 0))
        
        # Участники
        participants = self.safe_int(product.get('participants', 0))
        
        # Распределяемые токены (allocation) - может быть строка с форматированием
        allocation_str = product.get('show_allocation', '0')
        allocation = self._parse_number(allocation_str)
        
        # Внесенная сумма (show_total_lockup_amount)
        raise_current_str = product.get('show_total_lockup_amount', '0')
        raise_current = self._parse_number(raise_current_str)
        
        # Лимит на подписчика в токенах (show_delivery_max_amount)
        personal_limit_str = product.get('show_delivery_max_amount', '0')
        personal_limit = self._parse_number(personal_limit_str)
        
        min_subscribe = self.safe_float(product.get('min_subscribe_amount', 0))
        
        # В launchpad нет APR
        apr = 0.0
        
        # Метки
        labels = []
        if product.get('is_new_user_only') or product.get('new_user_only'):
            labels.append('🆕 Новые')
        if product.get('label'):
            labels.append(product.get('label'))
        
        pool = LaunchpoolPool(
            stake_coin=product_type,  # USD1, GUSD, GT - типы подписки
            stake_coin_icon=product.get('pay_type_icon', ''),
            apr=apr,
            min_stake=min_subscribe,
            max_stake=personal_limit,  # Лимит в токенах
            total_staked=raise_current,  # Внесенная сумма в USD
            pool_reward=allocation,  # Распределяемые токены
            participants=participants,
            is_new_user_only=bool(product.get('is_new_user_only') or product.get('new_user_only')),
            labels=labels,
            # Дополнительные поля для Launchpad
            extra_data={
                'subscription_price': price,
                'allocation_amount': allocation,
                'raise_current': raise_current,
                'personal_limit': personal_limit,
            }
        )
        
        return pool
    
    def _parse_number(self, value: Any) -> float:
        """Парсинг числа из строки с пробелами и форматированием"""
        if not value:
            return 0.0
        try:
            # Убираем пробелы и запятые
            cleaned = str(value).replace(' ', '').replace(',', '').replace('\xa0', '')
            return float(cleaned)
        except:
            return 0.0
    
    def _map_status(self, status_code: str) -> str:
        """Маппинг статуса Gate.io Launchpad"""
        status_map = {
            'UNDERWAY': 'active',
            'IN_PROCESS': 'active',
            'PREHEAT': 'upcoming',
            'NOT_STARTED': 'upcoming',
            'FINISH': 'ended',
            'FINISHED': 'ended',
            'CANCELLED': 'ended',
        }
        return status_map.get(status_code.upper(), 'unknown')
    
    def format_project(self, project: LaunchpoolProject) -> str:
        """
        Форматирование проекта Launchpad для Telegram.
        Переопределяем для специфичного формата Launchpad с расчётом аллокации.
        """
        lines = []
        
        # Токен
        lines.append(f"🪙 {project.token_name} ({project.token_symbol})")
        status_emoji = '✅' if project.status == 'active' else ('🟡' if project.status == 'upcoming' else '⏹️')
        status_text = project.status_text or project.get_status_text()
        lines.append(f"📊 Статус: {status_emoji} {status_text}")
        
        if project.time_remaining_str and project.time_remaining_str != "—":
            lines.append(f"⏰ Осталось: {project.time_remaining_str}")
        
        # Продукты подписки с расчётом аллокации
        if project.pools:
            for pool in project.pools:
                lines.append("")
                lines.append(f"📦 ПУЛ {pool.stake_coin}")
                
                # Получаем данные из extra_data
                extra = getattr(pool, 'extra_data', {}) or {}
                subscription_price = extra.get('subscription_price', 0)
                allocation_amount = extra.get('allocation_amount', 0) or pool.pool_reward
                raise_current = extra.get('raise_current', 0) or pool.total_staked
                personal_limit = extra.get('personal_limit', 0) or pool.max_stake
                
                # Стоимость подписки
                if subscription_price > 0:
                    lines.append(f"   🏷️ Цена: 1 {project.token_symbol} = ${subscription_price}")
                
                # Распределяется токенов
                if allocation_amount > 0:
                    alloc_value = allocation_amount * subscription_price if subscription_price > 0 else 0
                    if alloc_value > 0:
                        lines.append(f"   🎁 Распределяется: {self._format_number(allocation_amount)} {project.token_symbol} (${self._format_money(alloc_value)})")
                    else:
                        lines.append(f"   🎁 Распределяется: {self._format_number(allocation_amount)} {project.token_symbol}")
                
                # Внесенная сумма
                if raise_current > 0:
                    lines.append(f"   💵 Внесено: ${self._format_money(raise_current)}")
                
                # Переподписка
                if allocation_amount > 0 and raise_current > 0 and subscription_price > 0:
                    pool_value = allocation_amount * subscription_price
                    if pool_value > 0:
                        oversubscription = raise_current / pool_value
                        lines.append(f"   📊 Переподписка: ~{oversubscription:.1f}x")
                
                # Лимит на подписчика
                if personal_limit > 0:
                    lines.append(f"   🔒 Лимит: {self._format_number(personal_limit)} {project.token_symbol}")
                
                # Участников
                if pool.participants > 0:
                    lines.append(f"   👥 Участников: {pool.participants:,}")
                
                # Прогноз аллокации (только для активных)
                if project.status == 'active' and allocation_amount > 0 and raise_current > 0 and subscription_price > 0:
                    pool_value = allocation_amount * subscription_price
                    if pool_value > 0 and raise_current > pool_value:
                        lines.append("")
                        lines.append("   💰 ПРОГНОЗ АЛЛОКАЦИИ:")
                        lines.append("      Внесёшь    │ Получишь")
                        lines.append("      ──────────┼──────────────")
                        
                        # Рассчитываем для разных сумм
                        test_amounts = [1000, 5000, 10000]
                        
                        # Если есть лимит - добавляем его
                        if personal_limit > 0:
                            limit_value = personal_limit * subscription_price
                            if limit_value not in test_amounts and limit_value > 0:
                                test_amounts = [1000, 5000, limit_value]
                        
                        for amount in test_amounts:
                            share = amount / raise_current
                            tokens_received = allocation_amount * share
                            tokens_value = tokens_received * subscription_price
                            
                            amount_str = f"${amount:,.0f}"
                            if personal_limit > 0 and amount >= personal_limit * subscription_price * 0.99:
                                amount_str += " MAX"
                            
                            tokens_str = f"~{self._format_number(tokens_received)} {project.token_symbol} (${tokens_value:,.0f})"
                            lines.append(f"      {amount_str:<10}│ {tokens_str}")
        
        # Период
        lines.append("")
        lines.append("⏰ ПЕРИОД:")
        if project.start_time:
            lines.append(f"   • Старт: {project.start_time.strftime('%d.%m.%Y %H:%M')} UTC")
        if project.end_time:
            lines.append(f"   • Конец: {project.end_time.strftime('%d.%m.%Y %H:%M')} UTC")
        
        # Ссылки
        lines.append("")
        lines.append("━" * 32)
        if project.project_url:
            lines.append(f"🔗 Страница: {project.project_url}")
        
        return "\n".join(lines)
    
    def _format_number(self, num: float) -> str:
        """Форматирование больших чисел"""
        if num >= 1_000_000_000:
            return f"{num/1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"{num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        else:
            return f"{num:,.0f}"
    
    def _format_money(self, num: float) -> str:
        """Форматирование денежных сумм"""
        if num >= 1_000_000:
            return f"{num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        else:
            return f"{num:,.2f}"


# Для тестирования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    parser = GateLaunchpadParser()
    projects = parser.get_projects(status_filter='active')
    
    print(f"\n{'='*60}")
    print(f"Найдено проектов: {len(projects)}")
    print('='*60)
    
    for project in projects[:3]:
        print(parser.format_project(project))
        print("\n" + "="*60 + "\n")
