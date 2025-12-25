"""
parsers/staking_parser.py
Универсальный парсер стейкингов для Kucoin и Bybit
"""

import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from utils.price_fetcher import get_price_fetcher
from bybit_coin_mapping import BYBIT_COIN_MAPPING

logger = logging.getLogger(__name__)

class StakingParser:
    """Парсер стейкингов"""

    def __init__(self, api_url: str, exchange_name: str):
        self.api_url = api_url
        self.exchange_name = exchange_name.lower()
        self.price_fetcher = get_price_fetcher()

    def parse(self) -> List[Dict[str, Any]]:
        """
        Основной метод парсинга стейкингов

        Returns:
            Список стейкингов в унифицированном формате
        """
        try:
            logger.info(f"🔍 Парсинг стейкингов: {self.exchange_name}")

            # Разные биржи используют разные методы запроса
            if 'bybit' in self.exchange_name:
                # Bybit требует POST запрос с payload
                headers = {
                    'accept': '*/*',
                    'accept-language': 'en-US,en;q=0.9',
                    'content-type': 'application/json',
                    'origin': 'https://www.bybit.com',
                    'referer': 'https://www.bybit.com/en/earn/easy-earn',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                payload = {
                    "tab": "0",  # 0 - все, 1 - flexible, 2 - fixed
                    "page": 1,
                    "limit": 100,
                    "fixed_saving_version": 1,
                    "fuzzy_coin_name": "",
                    "sort_type": 0,
                    "match_user_asset": False,
                    "eligible_only": False
                }

                response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()

                # Проверяем статус ответа
                if data.get('ret_code') != 0:
                    logger.error(f"❌ Bybit API error: {data.get('ret_msg')}")
                    return []

                return self._parse_bybit(data)

            elif 'kucoin' in self.exchange_name:
                # Kucoin использует обычный GET
                response = requests.get(self.api_url, timeout=30)
                response.raise_for_status()
                data = response.json()
                return self._parse_kucoin(data)

            else:
                logger.warning(f"⚠️ Неизвестная биржа: {self.exchange_name}")
                return []

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга стейкингов: {e}", exc_info=True)
            return []

    def _parse_kucoin(self, data: dict) -> List[Dict[str, Any]]:
        """Парсинг Kucoin стейкингов"""
        stakings = []

        # Получаем массив продуктов
        products = data.get('data', [])
        if not products:
            logger.warning("⚠️ Kucoin: нет данных о стейкингах")
            return []

        logger.info(f"📊 Kucoin: найдено {len(products)} стейкингов")

        for product in products:
            try:
                # Основные поля (подтверждены API)
                coin = product.get('currency')
                income_coin = product.get('income_currency')

                # APR в формате строки "200.0000"
                apr_str = product.get('total_apr', product.get('apr', '0'))
                apr = float(apr_str) if apr_str else 0.0

                # Получаем цену токена
                token_price = self.price_fetcher.get_token_price(coin) if coin else None

                # Product ID
                product_id = str(product.get('product_id'))

                # Типы и статусы
                product_type = product.get('type')  # MULTI_TIME, SAVING
                status = product.get('status')  # ONGOING
                category = product.get('category')  # ACTIVITY, DEMAND
                category_text = product.get('category_text')  # Promotions, Savings

                # Период (duration в днях, 0 для flexible)
                term_days = int(product.get('duration', 0))

                # ВАЖНО: Kucoin публичный API НЕ предоставляет:
                # - user_limit (лимит на пользователя)
                # - total_places (количество мест)
                # - max_capacity/current_deposit (заполненность)
                # - start_time/end_time (временные метки)
                # Эти данные доступны только в приватном API для авторизованных пользователей

                staking = {
                    'exchange': 'Kucoin',
                    'product_id': product_id,
                    'coin': coin,
                    'reward_coin': income_coin if income_coin != coin else None,
                    'apr': apr,
                    'type': product_type,
                    'status': status,
                    'category': category,
                    'category_text': category_text,
                    'term_days': term_days,
                    'token_price_usd': token_price,
                    # Недоступно в публичном API:
                    'start_time': None,
                    'end_time': None,
                    'user_limit_tokens': None,
                    'user_limit_usd': None,
                    'total_places': None,
                    'max_capacity': None,
                    'current_deposit': None,
                    'fill_percentage': None,
                }

                stakings.append(staking)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга Kucoin продукта: {e}")
                continue

        return stakings

    def _parse_bybit(self, data: dict) -> List[Dict[str, Any]]:
        """
        Парсинг Bybit стейкингов
        ВАЖНО: Bybit API требует POST запрос с JSON payload
        """
        stakings = []

        # Структура: result -> coin_products -> [coin_product] -> saving_products
        result = data.get('result')
        if not result:
            logger.warning("⚠️ Bybit: нет result в ответе")
            return []

        coin_products = result.get('coin_products', [])
        if not coin_products:
            logger.warning("⚠️ Bybit: нет coin_products")
            return []

        logger.info(f"📊 Bybit: найдено {len(coin_products)} монет")

        total_products = 0

        for coin_product in coin_products:
            try:
                # ID монеты от Bybit - используем расширенный маппинг
                coin_id = coin_product.get('coin')
                coin_name = BYBIT_COIN_MAPPING.get(coin_id, f"COIN_{coin_id}")

                # Продукты этой монеты
                saving_products = coin_product.get('saving_products', [])

                for product in saving_products:
                    try:
                        # APY (строка с %)
                        apy_str = product.get('apy', '0%')
                        apy_float = float(apy_str.replace('%', '').strip())

                        # Получаем цену токена
                        token_price = self.price_fetcher.get_token_price(coin_name) if coin_name else None

                        # Product ID
                        product_id = str(product.get('product_id', ''))

                        # Тип (определяем по staking_term)
                        term = product.get('staking_term', '0')
                        product_type = "Flexible" if term == "0" else f"Fixed {term}d"
                        term_days = int(term)

                        # Статус
                        display_status = product.get('display_status', 0)
                        status_map = {
                            1: "Active",
                            2: "Sold Out",
                            3: "Coming Soon"
                        }
                        status = status_map.get(display_status, "Unknown")

                        # Заполненность
                        max_capacity = float(product.get('product_max_share', 0))
                        current_deposit = float(product.get('total_deposit_share', 0))

                        # Процент заполнения
                        fill_percentage = None
                        if max_capacity > 0:
                            fill_percentage = round((current_deposit / max_capacity) * 100, 2)

                        # VIP продукт
                        is_vip = product.get('is_vip', False)

                        staking = {
                            'exchange': 'Bybit',
                            'product_id': product_id,
                            'coin': coin_name,
                            'reward_coin': None,  # Обычно та же монета
                            'apr': apy_float,
                            'type': product_type,
                            'status': status,
                            'category': 'VIP' if is_vip else None,
                            'category_text': 'VIP Product' if is_vip else None,
                            'term_days': term_days,
                            'token_price_usd': token_price,
                            'reward_token_price_usd': None,
                            'start_time': None,  # Bybit не предоставляет в этом API
                            'end_time': None,
                            'user_limit_tokens': None,  # Требует авторизации
                            'user_limit_usd': None,
                            'total_places': None,
                            'max_capacity': max_capacity,
                            'current_deposit': current_deposit,
                            'fill_percentage': fill_percentage,
                        }

                        stakings.append(staking)
                        total_products += 1

                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка парсинга Bybit продукта {coin_name}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга Bybit монеты: {e}")
                continue

        logger.info(f"✅ Bybit: обработано {total_products} продуктов")
        return stakings

    def get_pool_fills(self) -> List[Dict[str, Any]]:
        """
        Получить данные о заполненности пулов (для кнопки "Проверить заполненность")

        Returns:
            Список активных стейкингов с данными о заполненности
        """
        all_stakings = self.parse()

        # Фильтруем только активные с данными о заполненности
        pools_with_fill = []
        for staking in all_stakings:
            if staking.get('fill_percentage') is not None:
                pools_with_fill.append(staking)

        logger.info(f"📊 Найдено {len(pools_with_fill)} пулов с данными о заполненности")
        return pools_with_fill
