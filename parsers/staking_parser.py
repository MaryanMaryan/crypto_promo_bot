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

    def __init__(self, api_url: str, exchange_name: str = None):
        self.api_url = api_url
        # Автоопределение биржи по URL если exchange_name не указан
        self.exchange_name = self._detect_exchange(api_url, exchange_name)
        self.price_fetcher = get_price_fetcher()

    def _detect_exchange(self, api_url: str, exchange_name: str = None) -> str:
        """
        Автоматически определяет биржу по URL API

        Args:
            api_url: URL API для парсинга
            exchange_name: Название биржи (если указано, используется оно)

        Returns:
            Название биржи в нижнем регистре
        """
        # Если exchange_name уже указан и не пустой, используем его
        if exchange_name and exchange_name.lower() not in ['none', 'unknown', '']:
            return exchange_name.lower()

        # Автоопределение по URL
        url_lower = api_url.lower()

        if 'bybit.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа Bybit")
            return 'bybit'
        elif 'kucoin.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа Kucoin")
            return 'kucoin'
        elif 'okx.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа OKX")
            return 'okx'
        elif 'binance.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа Binance")
            return 'binance'
        elif 'gate.io' in url_lower or 'gate.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа Gate.io")
            return 'gate'
        elif 'mexc.com' in url_lower:
            logger.info("🔍 Автоопределение: биржа MEXC")
            return 'mexc'
        else:
            logger.warning(f"⚠️ Не удалось определить биржу по URL: {api_url}")
            return 'unknown'

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
                    "tab": "2",  # 0 - все, 1 - flexible, 2 - fixed (ТОЛЬКО ФИКСИРОВАННЫЕ стейкинги)
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

            elif 'okx' in self.exchange_name:
                # OKX использует обычный GET
                headers = {
                    'accept': 'application/json',
                    'x-locale': 'en_US',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(self.api_url, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                return self._parse_okx(data)

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
                # ID монеты от Bybit
                # ВАЖНО: В Bybit API поле 'coin' указывает на монету награды для продуктов с return_coin=0,
                # а не на монету которая стейкается!
                api_coin_id = coin_product.get('coin')

                # Продукты этой монеты
                saving_products = coin_product.get('saving_products', [])

                for product in saving_products:
                    try:
                        # ОТЛАДКА: Проверяем ВСЕ продукты на проблемные символы
                        term = product.get('staking_term', '0')

                        # Определяем ПРАВИЛЬНУЮ монету для стейкинга
                        # В Bybit API поле 'coin' может указывать на монету награды, а не стейкинга!
                        # ВАЖНО: Нужно анализировать тег и return_coin для определения правильной монеты

                        return_coin = product.get('return_coin')
                        product_coin_id = product.get('coin', api_coin_id)
                        tag = product.get('product_tag_info', {}).get('display_tag_key', '')

                        # Сначала получаем APY для дополнительных проверок
                        apy_str = product.get('apy', '0%')
                        apy_float = float(apy_str.replace('%', '').strip())

                        # Определяем монету по тегу (наиболее надёжный способ)
                        if 'USDT' in tag or 'usdt' in tag:
                            # Тег содержит USDT - это USDT стейкинг
                            coin_id = 3  # USDT
                        elif api_coin_id == 5 and apy_float >= 500:
                            # ВАЖНО: BNB в API с очень высоким APR (≥500%) обычно означает USDT стейкинг
                            # Bybit не предлагает такие высокие ставки для BNB стейкинга
                            coin_id = 3  # USDT
                        elif return_coin == 0:
                            # Награда в других монетах, тега нет - определяем по api_coin_id
                            if api_coin_id == 5:  # BNB в API обычно означает USDT стейкинг
                                coin_id = 3  # USDT
                            elif api_coin_id == 463:  # MNT
                                coin_id = 463  # Стейкаем MNT
                            else:
                                # Для остальных используем coin из product или coin_product
                                coin_id = product_coin_id
                        else:
                            # Стандартный случай: стейкаем и получаем ту же монету
                            coin_id = return_coin if return_coin else api_coin_id

                        coin_name = BYBIT_COIN_MAPPING.get(coin_id, f"COIN_{coin_id}")

                        # Проверяем все текстовые поля на наличие < или >
                        for key, value in product.items():
                            if isinstance(value, str) and ('<' in value or '>' in value):
                                logger.warning(f"⚠️ [{coin_name}] Поле '{key}' содержит < или >: {value}")
                                logger.info(f"🔍 Полные данные продукта: {product}")

                        # Получаем цену токена
                        token_price = self.price_fetcher.get_token_price(coin_name) if coin_name else None

                        # Product ID
                        product_id = str(product.get('product_id', ''))

                        # Тип (определяем по staking_term)
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
                        if not is_vip and tag:
                            # Проверяем тег на VIP
                            is_vip = 'VIP' in tag or 'vip' in tag

                        # Продукт для новых пользователей
                        is_new_user = False
                        if tag:
                            is_new_user = 'newuser' in tag.lower() or 'new user' in tag.lower()

                        # Региональные теги (для СНГ, Азии и т.д.)
                        regional_tag = None
                        regional_countries = None
                        tag_info = product.get('product_tag_info', {})
                        if tag_info:
                            display_tag = tag_info.get('display_tag_key', '')
                            countries = tag_info.get('display_on_country_code', '')

                            # Определяем региональные предложения
                            if 'CIS' in display_tag:
                                regional_tag = 'CIS'  # СНГ
                                regional_countries = countries
                            elif 'Asia' in display_tag:
                                regional_tag = 'Asia'
                                regional_countries = countries
                            elif countries and not is_vip and not is_new_user:
                                # Есть страны, но не VIP и не New User - значит региональное
                                regional_tag = 'Regional'
                                regional_countries = countries

                        # Определяем категорию
                        category = None
                        category_text = None
                        if is_vip:
                            category = 'VIP'
                            category_text = 'VIP Product'
                        elif is_new_user:
                            category = 'New User'
                            category_text = 'New User Only'
                        elif regional_tag:
                            category = regional_tag
                            category_text = f'{regional_tag} Regional Offer'

                        # Даты начала и конца (unix timestamp -> datetime string)
                        from datetime import datetime
                        start_time_str = None
                        end_time_str = None

                        subscribe_start = product.get('subscribe_start_at')
                        subscribe_end = product.get('subscribe_end_at')

                        if subscribe_start and subscribe_start != '0':
                            try:
                                start_dt = datetime.utcfromtimestamp(int(subscribe_start))
                                start_time_str = start_dt.strftime('%d.%m.%Y %H:%M UTC')
                            except:
                                pass

                        if subscribe_end and subscribe_end != '0':
                            try:
                                end_dt = datetime.utcfromtimestamp(int(subscribe_end))
                                end_time_str = end_dt.strftime('%d.%m.%Y %H:%M UTC')
                            except:
                                pass

                        staking = {
                            'exchange': 'Bybit',
                            'product_id': product_id,
                            'coin': coin_name,
                            'reward_coin': None,  # Обычно та же монета
                            'apr': apy_float,
                            'type': product_type,
                            'status': status,
                            'category': category,
                            'category_text': category_text,
                            'term_days': term_days,
                            'token_price_usd': token_price,
                            'reward_token_price_usd': None,
                            'start_time': start_time_str,
                            'end_time': end_time_str,
                            'user_limit_tokens': None,  # Требует авторизации
                            'user_limit_usd': None,
                            'total_places': None,
                            'max_capacity': max_capacity,
                            'current_deposit': current_deposit,
                            'fill_percentage': fill_percentage,
                            'is_vip': is_vip,
                            'is_new_user': is_new_user,
                            'regional_tag': regional_tag,
                            'regional_countries': regional_countries,
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

    def _parse_okx(self, data: dict) -> List[Dict[str, Any]]:
        """
        Парсинг OKX Flash Earn стейкингов
        ВАЖНО: OKX API использует GET запрос и возвращает только активные проекты
        """
        stakings = []

        # Структура: data -> ongoingProjects
        ongoing_projects = data.get('data', {}).get('ongoingProjects', [])
        if not ongoing_projects:
            logger.warning("⚠️ OKX: нет активных проектов")
            return []

        logger.info(f"📊 OKX: найдено {len(ongoing_projects)} активных проектов")

        total_pools = 0

        for project in ongoing_projects:
            try:
                # Данные проекта
                project_id = project.get('projectId')
                end_time = project.get('endTime')  # timestamp в миллисекундах

                # Награды проекта (общие)
                project_rewards = project.get('rewardDetails', [])

                # Пулы проекта
                pool_details = project.get('poolDetails', [])

                if not pool_details:
                    logger.warning(f"⚠️ OKX: проект {project_id} не имеет пулов")
                    continue

                for pool in pool_details:
                    try:
                        # ID пула
                        pool_id = str(pool.get('projectId', ''))

                        # Монета стейкинга (из purchaseDetails)
                        purchase_details = pool.get('purchaseDetails', [])
                        if not purchase_details:
                            logger.warning(f"⚠️ OKX: пул {pool_id} не имеет purchaseDetails")
                            continue

                        purchase_detail = purchase_details[0]
                        coin = purchase_detail.get('currencyName')

                        # APR (в формате строки "0.0437" = 4.37%)
                        apr_data = pool.get('apr', {})
                        apr_str = apr_data.get('apr', '0')
                        apr = float(apr_str) * 100  # Конвертируем в проценты

                        # Монета награды (из rewardDetails пула)
                        reward_details = pool.get('rewardDetails', [])
                        reward_coin = None
                        reward_amount = None
                        if reward_details:
                            reward_coin = reward_details[0].get('currencyName')
                            reward_amount = reward_details[0].get('rewardAmount')

                        # Заполненность пула
                        pool_accumulated = purchase_detail.get('poolAccumulatedPurchaseAmount')
                        current_deposit = float(pool_accumulated) if pool_accumulated else None

                        # Лимиты
                        # ВАЖНО: В OKX API нет информации об общем лимите пула!
                        # maxStakingLimit - это лимит для ОДНОГО пользователя максимального VIP уровня
                        # Поэтому мы НЕ можем рассчитать корректный fill_percentage
                        limit_data = purchase_detail.get('limit', {})
                        max_staking_limit = limit_data.get('maxStakingLimit')

                        # Лимит для VIP 0 (обычные пользователи)
                        user_limit_str = purchase_detail.get('upperLimit')
                        user_limit_tokens = float(user_limit_str) if user_limit_str else None

                        # Процент заполнения - недоступен для OKX (нет данных об общем лимите)
                        fill_percentage = None
                        max_capacity = None  # Общий лимит пула недоступен в API

                        # Получаем цену токена стейкинга
                        token_price = self.price_fetcher.get_token_price(coin) if coin else None

                        # Получаем цену токена награды
                        reward_token_price = None
                        if reward_coin and reward_coin != coin:
                            reward_token_price = self.price_fetcher.get_token_price(reward_coin)

                        # Лимит в USD
                        user_limit_usd = None
                        if user_limit_tokens and token_price:
                            user_limit_usd = round(user_limit_tokens * token_price, 2)

                        # Название пула (обычно совпадает с монетой стейкинга)
                        pool_name = pool.get('projectName', coin)

                        staking = {
                            'exchange': 'OKX',
                            'product_id': pool_id,
                            'coin': coin,
                            'reward_coin': reward_coin if reward_coin != coin else None,
                            'apr': apr,
                            'type': 'Flash Earn',  # OKX Flash Earn - всегда flexible
                            'status': 'Active',  # Только активные в ongoingProjects
                            'category': None,
                            'category_text': None,
                            'term_days': 0,  # Flash Earn = flexible
                            'token_price_usd': token_price,
                            'reward_token_price_usd': reward_token_price,
                            'start_time': project.get('startTime'),
                            'end_time': end_time,
                            'user_limit_tokens': user_limit_tokens,
                            'user_limit_usd': user_limit_usd,
                            'total_places': None,
                            'max_capacity': max_capacity,
                            'current_deposit': current_deposit,
                            'fill_percentage': fill_percentage,
                            'pool_name': pool_name,
                            'reward_amount': reward_amount,
                        }

                        stakings.append(staking)
                        total_pools += 1

                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка парсинга OKX пула: {e}")
                        continue

            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга OKX проекта: {e}")
                continue

        logger.info(f"✅ OKX: обработано {total_pools} пулов")
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
