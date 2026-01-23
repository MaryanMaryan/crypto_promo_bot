"""
Миграция для обогащения существующих промоакций USD-эквивалентами.
Запустить один раз для обновления старых данных.

Использование:
    python migrate_enrich_promo_prices.py
"""

import re
import logging
from data.database import get_db_session
from data.models import PromoHistory
from utils.price_fetcher import get_price_fetcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Стейблкоины для которых цена = 1 USD
STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'USD1', 'USDE'}


def migrate_promo_prices():
    """Обновляет USD-эквиваленты для существующих промоакций"""
    
    price_fetcher = get_price_fetcher()
    if not price_fetcher:
        logger.error("❌ Не удалось инициализировать price_fetcher")
        return
    
    # Кэш цен токенов чтобы не делать повторные запросы
    price_cache = {}
    
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    with get_db_session() as session:
        # Получаем промоакции без USD-эквивалентов
        promos = session.query(PromoHistory).filter(
            PromoHistory.total_prize_pool_usd == None,
            PromoHistory.total_prize_pool != None,
            PromoHistory.total_prize_pool != '',
            PromoHistory.award_token != None,
            PromoHistory.award_token != ''
        ).all()
        
        total_count = len(promos)
        logger.info(f"📊 Найдено {total_count} промоакций для обогащения")
        
        for i, promo in enumerate(promos):
            try:
                award_token = promo.award_token
                total_prize_pool = promo.total_prize_pool
                
                if not award_token or not total_prize_pool:
                    skipped_count += 1
                    continue
                
                # Очищаем символ токена
                clean_token = award_token.upper().strip()
                token_match = re.search(r'([A-Z]{2,10})$', clean_token)
                if token_match:
                    clean_token = token_match.group(1)
                
                # Получаем цену из кэша или запрашиваем
                if clean_token in price_cache:
                    token_price = price_cache[clean_token]
                elif clean_token in STABLECOINS:
                    token_price = 1.0
                    price_cache[clean_token] = token_price
                else:
                    try:
                        token_price = price_fetcher.get_token_price(clean_token)
                        price_cache[clean_token] = token_price
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить цену {clean_token}: {e}")
                        token_price = None
                        price_cache[clean_token] = None
                
                if not token_price:
                    skipped_count += 1
                    continue
                
                # Парсим сумму
                try:
                    pool_str = str(total_prize_pool).replace(',', '').replace(' ', '')
                    pool_num = float(pool_str)
                    usd_value = pool_num * token_price
                    
                    promo.total_prize_pool_usd = usd_value
                    updated_count += 1
                    
                    if (i + 1) % 50 == 0:
                        logger.info(f"📝 Обработано {i + 1}/{total_count}...")
                        session.commit()
                        
                except (ValueError, TypeError) as e:
                    logger.debug(f"⚠️ Ошибка парсинга суммы '{total_prize_pool}': {e}")
                    skipped_count += 1
                    continue
                    
            except Exception as e:
                logger.warning(f"⚠️ Ошибка обработки промо {promo.id}: {e}")
                error_count += 1
                continue
        
        # Финальный коммит
        session.commit()
    
    logger.info(f"")
    logger.info(f"✅ Миграция завершена:")
    logger.info(f"   📊 Всего промоакций: {total_count}")
    logger.info(f"   ✅ Обновлено: {updated_count}")
    logger.info(f"   ⏭️ Пропущено: {skipped_count}")
    logger.info(f"   ❌ Ошибок: {error_count}")
    logger.info(f"   💰 Токенов в кэше: {len(price_cache)}")


if __name__ == "__main__":
    migrate_promo_prices()
