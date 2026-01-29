# utils/launchpool_filter.py
"""
Фильтрация Launchpool проектов на основе пользовательских настроек
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def filter_launchpool_project(
    project: Any,
    min_pool_usd: float = 0,
    min_apr: float = 0,
    stake_coins_filter: List[str] = None,
    min_user_limit_usd: float = 0
) -> bool:
    """
    Проверяет, соответствует ли проект фильтрам пользователя.
    
    Args:
        project: LaunchpoolProject объект
        min_pool_usd: Минимальный размер пула в USD (0 = без фильтра)
        min_apr: Минимальный APR (0 = без фильтра)
        stake_coins_filter: Список монет для стейка (пустой = все)
        min_user_limit_usd: Минимальный лимит юзера в USD (0 = без фильтра)
    
    Returns:
        True если проект проходит фильтры, False иначе
    """
    try:
        # 1. Фильтр по размеру пула
        if min_pool_usd > 0:
            pool_usd = getattr(project, 'total_pool_usd', 0) or 0
            if pool_usd < min_pool_usd:
                logger.debug(f"❌ {project.token_symbol}: пул ${pool_usd:,.0f} < мин. ${min_pool_usd:,.0f}")
                return False
        
        # 2. Фильтр по APR (берём максимальный APR из всех пулов)
        if min_apr > 0:
            pools = getattr(project, 'pools', []) or []
            if pools:
                max_apr = max([p.apr for p in pools if p.apr > 0], default=0)
            else:
                max_apr = 0
            
            if max_apr < min_apr:
                logger.debug(f"❌ {project.token_symbol}: APR {max_apr:.0f}% < мин. {min_apr:.0f}%")
                return False
        
        # 3. Фильтр по монетам стейка
        if stake_coins_filter and len(stake_coins_filter) > 0:
            pools = getattr(project, 'pools', []) or []
            project_coins = {p.stake_coin.upper() for p in pools if p.stake_coin}
            filter_coins = {c.upper() for c in stake_coins_filter}
            
            # Проект должен иметь хотя бы одну монету из фильтра
            if not project_coins.intersection(filter_coins):
                logger.debug(f"❌ {project.token_symbol}: монеты {project_coins} не в фильтре {filter_coins}")
                return False
        
        # 4. Фильтр по минимальному лимиту юзера
        if min_user_limit_usd > 0:
            pools = getattr(project, 'pools', []) or []
            if pools:
                # Берём максимальный лимит из всех пулов
                max_user_limit = max([p.max_stake for p in pools if p.max_stake > 0], default=0)
            else:
                max_user_limit = 0
            
            if max_user_limit < min_user_limit_usd:
                logger.debug(f"❌ {project.token_symbol}: лимит ${max_user_limit:,.0f} < мин. ${min_user_limit_usd:,.0f}")
                return False
        
        logger.debug(f"✅ {project.token_symbol}: проходит все фильтры")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Ошибка фильтрации проекта: {e}")
        return True  # При ошибке пропускаем фильтр


def filter_launchpool_projects(
    projects: List[Any],
    min_pool_usd: float = 0,
    min_apr: float = 0,
    stake_coins_filter: List[str] = None,
    min_user_limit_usd: float = 0
) -> List[Any]:
    """
    Фильтрует список проектов по настройкам пользователя.
    
    Returns:
        Отфильтрованный список проектов
    """
    if not projects:
        return []
    
    # Если все фильтры отключены - возвращаем всё
    if min_pool_usd <= 0 and min_apr <= 0 and not stake_coins_filter and min_user_limit_usd <= 0:
        return projects
    
    filtered = []
    for project in projects:
        if filter_launchpool_project(
            project,
            min_pool_usd=min_pool_usd,
            min_apr=min_apr,
            stake_coins_filter=stake_coins_filter,
            min_user_limit_usd=min_user_limit_usd
        ):
            filtered.append(project)
    
    if len(filtered) < len(projects):
        logger.info(f"🔍 Фильтрация: {len(projects)} → {len(filtered)} проектов")
    
    return filtered


def get_link_launchpool_filters(link) -> Dict[str, Any]:
    """
    Получить фильтры Launchpool из объекта ссылки.
    
    Args:
        link: ApiLink объект
    
    Returns:
        Словарь с настройками фильтров
    """
    filters = {
        'min_pool_usd': getattr(link, 'lp_min_pool_usd', 0) or 0,
        'min_apr': getattr(link, 'lp_min_apr', 0) or 0,
        'stake_coins_filter': [],
        'min_user_limit_usd': getattr(link, 'lp_min_user_limit_usd', 0) or 0
    }
    
    # Получаем фильтр монет
    if hasattr(link, 'get_lp_stake_coins_filter'):
        filters['stake_coins_filter'] = link.get_lp_stake_coins_filter()
    
    return filters
