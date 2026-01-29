# parsers/weex_useragent_parser.py
"""
WEEX USER AGENT PARSER
Специальный парсер для отслеживания изменений реферальной программы WEEX.
URL: https://www.weex.com/useragent

Отслеживает:
- Изменение сумм наград (10/30/40 USDT)
- Изменение требований (депозит/торговля)
- Изменение даты окончания акции
"""

import logging
import json
import re
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from playwright.sync_api import sync_playwright, Response

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class WeexUseragentParser(BaseParser):
    """
    Парсер реферальной программы WEEX (User Agent).
    Перехватывает API ответы через Playwright для получения данных о бонусах.
    """
    
    # API endpoint для данных реферальной программы
    API_ENDPOINT = 'getActivityDetailInfoNew'
    
    def __init__(self, url: str = 'https://www.weex.com/useragent'):
        super().__init__(url)
        self.exchange = 'weex'
        self._captured_data = None
    
    def get_promotions(self) -> List[Dict[str, Any]]:
        """
        Возвращает данные реферальной программы как одну "промоакцию".
        Используется для совместимости с системой парсинга.
        """
        try:
            logger.info(f"🔄 WeexUseragentParser: Начало парсинга реферальной программы")
            
            # Получаем данные через Playwright
            raw_data = self._fetch_with_intercept()
            
            if not raw_data:
                logger.warning(f"⚠️ Не удалось получить данные WEEX User Agent")
                return []
            
            # Парсим данные
            referral_data = self._parse_referral_data(raw_data)
            
            if not referral_data:
                logger.warning(f"⚠️ Не удалось распарсить данные реферальной программы")
                return []
            
            # Создаём хеш для отслеживания изменений
            data_hash = self._calculate_hash(referral_data)
            
            # Формируем результат как "промоакцию"
            promotion = {
                'promo_id': f"weex_useragent_{referral_data['activity_id']}",
                'title': 'WEEX Referral Program',
                'description': self._format_description(referral_data),
                'type': 'referral',
                'exchange': 'weex',
                'status': referral_data.get('status', 'IN_PROGRESS'),
                'start_time': referral_data.get('start_time'),
                'end_time': referral_data.get('end_time'),
                'link': self.url,
                # Дополнительные данные для хранения
                'referral_data': referral_data,
                'data_hash': data_hash,
                'levels': referral_data.get('levels', []),
            }
            
            logger.info(f"✅ WeexUseragentParser: Данные получены, хеш={data_hash[:16]}...")
            return [promotion]
            
        except Exception as e:
            logger.error(f"❌ Ошибка WeexUseragentParser: {e}", exc_info=True)
            return []
    
    def _fetch_with_intercept(self) -> Optional[Dict]:
        """Загружает страницу и перехватывает API ответ"""
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
            
            def handle_response(response: Response):
                url = response.url
                if response.status == 200 and 'application/json' in response.headers.get('content-type', ''):
                    try:
                        # Ищем нужный API (без uid параметра)
                        if self.API_ENDPOINT in url and 'uid=' not in url:
                            data = response.json()
                            captured_data['detail'] = data
                            logger.debug(f"📦 Перехвачен API: {self.API_ENDPOINT}")
                    except Exception as e:
                        logger.debug(f"Не удалось распарсить JSON: {e}")
            
            page.on('response', handle_response)
            
            logger.info(f"🔄 Загрузка страницы: {self.url}")
            page.goto(self.url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(5000)  # Ждём API запросы
            
            context.close()
            browser.close()
            playwright.stop()
            playwright = None
            
            return captured_data.get('detail')
            
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке страницы: {e}")
            return None
        finally:
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass
    
    def _parse_referral_data(self, api_data: Dict) -> Optional[Dict]:
        """Парсит данные реферальной программы из API ответа"""
        
        if not api_data or api_data.get('code') != '00000':
            return None
        
        data = api_data.get('data', {})
        
        result = {
            'activity_id': data.get('activityId'),
            'start_time': data.get('startTime'),
            'end_time': data.get('endTime'),
            'status': data.get('stage'),
            'levels': []
        }
        
        # Парсим уровни бонусов из taskConfig
        task_configs = data.get('taskConfig', [])
        
        for task in task_configs:
            # Получаем название на английском
            name_en = None
            for name_i18 in task.get('nameI18', []):
                if name_i18.get('lang') == 'en':
                    name_en = name_i18.get('name')
                    break
            
            # Получаем описание на английском
            content_en = None
            for content_i18 in task.get('contentI18', []):
                if content_i18.get('lang') == 'en':
                    content_en = content_i18.get('name')
                    break
            
            # Награда
            task_award = task.get('taskAward', {})
            reward_amount = task_award.get('awardAmountMin')
            
            # Для первого уровня (taskType == "NONE") парсим из названия
            if task.get('taskType') == 'NONE' and name_en:
                numbers = re.findall(r'\d+', name_en)
                if len(numbers) >= 2:
                    reward_amount = int(numbers[0])
            
            # Требования
            requirements = task.get('requirement', [])
            req = requirements[0] if requirements else {}
            
            min_deposit = req.get('inviteNetRechargeAmount')
            min_trading = req.get('inviteTradingVolume')
            required_invites = req.get('requiredVolume')
            
            # Для первого уровня парсим требования из content
            if task.get('taskType') == 'NONE' and content_en:
                deposit_match = re.search(r'depositing?\s*[≥>]+\s*([\d,]+)', content_en)
                if deposit_match:
                    min_deposit = int(deposit_match.group(1).replace(',', ''))
                
                trading_match = re.search(r'trading?\s*[≥>]+\s*([\d,]+)', content_en)
                if trading_match:
                    min_trading = int(trading_match.group(1).replace(',', ''))
            
            # Пропускаем если нет награды и названия
            if not reward_amount and not name_en:
                continue
            
            level_data = {
                'id': task.get('id'),
                'order': task.get('order'),
                'name': name_en or task.get('name'),
                'content': content_en,
                'reward_amount': reward_amount,
                'min_deposit': min_deposit,
                'min_trading': min_trading,
                'required_invites': required_invites,
                'task_type': task.get('taskType'),
            }
            
            result['levels'].append(level_data)
        
        # Сортируем по order
        result['levels'].sort(key=lambda x: x.get('order') or 0)
        
        return result
    
    def _calculate_hash(self, data: Dict) -> str:
        """Вычисляет хеш данных для отслеживания изменений"""
        # Создаём строку из ключевых полей
        key_data = {
            'end_time': data.get('end_time'),
            'levels': []
        }
        
        for level in data.get('levels', []):
            key_data['levels'].append({
                'reward_amount': level.get('reward_amount'),
                'min_deposit': level.get('min_deposit'),
                'min_trading': level.get('min_trading'),
                'required_invites': level.get('required_invites'),
            })
        
        json_str = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(json_str.encode()).hexdigest()
    
    def _format_description(self, data: Dict) -> str:
        """Форматирует описание для хранения"""
        lines = []
        for i, level in enumerate(data.get('levels', [])):
            reward = level.get('reward_amount')
            deposit = level.get('min_deposit')
            trading = level.get('min_trading')
            invites = level.get('required_invites')
            
            line = f"Lvl{i+1}: {reward} USDT"
            if invites:
                line += f" ({invites} friends)"
            if deposit:
                line += f", deposit≥{deposit}"
            if trading:
                line += f", trade≥{trading}"
            lines.append(line)
        
        return "; ".join(lines)
    
    # ==================== МЕТОДЫ ДЛЯ ФОРМАТИРОВАНИЯ УВЕДОМЛЕНИЙ ====================
    
    @staticmethod
    def format_number(num) -> str:
        """Форматирует число с разделителями тысяч"""
        if num is None:
            return "N/A"
        return f"{num:,.0f}".replace(",", " ")
    
    @staticmethod
    def timestamp_to_date(ts) -> str:
        """Конвертирует timestamp в читаемую дату"""
        if not ts:
            return "N/A"
        try:
            dt = datetime.fromtimestamp(ts / 1000)
            months_ru = {
                1: "января", 2: "февраля", 3: "марта", 4: "апреля",
                5: "мая", 6: "июня", 7: "июля", 8: "августа",
                9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
            }
            return f"{dt.day} {months_ru[dt.month]} {dt.year}"
        except:
            return "N/A"
    
    @classmethod
    def format_snapshot_message(cls, data: Dict) -> str:
        """Форматирует сообщение с текущим состоянием (первый запуск)"""
        
        if not data:
            return "❌ Не удалось получить данные"
        
        lines = [
            "🔵 WEEX | 🎁 REFERRAL | 📋 SNAPSHOT",
            "",
            "📊 Текущие условия:",
            "┌─────────────────────────────────"
        ]
        
        for i, level in enumerate(data.get('levels', [])):
            reward = level.get('reward_amount')
            deposit = level.get('min_deposit')
            trading = level.get('min_trading')
            invites = level.get('required_invites')
            task_type = level.get('task_type')
            
            # Формируем строку награды
            if task_type == 'NONE':
                reward_str = f"│ Lvl{i+1}: {reward} USDT (макс 100, за каждого)"
            elif invites:
                reward_str = f"│ Lvl{i+1}: {reward} USDT ({invites} друзей)"
            else:
                reward_str = f"│ Lvl{i+1}: {reward} USDT"
            
            lines.append(reward_str)
            
            if deposit:
                lines.append(f"│ → Депозит: ≥{cls.format_number(deposit)} USDT")
            if trading:
                lines.append(f"│ → Торговля: ≥{cls.format_number(trading)} USDT")
            
            if i < len(data.get('levels', [])) - 1:
                lines.append("├─────────────────────────────────")
        
        lines.append("└─────────────────────────────────")
        lines.append(f"📅 До: {cls.timestamp_to_date(data.get('end_time'))}")
        lines.append(f"💰 Комиссия: 40%")
        lines.append("")
        lines.append("🔗 https://www.weex.com/useragent")
        
        return "\n".join(lines)
    
    @classmethod
    def format_changes_message(cls, old_data: Dict, new_data: Dict) -> Optional[str]:
        """Форматирует сообщение об изменениях"""
        
        changes = []
        
        # Сравниваем уровни
        old_levels = old_data.get('levels', [])
        new_levels = new_data.get('levels', [])
        
        # Создаём словари по order для удобства сравнения
        old_by_order = {l.get('order'): l for l in old_levels}
        new_by_order = {l.get('order'): l for l in new_levels}
        
        all_orders = sorted(set(list(old_by_order.keys()) + list(new_by_order.keys())))
        
        for order in all_orders:
            old_level = old_by_order.get(order, {})
            new_level = new_by_order.get(order, {})
            
            if not old_level and new_level:
                # Новый уровень
                reward = new_level.get('reward_amount')
                changes.append(f"📊 ✨ Новый уровень {order} ({reward} USDT)!")
                changes.append("")
                continue
            
            if old_level and not new_level:
                # Удалён уровень
                reward = old_level.get('reward_amount')
                changes.append(f"📊 ❌ Удалён уровень {order} ({reward} USDT)")
                changes.append("")
                continue
            
            level_changes = []
            
            if old_level.get('reward_amount') != new_level.get('reward_amount'):
                level_changes.append(f"  💰 Награда: {old_level.get('reward_amount')} → {new_level.get('reward_amount')} USDT")
            
            if old_level.get('min_deposit') != new_level.get('min_deposit'):
                level_changes.append(f"  📥 Депозит: {cls.format_number(old_level.get('min_deposit'))} → {cls.format_number(new_level.get('min_deposit'))} USDT")
            
            if old_level.get('min_trading') != new_level.get('min_trading'):
                level_changes.append(f"  📈 Торговля: {cls.format_number(old_level.get('min_trading'))} → {cls.format_number(new_level.get('min_trading'))} USDT")
            
            if old_level.get('required_invites') != new_level.get('required_invites'):
                level_changes.append(f"  👥 Приглашений: {old_level.get('required_invites') or 'за каждого'} → {new_level.get('required_invites') or 'за каждого'}")
            
            if level_changes:
                reward = new_level.get('reward_amount')
                changes.append(f"📊 Уровень {order} ({reward} USDT):")
                changes.extend(level_changes)
                changes.append("")
        
        # Сравниваем дату окончания
        if old_data.get('end_time') != new_data.get('end_time'):
            changes.append(f"📅 Дата окончания: {cls.timestamp_to_date(old_data.get('end_time'))} → {cls.timestamp_to_date(new_data.get('end_time'))}")
        
        if not changes:
            return None  # Нет изменений
        
        lines = [
            "🔴 WEEX | 🎁 REFERRAL | ⚠️ ИЗМЕНЕНИЯ!",
            "",
        ]
        lines.extend(changes)
        if not lines[-1]:
            lines.pop()  # Убираем последнюю пустую строку
        lines.append("")
        lines.append("🔗 https://www.weex.com/useragent")
        
        return "\n".join(lines)
    
    @classmethod
    def format_fallback_message(cls, data: Dict) -> str:
        """Форматирует fallback сообщение (если детальное сравнение не работает)"""
        
        lines = [
            "🔴 WEEX | 🎁 REFERRAL | 🆕 ИЗМЕНЕНИЯ!",
            "",
            "⚠️ Обнаружены изменения в реферальной программе!",
            "",
            "📊 Текущие бонусы:"
        ]
        
        for i, level in enumerate(data.get('levels', [])):
            reward = level.get('reward_amount')
            deposit = level.get('min_deposit')
            trading = level.get('min_trading')
            invites = level.get('required_invites')
            
            line = f"• Lvl{i+1}: {reward} USDT"
            if deposit and trading:
                line += f" (депозит ≥{cls.format_number(deposit)}, торговля ≥{cls.format_number(trading)})"
            
            lines.append(line)
        
        lines.append(f"📅 До: {cls.timestamp_to_date(data.get('end_time'))}")
        lines.append("")
        lines.append("🔗 https://www.weex.com/useragent")
        
        return "\n".join(lines)
