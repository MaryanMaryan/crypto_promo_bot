# parsers/universal_fallback_parser.py
"""
УНИВЕРСАЛЬНЫЙ FALLBACK ПАРСЕР ДЛЯ CRYPTO PROMO BOT v3.0
Мульти-стратегический парсинг: API → HTML → Комбинированный
"""

import logging
import hashlib
import time
import requests
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from .base_parser import BaseParser
from .html_templates import get_html_selectors, get_html_urls

logger = logging.getLogger(__name__)

class UniversalFallbackParser(BaseParser):
    """Универсальный парсер с автоматическим fallback между API и HTML"""

    def __init__(self, url: str, api_urls: List[str] = None, html_urls: List[str] = None):
        super().__init__(url)
        self.strategy_used = None
        self.combined_data = []
        self.exchange = self._extract_exchange_from_url(url)  # ✅ ДОБАВИТЬ
        # Дополнительные URL для FALLBACK системы
        self.api_urls = api_urls or []
        self.html_urls = html_urls or []
        
    def _extract_exchange_from_url(self, url: str) -> str:
        """Извлекает название биржи из URL"""
        if 'bybit' in url.lower():
            return 'bybit'
        elif 'binance' in url.lower():
            return 'binance'
        elif 'mexc' in url.lower():
            return 'mexc'
        elif 'gate' in url.lower():
            return 'gate'
        elif 'okx' in url.lower():
            return 'okx'
        elif 'bitget' in url.lower():
            return 'bitget'
        else:
            return 'unknown'
    
    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Универсальный метод выполнения запроса через систему ротации"""
        try:
            # Используем метод make_request из BaseParser
            response = self.make_request(url)
            return response
        except Exception as e:
            logger.error(f"❌ Ошибка запроса к {url}: {e}")
            return None
    
    # Остальные методы остаются без изменений...
    def get_promotions(self) -> List[Dict[str, Any]]:
        """Основной метод получения промоакций с приоритетной системой"""
        logger.info("=" * 80)
        logger.info(f"🎯 UniversalFallbackParser: Начало мульти-стратегического парсинга")
        logger.info(f"   Биржа: {self.exchange}")
        logger.info(f"   URL: {self.url}")

        strategy_priority = self._get_strategy_priority()
        logger.info(f"📋 Приоритет стратегий для {self.exchange}: {strategy_priority}")

        results = []

        for i, strategy in enumerate(strategy_priority, 1):
            try:
                logger.info("-" * 60)
                logger.info(f"🔄 Стратегия {i}/{len(strategy_priority)}: {strategy.upper()}")

                if strategy == "api" and self._is_api_url():
                    logger.info(f"🔧 Начало API парсинга для {self.exchange}")
                    logger.info(f"   URL распознан как API endpoint: {self.url}")

                    api_results = self._parse_via_api()

                    if api_results:
                        results.extend(api_results)
                        self.strategy_used = "api"
                        logger.info(f"✅ API парсинг УСПЕШЕН: найдено {len(api_results)} промоакций")
                        for j, promo in enumerate(api_results[:5], 1):
                            logger.info(f"   {j}. {promo.get('title', 'Без названия')}")
                        if len(api_results) > 5:
                            logger.info(f"   ... и еще {len(api_results) - 5} промоакций")
                    else:
                        logger.warning(f"⚠️ API парсинг не вернул результатов")

                elif strategy == "html":
                    logger.info(f"🌐 Начало HTML парсинга для {self.exchange}")
                    html_results = self._parse_via_html()

                    if html_results:
                        results.extend(html_results)
                        self.strategy_used = "html" if not self.strategy_used else "combined"
                        logger.info(f"✅ HTML парсинг УСПЕШЕН: найдено {len(html_results)} промоакций")
                        for j, promo in enumerate(html_results[:5], 1):
                            logger.info(f"   {j}. {promo.get('title', 'Без названия')}")
                        if len(html_results) > 5:
                            logger.info(f"   ... и еще {len(html_results) - 5} промоакций")
                    else:
                        logger.warning(f"⚠️ HTML парсинг не вернул результатов")

                else:
                    if strategy == "api" and not self._is_api_url():
                        logger.info(f"⏭️ Пропускаем API парсинг: URL не является API endpoint")

            except Exception as e:
                logger.error(f"❌ ОШИБКА в стратегии {strategy} для {self.exchange}: {e}", exc_info=True)
                continue

        logger.info("-" * 60)

        if len(results) > 0:
            logger.info(f"🔄 Объединение и дедупликация {len(results)} результатов...")
            final_results = self._combine_and_deduplicate(results)
            logger.info(f"🎉 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ: {len(final_results)} уникальных промоакций")
            logger.info(f"📊 Использованная стратегия: {self.strategy_used}")
            logger.info("=" * 80)
            return final_results
        else:
            logger.error(f"❌ ВСЕ СТРАТЕГИИ ПАРСИНГА ПРОВАЛИЛИСЬ для {self.exchange}")
            logger.error(f"   Попробованные стратегии: {strategy_priority}")
            logger.info("=" * 80)
            return []
    
    def _get_strategy_priority(self) -> List[str]:
        """Определяет приоритет стратегий для каждой биржи"""
        strategy_map = {
            "bybit": ["html", "api"],
            "mexc": ["api", "html"],
            "binance": ["html"],
            "gate": ["html"],
            "okx": ["html"],
            "bitget": ["html"]
        }
        return strategy_map.get(self.exchange, ["html", "api"])
    
    def _is_api_url(self) -> bool:
        """Проверяет, является ли URL API endpoint'ом"""
        api_indicators = ['/api/', '/x-api/', '/v1/', '/v2/', '/v3/', '/v4/', '/v5/']
        return any(indicator in self.url.lower() for indicator in api_indicators)
    
    def _parse_via_api(self) -> List[Dict[str, Any]]:
        """Парсинг через API (использует UniversalParser) с поддержкой множественных URL"""
        try:
            from .universal_parser import UniversalParser

            all_api_promos = []

            # Парсим основной URL если он API
            if self._is_api_url():
                logger.info(f"📡 Парсинг основного API URL: {self.url}")
                api_parser = UniversalParser(self.url)
                promotions = api_parser.get_promotions()

                for promo in promotions:
                    promo['data_source'] = 'api'
                    promo['source_url'] = self.url
                    if not promo.get('promo_id'):
                        promo['promo_id'] = self._generate_html_promo_id(promo)

                all_api_promos.extend(promotions)
                logger.info(f"✅ Основной API URL вернул {len(promotions)} промоакций")

            # Парсим дополнительные API URLs
            if self.api_urls:
                logger.info(f"📡 Парсинг {len(self.api_urls)} дополнительных API URLs...")
                for i, api_url in enumerate(self.api_urls, 1):
                    try:
                        logger.info(f"   [{i}/{len(self.api_urls)}] Парсинг {api_url}")
                        api_parser = UniversalParser(api_url)
                        promotions = api_parser.get_promotions()

                        for promo in promotions:
                            promo['data_source'] = 'api'
                            promo['source_url'] = api_url
                            if not promo.get('promo_id'):
                                promo['promo_id'] = self._generate_html_promo_id(promo)

                        all_api_promos.extend(promotions)
                        logger.info(f"   ✅ API URL #{i} вернул {len(promotions)} промоакций")

                    except Exception as e:
                        logger.error(f"   ❌ Ошибка парсинга API URL #{i}: {e}")
                        continue

            logger.info(f"📊 Всего получено {len(all_api_promos)} промоакций из всех API URLs")
            return all_api_promos

        except Exception as e:
            logger.error(f"❌ Ошибка API парсинга: {e}")
            return []
    
    def _parse_via_html(self) -> List[Dict[str, Any]]:
        """Парсинг через HTML страницы с поддержкой множественных URL"""
        try:
            all_html_urls = []

            # Добавляем основной URL если он не API
            if not self._is_api_url():
                all_html_urls.append(self.url)
                logger.info(f"🌐 Добавлен основной HTML URL: {self.url}")

            # Добавляем дополнительные HTML URLs из базы данных
            if self.html_urls:
                all_html_urls.extend(self.html_urls)
                logger.info(f"🌐 Добавлено {len(self.html_urls)} дополнительных HTML URLs из БД")

            # Если нет URL из БД, пытаемся получить из шаблонов
            if not all_html_urls:
                logger.info(f"🔍 Поиск HTML URL для биржи {self.exchange} в шаблонах...")
                html_urls = get_html_urls(self.exchange)

                if not html_urls:
                    logger.warning(f"⚠️ Нет настроенных HTML URL для биржи {self.exchange}")
                    logger.warning(f"   Необходимо добавить HTML ссылки через бот или в html_templates.py")
                    return []

                all_html_urls.extend(html_urls)

            logger.info(f"📋 Всего {len(all_html_urls)} HTML URL для парсинга:")
            for i, url in enumerate(all_html_urls, 1):
                logger.info(f"   {i}. {url}")

            all_html_promos = []

            for i, html_url in enumerate(all_html_urls, 1):
                try:
                    logger.info(f"🌐 [{i}/{len(all_html_urls)}] Парсинг HTML страницы: {html_url}")
                    response = self._make_request(html_url)

                    if not response:
                        logger.warning(f"⚠️ Не получен ответ от {html_url}")
                        continue

                    if response.status_code != 200:
                        logger.warning(f"⚠️ Неуспешный статус код {response.status_code} для {html_url}")
                        continue

                    logger.info(f"✅ HTML страница успешно загружена, размер: {len(response.text)} символов")

                    html_promos = self._parse_html_content(response.text, html_url)
                    all_html_promos.extend(html_promos)

                    if html_promos:
                        logger.info(f"✅ Найдено {len(html_promos)} промоакций в {html_url}")
                    else:
                        logger.warning(f"⚠️ Промоакции не найдены в {html_url}")

                    if i < len(all_html_urls):
                        logger.debug(f"⏳ Пауза 2 секунды перед следующим запросом...")
                        time.sleep(2)

                except Exception as e:
                    logger.error(f"❌ Ошибка парсинга HTML {html_url}: {e}", exc_info=True)
                    continue

            logger.info(f"📊 Всего найдено {len(all_html_promos)} промоакций из всех HTML URLs")
            return all_html_promos

        except Exception as e:
            logger.error(f"❌ Общая ошибка HTML парсинга: {e}", exc_info=True)
            return []
    
    def _parse_html_content(self, html_content: str, source_url: str) -> List[Dict[str, Any]]:
        """Парсит контент HTML страницы"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            selectors = get_html_selectors(self.exchange)
            
            if not selectors:
                logger.warning(f"⚠️ Нет селекторов для биржи {self.exchange}")
                return []
            
            containers = soup.select(selectors['container'])
            logger.info(f"🔍 Найдено {len(containers)} контейнеров на {self.exchange}")
            
            promotions = []
            
            for container in containers:
                try:
                    promo = self._extract_promo_from_container(container, selectors, source_url)
                    if promo and self._is_valid_promo(promo):
                        promotions.append(promo)
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка извлечения промо из контейнера: {e}")
                    continue
            
            return promotions
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга HTML контента: {e}")
            return []
    
    def _extract_promo_from_container(self, container, selectors: dict, source_url: str) -> Optional[Dict[str, Any]]:
        """Извлекает данные промоакции из HTML контейнера"""
        try:
            promo = {
                'exchange': self.exchange,
                'data_source': 'html',
                'source_url': source_url
            }
            
            title_element = container.select_one(selectors['title'])
            if title_element:
                promo['title'] = title_element.get_text(strip=True)
            
            desc_element = container.select_one(selectors.get('description', ''))
            if desc_element:
                promo['description'] = desc_element.get_text(strip=True)
            
            link_element = container.select_one(selectors.get('link', ''))
            if link_element and link_element.get('href'):
                link = link_element.get('href')
                if link.startswith('/'):
                    base_domain = '/'.join(source_url.split('/')[:3])
                    promo['link'] = base_domain + link
                else:
                    promo['link'] = link
            
            time_element = container.select_one(selectors.get('time', ''))
            if time_element:
                promo['start_time'] = time_element.get_text(strip=True)
            
            prize_element = container.select_one(selectors.get('prize', ''))
            if prize_element:
                promo['total_prize_pool'] = prize_element.get_text(strip=True)
            
            token_element = container.select_one(selectors.get('token', ''))
            if token_element:
                promo['award_token'] = token_element.get_text(strip=True)
            
            participants_element = container.select_one(selectors.get('participants', ''))
            if participants_element:
                promo['participants_count'] = participants_element.get_text(strip=True)
            
            image_element = container.select_one(selectors.get('image', ''))
            if image_element and image_element.get('src'):
                promo['icon'] = image_element.get('src')
            
            if promo.get('title') or promo.get('link'):
                promo['promo_id'] = self._generate_html_promo_id(promo)
                return promo
            
            return None
            
        except Exception as e:
            logger.debug(f"⚠️ Ошибка извлечения промо из контейнера: {e}")
            return None
    
    def _generate_html_promo_id(self, promo: Dict[str, Any]) -> str:
        """Генерирует уникальный ID для HTML промоакции"""
        try:
            title = promo.get('title', '')
            link = promo.get('link', '')
            exchange = promo.get('exchange', '')
            
            stable_key = f"{exchange}_{title}_{link}"
            content_hash = hashlib.md5(stable_key.encode('utf-8')).hexdigest()[:12]
            return f"{exchange}_html_{content_hash}"
            
        except Exception as e:
            logger.error(f"❌ Ошибка генерации HTML ID: {e}")
            return f"{self.exchange}_html_error"
    
    def _is_valid_promo(self, promo: Dict[str, Any]) -> bool:
        """Проверяет валидность промоакции"""
        if not promo.get('title') and not promo.get('description'):
            return False
        
        if not promo.get('promo_id'):
            return False
        
        return True
    
    def _combine_and_deduplicate(self, promotions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Комбинирует и дедуплицирует промоакции из разных источников"""
        try:
            unique_promos = {}
            
            for promo in promotions:
                promo_id = promo.get('promo_id')
                if not promo_id:
                    continue
                
                if promo_id in unique_promos:
                    existing_promo = unique_promos[promo_id]
                    self._merge_promo_data(existing_promo, promo)
                else:
                    unique_promos[promo_id] = promo
            
            return list(unique_promos.values())
            
        except Exception as e:
            logger.error(f"❌ Ошибка комбинирования данных: {e}")
            return promotions
    
    def _merge_promo_data(self, existing_promo: Dict[str, Any], new_promo: Dict[str, Any]):
        """Объединяет данные из разных источников"""
        try:
            for key, value in new_promo.items():
                if key not in existing_promo or not existing_promo[key]:
                    existing_promo[key] = value
            
            if 'data_sources' not in existing_promo:
                existing_promo['data_sources'] = []
            
            source = new_promo.get('data_source', 'unknown')
            if source not in existing_promo['data_sources']:
                existing_promo['data_sources'].append(source)
            
            if len(existing_promo['data_sources']) > 1:
                existing_promo['data_source'] = 'combined'
                
        except Exception as e:
            logger.error(f"❌ Ошибка объединения данных: {e}")
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """Возвращает информацию о использованной стратегии"""
        return {
            'exchange': self.exchange,
            'strategy_used': self.strategy_used,
            'url': self.url,
            'combined_data_count': len(self.combined_data)
        }

    def get_error_stats(self) -> Dict[str, Any]:
        """Возвращает статистику ошибок парсинга"""
        # Пока что возвращаем базовую статистику
        # В будущем можно добавить трекинг ошибок
        return {
            'total_errors': 0,
            'api_errors': 0,
            'html_errors': 0
        }


# Тестирование парсера
if __name__ == "__main__":
    def test_fallback_parser():
        """Тестирование fallback парсера"""
        test_urls = [
            "https://www.mexc.com/api/financialactivity/launchpad/list",  # API
            "https://www.bybit.com/en/trade/spot/token-splash",  # HTML
            "https://www.binance.com/ru/"  # HTML
        ]
        
        for url in test_urls:
            print(f"\n=== Тестирование {url} ===")
            try:
                parser = UniversalFallbackParser(url)
                promos = parser.get_promotions()
                print(f"Найдено промоакций: {len(promos)}")
                if promos:
                    for promo in promos[:2]:
                        print(f" - {promo.get('title')} | {promo.get('link')}")
                print(f"Стратегия: {parser.get_strategy_info()}")
            except Exception as e:
                print(f"❌ Ошибка: {e}")
    
    test_fallback_parser()