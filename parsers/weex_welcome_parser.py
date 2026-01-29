# parsers/weex_welcome_parser.py
"""
WEEX WELCOME BONUS PARSER
Парсер для отслеживания изменений в Welcome Bonus Event.
https://www.weex.com/events/welcome-event

Отслеживает:
- Изменения сумм наград
- Изменения условий (депозит, объём торговли, hold days)
- Добавление/удаление наград
- Изменения групп задач
"""

import logging
import json
import hashlib
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from playwright.sync_api import sync_playwright, Response

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class WeexWelcomeParser(BaseParser):
    """
    Парсер для WEEX Welcome Bonus Event.
    Перехватывает API ответы через Playwright и отслеживает изменения в структуре наград.
    """

    # URL страницы и API endpoint
    PAGE_URL = "https://www.weex.com/events/welcome-event"
    API_ENDPOINT = "activity/general/beginner/baseInfo"
    
    # Типы бонусов для отображения
    BONUS_TYPE_NAMES = {
        'FUTURES_COUPON': '🎫 Futures Coupon',
        'POSITION_AIRDROP': '🪂 Position Airdrop',
        'GIFT_CASH': '💰 Gift Cash',
    }
    
    # Типы задач для отображения
    TASK_TYPE_NAMES = {
        'REGISTER_PASS': '📝 Registration',
        'RECHARGE': '💳 Deposit',
        'LEVER_TRADING': '📈 Futures Trading',
    }

    def __init__(self, url: str = None):
        super().__init__(url or self.PAGE_URL)
        self.exchange = 'weex'
        self._captured_data = {}

    def get_promotions(self) -> List[Dict[str, Any]]:
        """
        Основной метод - получает текущее состояние Welcome Bonus.
        Возвращает список наград в нормализованном формате.
        """
        try:
            logger.info(f"🎁 WeexWelcomeParser: Начало парсинга Welcome Bonus")
            
            raw_data = self._fetch_welcome_data()
            
            if not raw_data:
                logger.warning(f"⚠️ Не удалось получить данные Welcome Bonus")
                return []
            
            # Парсим данные
            rewards = self._parse_rewards(raw_data)
            logger.info(f"✅ WeexWelcomeParser: Найдено {len(rewards)} наград")
            
            return rewards
            
        except Exception as e:
            logger.error(f"❌ Ошибка WeexWelcomeParser: {e}", exc_info=True)
            return []

    def get_full_data(self) -> Optional[Dict]:
        """
        Получает полные сырые данные API для сохранения snapshot.
        """
        try:
            return self._fetch_welcome_data()
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных: {e}")
            return None

    def _fetch_welcome_data(self) -> Optional[Dict]:
        """Загружает страницу и перехватывает API ответ с данными Welcome Bonus"""
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

            # Применяем stealth если доступен
            if STEALTH_AVAILABLE:
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

            # Перехватчик ответов
            def handle_response(response: Response):
                url = response.url
                if response.status == 200 and self.API_ENDPOINT in url:
                    try:
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' in content_type:
                            data = response.json()
                            if data.get('code') == '00000' and data.get('data'):
                                captured_data['welcome'] = data
                                logger.debug(f"📦 Перехвачен API ответ Welcome Bonus")
                    except Exception as e:
                        logger.debug(f"Не удалось распарсить JSON: {e}")

            page.on('response', handle_response)

            # Загружаем страницу
            logger.info(f"🔄 Загрузка страницы: {self.PAGE_URL}")
            start_time = time.time()
            page.goto(self.PAGE_URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(5000)  # Ждём API запросы
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Страница загружена за {elapsed:.1f} сек")

            # Закрываем браузер
            context.close()
            browser.close()
            playwright.stop()
            playwright = None

            return captured_data.get('welcome')

        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке страницы: {e}")
            return None
        finally:
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass

    def _parse_rewards(self, raw_data: Dict) -> List[Dict[str, Any]]:
        """Парсит награды из сырых данных API"""
        rewards = []
        
        data = raw_data.get('data', {})
        task_requirements = data.get('taskRequirement', [])
        task_groups = data.get('activityTaskGroupConfig', [])
        
        # Создаём маппинг групп по ID задач
        group_map = {}
        for group in task_groups:
            if group.get('groupLevel') == 'TWO':  # Только подгруппы
                group_name = self._get_localized_name(group.get('groupNameI18', []), 'en_US') or group.get('groupName', '')
                for task_id in group.get('taskConfigIds', []):
                    group_map[task_id] = group_name
        
        for task in task_requirements:
            try:
                task_id = task.get('id')
                bonus_settings = task.get('bonusSettings', [])
                requirement = task.get('requirement', {})
                
                if not bonus_settings:
                    continue
                
                # Берём первый бонус (обычно один)
                bonus = bonus_settings[0]
                
                # Сумма награды
                bonus_amount = bonus.get('bonusAmount', 0)
                max_bonus_amount = bonus.get('maxBonusAmount')
                
                # Формируем строку суммы
                if max_bonus_amount and max_bonus_amount != bonus_amount:
                    amount_str = f"{bonus_amount}-{max_bonus_amount}"
                else:
                    amount_str = str(bonus_amount)
                
                # Тип бонуса
                bonus_type = bonus.get('bonusType', 'UNKNOWN')
                bonus_type_name = self.BONUS_TYPE_NAMES.get(bonus_type, bonus_type)
                
                # Тип задачи
                task_type = task.get('taskType', requirement.get('type', 'UNKNOWN'))
                task_type_name = self.TASK_TYPE_NAMES.get(task_type, task_type)
                
                # Условия
                conditions = self._extract_conditions(requirement)
                
                # Группа
                group_name = group_map.get(task_id, 'Other')
                
                reward = {
                    'id': task_id,
                    'amount': bonus_amount,
                    'max_amount': max_bonus_amount,
                    'amount_str': amount_str,
                    'bonus_type': bonus_type,
                    'bonus_type_name': bonus_type_name,
                    'task_type': task_type,
                    'task_type_name': task_type_name,
                    'group': group_name,
                    'conditions': conditions,
                    'product_code': bonus.get('productCode'),  # Например ETH/USDT
                    'update_time': task.get('updateTime'),
                }
                
                rewards.append(reward)
                
            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга награды {task.get('id')}: {e}")
                continue
        
        return rewards

    def _extract_conditions(self, requirement: Dict) -> Dict[str, Any]:
        """Извлекает условия из requirement"""
        conditions = {}
        
        # Депозит
        deposit = requirement.get('netRechargeAmount') or requirement.get('firstRechargeAmount') or requirement.get('totalRechargeAmount')
        if deposit:
            conditions['deposit'] = deposit
        
        # Объём торговли
        trading_volume = requirement.get('tradingVolume') or requirement.get('firstTradingAmount')
        if trading_volume:
            conditions['trading_volume'] = trading_volume
        
        # Hold days
        hold_days = requirement.get('holdDays')
        if hold_days:
            conditions['hold_days'] = hold_days
        
        # Регистрация (bind email/mobile)
        if requirement.get('isBindEmail') or requirement.get('isBindMobile'):
            conditions['requires_verification'] = True
        
        return conditions

    def _get_localized_name(self, i18n_list: List[Dict], lang: str = 'en_US') -> str:
        """Получает локализованное название"""
        for item in i18n_list:
            if item.get('lang') == lang:
                return item.get('name', '')
        # Fallback на английский
        for item in i18n_list:
            if 'en' in item.get('lang', '').lower():
                return item.get('name', '')
        return ''

    # ==================== СРАВНЕНИЕ И DIFF ====================

    def compare_states(self, old_rewards: List[Dict], new_rewards: List[Dict]) -> Dict[str, Any]:
        """
        Сравнивает старое и новое состояние наград.
        Возвращает dict с изменениями.
        """
        changes = {
            'has_changes': False,
            'added': [],      # Новые награды
            'removed': [],    # Удалённые награды
            'modified': [],   # Изменённые награды
            'summary': '',    # Краткое описание
        }
        
        # Создаём маппинг по ID
        old_map = {r['id']: r for r in old_rewards}
        new_map = {r['id']: r for r in new_rewards}
        
        old_ids = set(old_map.keys())
        new_ids = set(new_map.keys())
        
        # Добавленные
        for rid in (new_ids - old_ids):
            changes['added'].append(new_map[rid])
        
        # Удалённые
        for rid in (old_ids - new_ids):
            changes['removed'].append(old_map[rid])
        
        # Изменённые
        for rid in (old_ids & new_ids):
            old_r = old_map[rid]
            new_r = new_map[rid]
            
            diffs = self._compare_reward(old_r, new_r)
            if diffs:
                changes['modified'].append({
                    'id': rid,
                    'old': old_r,
                    'new': new_r,
                    'diffs': diffs,
                })
        
        # Проверяем есть ли изменения
        if changes['added'] or changes['removed'] or changes['modified']:
            changes['has_changes'] = True
            
            # Формируем summary
            parts = []
            if changes['added']:
                parts.append(f"+{len(changes['added'])} new")
            if changes['removed']:
                parts.append(f"-{len(changes['removed'])} removed")
            if changes['modified']:
                parts.append(f"~{len(changes['modified'])} modified")
            changes['summary'] = ', '.join(parts)
        
        return changes

    def _compare_reward(self, old: Dict, new: Dict) -> List[Dict]:
        """Сравнивает две награды, возвращает список различий"""
        diffs = []
        
        # Сравниваем сумму
        if old.get('amount') != new.get('amount'):
            diffs.append({
                'field': 'amount',
                'old': old.get('amount'),
                'new': new.get('amount'),
                'label': '💰 Сумма',
            })
        
        if old.get('max_amount') != new.get('max_amount'):
            diffs.append({
                'field': 'max_amount',
                'old': old.get('max_amount'),
                'new': new.get('max_amount'),
                'label': '💰 Макс. сумма',
            })
        
        # Сравниваем тип бонуса
        if old.get('bonus_type') != new.get('bonus_type'):
            diffs.append({
                'field': 'bonus_type',
                'old': old.get('bonus_type_name'),
                'new': new.get('bonus_type_name'),
                'label': '🎁 Тип награды',
            })
        
        # Сравниваем условия
        old_cond = old.get('conditions', {})
        new_cond = new.get('conditions', {})
        
        # Депозит (только если хотя бы одно значение не None)
        old_dep = old_cond.get('deposit')
        new_dep = new_cond.get('deposit')
        if old_dep != new_dep and (old_dep is not None or new_dep is not None):
            diffs.append({
                'field': 'deposit',
                'old': old_dep,
                'new': new_dep,
                'label': '💳 Депозит',
            })
        
        # Объём торговли (только если хотя бы одно значение не None)
        old_vol = old_cond.get('trading_volume')
        new_vol = new_cond.get('trading_volume')
        if old_vol != new_vol and (old_vol is not None or new_vol is not None):
            diffs.append({
                'field': 'trading_volume',
                'old': old_vol,
                'new': new_vol,
                'label': '📈 Объём торговли',
            })
        
        # Hold days (только если хотя бы одно значение не None)
        old_hold = old_cond.get('hold_days')
        new_hold = new_cond.get('hold_days')
        if old_hold != new_hold and (old_hold is not None or new_hold is not None):
            diffs.append({
                'field': 'hold_days',
                'old': old_hold,
                'new': new_hold,
                'label': '📅 Hold дней',
            })
        
        # Группа
        if old.get('group') != new.get('group'):
            diffs.append({
                'field': 'group',
                'old': old.get('group'),
                'new': new.get('group'),
                'label': '📂 Группа',
            })
        
        return diffs

    # ==================== ФОРМАТИРОВАНИЕ СООБЩЕНИЙ ====================

    def format_snapshot_message(self, rewards: List[Dict]) -> str:
        """
        Форматирует полный snapshot всех наград.
        Используется при первом добавлении ссылки.
        """
        if not rewards:
            return "❌ Нет данных о наградах"
        
        # Группируем награды
        groups = {}
        for r in rewards:
            group = r.get('group', 'Other')
            if group not in groups:
                groups[group] = []
            groups[group].append(r)
        
        # Считаем общую сумму
        total_min = sum(r.get('amount', 0) for r in rewards)
        total_max = sum(r.get('max_amount') or r.get('amount', 0) for r in rewards)
        
        lines = [
            f"🔵 <b>WEEX</b> | 🎁 <b>WELCOME BONUS</b> | 📋 <b>SNAPSHOT</b>",
            f"",
            f"💎 <b>Всего наград:</b> {len(rewards)} | 💰 <b>Общая сумма:</b> {self._format_amount_range(total_min, total_max)} USDT",
            f"",
        ]
        
        # Порядок групп
        group_order = ['New user rewards', 'Futures deposit', 'Futures trading']
        group_icons = {
            'New user rewards': '🎫',
            'Futures deposit': '💼',
            'Futures trading': '📊',
        }
        
        for group_name in group_order:
            if group_name not in groups:
                continue
            
            group_rewards = groups[group_name]
            icon = group_icons.get(group_name, '📦')
            
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"{icon} <b>{group_name.upper()}</b> ({len(group_rewards)})")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            # Группируем по типу бонуса для красивого отображения
            bonus_type_groups = {}
            for r in group_rewards:
                bonus_type = r.get('bonus_type_name', r.get('bonus_type', '')).strip()
                if bonus_type not in bonus_type_groups:
                    bonus_type_groups[bonus_type] = []
                bonus_type_groups[bonus_type].append(r)
            
            # NEW USER REWARDS - показываем каждую награду отдельно
            if group_name == 'New user rewards':
                for r in group_rewards:
                    bonus_type = r.get('bonus_type_name', r.get('bonus_type', ''))
                    amount = r.get('amount_str', '?')
                    
                    # Иконки для типов бонусов
                    type_icon = {
                        'Futures Coupon': '🎟️',
                        'Gift Cash': '💵',
                        'Position Airdrop': '🪂'
                    }.get(bonus_type, '🎁')
                    
                    lines.append(f"{type_icon} <b>{bonus_type}</b>")
                    lines.append(f"   💰 {amount} USDT")
                    
                    # Условия
                    cond = r.get('conditions', {})
                    cond_parts = []
                    if cond.get('deposit'):
                        cond_parts.append(f"💳 Deposit: {self._format_number(cond['deposit'])}")
                    if cond.get('trading_volume'):
                        cond_parts.append(f"📈 Volume: {self._format_number(cond['trading_volume'])}")
                    if cond.get('hold_days'):
                        cond_parts.append(f"📅 Hold: {cond['hold_days']}d")
                    
                    if cond_parts:
                        lines.append(f"   📋 {' | '.join(cond_parts)}")
                    
                    lines.append("")
            
            # FUTURES DEPOSIT - группируем одинаковые бонусы
            elif group_name == 'Futures deposit':
                # Все Position Airdrop с одинаковым hold_days
                hold_days_groups = {}
                for r in group_rewards:
                    hold_days = r.get('conditions', {}).get('hold_days', 0)
                    if hold_days not in hold_days_groups:
                        hold_days_groups[hold_days] = []
                    hold_days_groups[hold_days].append(r)
                
                for hold_days, rewards_list in hold_days_groups.items():
                    bonus_type = rewards_list[0].get('bonus_type_name', 'Position Airdrop')
                    lines.append(f"🪂 <b>{bonus_type}</b> ({hold_days} days hold):")
                    
                    for i, r in enumerate(rewards_list):
                        is_last = (i == len(rewards_list) - 1)
                        prefix = "└" if is_last else "├"
                        amount = r.get('amount_str', '?')
                        deposit = self._format_number(r.get('conditions', {}).get('deposit', 0))
                        lines.append(f"{prefix} 💰 {amount} USDT → 💳 Deposit: {deposit}")
                    
                    lines.append("")
            
            # FUTURES TRADING - группируем по trading volume
            elif group_name == 'Futures trading':
                bonus_type = group_rewards[0].get('bonus_type_name', 'Gift Cash')
                lines.append(f"💵 <b>{bonus_type}</b> by Trading Volume:")
                
                for i, r in enumerate(group_rewards):
                    is_last = (i == len(group_rewards) - 1)
                    prefix = "└" if is_last else "├"
                    amount = r.get('amount_str', '?')
                    volume = self._format_number(r.get('conditions', {}).get('trading_volume', 0))
                    lines.append(f"{prefix} 💰 {amount} USDT → 📈 {volume}")
                
                lines.append("")
        
        lines.append(f"🔗 <a href=\"{self.PAGE_URL}\">Открыть страницу</a>")
        
        return "\n".join(lines)

    def format_changes_message(self, changes: Dict[str, Any]) -> str:
        """
        Форматирует сообщение об изменениях.
        Используется при обнаружении diff.
        """
        if not changes.get('has_changes'):
            return ""
        
        lines = [
            f"🔴 <b>WEEX</b> | 🎁 <b>WELCOME BONUS</b> | ⚠️ <b>ИЗМЕНЕНИЯ!</b>",
            f"",
        ]
        
        # Добавленные награды
        if changes.get('added'):
            lines.append(f"✨ <b>НОВЫЕ НАГРАДЫ ({len(changes['added'])}):</b>")
            for r in changes['added']:
                amount = r.get('amount_str', '?')
                bonus_type = r.get('bonus_type_name', r.get('bonus_type', ''))
                group = r.get('group', '')
                
                cond_str = self._format_conditions_short(r.get('conditions', {}))
                lines.append(f"  ➕ {amount} USDT {bonus_type}")
                if cond_str:
                    lines.append(f"      {cond_str}")
                if group:
                    lines.append(f"      📂 {group}")
            lines.append("")
        
        # Удалённые награды
        if changes.get('removed'):
            lines.append(f"❌ <b>УДАЛЁННЫЕ НАГРАДЫ ({len(changes['removed'])}):</b>")
            for r in changes['removed']:
                amount = r.get('amount_str', '?')
                bonus_type = r.get('bonus_type_name', r.get('bonus_type', ''))
                lines.append(f"  ➖ {amount} USDT {bonus_type}")
            lines.append("")
        
        # Изменённые награды
        if changes.get('modified'):
            lines.append(f"📊 <b>ИЗМЕНЁННЫЕ НАГРАДЫ ({len(changes['modified'])}):</b>")
            for mod in changes['modified']:
                reward_id = mod['id']
                old_r = mod['old']
                new_r = mod['new']
                diffs = mod['diffs']
                
                # Заголовок награды
                new_amount = new_r.get('amount_str', '?')
                bonus_type = new_r.get('bonus_type_name', '')
                lines.append(f"  📝 <b>#{reward_id}</b> ({bonus_type}):")
                
                # Детали изменений
                for d in diffs:
                    label = d['label']
                    old_val = d['old']
                    new_val = d['new']
                    
                    # Форматируем числа
                    if d['field'] in ('amount', 'max_amount', 'deposit', 'trading_volume'):
                        old_val = self._format_number(old_val) if old_val else 'N/A'
                        new_val = self._format_number(new_val) if new_val else 'N/A'
                    
                    lines.append(f"      {label}: {old_val} → {new_val}")
            lines.append("")
        
        lines.append(f"🔗 <a href=\"{self.PAGE_URL}\">Открыть страницу</a>")
        
        return "\n".join(lines)

    def _format_conditions_short(self, conditions: Dict) -> str:
        """Форматирует условия в короткую строку"""
        parts = []
        if conditions.get('deposit'):
            parts.append(f"💳 Deposit: {self._format_number(conditions['deposit'])} USDT")
        if conditions.get('trading_volume'):
            parts.append(f"📈 Volume: {self._format_number(conditions['trading_volume'])} USDT")
        if conditions.get('hold_days'):
            parts.append(f"📅 Hold: {conditions['hold_days']} days")
        return ', '.join(parts)

    def _format_number(self, num) -> str:
        """Форматирует число с разделителями (1000 → 1K, 1000000 → 1M)"""
        if num is None:
            return 'N/A'
        try:
            num = float(num)
            if num >= 1_000_000:
                return f"{num/1_000_000:.0f}M"
            elif num >= 1_000:
                return f"{num/1_000:.0f}K"
            else:
                return f"{num:.0f}"
        except:
            return str(num)

    def _format_amount_range(self, min_val: float, max_val: float) -> str:
        """Форматирует диапазон сумм"""
        if min_val == max_val:
            return self._format_number(min_val)
        return f"{self._format_number(min_val)}-{self._format_number(max_val)}"

    # ==================== СЕРИАЛИЗАЦИЯ ДЛЯ SNAPSHOT ====================

    def serialize_for_snapshot(self, rewards: List[Dict]) -> str:
        """Сериализует награды в JSON для хранения в БД"""
        return json.dumps(rewards, ensure_ascii=False)

    def deserialize_from_snapshot(self, snapshot: str) -> List[Dict]:
        """Десериализует награды из JSON snapshot"""
        if not snapshot:
            return []
        try:
            return json.loads(snapshot)
        except:
            return []

    def get_snapshot_hash(self, rewards: List[Dict]) -> str:
        """Возвращает hash для быстрого сравнения состояний"""
        serialized = self.serialize_for_snapshot(rewards)
        return hashlib.md5(serialized.encode()).hexdigest()

    # ==================== ИНФОРМАЦИЯ О ПАРСЕРЕ ====================

    def get_strategy_info(self) -> Dict[str, Any]:
        """Возвращает информацию о стратегии парсинга"""
        return {
            'strategy_used': 'weex_welcome_playwright',
            'parser_type': 'WeexWelcomeParser',
            'exchange': 'weex',
            'method': 'playwright_api_intercept',
            'description': 'Перехват API Welcome Bonus через Playwright'
        }

    def get_error_stats(self) -> Dict[str, Any]:
        """Возвращает статистику ошибок"""
        return {
            'total_errors': 0,
            'errors': []
        }
