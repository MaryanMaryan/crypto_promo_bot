"""
parsers/staking_parser.py
Универсальный парсер стейкингов для Kucoin и Bybit
"""

import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from utils.price_fetcher import get_price_fetcher
from utils.exchange_auth_manager import get_exchange_auth_manager
from bybit_coin_mapping import BYBIT_COIN_MAPPING

logger = logging.getLogger(__name__)

class StakingParser:
    """Парсер стейкингов"""

    def __init__(self, api_url: str, exchange_name: str = None, use_auth: bool = True):
        self.api_url = api_url
        # Автоопределение биржи по URL если exchange_name не указан
        self.exchange_name = self._detect_exchange(api_url, exchange_name)
        self.price_fetcher = get_price_fetcher()
        
        # Авторизация для получения расширенных данных (user_limit)
        self.use_auth = use_auth
        self.auth_manager = get_exchange_auth_manager() if use_auth else None

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
                return self._parse_bybit_with_auth()

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

            elif 'gate' in self.exchange_name:
                # Gate.io использует обычный GET с пагинацией
                return self._parse_gate()

            else:
                logger.warning(f"⚠️ Неизвестная биржа: {self.exchange_name}")
                return []

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга стейкингов: {e}", exc_info=True)
            return []

    def _parse_bybit_with_auth(self) -> List[Dict[str, Any]]:
        """
        Парсинг Bybit стейкингов с авторизацией для получения user_limit
        
        Если авторизация доступна - использует приватный API,
        иначе fallback на публичный API.
        При ошибках API (403/404) используется браузерный парсинг.
        """
        # Проверяем наличие ключей Bybit
        has_auth = self.use_auth and self.auth_manager and self.auth_manager.has_credentials('bybit')
        
        if has_auth:
            logger.info("🔑 Bybit: использую авторизованный запрос")
        else:
            logger.info("📢 Bybit: публичный запрос (без user_limit)")
        
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
        
        # Если есть авторизация - добавляем подпись
        if has_auth:
            auth_headers = self.auth_manager.get_bybit_headers(payload)
            if auth_headers:
                headers.update(auth_headers)
        
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            
            # Если API заблокирован (403/404) - используем браузерный парсинг
            if response.status_code in (403, 404):
                logger.warning(f"⚠️ Bybit API вернул {response.status_code}, пробуем браузерный парсинг...")
                return self._parse_bybit_with_browser(has_auth)
            
            response.raise_for_status()
            data = response.json()

            # Проверяем статус ответа
            if data.get('ret_code') != 0:
                logger.error(f"❌ Bybit API error: {data.get('ret_msg')}")
                return []

            return self._parse_bybit(data, has_auth=has_auth)
            
        except requests.exceptions.HTTPError as e:
            # Для других HTTP ошибок тоже пробуем браузер
            if hasattr(e, 'response') and e.response.status_code in (403, 404):
                logger.warning(f"⚠️ Bybit API HTTP ошибка, пробуем браузерный парсинг...")
                return self._parse_bybit_with_browser(has_auth)
            logger.error(f"❌ Ошибка Bybit парсинга: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Ошибка Bybit парсинга: {e}")
            return []
    
    def _parse_bybit_with_browser(self, has_auth: bool = False) -> List[Dict[str, Any]]:
        """
        Fallback парсинг Bybit через браузер когда API заблокирован
        
        Args:
            has_auth: Есть ли авторизация (для парсинга user_limit)
            
        Returns:
            Список стейкингов
        """
        try:
            from .browser_parser import BrowserParser
            
            logger.info("🌐 Bybit: использую браузерный парсинг (API заблокирован)")
            
            browser_parser = BrowserParser(self.api_url)
            promotions = browser_parser.get_promotions()
            
            if not promotions:
                logger.warning("⚠️ Браузерный парсинг Bybit не вернул данных")
                return []
            
            # Конвертируем промоакции в формат стейкингов
            stakings = []
            for promo in promotions:
                staking = {
                    'exchange': 'Bybit',
                    'product_id': promo.get('product_id', ''),
                    'coin': promo.get('coin', promo.get('title', 'Unknown')),
                    'reward_coin': promo.get('reward_coin'),
                    'apr': promo.get('apr', 0),
                    'type': promo.get('type', 'Unknown'),
                    'status': promo.get('status', 'Unknown'),
                    'category': promo.get('category'),
                    'category_text': promo.get('category_text'),
                    'term_days': promo.get('term_days', 0),
                    'token_price_usd': promo.get('token_price_usd'),
                    'start_time': promo.get('start_time'),
                    'end_time': promo.get('end_time'),
                    'user_limit_tokens': promo.get('user_limit_tokens'),
                    'user_limit_usd': promo.get('user_limit_usd'),
                    'max_capacity': promo.get('max_capacity'),
                    'current_deposit': promo.get('current_deposit'),
                    'fill_percentage': promo.get('fill_percentage'),
                    'is_vip': promo.get('is_vip', False),
                    'is_new_user': promo.get('is_new_user', False),
                }
                stakings.append(staking)
            
            logger.info(f"✅ Браузерный парсинг: получено {len(stakings)} стейкингов")
            return stakings
            
        except Exception as e:
            logger.error(f"❌ Ошибка браузерного парсинга Bybit: {e}")
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

    def _parse_bybit(self, data: dict, has_auth: bool = False) -> List[Dict[str, Any]]:
        """
        Парсинг Bybit стейкингов
        ВАЖНО: Bybit API требует POST запрос с JSON payload
        
        Args:
            data: Ответ API
            has_auth: Есть ли авторизация (для парсинга user_limit)
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

                        # Парсинг user_limit (доступен только с авторизацией)
                        user_limit_tokens = None
                        user_limit_usd = None
                        
                        # Пробуем получить user_max_subscribe (лимит на пользователя)
                        user_max_subscribe = product.get('user_max_subscribe')
                        if user_max_subscribe:
                            try:
                                user_limit_tokens = float(user_max_subscribe)
                                if token_price and user_limit_tokens:
                                    user_limit_usd = round(user_limit_tokens * token_price, 2)
                            except:
                                pass
                        
                        # Альтернативные поля для лимита
                        if user_limit_tokens is None:
                            # Пробуем min_purchase_amount как альтернативу
                            min_purchase = product.get('min_purchase_amount') or product.get('min_subscribe_amount')
                            max_purchase = product.get('max_purchase_amount') or product.get('max_subscribe_amount')
                            if max_purchase:
                                try:
                                    user_limit_tokens = float(max_purchase)
                                    if token_price and user_limit_tokens:
                                        user_limit_usd = round(user_limit_tokens * token_price, 2)
                                except:
                                    pass
                        
                        if has_auth and user_limit_tokens:
                            logger.debug(f"🔑 {coin_name}: user_limit = {user_limit_tokens} (${user_limit_usd})")

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
                            'user_limit_tokens': user_limit_tokens,
                            'user_limit_usd': user_limit_usd,
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

                        # Общая сумма наград проекта
                        total_reward_amount = None
                        if project_rewards:
                            total_reward_amount = project_rewards[0].get('totalRewardAmount')

                        # Время до конца (countdown)
                        countdown = project.get('countdownToEnd', 0)

                        staking = {
                            'exchange': 'OKX',
                            'product_id': pool_id,
                            'project_id': project_id,  # ID проекта для группировки
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
                            'countdown': countdown,  # Время до конца в мс
                            'user_limit_tokens': user_limit_tokens,
                            'user_limit_usd': user_limit_usd,
                            'total_places': None,
                            'max_capacity': max_capacity,
                            'current_deposit': current_deposit,
                            'fill_percentage': fill_percentage,
                            'pool_name': pool_name,
                            'reward_amount': reward_amount,
                            'total_reward_amount': total_reward_amount,  # Общий пул наград
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

    def _parse_gate(self) -> List[Dict[str, Any]]:
        """
        Парсинг Gate.io стейкингов с пагинацией и объединением Fixed/Flexible
        ВАЖНО: Gate.io API требует GET запрос с пагинацией через параметр page
        """
        stakings = []

        # Параметры для пагинации
        page = 1
        limit = 100  # Увеличиваем лимит для эффективности

        try:
            logger.info(f"🔍 Gate.io: начало парсинга с пагинацией")

            while True:
                # Формируем URL с параметрами
                # Извлекаем базовый URL без параметров
                base_url = self.api_url.split('?')[0]

                # Формируем параметры
                params = {
                    'available': 'false',
                    'limit': limit,
                    'have_balance': 2,
                    'have_award': 0,
                    'is_subscribed': 0,
                    'sort_business': 1,
                    'kyc_level': 1,
                    'search_type': 0,
                    'page': page
                }

                headers = {
                    'accept': 'application/json',
                    'accept-language': 'en-US,en;q=0.9',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                logger.info(f"📄 Gate.io: запрос страницы {page}")
                response = requests.get(base_url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                # Проверяем статус ответа
                if data.get('code') != 0:
                    logger.error(f"❌ Gate.io API error: {data.get('message')}")
                    break

                # Получаем список монет
                coin_list = data.get('data', {}).get('list', [])

                if not coin_list:
                    logger.info(f"📭 Gate.io: страница {page} пустая, завершаем пагинацию")
                    break

                logger.info(f"📊 Gate.io: найдено {len(coin_list)} монет на странице {page}")

                # Парсим каждую монету
                for coin_data in coin_list:
                    try:
                        coin = coin_data.get('asset')

                        # ФИЛЬТР 1: Проверяем total_lend_available
                        total_lend_available = float(coin_data.get('total_lend_available', 0))
                        if total_lend_available <= 0:
                            logger.debug(f"🔽 Gate.io: пропущена монета {coin} (total_lend_available={total_lend_available})")
                            continue

                        # ФИЛЬТР 2: Проверяем заполненность
                        total_lend_amount = float(coin_data.get('total_lend_amount', 0))
                        total_lend_all_amount = float(coin_data.get('total_lend_all_amount', 0))
                        fill_percentage = None
                        if total_lend_all_amount > 0:
                            fill_percentage = round((total_lend_amount / total_lend_all_amount) * 100, 2)
                            # Скрываем 100% заполненные
                            if fill_percentage >= 100:
                                logger.debug(f"🔽 Gate.io: пропущена монета {coin} (заполненность={fill_percentage}%)")
                                continue

                        # Собираем Fixed и Flexible продукты
                        fixed_list = coin_data.get('fixed_list') or []
                        fixable_list = coin_data.get('fixable_list') or []

                        # Создаем объединенный продукт если есть оба типа
                        combined_staking = self._create_combined_gate_product(
                            coin, coin_data, fixed_list, fixable_list
                        )

                        if combined_staking:
                            stakings.append(combined_staking)

                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка парсинга монеты Gate.io: {e}")
                        continue

                # Проверяем, есть ли еще страницы
                # Если вернулось меньше чем limit, значит это последняя страница
                if len(coin_list) < limit:
                    logger.info(f"✅ Gate.io: достигнута последняя страница {page}")
                    break

                page += 1

                # Защита от бесконечного цикла (максимум 100 страниц)
                if page > 100:
                    logger.warning(f"⚠️ Gate.io: достигнут лимит страниц (100)")
                    break

            logger.info(f"✅ Gate.io: обработано {len(stakings)} стейкингов")
            return stakings

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга Gate.io: {e}", exc_info=True)
            return []

    def _create_combined_gate_product(
        self,
        coin: str,
        coin_data: dict,
        fixed_list: list,
        fixable_list: list
    ) -> Optional[Dict[str, Any]]:
        """
        Создает объединенный продукт Gate.io из Fixed и Flexible стейкингов

        Правила:
        - Если есть оба типа → создать объединенный продукт "Fixed/Flexible"
        - Если только один тип → создать обычный продукт
        - Данные пула → показывать только для Flexible (когда оба типа есть)
        - APR → максимальный из обоих типов

        Args:
            coin: Символ монеты
            coin_data: Общие данные монеты из API
            fixed_list: Список фиксированных продуктов
            fixable_list: Список гибких продуктов

        Returns:
            Словарь с данными стейкинга или None
        """
        try:
            # Фильтруем активные продукты (sale_status=1)
            active_fixed = [p for p in fixed_list if p.get('sale_status') == 1]
            active_flexible = [p for p in fixable_list if p.get('sale_status') == 1]

            # Если нет активных продуктов - пропускаем
            if not active_fixed and not active_flexible:
                logger.debug(f"🔽 Gate.io: нет активных продуктов для {coin}")
                return None

            # Получаем цену токена
            token_price = self.price_fetcher.get_token_price(coin) if coin else None

            # Данные о пуле (общие для монеты)
            total_lend_amount = float(coin_data.get('total_lend_amount', 0))
            total_lend_all_amount = float(coin_data.get('total_lend_all_amount', 0))

            fill_percentage = None
            max_capacity = None
            current_deposit = None

            if total_lend_all_amount > 0:
                max_capacity = total_lend_all_amount
                current_deposit = total_lend_amount
                fill_percentage = round((total_lend_amount / total_lend_all_amount) * 100, 2)

            # СЛУЧАЙ 1: Есть оба типа - создаем объединенный продукт
            if active_fixed and active_flexible:
                # Берем максимальный APR из Fixed
                fixed_apr = max(float(p.get('year_rate', 0)) * 100 for p in active_fixed)

                # Берем максимальный APR из Flexible
                flexible_product = active_flexible[0]  # Обычно один Flexible продукт
                flexible_apr_str = flexible_product.get('max_year_rate') or flexible_product.get('year_rate', '0')
                flexible_apr = float(flexible_apr_str) * 100

                # Максимальный APR для отображения
                max_apr = max(fixed_apr, flexible_apr)

                # Лимит на аккаунт (из Flexible)
                user_limit_tokens = float(flexible_product.get('user_max_lend_amount', 0))
                user_limit_usd = None
                if user_limit_tokens and user_limit_tokens > 0 and token_price:
                    user_limit_usd = round(user_limit_tokens * token_price, 2)

                # Product ID (комбинированный)
                product_id = f"gate_combined_{coin}"

                staking = {
                    'exchange': 'Gate.io',
                    'product_id': product_id,
                    'coin': coin,
                    'reward_coin': None,
                    'apr': max_apr,
                    'type': 'Fixed/Flexible',  # Объединенный тип
                    'status': 'Active',
                    'category': 'Combined',
                    'category_text': f'Fixed: {fixed_apr:.1f}% | Flexible: {flexible_apr:.1f}%',
                    'term_days': 0,  # Для комбинированного используем 0
                    'token_price_usd': token_price,
                    'reward_token_price_usd': None,
                    'start_time': None,
                    'end_time': None,
                    'user_limit_tokens': user_limit_tokens if user_limit_tokens > 0 else None,
                    'user_limit_usd': user_limit_usd,
                    'total_places': None,
                    # Данные пула показываем только для Flexible (по требованию)
                    'max_capacity': max_capacity,
                    'current_deposit': current_deposit,
                    'fill_percentage': fill_percentage,
                    'is_vip': False,
                    'is_new_user': False,
                    'regional_tag': None,
                    'regional_countries': None,
                    # Дополнительные поля для объединенного продукта
                    'fixed_apr': fixed_apr,
                    'flexible_apr': flexible_apr,
                }

                logger.debug(f"✅ Gate.io: создан объединенный продукт {coin} (Fixed: {fixed_apr:.1f}% | Flexible: {flexible_apr:.1f}%)")
                return staking

            # СЛУЧАЙ 2: Только Fixed продукты
            elif active_fixed and not active_flexible:
                # Берем продукт с максимальным APR
                best_fixed = max(active_fixed, key=lambda p: float(p.get('year_rate', 0)))
                apr = float(best_fixed.get('year_rate', 0)) * 100
                lock_period = int(best_fixed.get('lock_up_period', 0))

                product_type = f"Fixed {lock_period}d" if lock_period > 0 else "Flexible"
                product_id = f"gate_fixed_{best_fixed.get('id')}_{coin}"

                # Лимит на аккаунт
                user_limit_tokens = float(best_fixed.get('user_max_lend_volume', 0))
                user_limit_usd = None
                if user_limit_tokens and user_limit_tokens > 0 and token_price:
                    user_limit_usd = round(user_limit_tokens * token_price, 2)

                staking = {
                    'exchange': 'Gate.io',
                    'product_id': product_id,
                    'coin': coin,
                    'reward_coin': None,
                    'apr': apr,
                    'type': product_type,
                    'status': 'Active',
                    'category': None,
                    'category_text': None,
                    'term_days': lock_period,
                    'token_price_usd': token_price,
                    'reward_token_price_usd': None,
                    'start_time': None,
                    'end_time': None,
                    'user_limit_tokens': user_limit_tokens if user_limit_tokens > 0 else None,
                    'user_limit_usd': user_limit_usd,
                    'total_places': None,
                    'max_capacity': max_capacity,
                    'current_deposit': current_deposit,
                    'fill_percentage': fill_percentage,
                    'is_vip': False,
                    'is_new_user': False,
                    'regional_tag': None,
                    'regional_countries': None,
                }

                logger.debug(f"✅ Gate.io: создан Fixed продукт {coin} ({apr:.1f}%)")
                return staking

            # СЛУЧАЙ 3: Только Flexible продукты
            elif active_flexible and not active_fixed:
                flexible_product = active_flexible[0]

                # APR
                max_apr_str = flexible_product.get('max_year_rate') or flexible_product.get('year_rate', '0')
                apr = float(max_apr_str) * 100

                # Лимит на аккаунт
                user_limit_tokens = float(flexible_product.get('user_max_lend_amount', 0))
                user_limit_usd = None
                if user_limit_tokens and user_limit_tokens > 0 and token_price:
                    user_limit_usd = round(user_limit_tokens * token_price, 2)

                product_id = f"gate_flexible_{flexible_product.get('id')}_{coin}"

                staking = {
                    'exchange': 'Gate.io',
                    'product_id': product_id,
                    'coin': coin,
                    'reward_coin': None,
                    'apr': apr,
                    'type': 'Flexible',
                    'status': 'Active',
                    'category': None,
                    'category_text': None,
                    'term_days': 0,
                    'token_price_usd': token_price,
                    'reward_token_price_usd': None,
                    'start_time': None,
                    'end_time': None,
                    'user_limit_tokens': user_limit_tokens if user_limit_tokens > 0 else None,
                    'user_limit_usd': user_limit_usd,
                    'total_places': None,
                    'max_capacity': max_capacity,
                    'current_deposit': current_deposit,
                    'fill_percentage': fill_percentage,
                    'is_vip': False,
                    'is_new_user': False,
                    'regional_tag': None,
                    'regional_countries': None,
                }

                logger.debug(f"✅ Gate.io: создан Flexible продукт {coin} ({apr:.1f}%)")
                return staking

            return None

        except Exception as e:
            logger.warning(f"⚠️ Ошибка создания объединенного продукта Gate.io для {coin}: {e}")
            return None

    def _parse_gate_fixed_product(self, coin: str, coin_data: dict, product: dict) -> Optional[Dict[str, Any]]:
        """
        Парсинг одного фиксированного стейкинга Gate.io (из fixed_list)

        Args:
            coin: Символ монеты (USDT, BTC, ETH)
            coin_data: Данные монеты с общей информацией
            product: Данные конкретного продукта из fixed_list

        Returns:
            Словарь с данными стейкинга или None если не подходит под фильтры
        """
        try:
            # Проверка статуса (1 = активный)
            sale_status = product.get('sale_status')
            if sale_status != 1:
                logger.debug(f"🔽 Gate.io: пропущен неактивный продукт {coin} (sale_status={sale_status})")
                return None

            # Получаем APR (уже в процентах, нужно конвертировать из строки)
            apr_str = product.get('year_rate', '0')
            apr = float(apr_str) * 100  # Конвертируем в проценты (0.025 -> 2.5%)

            # Получаем цену токена
            token_price = self.price_fetcher.get_token_price(coin) if coin else None

            # Product ID
            product_id = f"gate_fixed_{product.get('id')}_{coin}"

            # Период блокировки
            lock_period = int(product.get('lock_up_period', 0))

            # Тип продукта
            product_type = f"Fixed {lock_period}d" if lock_period > 0 else "Flexible"

            # VIP уровень
            min_vip = product.get('min_vip', 0)
            max_vip = product.get('max_vip', 0)
            is_vip = min_vip > 0 or max_vip > 0

            # Категория из тегов
            category = None
            category_text = None
            title = product.get('title', '')
            subtitle = product.get('subtitle', '')

            if title or subtitle:
                category = 'Promotional'
                category_text = f"{title} - {subtitle}" if subtitle else title

            if is_vip:
                category = 'VIP'
                category_text = f"VIP {min_vip}-{max_vip}" if max_vip > min_vip else f"VIP {min_vip}+"

            # Лимиты
            user_limit_tokens = float(product.get('user_max_lend_volume', 0))
            user_limit_usd = None
            if user_limit_tokens and token_price:
                user_limit_usd = round(user_limit_tokens * token_price, 2)

            # Заполненность (для фиксированных продуктов)
            # У Gate.io для fixed_list есть product_total_volume и user_total_amount
            product_total_volume = float(product.get('product_total_volume', 0))
            user_total_amount = float(product.get('user_total_amount', 0))

            fill_percentage = None
            max_capacity = None
            current_deposit = None

            # Используем данные из coin_data для общей заполненности
            total_lend_amount = float(coin_data.get('total_lend_amount', 0))
            total_lend_available = float(coin_data.get('total_lend_available', 0))
            total_lend_all_amount = float(coin_data.get('total_lend_all_amount', 0))

            # ВАЖНО: Проверяем доступность по полю total_lend_available
            # Если Gate.io API возвращает total_lend_available=0, значит стейкинг недоступен
            if total_lend_available <= 0:
                logger.debug(f"🔽 Gate.io: пропущен недоступный фиксированный продукт {coin} (total_lend_available={total_lend_available})")
                return None

            if total_lend_all_amount > 0:
                max_capacity = total_lend_all_amount
                current_deposit = total_lend_amount
                fill_percentage = round((total_lend_amount / total_lend_all_amount) * 100, 2)

            # Временные метки (если есть)
            start_time = product.get('start_time')
            end_time = product.get('end_time')

            # Форматируем даты
            start_time_str = None
            end_time_str = None

            if start_time and start_time != "0001-01-01T00:00:00Z":
                start_time_str = start_time

            if end_time and end_time != "0001-01-01T00:00:00Z":
                end_time_str = end_time

            staking = {
                'exchange': 'Gate.io',
                'product_id': product_id,
                'coin': coin,
                'reward_coin': None,  # Gate.io обычно возвращает ту же монету
                'apr': apr,
                'type': product_type,
                'status': 'Active',
                'category': category,
                'category_text': category_text,
                'term_days': lock_period,
                'token_price_usd': token_price,
                'reward_token_price_usd': None,
                'start_time': start_time_str,
                'end_time': end_time_str,
                'user_limit_tokens': user_limit_tokens if user_limit_tokens > 0 else None,
                'user_limit_usd': user_limit_usd,
                'total_places': None,
                'max_capacity': max_capacity,
                'current_deposit': current_deposit,
                'fill_percentage': fill_percentage,
                'is_vip': is_vip,
                'is_new_user': False,
                'regional_tag': None,
                'regional_countries': None,
            }

            return staking

        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга Gate.io фиксированного продукта: {e}")
            return None

    def _parse_gate_fixable_product(self, coin: str, coin_data: dict, product: dict) -> Optional[Dict[str, Any]]:
        """
        Парсинг одного гибкого стейкинга Gate.io (из fixable_list)

        Args:
            coin: Символ монеты (USDT, BTC, ETH)
            coin_data: Данные монеты с общей информацией
            product: Данные конкретного продукта из fixable_list

        Returns:
            Словарь с данными стейкинга или None если не подходит под фильтры
        """
        try:
            # Проверка статуса (1 = активный)
            sale_status = product.get('sale_status')
            if sale_status != 1:
                logger.debug(f"🔽 Gate.io: пропущен неактивный гибкий продукт {coin} (sale_status={sale_status})")
                return None

            # Получаем максимальный APR (для гибких стейкингов он может быть с бонусами)
            max_apr_str = product.get('max_year_rate', '0')
            max_apr = float(max_apr_str) * 100  # Конвертируем в проценты

            # Базовый APR
            base_apr_str = product.get('year_rate', '0')
            base_apr = float(base_apr_str) * 100

            # Используем максимальный APR для отображения
            apr = max_apr if max_apr > base_apr else base_apr

            # Получаем цену токена
            token_price = self.price_fetcher.get_token_price(coin) if coin else None

            # Product ID
            product_id = f"gate_flexible_{product.get('id')}_{coin}"

            # Тип
            product_type = "Flexible"

            # Бонусы (если есть)
            bonus_asset = product.get('bonus_asset')
            bonus_icon = product.get('bonus_icon')

            category = None
            category_text = None

            if bonus_asset:
                category = 'Bonus'
                category_text = f"Bonus: {bonus_asset}"

            # Ladder APR (ступенчатые ставки)
            ladder_apr = product.get('ladder_apr', [])
            if ladder_apr:
                # Берем максимальную ставку из ladder
                max_ladder_apr = max([float(item.get('apr', 0)) for item in ladder_apr]) * 100
                if max_ladder_apr > apr:
                    apr = max_ladder_apr

            # Лимиты
            user_max_lend = float(product.get('user_max_lend_amount', 0))
            user_limit_tokens = user_max_lend if user_max_lend > 0 else None

            user_limit_usd = None
            if user_limit_tokens and token_price:
                user_limit_usd = round(user_limit_tokens * token_price, 2)

            # Заполненность (из coin_data)
            total_lend_amount = float(coin_data.get('total_lend_amount', 0))
            total_lend_available = float(coin_data.get('total_lend_available', 0))
            total_lend_all_amount = float(coin_data.get('total_lend_all_amount', 0))

            # ВАЖНО: Проверяем доступность по полю total_lend_available
            # Если Gate.io API возвращает total_lend_available=0, значит стейкинг недоступен
            # даже если математически остается небольшой остаток
            if total_lend_available <= 0:
                logger.debug(f"🔽 Gate.io: пропущен недоступный гибкий продукт {coin} (total_lend_available={total_lend_available})")
                return None

            fill_percentage = None
            max_capacity = None
            current_deposit = None

            if total_lend_all_amount > 0:
                max_capacity = total_lend_all_amount
                current_deposit = total_lend_amount
                fill_percentage = round((total_lend_amount / total_lend_all_amount) * 100, 2)

            staking = {
                'exchange': 'Gate.io',
                'product_id': product_id,
                'coin': coin,
                'reward_coin': bonus_asset if bonus_asset else None,
                'apr': apr,
                'type': product_type,
                'status': 'Active',
                'category': category,
                'category_text': category_text,
                'term_days': 0,  # Flexible = 0 дней
                'token_price_usd': token_price,
                'reward_token_price_usd': None,
                'start_time': None,
                'end_time': None,
                'user_limit_tokens': user_limit_tokens,
                'user_limit_usd': user_limit_usd,
                'total_places': None,
                'max_capacity': max_capacity,
                'current_deposit': current_deposit,
                'fill_percentage': fill_percentage,
                'is_vip': False,
                'is_new_user': False,
                'regional_tag': None,
                'regional_countries': None,
            }

            return staking

        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга Gate.io гибкого продукта: {e}")
            return None

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
