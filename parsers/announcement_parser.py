# parsers/announcement_parser.py
"""
Умный парсер анонсов с поддержкой различных стратегий отслеживания изменений
+ Поддержка браузерного парсинга для динамических страниц с JavaScript
"""
import re
import hashlib
import logging
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class AnnouncementParser(BaseParser):
    """
    Парсер анонсов с поддержкой различных стратегий:
    - any_change: Отслеживание любых изменений на странице
    - element_change: Отслеживание изменений в конкретном элементе (CSS Selector)
    - any_keyword: Поиск любого из ключевых слов
    - all_keywords: Все ключевые слова должны присутствовать
    - regex: Поиск по регулярному выражению
    """

    def __init__(self, url: str):
        super().__init__(url)
        self.strategies = {
            'any_change': self._strategy_any_change,
            'element_change': self._strategy_element_change,
            'any_keyword': self._strategy_any_keyword,
            'all_keywords': self._strategy_all_keywords,
            'regex': self._strategy_regex
        }

    def parse(
        self,
        strategy: str,
        last_snapshot: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        regex_pattern: Optional[str] = None,
        css_selector: Optional[str] = None,
        use_browser: bool = False
    ) -> Dict[str, Any]:
        """
        Парсинг анонсов с использованием выбранной стратегии

        Args:
            strategy: Название стратегии ('any_change', 'element_change', 'any_keyword', 'all_keywords', 'regex')
            last_snapshot: Предыдущий снимок (hash или содержимое)
            keywords: Список ключевых слов (для стратегий any_keyword и all_keywords)
            regex_pattern: Регулярное выражение (для стратегии regex)
            css_selector: CSS селектор (для стратегии element_change)
            use_browser: Использовать браузерный парсер (Playwright) для динамических страниц

        Returns:
            {
                'changed': bool,  # Были ли изменения
                'new_snapshot': str,  # Новый снимок для сохранения
                'matched_content': str,  # Найденный контент (если есть)
                'message': str  # Сообщение о результате
            }
        """
        try:
            logger.info(f"🔍 AnnouncementParser: Начало парсинга")
            logger.info(f"   URL: {self.url}")
            logger.info(f"   Стратегия: {strategy}")
            logger.info(f"   Браузерный парсер: {'✅ ДА' if use_browser else '❌ НЕТ'}")

            # Проверка валидности стратегии
            if strategy not in self.strategies:
                logger.error(f"❌ Неизвестная стратегия: {strategy}")
                return {
                    'changed': False,
                    'new_snapshot': last_snapshot,
                    'matched_content': None,
                    'message': f"Неизвестная стратегия: {strategy}"
                }

            # Получаем HTML страницы (браузерный или обычный парсинг)
            if use_browser:
                logger.info(f"🌐 Используем браузерный парсер (Playwright)")
                html_content = self._fetch_with_browser()
                
                if not html_content:
                    logger.error(f"❌ Браузерный парсер не смог загрузить страницу")
                    return {
                        'changed': False,
                        'new_snapshot': last_snapshot,
                        'matched_content': None,
                        'message': "Не удалось загрузить страницу через браузер"
                    }
            else:
                logger.debug(f"📡 Загрузка HTML страницы через HTTP...")
                response = self.make_request(self.url, timeout=(10, 30))

                if not response:
                    logger.error(f"❌ Не удалось загрузить страницу")
                    return {
                        'changed': False,
                        'new_snapshot': last_snapshot,
                        'matched_content': None,
                        'message': "Не удалось загрузить страницу"
                    }

                response.raise_for_status()
                html_content = response.text
            
            logger.info(f"✅ HTML загружен ({len(html_content)} байт)")

            # Парсим HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # Выполняем выбранную стратегию
            strategy_func = self.strategies[strategy]
            result = strategy_func(
                soup=soup,
                html_content=html_content,
                last_snapshot=last_snapshot,
                keywords=keywords,
                regex_pattern=regex_pattern,
                css_selector=css_selector,
                use_browser=use_browser  # Передаем флаг браузерного парсинга
            )

            logger.info(f"✅ Парсинг завершен: {result['message']}")
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге анонсов: {e}", exc_info=True)
            return {
                'changed': False,
                'new_snapshot': last_snapshot,
                'matched_content': None,
                'message': f"Ошибка парсинга: {str(e)}"
            }

    def _strategy_any_change(
        self,
        soup: BeautifulSoup,
        html_content: str,
        last_snapshot: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Стратегия 1: Отслеживание любых изменений на странице
        Сравнивает hash всей страницы
        """
        logger.info(f"🔍 Стратегия: Отслеживание любых изменений")

        # Удаляем динамические элементы перед хэшированием
        # (даты, времена, токены сессий и т.д.)
        clean_html = self._clean_html(html_content)

        # Создаем hash страницы
        page_hash = hashlib.md5(clean_html.encode('utf-8')).hexdigest()
        logger.debug(f"   Новый hash: {page_hash}")

        # Если нет предыдущего снимка - это первая проверка
        if not last_snapshot:
            logger.info(f"   Первая проверка - сохраняем снимок")
            return {
                'changed': False,
                'new_snapshot': page_hash,
                'matched_content': None,
                'message': 'Первая проверка - снимок сохранен'
            }

        # Сравниваем с предыдущим снимком
        if page_hash != last_snapshot:
            logger.info(f"   ✅ Обнаружены изменения!")
            logger.debug(f"   Старый hash: {last_snapshot}")
            return {
                'changed': True,
                'new_snapshot': page_hash,
                'matched_content': f"Страница изменилась (hash: {page_hash[:8]}...)",
                'message': 'Обнаружены изменения на странице'
            }
        else:
            logger.info(f"   Изменений не обнаружено")
            return {
                'changed': False,
                'new_snapshot': page_hash,
                'matched_content': None,
                'message': 'Изменений не обнаружено'
            }

    def _strategy_element_change(
        self,
        soup: BeautifulSoup,
        html_content: str,
        last_snapshot: Optional[str] = None,
        css_selector: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Стратегия 2: Отслеживание изменений в конкретном элементе
        Сравнивает hash содержимого элемента по CSS селектору
        """
        logger.info(f"🎯 Стратегия: Отслеживание изменений в элементе")
        logger.info(f"   CSS селектор: {css_selector}")

        if not css_selector:
            return {
                'changed': False,
                'new_snapshot': last_snapshot,
                'matched_content': None,
                'message': 'CSS селектор не указан'
            }

        try:
            # Находим элемент
            elements = soup.select(css_selector)

            if not elements:
                logger.warning(f"   ⚠️ Элемент не найден: {css_selector}")
                return {
                    'changed': False,
                    'new_snapshot': last_snapshot,
                    'matched_content': None,
                    'message': f'Элемент не найден: {css_selector}'
                }

            # Берем первый найденный элемент
            element = elements[0]
            element_content = element.get_text(strip=True)
            logger.debug(f"   Найден элемент, контент: {element_content[:100]}...")

            # Создаем hash содержимого
            element_hash = hashlib.md5(element_content.encode('utf-8')).hexdigest()
            logger.debug(f"   Новый hash элемента: {element_hash}")

            # Если нет предыдущего снимка - это первая проверка
            if not last_snapshot:
                logger.info(f"   Первая проверка - сохраняем снимок")
                return {
                    'changed': False,
                    'new_snapshot': element_hash,
                    'matched_content': None,
                    'message': 'Первая проверка - снимок элемента сохранен'
                }

            # Сравниваем с предыдущим снимком
            if element_hash != last_snapshot:
                logger.info(f"   ✅ Обнаружены изменения в элементе!")
                logger.debug(f"   Старый hash: {last_snapshot}")
                return {
                    'changed': True,
                    'new_snapshot': element_hash,
                    'matched_content': element_content[:500],  # Первые 500 символов
                    'message': f'Элемент изменился: {css_selector}'
                }
            else:
                logger.info(f"   Изменений в элементе не обнаружено")
                return {
                    'changed': False,
                    'new_snapshot': element_hash,
                    'matched_content': None,
                    'message': 'Изменений в элементе не обнаружено'
                }

        except Exception as e:
            logger.error(f"   ❌ Ошибка при поиске элемента: {e}")
            return {
                'changed': False,
                'new_snapshot': last_snapshot,
                'matched_content': None,
                'message': f'Ошибка поиска элемента: {str(e)}'
            }

    def _strategy_any_keyword(
        self,
        soup: BeautifulSoup,
        html_content: str,
        keywords: Optional[List[str]] = None,
        use_browser: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Стратегия 3: Поиск любого из ключевых слов
        Возвращает True, если найдено хотя бы одно ключевое слово
        """
        logger.info(f"📝 Стратегия: Поиск любого ключевого слова")
        logger.info(f"   Ключевые слова: {keywords}")

        if not keywords:
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': 'Ключевые слова не указаны'
            }

        # Получаем текст всей страницы
        page_text = soup.get_text().lower()

        # Ищем совпадения
        matched_keywords = []
        for keyword in keywords:
            if keyword.lower() in page_text:
                matched_keywords.append(keyword)
                logger.debug(f"   ✅ Найдено: {keyword}")

        if matched_keywords:
            logger.info(f"   ✅ Найдено {len(matched_keywords)} ключевых слов")
            
            # Извлекаем ссылки на анонсы, содержащие ключевые слова
            announcement_links = self._extract_announcement_links(soup, keywords)
            
            result = {
                'changed': True,
                'new_snapshot': None,  # Для keyword стратегий снимок не нужен
                'matched_content': f"Найдены ключевые слова: {', '.join(matched_keywords)}",
                'message': f'Найдены ключевые слова: {", ".join(matched_keywords)}'
            }
            
            # Добавляем найденные ссылки, если они есть
            if announcement_links:
                result['announcement_links'] = announcement_links
                logger.info(f"   🔗 Найдено {len(announcement_links)} ссылок на анонсы")
            else:
                logger.warning(f"   ⚠️ Ключевые слова найдены, но ссылки на анонсы не извлечены")
                logger.warning(f"   💡 Возможно, страница использует динамический контент или нестандартную структуру")
                # Добавляем отладочную информацию
                total_links = len(soup.find_all('a', href=True))
                logger.warning(f"   📊 Всего ссылок на странице: {total_links}")
                logger.warning(f"   🌐 Браузерный парсинг: {'включен' if use_browser else 'ВЫКЛЮЧЕН'}")
                
                # Добавляем диагностическую информацию в результат
                result['debug_info'] = {
                    'total_links_on_page': total_links,
                    'browser_parsing_enabled': use_browser,
                    'page_size': len(html_content) if html_content else 0
                }
            
            return result
        else:
            logger.info(f"   Ключевые слова не найдены")
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': 'Ключевые слова не найдены'
            }

    def _strategy_all_keywords(
        self,
        soup: BeautifulSoup,
        html_content: str,
        keywords: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Стратегия 4: Все ключевые слова должны присутствовать
        Возвращает True только если найдены ВСЕ ключевые слова
        """
        logger.info(f"📚 Стратегия: Поиск всех ключевых слов")
        logger.info(f"   Ключевые слова: {keywords}")

        if not keywords:
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': 'Ключевые слова не указаны'
            }

        # Получаем текст всей страницы
        page_text = soup.get_text().lower()

        # Проверяем наличие всех ключевых слов
        matched_keywords = []
        missing_keywords = []

        for keyword in keywords:
            if keyword.lower() in page_text:
                matched_keywords.append(keyword)
                logger.debug(f"   ✅ Найдено: {keyword}")
            else:
                missing_keywords.append(keyword)
                logger.debug(f"   ❌ Не найдено: {keyword}")

        if len(matched_keywords) == len(keywords):
            logger.info(f"   ✅ Все ключевые слова найдены!")
            return {
                'changed': True,
                'new_snapshot': None,
                'matched_content': f"Все ключевые слова найдены: {', '.join(matched_keywords)}",
                'message': f'Все ключевые слова найдены: {", ".join(matched_keywords)}'
            }
        else:
            logger.info(f"   Найдено {len(matched_keywords)}/{len(keywords)} ключевых слов")
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': f'Не найдены: {", ".join(missing_keywords)}'
            }

    def _strategy_regex(
        self,
        soup: BeautifulSoup,
        html_content: str,
        regex_pattern: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Стратегия 5: Поиск по регулярному выражению
        Возвращает True, если найдено совпадение с regex
        """
        logger.info(f"⚡ Стратегия: Поиск по регулярному выражению")
        logger.info(f"   Regex: {regex_pattern}")

        if not regex_pattern:
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': 'Регулярное выражение не указано'
            }

        try:
            # Компилируем regex
            pattern = re.compile(regex_pattern, re.IGNORECASE)

            # Получаем текст страницы
            page_text = soup.get_text()

            # Ищем совпадения
            matches = pattern.findall(page_text)

            if matches:
                logger.info(f"   ✅ Найдено {len(matches)} совпадений")
                # Берем первые 5 совпадений
                sample_matches = matches[:5]
                return {
                    'changed': True,
                    'new_snapshot': None,
                    'matched_content': f"Найдено {len(matches)} совпадений: {', '.join(sample_matches)}",
                    'message': f'Найдено {len(matches)} совпадений с regex'
                }
            else:
                logger.info(f"   Совпадений не найдено")
                return {
                    'changed': False,
                    'new_snapshot': None,
                    'matched_content': None,
                    'message': 'Совпадений с regex не найдено'
                }

        except re.error as e:
            logger.error(f"   ❌ Ошибка в регулярном выражении: {e}")
            return {
                'changed': False,
                'new_snapshot': None,
                'matched_content': None,
                'message': f'Ошибка в regex: {str(e)}'
            }

    def _fetch_with_browser(self) -> Optional[str]:
        """
        Загружает страницу через Playwright (браузерный парсинг) для динамического контента
        С автоматическим fallback: сначала БЕЗ прокси (быстрее), потом с прокси
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        
        logger.info("🚀 Запуск Playwright для браузерного парсинга...")
        
        # Получаем прокси и User-Agent
        proxy, user_agent = self.rotation_manager.get_optimal_combination(self._extract_exchange_from_url(self.url))
        
        # Попытка 1: БЕЗ ПРОКСИ (обычно быстрее и надежнее для MEXC)
        logger.info("🔧 Попытка 1: Загрузка БЕЗ ПРОКСИ (быстрее)")
        result = self._try_load_with_playwright(None, user_agent)
        if result:
            return result
        
        # Попытка 2: С прокси (если без прокси не получилось)
        if proxy:
            logger.warning("⚠️ Не удалось загрузить без прокси, пробуем С ПРОКСИ...")
            logger.info(f"🔧 Попытка 2: Загрузка С ПРОКСИ {proxy.address}")
            result = self._try_load_with_playwright(proxy, user_agent)
            if result:
                return result
        
        logger.error("❌ Не удалось загрузить страницу ни без прокси, ни с прокси")
        return None
    
    def _try_load_with_playwright(self, proxy, user_agent) -> Optional[str]:
        """
        Попытка загрузки страницы через Playwright с заданными настройками
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
            
            with sync_playwright() as p:
                # Настройки браузера
                browser_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',  # Для стабильности
                ]
                
                launch_options = {
                    'headless': True,
                    'args': browser_args
                }
                
                # Добавляем прокси только если указан
                if proxy:
                    launch_options['proxy'] = {
                        'server': f"{proxy.protocol}://{proxy.address}"
                    }
                
                browser = p.chromium.launch(**launch_options)
                
                # Настройки контекста
                context_options = {
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'en-US',
                    'ignore_https_errors': True,  # Игнорируем SSL ошибки
                }
                
                if user_agent:
                    context_options['user_agent'] = user_agent.user_agent_string
                
                context = browser.new_context(**context_options)
                page = context.new_page()
                
                # Применяем stealth (опционально)
                try:
                    from playwright_stealth import Stealth
                    stealth_obj = Stealth()
                    stealth_obj.apply_stealth_sync(page)
                except:
                    pass  # Игнорируем ошибки stealth
                
                logger.info(f"🌐 Загрузка страницы: {self.url}")
                
                # Переходим на страницу - используем networkidle для MEXC (ждет когда сеть успокоится)
                # Таймаут 60 секунд - достаточно для большинства случаев
                try:
                    page.goto(self.url, wait_until='networkidle', timeout=60000)
                    logger.info("✅ Страница полностью загружена (networkidle)")
                except PlaywrightTimeout:
                    logger.info("⏱️ Networkidle таймаут, но контент уже загружен")
                    # Даже если таймаут, контент уже загрузился
                
                # Минимальное ожидание для рендеринга React
                page.wait_for_timeout(2000)
                
                # Скроллим для триггера lazy loading
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                except:
                    pass
                
                # Получаем HTML
                html_content = page.content()
                
                # Проверяем, что получили реальный контент (не пустую страницу)
                if len(html_content) < 1000:
                    logger.warning(f"⚠️ Подозрительно маленький размер страницы: {len(html_content)} байт")
                    context.close()
                    browser.close()
                    return None
                
                logger.info(f"✅ Страница загружена ({len(html_content)} байт)")
                
                # Закрываем браузер
                context.close()
                browser.close()
                
                return html_content
                
        except PlaywrightTimeout:
            logger.warning("⏰ Таймаут при загрузке страницы")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при загрузке: {e}")
            return None

    def _extract_announcement_links(self, soup: BeautifulSoup, keywords: List[str]) -> List[Dict[str, str]]:
        """
        Извлекает ссылки на анонсы, которые содержат указанные ключевые слова
        
        Args:
            soup: Объект BeautifulSoup для парсинга
            keywords: Список ключевых слов для поиска
            
        Returns:
            Список словарей с информацией о найденных анонсах:
            [{'title': 'Заголовок', 'url': 'https://...', 'matched_keywords': ['keyword1'], 'description': '...'}]
        """
        announcement_links = []
        
        # Паттерны для различных бирж
        link_patterns = {
            'mexc.co': {
                # MEXC использует React и динамическую загрузку
                # Ищем все ссылки на /announcements/article/
                'selectors': [
                    'a[href*="/announcements/article/"]',
                    'a[href*="/support/articles/"]',
                ],
                'container_selectors': ['article', 'div[class*="article"]', 'div[class*="announcement"]', 'div[class*="news"]'],
                'url_prefix': 'https://www.mexc.co'
            },
            'binance.com': {
                'selectors': ['a[href*="/support/announcement/"]', '.css-article a'],
                'container_selectors': ['article', '.article-item'],
                'url_prefix': 'https://www.binance.com'
            },
            'bybit.com': {
                'selectors': ['a[href*="/announcements/"]', '.announcement-list a'],
                'container_selectors': ['.announcement-item'],
                'url_prefix': 'https://www.bybit.com'
            },
            'okx.com': {
                'selectors': ['a[href*="/support/hc/"]', '.article-item a'],
                'container_selectors': ['.article-card'],
                'url_prefix': 'https://www.okx.com'
            },
            'gate.io': {
                'selectors': ['a[href*="/article/"]', '.article-link'],
                'container_selectors': ['.article-wrapper'],
                'url_prefix': 'https://www.gate.io'
            },
            'kucoin.com': {
                'selectors': ['a[href*="/news/"]', '.news-list a'],
                'container_selectors': ['.news-card'],
                'url_prefix': 'https://www.kucoin.com'
            }
        }
        
        # Определяем биржу из URL
        exchange = None
        for exch in link_patterns.keys():
            if exch in self.url:
                exchange = exch
                break
        
        if not exchange:
            logger.debug("   ⚠️ Неизвестная биржа, используем общий паттерн")
            # Общий паттерн для любых ссылок
            all_links = soup.find_all('a', href=True)
            logger.info(f"   📊 Найдено {len(all_links)} ссылок на странице")
        else:
            # Ищем ссылки по специфичным селекторам
            config = link_patterns[exchange]
            all_links = []
            for selector in config['selectors']:
                found = soup.select(selector)
                all_links.extend(found)
                logger.debug(f"   🔍 Селектор '{selector}': найдено {len(found)} ссылок")
            
            logger.info(f"   📊 Найдено {len(all_links)} ссылок анонсов для {exchange}")
        
        # Обрабатываем найденные ссылки
        seen_urls = set()  # Избегаем дубликатов
        
        for link in all_links:
            try:
                href = link.get('href', '')
                if not href:
                    continue
                
                # Формируем полный URL
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    # Относительная ссылка
                    if exchange and exchange in link_patterns:
                        full_url = link_patterns[exchange]['url_prefix'] + href
                    else:
                        # Извлекаем базовый URL из self.url
                        from urllib.parse import urlparse
                        parsed = urlparse(self.url)
                        full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                else:
                    continue
                
                # Избегаем дубликатов
                if full_url in seen_urls:
                    continue
                
                # Получаем текст ссылки
                link_text = link.get_text(strip=True)
                
                # Ищем родительский контейнер для более полного контекста
                parent_text = ""
                description = ""
                
                if exchange and exchange in link_patterns:
                    # Ищем родительский контейнер анонса
                    parent = None
                    for container_sel in link_patterns[exchange].get('container_selectors', []):
                        parent = link.find_parent(container_sel) if not container_sel.startswith('.') else link.find_parent(class_=container_sel.replace('.', ''))
                        if parent:
                            break
                    
                    if not parent:
                        # Просто берем ближайшего родителя (div, article, li)
                        parent = link.find_parent(['div', 'article', 'li', 'section'])
                    
                    if parent:
                        parent_text = parent.get_text(separator=' ', strip=True)
                        # Ищем описание (обычно в <p>, <span>, или <div> внутри контейнера)
                        desc_elem = parent.find(['p', 'span', 'div'], recursive=True)
                        if desc_elem and desc_elem != link:
                            description = desc_elem.get_text(strip=True)[:300]  # Первые 300 символов
                else:
                    # Для неизвестных бирж берем ближайшего родителя
                    parent = link.find_parent(['div', 'article', 'li'])
                    if parent:
                        parent_text = parent.get_text(separator=' ', strip=True)
                
                # Проверяем ключевые слова в тексте ссылки и родительском контейнере
                search_text = (link_text + ' ' + parent_text).lower()
                matched = []
                for keyword in keywords:
                    if keyword.lower() in search_text:
                        matched.append(keyword)
                
                # Если нашли совпадения, добавляем ссылку
                if matched:
                    announcement_data = {
                        'title': link_text[:200] if link_text else 'Без названия',  # Увеличили лимит
                        'url': full_url,
                        'matched_keywords': matched
                    }
                    
                    # Добавляем описание, если оно есть
                    if description and description != link_text:
                        announcement_data['description'] = description
                    
                    announcement_links.append(announcement_data)
                    seen_urls.add(full_url)
                    
                    logger.info(f"   ✅ Найден анонс: {link_text[:80]}...")
                    logger.debug(f"      URL: {full_url}")
                    logger.debug(f"      Ключевые слова: {', '.join(matched)}")
                    if description:
                        logger.debug(f"      Описание: {description[:100]}...")
            
            except Exception as e:
                logger.debug(f"   ⚠️ Ошибка при обработке ссылки: {e}")
                continue
        
        # FALLBACK: Если не нашли ни одной ссылки через селекторы,
        # попробуем найти ВСЕ ссылки на странице и проверить их контекст
        if len(announcement_links) == 0:
            logger.warning(f"   ⚠️ Не найдено ссылок через селекторы, пробуем fallback...")
            fallback_links = self._extract_links_fallback(soup, keywords, link_patterns.get(exchange, {}))
            announcement_links.extend(fallback_links)
        
        # SUPER FALLBACK: Если и fallback не помог, пробуем последний способ
        if len(announcement_links) == 0:
            logger.warning(f"   ⚠️ Fallback не помог, пробуем SUPER FALLBACK (поиск по всем ссылкам)...")
            super_fallback_links = self._extract_links_super_fallback(soup, keywords, link_patterns.get(exchange, {}))
            announcement_links.extend(super_fallback_links)
        
        # Ограничиваем количество ссылок (топ-10)
        return announcement_links[:10]
    
    def _extract_links_fallback(self, soup: BeautifulSoup, keywords: List[str], exchange_config: dict) -> List[Dict[str, str]]:
        """
        Fallback метод для поиска ссылок, когда основные селекторы не дают результата.
        Ищет ВСЕ текстовые блоки с ключевыми словами и пытается найти рядом ссылки.
        """
        logger.info("   🔄 FALLBACK: Поиск ссылок по всей странице...")
        announcement_links = []
        seen_urls = set()
        
        # Ищем все элементы, содержащие ключевые слова
        for keyword in keywords:
            # Ищем все элементы с текстом, содержащим ключевое слово
            elements = soup.find_all(string=lambda text: text and keyword.lower() in text.lower())
            
            logger.debug(f"   🔍 Найдено {len(elements)} элементов с ключевым словом '{keyword}'")
            
            for element in elements:
                try:
                    # Ищем ближайшую ссылку (в родителях, соседях или детях)
                    parent = element.parent
                    link = None
                    container = None
                    
                    # Стратегия 1: Проверяем, является ли сам элемент или его родитель ссылкой
                    current = parent
                    for _ in range(5):  # Проверяем до 5 уровней вверх
                        if current and current.name == 'a' and current.get('href'):
                            link = current
                            container = current.find_parent(['div', 'article', 'section', 'li'])
                            break
                        # Ищем ссылку внутри текущего уровня
                        if current:
                            link = current.find('a', href=True)
                            if link:
                                container = current
                                break
                            current = current.parent
                        else:
                            break
                    
                    # Стратегия 2: Если не нашли в родителях, ищем в соседних элементах
                    if not link and parent:
                        # Ищем ближайший родительский контейнер
                        container = parent.find_parent(['div', 'article', 'section', 'li', 'tr'])
                        if container:
                            # Ищем ВСЕ ссылки внутри контейнера
                            links_in_container = container.find_all('a', href=True)
                            if links_in_container:
                                # Берем первую подходящую ссылку
                                link = links_in_container[0]
                                logger.debug(f"   📍 Найдена ссылка в соседнем элементе контейнера")
                    
                    # Стратегия 3: Если все еще не нашли, ищем следующий/предыдущий элемент с ссылкой
                    if not link and parent:
                        # Ищем следующий элемент
                        next_sibling = parent.find_next_sibling()
                        if next_sibling:
                            link = next_sibling.find('a', href=True) if next_sibling.name != 'a' else next_sibling
                        
                        # Если не нашли, ищем предыдущий элемент
                        if not link:
                            prev_sibling = parent.find_previous_sibling()
                            if prev_sibling:
                                link = prev_sibling.find('a', href=True) if prev_sibling.name != 'a' else prev_sibling
                    
                    if link:
                        href = link.get('href', '')
                        if not href:
                            continue
                        
                        # Формируем полный URL
                        if href.startswith('http'):
                            full_url = href
                        elif href.startswith('/'):
                            url_prefix = exchange_config.get('url_prefix', '')
                            if url_prefix:
                                full_url = url_prefix + href
                            else:
                                from urllib.parse import urlparse
                                parsed = urlparse(self.url)
                                full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                        else:
                            continue
                        
                        # Избегаем дубликатов
                        if full_url in seen_urls:
                            continue
                        
                        # Получаем текст и описание
                        link_text = link.get_text(strip=True)
                        
                        # Если текст ссылки пустой или слишком короткий, берем текст из контейнера
                        if not link_text or len(link_text) < 10:
                            if container:
                                # Пытаемся найти заголовок
                                title_elem = container.find(['h1', 'h2', 'h3', 'h4', 'strong', 'b'])
                                if title_elem:
                                    link_text = title_elem.get_text(strip=True)
                                else:
                                    # Берем первые 100 символов из контейнера
                                    container_text = container.get_text(strip=True)
                                    link_text = container_text[:100] if container_text else "Без названия"
                        
                        description = ""
                        if container:
                            # Пытаемся найти описание
                            desc_elem = container.find(['p', 'span', 'div'], recursive=True)
                            if desc_elem and desc_elem != link:
                                desc_text = desc_elem.get_text(strip=True)
                                # Берем текст, который содержит ключевое слово или находится рядом
                                if keyword.lower() in desc_text.lower():
                                    description = desc_text[:300]
                                elif len(desc_text) > 20:
                                    description = desc_text[:300]
                        
                        announcement_data = {
                            'title': link_text[:200] if link_text else 'Без названия',
                            'url': full_url,
                            'matched_keywords': [keyword]
                        }
                        
                        if description and description != link_text:
                            announcement_data['description'] = description
                        
                        announcement_links.append(announcement_data)
                        seen_urls.add(full_url)
                        
                        logger.info(f"   ✅ FALLBACK нашел: {link_text[:80]}...")
                        logger.debug(f"      URL: {full_url}")
                        if description:
                            logger.debug(f"      Описание: {description[:100]}...")
                
                except Exception as e:
                    logger.debug(f"   ⚠️ Ошибка в fallback для '{keyword}': {e}")
                    continue
        
        logger.info(f"   📊 FALLBACK результат: найдено {len(announcement_links)} ссылок")
        return announcement_links[:10]
    
    def _extract_links_super_fallback(self, soup: BeautifulSoup, keywords: List[str], exchange_config: dict) -> List[Dict[str, str]]:
        """
        SUPER FALLBACK: Последний шанс найти ссылки.
        Берет ВСЕ ссылки на странице и проверяет, есть ли рядом ключевые слова.
        """
        logger.info("   🚀 SUPER FALLBACK: Проверяем все ссылки на странице...")
        announcement_links = []
        seen_urls = set()
        
        # Находим ВСЕ ссылки на странице
        all_links = soup.find_all('a', href=True)
        logger.info(f"   📊 Найдено {len(all_links)} ссылок на странице")
        
        # Объединяем ключевые слова в одну строку для поиска
        keywords_lower = [kw.lower() for kw in keywords]
        
        for link in all_links:
            try:
                href = link.get('href', '')
                if not href or href.startswith('#') or href == '/':
                    continue
                
                # Формируем полный URL
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    url_prefix = exchange_config.get('url_prefix', '')
                    if url_prefix:
                        full_url = url_prefix + href
                    else:
                        from urllib.parse import urlparse
                        parsed = urlparse(self.url)
                        full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                else:
                    continue
                
                # Пропускаем уже найденные URL
                if full_url in seen_urls:
                    continue
                
                # Получаем текст ссылки
                link_text = link.get_text(strip=True)
                
                # Ищем самый большой родительский контейнер (до 10 уровней)
                container = link
                for _ in range(10):
                    parent = container.find_parent(['div', 'article', 'section', 'li', 'tr', 'td'])
                    if parent:
                        container = parent
                    else:
                        break
                
                # Получаем весь текст из контейнера
                container_text = container.get_text(separator=' ', strip=True).lower()
                
                # Проверяем, содержит ли контейнер хотя бы одно ключевое слово
                matched_keywords = []
                for keyword in keywords:
                    if keyword.lower() in container_text:
                        matched_keywords.append(keyword)
                
                if matched_keywords:
                    # Нашли совпадение! Извлекаем информацию
                    
                    # Пытаемся найти лучший заголовок
                    title = link_text
                    if not title or len(title) < 10:
                        # Ищем заголовок в родителях
                        header = container.find(['h1', 'h2', 'h3', 'h4', 'h5'])
                        if header:
                            title = header.get_text(strip=True)
                        else:
                            # Берем текст из контейнера (первые 100 символов)
                            title = container_text[:100]
                    
                    # Извлекаем описание
                    description = ""
                    desc_elem = container.find(['p', 'div', 'span'])
                    if desc_elem:
                        desc_text = desc_elem.get_text(strip=True)
                        if len(desc_text) > 20:
                            description = desc_text[:300]
                    
                    announcement_data = {
                        'title': title[:200] if title else 'Без названия',
                        'url': full_url,
                        'matched_keywords': matched_keywords
                    }
                    
                    if description and description != title:
                        announcement_data['description'] = description
                    
                    announcement_links.append(announcement_data)
                    seen_urls.add(full_url)
                    
                    logger.info(f"   ✅ SUPER FALLBACK нашел: {title[:80]}...")
                    logger.debug(f"      URL: {full_url}")
                    logger.debug(f"      Ключевые слова: {', '.join(matched_keywords)}")
            
            except Exception as e:
                logger.debug(f"   ⚠️ Ошибка в super fallback: {e}")
                continue
        
        logger.info(f"   📊 SUPER FALLBACK результат: найдено {len(announcement_links)} ссылок")
        return announcement_links[:10]

    def _clean_html(self, html: str) -> str:
        """
        Очистка HTML от динамических элементов перед хэшированием
        """
        # Удаляем скрипты и стили
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(['script', 'style']):
            script.decompose()

        # Удаляем комментарии
        for comment in soup.findAll(text=lambda text: isinstance(text, str) and text.startswith('<!--')):
            comment.extract()

        # Получаем очищенный текст
        clean_text = soup.get_text()

        # Удаляем лишние пробелы
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        return clean_text
