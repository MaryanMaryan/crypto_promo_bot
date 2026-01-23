# bot/parser_service.py
import logging
import time
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from data.database import get_db, get_db_session, PromoHistory, ApiLink
from parsers.universal_fallback_parser import UniversalFallbackParser
from parsers.staking_parser import StakingParser
from parsers.announcement_parser import AnnouncementParser
from parsers.weex_parser import WeexParser
from parsers.bybit_launchpool_parser import BybitLaunchpoolParser
from parsers.mexc_launchpool_parser import MexcLaunchpoolParser
from parsers.gate_launchpool_parser import GateLaunchpoolParser
from parsers.gate_launchpad_parser import GateLaunchpadParser
from parsers.bingx_launchpool_parser import BingxLaunchpoolParser
from parsers.bitget_launchpool_parser import BitgetLaunchpoolParser
from parsers.bitget_poolx_parser import BitgetPoolxParser
from parsers.bitget_candybomb_parser import BitgetCandybombParser
from services.stability_tracker_service import StabilityTrackerService
from utils.price_fetcher import get_price_fetcher

logger = logging.getLogger(__name__)

class ParserService:
    """Сервис для управления парсерами с улучшенной обработкой ошибок"""

    # Биржи, требующие специальных парсеров
    SPECIAL_PARSERS = {
        'weex': WeexParser,
        'bybit_launchpool': BybitLaunchpoolParser,
        'mexc_launchpool': MexcLaunchpoolParser,
        'gate_launchpool': GateLaunchpoolParser,
        'gate_launchpad': GateLaunchpadParser,
        'bingx_launchpool': BingxLaunchpoolParser,
        'bitget_launchpool': BitgetLaunchpoolParser,
        'bitget_poolx': BitgetPoolxParser,
        'bitget_candybomb': BitgetCandybombParser,
    }
    
    # Стейблкоины для которых цена = 1 USD
    STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'USD1', 'USDE'}

    def __init__(self):
        self.parsers = {}
        self.stats = {
            'total_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'new_promos_found': 0,
            'fallback_rejected': 0,
            'fallback_accepted': 0,
            'last_check_time': None
        }
        # Инициализируем price_fetcher для обогащения данных USD-эквивалентами
        try:
            self.price_fetcher = get_price_fetcher()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось инициализировать price_fetcher: {e}")
            self.price_fetcher = None

    def _extract_exchange_from_url(self, url: str) -> str:
        """Извлекает название биржи из URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Убираем www. и поддомены
            parts = domain.split('.')
            if len(parts) >= 2:
                # Берём основную часть домена
                main_domain = parts[-2] if parts[-1] in ['com', 'io', 'org', 'net', 'ru'] else parts[-1]
                return main_domain
            return domain
        except:
            return ''

    def _select_parser(self, url: str, api_url: Optional[str], html_url: Optional[str], parsing_type: str, special_parser: Optional[str] = None, category: str = None):
        """
        Выбирает подходящий парсер на основе:
        1. Явного указания special_parser (выбор пользователя)
        2. Категории ссылки
        3. Автоопределения по URL
        """
        
        # Если явно указан парсер пользователем - используем его
        if special_parser:
            logger.info(f"🔧 Выбран парсер пользователем: {special_parser}")
            
            # Специальные парсеры (weex, okx_boost)
            if special_parser in self.SPECIAL_PARSERS:
                parser_class = self.SPECIAL_PARSERS[special_parser]
                target_url = html_url or url
                logger.info(f"🔧 Используется специальный парсер: {parser_class.__name__} для {target_url}")
                return parser_class(target_url)
            
            # Стейкинг парсер
            elif special_parser == 'staking':
                target_url = api_url or url
                logger.info(f"📊 Используется StakingParser для {target_url}")
                return StakingParser(api_url=target_url)
            
            # Анонс парсер - возвращаем None, обработка будет в check_announcements
            elif special_parser == 'announcement':
                logger.info(f"📢 Выбран AnnouncementParser - будет использован в check_announcements")
                # Возвращаем UniversalFallbackParser как fallback, но announcement будет обработан отдельно
                return UniversalFallbackParser(url, api_url=api_url, html_url=html_url, parsing_type=parsing_type)
            
            else:
                logger.warning(f"⚠️ Неизвестный парсер '{special_parser}', используем автоопределение")
        
        # АВТООПРЕДЕЛЕНИЕ: если парсер не указан явно
        
        # Определяем биржу из всех доступных URL
        exchange = self._extract_exchange_from_url(url)
        
        # Также проверяем html_url (для типа "Только Browser")
        if not exchange or exchange not in self.SPECIAL_PARSERS:
            if html_url:
                exchange = self._extract_exchange_from_url(html_url)
        
        # Также проверяем api_url
        if not exchange or exchange not in self.SPECIAL_PARSERS:
            if api_url:
                exchange = self._extract_exchange_from_url(api_url)
        
        logger.info(f"🔍 Автоопределение биржи: {exchange or 'unknown'}")
        
        # Учитываем категорию при автовыборе
        if category == 'staking' and api_url:
            # Для категории staking автоматически используем StakingParser
            logger.info(f"📊 Автовыбор: StakingParser для категории staking")
            return StakingParser(api_url=api_url)
        
        # Проверяем, есть ли специальный парсер для этой биржи
        if exchange in self.SPECIAL_PARSERS:
            parser_class = self.SPECIAL_PARSERS[exchange]
            target_url = html_url or url
            logger.info(f"🔧 Автовыбор: специальный парсер {parser_class.__name__} для биржи {exchange}")
            return parser_class(target_url)
        
        # Пробуем с суффиксом на основе URL
        # Для launchpool/launchpad пробуем exchange_launchpool/exchange_launchpad
        if exchange:
            check_url = url or api_url or html_url or ''
            url_lower = check_url.lower()
            
            # Проверяем по категории
            if category in ['launchpool', 'launchpad']:
                parser_key = f"{exchange}_{category}"
                if parser_key in self.SPECIAL_PARSERS:
                    parser_class = self.SPECIAL_PARSERS[parser_key]
                    target_url = html_url or url
                    logger.info(f"🔧 Автовыбор: специальный парсер {parser_class.__name__} для {parser_key}")
                    return parser_class(target_url)
            
            # Проверяем по содержимому URL
            if 'launchpool' in url_lower:
                parser_key = f"{exchange}_launchpool"
                if parser_key in self.SPECIAL_PARSERS:
                    parser_class = self.SPECIAL_PARSERS[parser_key]
                    target_url = html_url or url
                    logger.info(f"🔧 Автовыбор: парсер {parser_class.__name__} по URL (launchpool)")
                    return parser_class(target_url)
            
            elif 'launchpad' in url_lower:
                parser_key = f"{exchange}_launchpad"
                if parser_key in self.SPECIAL_PARSERS:
                    parser_class = self.SPECIAL_PARSERS[parser_key]
                    target_url = html_url or url
                    logger.info(f"🔧 Автовыбор: парсер {parser_class.__name__} по URL (launchpad)")
                    return parser_class(target_url)
            
            elif 'candy-bomb' in url_lower or 'candybomb' in url_lower:
                parser_key = f"{exchange}_candybomb"
                if parser_key in self.SPECIAL_PARSERS:
                    parser_class = self.SPECIAL_PARSERS[parser_key]
                    target_url = html_url or url
                    logger.info(f"🔧 Автовыбор: парсер {parser_class.__name__} по URL (candybomb)")
                    return parser_class(target_url)
        
        # По умолчанию используем UniversalFallbackParser
        logger.info(f"🌐 Автовыбор: UniversalFallbackParser")
        return UniversalFallbackParser(url, api_url=api_url, html_url=html_url, parsing_type=parsing_type)

    def _convert_to_datetime(self, time_value: Any) -> Optional[datetime]:
        """Конвертирует различные форматы времени в datetime объект"""
        if not time_value:
            return None

        # Если уже datetime объект
        if isinstance(time_value, datetime):
            return time_value

        # Если timestamp (миллисекунды)
        if isinstance(time_value, (int, float)):
            try:
                # Если timestamp в миллисекундах (больше чем 10^10)
                if time_value > 10**10:
                    return datetime.fromtimestamp(time_value / 1000)
                else:
                    return datetime.fromtimestamp(time_value)
            except (ValueError, OSError) as e:
                logger.warning(f"⚠️ Не удалось конвертировать timestamp {time_value}: {e}")
                return None

        # Если строка
        if isinstance(time_value, str):
            # Пробуем различные форматы даты
            date_formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%d',
                '%d.%m.%Y %H:%M',
                '%d.%m.%Y',
                '%d/%m/%Y %H:%M',
                '%d/%m/%Y',
            ]

            for fmt in date_formats:
                try:
                    return datetime.strptime(time_value, fmt)
                except ValueError:
                    continue

            # Если не удалось распарсить как дату, возвращаем None
            logger.debug(f"⚠️ Не удалось конвертировать строку времени: {time_value}")
            return None

        logger.warning(f"⚠️ Неизвестный формат времени: {type(time_value)} - {time_value}")
        return None

    def _safe_int(self, value: Any) -> Optional[int]:
        """Безопасное преобразование в int"""
        if value is None:
            return None
        try:
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                # Убираем пробелы и запятые
                clean_value = value.replace(',', '').replace(' ', '').strip()
                if clean_value:
                    return int(float(clean_value))
            return None
        except (ValueError, TypeError):
            return None

    def _safe_float(self, value: Any) -> Optional[float]:
        """Безопасное преобразование в float"""
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                # Убираем пробелы и запятые
                clean_value = value.replace(',', '').replace(' ', '').strip()
                if clean_value:
                    return float(clean_value)
            return None
        except (ValueError, TypeError):
            return None
    
    def _serialize_raw_data(self, raw_data: Any) -> Optional[str]:
        """Сериализует raw_data в JSON строку для хранения в БД"""
        if raw_data is None:
            return None
        try:
            import json
            if isinstance(raw_data, str):
                # Уже строка - проверим что это валидный JSON
                json.loads(raw_data)
                return raw_data
            return json.dumps(raw_data, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка сериализации raw_data: {e}")
            return None
    
    def _check_with_special_parser(self, link_id: int, url: str, special_parser: str, link) -> Optional[Dict]:
        """
        Проверяет ссылку с использованием специального парсера (для announcement с special_parser).
        Возвращает результат в формате, совместимом с check_announcements.
        """
        try:
            logger.info(f"🔧 Использование специального парсера '{special_parser}' для announcement ссылки {link_id}")
            
            # Получаем парсер
            html_url = link.get_primary_html_url()
            api_url = link.get_primary_api_url()
            target_url = html_url or api_url or url
            
            parser = self._select_parser(url, api_url, html_url, link.parsing_type or 'combined', special_parser)
            
            # Получаем промоакции
            promotions = parser.get_promotions()
            
            if not promotions:
                logger.info(f"ℹ️ Специальный парсер не вернул промоакций")
                return None
            
            logger.info(f"📦 Специальный парсер вернул {len(promotions)} промоакций")
            
            # Фильтруем новые промоакции
            new_promos = self._filter_new_promotions(link_id, promotions)
            
            if new_promos:
                logger.info(f"🎉 Найдено {len(new_promos)} НОВЫХ промоакций!")
                
                # Обогащаем промоакции USD-эквивалентами
                exchange = self._extract_exchange_from_url(api_url or url)
                new_promos = self._enrich_promos_with_prices(new_promos, exchange)
                
                # Сохраняем в историю
                saved_count = self._save_to_history(link_id, new_promos)
                
                # Формируем сообщение для уведомления
                promo_titles = [p.get('title', 'Без названия') for p in new_promos[:3]]
                message = f"Найдено {len(new_promos)} новых промоакций:\n" + "\n".join(f"• {t}" for t in promo_titles)
                if len(new_promos) > 3:
                    message += f"\n...и ещё {len(new_promos) - 3}"
                
                return {
                    'changed': True,
                    'message': message,
                    'matched_content': str(new_promos),
                    'strategy': f'special_parser:{special_parser}',
                    'url': url,
                    'new_promos': new_promos  # Добавляем сами промоакции для форматирования
                }
            else:
                logger.info(f"ℹ️ Все промоакции уже известны")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка в _check_with_special_parser: {e}", exc_info=True)
            return None

    def check_for_new_promos(self, link_id: int, url: str) -> List[Dict[str, Any]]:
        """Проверяет новые промоакции для указанной ссылки"""
        self.stats['total_checks'] += 1
        self.stats['last_check_time'] = time.time()

        try:
            logger.info(f"🔍 ParserService: Начало проверки ссылки {link_id}")
            logger.info(f"   Основной URL: {url}")

            # Получаем URL из базы данных (новая система)
            api_url = None
            html_url = None
            parsing_type = 'combined'  # По умолчанию
            special_parser = None  # Специальный парсер
            category = 'launches'  # Категория для автовыбора парсера

            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                if link:
                    api_url = link.get_primary_api_url()
                    html_url = link.get_primary_html_url()
                    parsing_type = link.parsing_type or 'combined'
                    special_parser = link.special_parser  # Получаем выбранный парсер
                    category = link.category or 'launches'

            logger.info(f"📡 API URL: {api_url or 'Не указан'}")
            logger.info(f"🌐 HTML URL (fallback): {html_url or 'Не указан'}")
            logger.info(f"🎯 Тип парсинга: {parsing_type}")
            logger.info(f"🗂️ Категория: {category}")
            if special_parser:
                logger.info(f"🔧 Выбранный парсер: {special_parser}")

            # Выбираем парсер в зависимости от настроек и категории
            parser = self._select_parser(url, api_url, html_url, parsing_type, special_parser, category)

            logger.info(f"📡 Запуск парсинга...")
            promotions = parser.get_promotions()

            if not promotions:
                logger.info(f"ℹ️ ParserService: Парсер не вернул промоакций для ссылки {link_id}")
                self.stats['successful_checks'] += 1
                return []

            logger.info(f"📦 ParserService: Парсер вернул {len(promotions)} промоакций")

            # Получаем детальную информацию о парсинге
            strategy_info = parser.get_strategy_info()
            logger.info(f"📊 Стратегия парсинга: {strategy_info['strategy_used']}")
            logger.debug(f"   Детали стратегии: {strategy_info}")

            # Логируем ошибки если есть
            error_stats = parser.get_error_stats()
            if error_stats and error_stats.get('total_errors', 0) > 0:
                logger.warning(f"⚠️ Ошибки парсинга: {error_stats}")

            # Логируем найденные промоакции
            logger.info(f"📋 Список найденных промоакций:")
            for i, promo in enumerate(promotions, 1):
                logger.info(f"   {i}. {promo.get('title', 'Без названия')} (promo_id: {promo.get('promo_id', 'N/A')})")

            # Фильтруем только новые промоакции
            logger.info(f"🔍 Фильтрация новых промоакций...")
            new_promos = self._filter_new_promotions(link_id, promotions)

            if new_promos:
                logger.info(f"🎉 ParserService: Найдено {len(new_promos)} НОВЫХ промоакций для ссылки {link_id}")
                logger.info(f"📋 Список НОВЫХ промоакций:")
                for i, promo in enumerate(new_promos, 1):
                    logger.info(f"   {i}. {promo.get('title', 'Без названия')} (promo_id: {promo.get('promo_id', 'N/A')})")

                # Обогащаем промоакции USD-эквивалентами
                exchange = self._extract_exchange_from_url(api_url or url)
                new_promos = self._enrich_promos_with_prices(new_promos, exchange)

                # Сохраняем новые промоакции
                logger.info(f"💾 Сохранение {len(new_promos)} новых промоакций в базу данных...")
                saved_count = self._save_to_history(link_id, new_promos)
                self.stats['new_promos_found'] += saved_count
                self.stats['successful_checks'] += 1

                if saved_count < len(new_promos):
                    logger.warning(f"⚠️ Сохранено только {saved_count} из {len(new_promos)} новых промоакций")
                else:
                    logger.info(f"✅ Все {saved_count} промоакций успешно сохранены")

                return new_promos[:saved_count]
            else:
                logger.info(f"ℹ️ ParserService: Все промоакции уже были в базе данных (нет новых)")
                self.stats['successful_checks'] += 1
                return []

        except Exception as e:
            self.stats['failed_checks'] += 1
            logger.error(f"❌ ParserService: Критическая ошибка при проверке ссылки {link_id}: {e}", exc_info=True)
            return []
    
    def _filter_new_promotions(self, link_id: int, promotions: List[Dict]) -> List[Dict]:
        """Фильтрует только новые промоакции и удаляет устаревшие"""
        try:
            logger.debug(f"🔍 Начало фильтрации промоакций для ссылки {link_id}")

            # Статистика фильтрации
            stats = {
                'total': len(promotions),
                'existing': 0,
                'new': 0,
                'invalid': 0,
                'fallback_rejected': 0,
                'outdated_removed': 0
            }

            with get_db_session() as db:
                # Получаем ID существующих промоакций для этой ссылки
                existing_promo_ids = {
                    promo.promo_id for promo in
                    db.query(PromoHistory.promo_id)
                    .filter(PromoHistory.api_link_id == link_id)
                    .all()
                }

                logger.info(f"📊 В базе данных уже есть {len(existing_promo_ids)} промоакций для ссылки {link_id}")
                if existing_promo_ids:
                    logger.debug(f"   Существующие ID: {list(existing_promo_ids)[:10]}{'...' if len(existing_promo_ids) > 10 else ''}")

                # НОВОЕ: Очистка устаревших промо (есть в БД, но нет в API)
                current_promo_ids = {p.get('promo_id') for p in promotions if p.get('promo_id')}
                outdated_ids = existing_promo_ids - current_promo_ids
                
                if outdated_ids:
                    # Удаляем устаревшие промо
                    deleted = db.query(PromoHistory).filter(
                        PromoHistory.promo_id.in_(outdated_ids)
                    ).delete(synchronize_session=False)
                    db.commit()
                    stats['outdated_removed'] = deleted
                    logger.info(f"🗑️ Удалено {deleted} устаревших промоакций (нет в API)")

                # Фильтруем только новые промоакции с валидными ID
                new_promos = []
                for promo in promotions:
                    promo_id = promo.get('promo_id')
                    if not promo_id:
                        logger.warning(f"⚠️ Промоакция без promo_id: {promo.get('title', 'Без названия')}")
                        stats['invalid'] += 1
                        continue

                    # Дополнительная проверка для fallback промо
                    if '_fallback_' in promo_id:
                        # Быстрая проверка: есть ли хоть какие-то данные кроме ID и title
                        has_data = any([
                            promo.get('total_prize_pool'),
                            promo.get('award_token'),
                            promo.get('link'),
                            promo.get('description')
                        ])

                        if not has_data:
                            logger.warning(
                                f"⚠️ ФИЛЬТР: Fallback промоакция '{promo.get('title', 'Без названия')}' "
                                f"({promo_id}) не содержит значимых данных - пропускаем на этапе фильтрации"
                            )
                            stats['fallback_rejected'] += 1
                            continue

                    if promo_id in existing_promo_ids:
                        # НОВОЕ: Обновляем данные существующей промоакции (winners_count, reward_per_winner и т.д.)
                        self._update_existing_promo(db, promo_id, promo)
                        logger.debug(f"   ⏭️ Существующая промоакция (обновлены данные): {promo.get('title', 'Без названия')} ({promo_id})")
                        stats['existing'] += 1
                    else:
                        logger.debug(f"   ✅ НОВАЯ промоакция: {promo.get('title', 'Без названия')} ({promo_id})")
                        new_promos.append(promo)
                        stats['new'] += 1

                # Выводим детальную статистику
                logger.info(f"📊 Результат фильтрации:")
                logger.info(f"   Всего промоакций: {stats['total']}")
                logger.info(f"   Уже существуют в БД: {stats['existing']}")
                logger.info(f"   Новых промоакций: {stats['new']}")
                if stats['invalid'] > 0:
                    logger.info(f"   Без promo_id: {stats['invalid']}")
                if stats['fallback_rejected'] > 0:
                    logger.info(f"   Fallback отклонено (нет данных): {stats['fallback_rejected']}")
                if stats['outdated_removed'] > 0:
                    logger.info(f"   🗑️ Устаревших удалено: {stats['outdated_removed']}")

                return new_promos

        except Exception as e:
            logger.error(f"❌ Ошибка фильтрации промоакций: {e}", exc_info=True)
            return []  # В случае ошибки возвращаем пустой список
    
    def _update_existing_promo(self, db, promo_id: str, promo: Dict):
        """Обновляет данные существующей промоакции (participants_count, conditions, reward_type, max_reward и т.д.)"""
        try:
            logger.debug(f"📝 _update_existing_promo вызван для {promo.get('title')} (ID: {promo_id})")
            
            # Получаем все данные из прома
            winners_count = promo.get('winners_count')
            reward_per_winner = promo.get('reward_per_winner')
            participants_count = promo.get('participants_count')
            conditions = promo.get('conditions')
            reward_type = promo.get('reward_type')
            user_max_rewards = promo.get('user_max_rewards')
            start_time = promo.get('start_time')
            end_time = promo.get('end_time')
            total_prize_pool = promo.get('total_prize_pool')
            
            # Получаем существующую запись
            existing = db.query(PromoHistory).filter(PromoHistory.promo_id == promo_id).first()
            if not existing:
                return
            
            updated = False
            
            # ВСЕГДА обновляем participants_count (это динамическое значение)
            if participants_count:
                new_count = self._safe_int(participants_count)
                if new_count and new_count != existing.participants_count:
                    existing.participants_count = new_count
                    updated = True
            
            # Обновляем только если текущие значения пустые
            if winners_count and not existing.winners_count:
                existing.winners_count = self._safe_int(winners_count)
                updated = True
                
            if reward_per_winner and not existing.reward_per_winner:
                existing.reward_per_winner = str(reward_per_winner)
                updated = True
            
            # Условия - конвертируем массив в строку
            if conditions and not existing.conditions:
                if isinstance(conditions, list):
                    existing.conditions = ', '.join(conditions)
                else:
                    existing.conditions = str(conditions)
                updated = True
            
            # Тип награды - конвертируем массив в строку
            if reward_type and not existing.reward_type:
                if isinstance(reward_type, list):
                    existing.reward_type = ', '.join(reward_type)
                else:
                    existing.reward_type = str(reward_type)
                updated = True
            
            # Макс награда на юзера
            if user_max_rewards and not existing.max_reward_per_user:
                existing.max_reward_per_user = str(user_max_rewards)
                updated = True
            
            # Призовой пул (если пустой)
            if total_prize_pool and not existing.total_prize_pool:
                existing.total_prize_pool = str(total_prize_pool)
                updated = True
            
            # Обновляем даты если они появились
            if start_time and not existing.start_time:
                existing.start_time = self._convert_to_datetime(start_time)
                updated = True

            if end_time and not existing.end_time:
                existing.end_time = self._convert_to_datetime(end_time)
                updated = True

            # MEXC Airdrop специфичные поля (раздельные пулы)
            token_pool = promo.get('token_pool')
            token_pool_currency = promo.get('token_pool_currency')
            bonus_usdt = promo.get('bonus_usdt')

            if token_pool and not existing.token_pool:
                existing.token_pool = self._safe_float(token_pool)
                updated = True

            if token_pool_currency and not existing.token_pool_currency:
                existing.token_pool_currency = str(token_pool_currency)
                updated = True

            if bonus_usdt and not existing.bonus_usdt:
                existing.bonus_usdt = self._safe_float(bonus_usdt)
                updated = True

            # === RAW_DATA ДЛЯ LAUNCHPOOL (pools, APR, заробіток) ===
            # Оновлюємо raw_data для лаунчпулів - це динамічні дані які потрібно оновлювати
            raw_data = promo.get('raw_data')
            if raw_data and promo.get('is_launchpool'):
                existing.raw_data = self._serialize_raw_data(raw_data)
                updated = True
                logger.debug(f"📊 Оновлено raw_data для launchpool: {promo.get('title')}")

            # === РАСЧЁТ ЦЕНЫ ТОКЕНА ДЛЯ MEXC AIRDROP ===
            # Если есть token_pool_currency - получаем цену токена для расчёта USD эквивалента
            if token_pool_currency and (not existing.token_price or not hasattr(existing, 'token_price')):
                try:
                    clean_token = str(token_pool_currency).upper().strip()
                    if clean_token in self.STABLECOINS:
                        existing.token_price = 1.0
                        updated = True
                    elif self.price_fetcher:
                        fetched_price = self.price_fetcher.get_token_price(clean_token, preferred_exchange='MEXC')
                        if fetched_price:
                            existing.token_price = fetched_price
                            updated = True
                            logger.info(f"💵 Получена цена токена {clean_token}: ${fetched_price:.6f}")
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить цену {token_pool_currency}: {e}")

            # Gate.io возвращает некорректные USD цены - всегда пересчитываем через price_fetcher
            force_recalculate = existing.exchange and 'gate' in existing.exchange.lower()
            
            # Обновляем USD-эквиваленты если их нет (и не Gate.io)
            if not force_recalculate:
                total_prize_pool_usd = promo.get('total_prize_pool_usd')
                reward_per_winner_usd = promo.get('reward_per_winner_usd')
                
                if total_prize_pool_usd and not existing.total_prize_pool_usd:
                    existing.total_prize_pool_usd = self._safe_float(total_prize_pool_usd)
                    updated = True
                
                if reward_per_winner_usd and not existing.reward_per_winner_usd:
                    existing.reward_per_winner_usd = self._safe_float(reward_per_winner_usd)
                    updated = True
            
            # Если USD-эквиваленты всё ещё пустые (или Gate.io) - пробуем рассчитать через price_fetcher
            should_calculate_pool = force_recalculate or not existing.total_prize_pool_usd
            should_calculate_reward = force_recalculate or not existing.reward_per_winner_usd
            
            if (should_calculate_pool or should_calculate_reward) and existing.award_token:
                # Получаем цену токена один раз для обоих расчётов
                token_price = None
                clean_token = existing.award_token.upper().strip()
                
                if clean_token in self.STABLECOINS:
                    token_price = 1.0
                elif self.price_fetcher:
                    try:
                        token_price = self.price_fetcher.get_token_price(clean_token, preferred_exchange=existing.exchange)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить цену {clean_token}: {e}")
                
                if token_price:
                    # Расчёт total_prize_pool_usd
                    if should_calculate_pool and existing.total_prize_pool:
                        logger.info(f"💵 Попытка расчёта USD для {promo.get('title')}: pool={existing.total_prize_pool}, token={existing.award_token}")
                        try:
                            pool_str = str(existing.total_prize_pool).replace(',', '').replace(' ', '')
                            pool_num = float(pool_str)
                            existing.total_prize_pool_usd = pool_num * token_price
                            updated = True
                            logger.info(f"💰 Рассчитан total_prize_pool_usd=${existing.total_prize_pool_usd:.2f} для {promo.get('title')}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"⚠️ Не удалось рассчитать pool USD для {promo.get('title')}: {e}")
                    
                    # Расчёт reward_per_winner_usd (из reward_per_winner или max_reward_per_user)
                    if should_calculate_reward:
                        # Пробуем reward_per_winner сначала, потом max_reward_per_user
                        reward_source = existing.reward_per_winner or existing.max_reward_per_user
                        if reward_source:
                            try:
                                # Парсим число из строки типа "2000 SCOR" или "200 ELSA" или просто "54000"
                                import re
                                reward_match = re.match(r'([\d,]+(?:\.\d+)?)', str(reward_source).replace(' ', ''))
                                if reward_match:
                                    reward_num = float(reward_match.group(1).replace(',', ''))
                                    existing.reward_per_winner_usd = reward_num * token_price
                                    updated = True
                                    logger.info(f"💵 Рассчитан reward_per_winner_usd=${existing.reward_per_winner_usd:.2f} для {promo.get('title')}")
                            except (ValueError, TypeError) as e:
                                logger.debug(f"⚠️ Не удалось рассчитать reward USD для {promo.get('title')}: {e}")
                else:
                    if should_calculate_pool:
                        logger.warning(f"⚠️ Не удалось получить цену для {promo.get('title')}: {existing.award_token}")

            if updated:
                existing.last_updated = datetime.utcnow()
                db.commit()
                logger.debug(f"📝 Обновлены данные для {promo.get('title')}: participants={participants_count}, conditions={conditions}, reward_type={reward_type}")
                
                # Записываем участников в историю для отслеживания изменений
                if participants_count:
                    try:
                        from services.participants_tracker_service import ParticipantsTrackerService
                        exchange = existing.exchange or promo.get('exchange', 'Unknown')
                        title = promo.get('title')
                        p_count = self._safe_int(participants_count)
                        if p_count:
                            ParticipantsTrackerService.record_participants(exchange, promo_id, p_count, title)
                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка записи участников: {e}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка обновления промоакции {promo_id}: {e}")

    def _enrich_promos_with_prices(self, promotions: List[Dict], exchange: str = None) -> List[Dict]:
        """
        Обогащает промоакции USD-эквивалентами используя price_fetcher.
        Вызывается при сохранении промоакций в БД.
        
        Args:
            promotions: Список промоакций для обогащения
            exchange: Название биржи (для предпочтительного источника цен)
            
        Returns:
            Список обогащённых промоакций
        """
        if not self.price_fetcher:
            logger.debug("⚠️ price_fetcher недоступен, пропуск обогащения ценами")
            return promotions
        
        # Gate.io возвращает некорректные USD цены - всегда пересчитываем
        force_recalculate = exchange and 'gate' in exchange.lower()
        
        enriched_count = 0
        
        for promo in promotions:
            try:
                award_token = promo.get('award_token')
                total_prize_pool = promo.get('total_prize_pool')
                total_prize_pool_usd = promo.get('total_prize_pool_usd')
                reward_per_winner = promo.get('reward_per_winner')
                reward_per_winner_usd = promo.get('reward_per_winner_usd')
                
                # Для Gate.io - сбрасываем некорректные USD значения из API
                if force_recalculate:
                    total_prize_pool_usd = None
                    reward_per_winner_usd = None
                    promo['total_prize_pool_usd'] = None
                    promo['reward_per_winner_usd'] = None
                
                # Пропускаем если нет токена или уже есть USD значения
                if not award_token:
                    continue
                    
                # Очищаем символ токена (может содержать числа типа "2000 SCOR")
                clean_token = award_token.upper().strip()
                # Убираем числа из начала если есть
                token_match = re.search(r'([A-Z]{2,10})$', clean_token)
                if token_match:
                    clean_token = token_match.group(1)
                
                # Проверяем на стейблкоин
                is_stablecoin = clean_token in self.STABLECOINS
                
                token_price = None
                if is_stablecoin:
                    token_price = 1.0
                else:
                    try:
                        token_price = self.price_fetcher.get_token_price(clean_token, preferred_exchange=exchange)
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить цену {clean_token}: {e}")
                
                if not token_price:
                    continue
                
                promo_enriched = False
                
                # Обогащаем total_prize_pool_usd если отсутствует
                if not total_prize_pool_usd and total_prize_pool:
                    try:
                        pool_str = str(total_prize_pool).replace(',', '').replace(' ', '')
                        pool_num = float(pool_str)
                        promo['total_prize_pool_usd'] = pool_num * token_price
                        promo_enriched = True
                        logger.debug(f"💰 Обогащено: {promo.get('title')} - pool_usd=${promo['total_prize_pool_usd']:.2f}")
                    except (ValueError, TypeError):
                        pass
                
                # Обогащаем reward_per_winner_usd если отсутствует
                if not reward_per_winner_usd and reward_per_winner:
                    try:
                        # Парсим число из строки типа "2000 SCOR" или "20 USDT"
                        reward_match = re.match(r'([\d,]+(?:\.\d+)?)', str(reward_per_winner).replace(' ', ''))
                        if reward_match:
                            reward_num = float(reward_match.group(1).replace(',', ''))
                            promo['reward_per_winner_usd'] = reward_num * token_price
                            promo_enriched = True
                    except (ValueError, TypeError):
                        pass
                
                if promo_enriched:
                    enriched_count += 1
                
                # === MEXC AIRDROP: Обогащаем token_price для пула токенов ===
                token_pool = promo.get('token_pool')
                token_pool_currency = promo.get('token_pool_currency')
                if token_pool and token_pool_currency and not promo.get('token_price'):
                    try:
                        clean_pool_token = str(token_pool_currency).upper().strip()
                        if clean_pool_token in self.STABLECOINS:
                            promo['token_price'] = 1.0
                            logger.debug(f"💵 MEXC Airdrop: {promo.get('title')} - {clean_pool_token} = стейблкоин")
                        else:
                            pool_token_price = self.price_fetcher.get_token_price(clean_pool_token, preferred_exchange='MEXC')
                            if pool_token_price:
                                promo['token_price'] = pool_token_price
                                logger.info(f"💵 MEXC Airdrop: {promo.get('title')} - цена {clean_pool_token} = ${pool_token_price:.6f}")
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить цену {token_pool_currency}: {e}")
                    
            except Exception as e:
                logger.warning(f"⚠️ Ошибка обогащения промо {promo.get('title')}: {e}")
                continue
        
        if enriched_count > 0:
            logger.info(f"💰 Обогащено ценами: {enriched_count}/{len(promotions)} промоакций")
        
        return promotions

    def _calculate_usd_value(self, amount: Any, token: str, exchange: str = None) -> Optional[float]:
        """
        Рассчитывает USD-эквивалент для суммы токенов.
        
        Args:
            amount: Сумма (число или строка)
            token: Символ токена
            exchange: Название биржи (для предпочтительного источника цен)
            
        Returns:
            USD-эквивалент или None
        """
        if not self.price_fetcher or not amount or not token:
            return None
        
        try:
            # Очищаем символ токена
            clean_token = token.upper().strip()
            token_match = re.search(r'([A-Z]{2,10})$', clean_token)
            if token_match:
                clean_token = token_match.group(1)
            
            # Проверяем на стейблкоин
            if clean_token in self.STABLECOINS:
                token_price = 1.0
            else:
                token_price = self.price_fetcher.get_token_price(clean_token, preferred_exchange=exchange)
            
            if not token_price:
                return None
            
            # Парсим сумму
            amount_str = str(amount).replace(',', '').replace(' ', '')
            amount_num = float(amount_str)
            
            return amount_num * token_price
            
        except Exception as e:
            logger.debug(f"⚠️ Ошибка расчёта USD для {amount} {token}: {e}")
            return None
    
    def _save_to_history(self, link_id: int, promotions: List[Dict]) -> int:
        """Сохраняет промоакции в историю с валидацией"""
        saved_count = 0

        try:
            with get_db_session() as db:
                for promo in promotions:
                    try:
                        # Валидация перед сохранением
                        if not self._validate_promo_for_saving(promo):
                            # Обновляем статистику
                            promo_id = promo.get('promo_id', '')
                            if '_fallback_' in promo_id:
                                self.stats['fallback_rejected'] += 1

                            logger.warning(f"⚠️ Пропускаем невалидную промоакцию: {promo.get('title')}")
                            continue

                        # Обновляем статистику для принятых fallback
                        promo_id = promo.get('promo_id', '')
                        if '_fallback_' in promo_id:
                            self.stats['fallback_accepted'] += 1

                        history_item = PromoHistory(
                            api_link_id=link_id,
                            promo_id=promo.get('promo_id'),
                            exchange=promo.get('exchange', 'Unknown'),
                            title=promo.get('title', ''),
                            description=promo.get('description', ''),
                            total_prize_pool=promo.get('total_prize_pool', ''),
                            award_token=promo.get('award_token', ''),
                            start_time=self._convert_to_datetime(promo.get('start_time')),
                            end_time=self._convert_to_datetime(promo.get('end_time')),
                            link=promo.get('link', ''),
                            icon=promo.get('icon', ''),
                            # Новые поля для детальной информации
                            participants_count=self._safe_int(promo.get('participants_count')),
                            winners_count=self._safe_int(promo.get('winners_count')),
                            reward_per_winner=str(promo.get('reward_per_winner', '')) if promo.get('reward_per_winner') else None,
                            reward_per_winner_usd=self._safe_float(promo.get('reward_per_winner_usd')),
                            # Условия и тип награды - конвертируем массивы в строки
                            conditions=', '.join(promo.get('conditions')) if isinstance(promo.get('conditions'), list) else str(promo.get('conditions', '')) if promo.get('conditions') else None,
                            reward_type=', '.join(promo.get('reward_type')) if isinstance(promo.get('reward_type'), list) else str(promo.get('reward_type', '')) if promo.get('reward_type') else None,
                            total_prize_pool_usd=self._safe_float(promo.get('total_prize_pool_usd')),
                            status=str(promo.get('status', '')) if promo.get('status') else None,
                            # Gate.io специфичные поля
                            max_reward_per_user=str(promo.get('user_max_rewards', '')) if promo.get('user_max_rewards') else None,
                            # MEXC Airdrop специфичные поля (раздельные пулы)
                            token_pool=self._safe_float(promo.get('token_pool')),
                            token_pool_currency=str(promo.get('token_pool_currency', '')) if promo.get('token_pool_currency') else None,
                            bonus_usdt=self._safe_float(promo.get('bonus_usdt')),
                            # MEXC Launchpad и другие специальные форматы
                            promo_type=promo.get('promo_type'),
                            raw_data=self._serialize_raw_data(promo.get('raw_data'))
                        )
                        db.add(history_item)
                        saved_count += 1

                    except Exception as e:
                        logger.error(f"❌ Ошибка сохранения промоакции {promo.get('title')}: {e}")
                        continue

                # Явный commit для уверенности
                db.commit()
                logger.info(f"💾 Успешно сохранено {saved_count} промоакций")
                
                # Записываем историю участников для отслеживания изменений
                try:
                    from services.participants_tracker_service import ParticipantsTrackerService
                    # Получаем exchange из первой промоакции
                    if promotions:
                        exchange = promotions[0].get('exchange', 'Unknown')
                        recorded = ParticipantsTrackerService.record_batch(exchange, promotions)
                        if recorded > 0:
                            logger.debug(f"📊 Записано {recorded} записей в историю участников")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка записи истории участников: {e}")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка сохранения в историю: {e}")

        return saved_count
    
    def _validate_promo_for_saving(self, promo: Dict[str, Any]) -> bool:
        """Проверяет валидность промоакции перед сохранением"""
        try:
            # Обязательные поля
            if not promo.get('promo_id'):
                logger.debug("❌ Пропуск промоакции: отсутствует promo_id")
                return False

            promo_id = promo.get('promo_id')

            # СТРОГАЯ ВАЛИДАЦИЯ для fallback промоакций
            if '_fallback_' in promo_id:
                logger.debug(f"🔍 Обнаружена fallback промоакция: {promo_id}")

                # Подсчитываем значимые заполненные поля
                significant_fields = [
                    'total_prize_pool',
                    'award_token',
                    'link',
                    'description',
                    'participants_count',
                    'start_time',
                    'end_time'
                ]

                filled_fields = []
                for field in significant_fields:
                    value = promo.get(field)
                    # Проверяем что поле не только существует, но и имеет значение
                    if value and str(value).strip() and str(value).strip() != '':
                        filled_fields.append(field)

                # Требуем минимум 3 значимых поля для fallback промо
                if len(filled_fields) < 3:
                    logger.warning(
                        f"❌ ОТКЛОНЕНО: Fallback промоакция '{promo.get('title', 'Без названия')}' "
                        f"(ID: {promo_id}) содержит недостаточно данных"
                    )
                    logger.warning(f"   Заполненные поля ({len(filled_fields)}/3): {filled_fields}")
                    logger.warning(f"   Требуется минимум 3 из: {significant_fields}")
                    return False

                logger.info(
                    f"✅ ПРИНЯТО: Fallback промоакция '{promo.get('title', 'Без названия')}' "
                    f"прошла валидацию ({len(filled_fields)} полей)"
                )
                logger.debug(f"   Заполненные поля: {filled_fields}")

            # МЯГКАЯ ВАЛИДАЦИЯ для обычных промоакций (существующая логика)
            if not promo.get('title') and not promo.get('description'):
                logger.debug("❌ Пропуск промоакции: отсутствует title и description")
                return False

            # Минимальная длина заголовка
            title = promo.get('title', '')
            if len(title.strip()) < 2:
                logger.debug(f"❌ Пропуск промоакции: слишком короткий заголовок '{title}'")
                return False

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка валидации промо: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику работы сервиса"""
        success_rate = 0
        if self.stats['total_checks'] > 0:
            success_rate = (self.stats['successful_checks'] / self.stats['total_checks']) * 100

        return {
            'total_checks': self.stats['total_checks'],
            'successful_checks': self.stats['successful_checks'],
            'failed_checks': self.stats['failed_checks'],
            'new_promos_found': self.stats['new_promos_found'],
            'fallback_rejected': self.stats['fallback_rejected'],
            'fallback_accepted': self.stats['fallback_accepted'],
            'success_rate': round(success_rate, 2),
            'last_check_time': self.stats['last_check_time']
        }
    
    def parse_staking_link(self, link_id: int, api_url: str, exchange_name: str, page_url: str = None, min_apr: float = None) -> List[Dict[str, Any]]:
        """
        Парсит стейкинг-ссылку и возвращает новые стейкинги

        Args:
            link_id: ID ссылки в БД
            api_url: URL API для парсинга стейкингов
            exchange_name: Название биржи (Bybit, Kucoin и т.д.)
            page_url: URL страницы для пользователя (опционально)
            min_apr: Минимальный APR для фильтрации (опционально)

        Returns:
            Список новых стейкингов
        """
        try:
            logger.info(f"🔍 ParserService: Начало парсинга стейкинг-ссылки {link_id}")
            logger.info(f"   Биржа: {exchange_name}")
            logger.info(f"   API URL: {api_url}")
            if min_apr is not None:
                logger.info(f"   Min APR: {min_apr}%")

            # Проверяем, нужен ли специальный парсер для Bitget PoolX
            if 'bitget.com' in api_url.lower() and 'poolx' in api_url.lower():
                logger.info(f"📡 Используем специальный парсер BitgetPoolxParser...")
                return self._parse_bitget_poolx_staking(link_id, api_url, min_apr)

            # Создаем парсер стейкингов
            parser = StakingParser(api_url=api_url, exchange_name=exchange_name)

            # Парсим стейкинги
            logger.info(f"📡 Запуск парсинга стейкингов...")
            stakings = parser.parse()

            if not stakings:
                logger.info(f"ℹ️ ParserService: Парсер не вернул стейкингов для ссылки {link_id}")
                return []

            logger.info(f"📦 ParserService: Парсер вернул {len(stakings)} стейкингов")

            # Логируем найденные стейкинги
            logger.info(f"📋 Список найденных стейкингов:")
            for i, staking in enumerate(stakings[:10], 1):  # Первые 10
                coin = staking.get('coin', 'N/A')
                apr = staking.get('apr', 0)
                staking_type = staking.get('type', 'N/A')
                logger.info(f"   {i}. {coin} - {apr}% ({staking_type})")
            if len(stakings) > 10:
                logger.info(f"   ... и ещё {len(stakings) - 10} стейкингов")

            # Проверяем на новые стейкинги (с фильтрацией по min_apr)
            logger.info(f"🔍 Проверка новых стейкингов...")
            new_stakings = check_and_save_new_stakings(stakings, link_id=link_id, min_apr=min_apr)

            if new_stakings:
                logger.info(f"🎉 ParserService: Найдено {len(new_stakings)} НОВЫХ стейкингов для ссылки {link_id}")
                logger.info(f"📋 Список НОВЫХ стейкингов:")
                for i, staking in enumerate(new_stakings, 1):
                    coin = staking.get('coin', 'N/A')
                    apr = staking.get('apr', 0)
                    staking_type = staking.get('type', 'N/A')
                    logger.info(f"   {i}. {coin} - {apr}% ({staking_type})")

                # Для OKX группируем пулы по проектам
                if 'okx' in exchange_name.lower():
                    logger.info(f"🔍 Группировка пулов OKX по проектам...")
                    grouped = self._group_okx_pools(new_stakings)
                    logger.info(f"📦 Сгруппировано в {len(grouped)} проектов")
                    # Помечаем что это группы
                    for group in grouped:
                        group[0]['_is_okx_group'] = True
                        group[0]['_group_pools'] = group
                    return grouped[0] if grouped else []  # Возвращаем первую группу (все пулы одного проекта)

                return new_stakings
            else:
                logger.info(f"ℹ️ ParserService: Все стейкинги уже были в базе данных (нет новых)")
                return []

        except Exception as e:
            logger.error(f"❌ ParserService: Критическая ошибка при парсинге стейкинг-ссылки {link_id}: {e}", exc_info=True)
            return []

    def _parse_bitget_poolx_staking(self, link_id: int, api_url: str, min_apr: float = None) -> List[Dict[str, Any]]:
        """
        Специальный парсер для Bitget PoolX стейкингов
        Конвертирует LaunchpoolProject в формат стейкингов
        """
        import asyncio
        from parsers.bitget_poolx_parser import BitgetPoolxParser
        from utils.price_fetcher import get_price_fetcher
        
        try:
            parser = BitgetPoolxParser()
            
            # Запускаем асинхронный парсинг
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, parser.get_projects_async())
                    projects = future.result()
            except RuntimeError:
                projects = asyncio.run(parser.get_projects_async())
            
            if not projects:
                logger.info(f"ℹ️ BitgetPoolxParser: Нет проектов")
                return []
            
            logger.info(f"📦 BitgetPoolxParser: Найдено {len(projects)} проектов")
            
            # Конвертируем проекты в формат стейкингов
            stakings = []
            price_fetcher = get_price_fetcher()
            
            for project in projects:
                # Только активные и upcoming
                if project.status not in ['active', 'upcoming']:
                    continue
                
                # Для каждого пула создаём стейкинг
                for pool in project.pools:
                    # Получаем цену стейк-токена
                    token_price = price_fetcher.get_token_price(pool.stake_coin)
                    
                    # Рассчитываем user_limit_usd
                    user_limit_usd = None
                    if pool.max_stake and token_price:
                        user_limit_usd = pool.max_stake * token_price
                    
                    staking = {
                        'exchange': 'Bitget',
                        'product_id': f"{project.id}_{pool.stake_coin}",
                        'coin': pool.stake_coin,
                        'reward_coin': project.token_symbol,
                        'apr': pool.apr,
                        'type': 'PoolX',
                        'status': project.status.capitalize(),
                        'category': 'poolx',
                        'category_text': 'PoolX Staking',
                        'term_days': project.days_left,
                        'token_price_usd': token_price,
                        'start_time': project.start_time,
                        'end_time': project.end_time,
                        'user_limit_tokens': pool.max_stake,
                        'user_limit_usd': user_limit_usd,
                        'max_capacity': None,
                        'current_deposit': pool.total_staked,
                        'fill_percentage': None,
                        'is_vip': False,
                        'is_new_user': False,
                        'total_rewards': project.total_pool_tokens,
                        'pool_reward': pool.pool_reward,
                        'participants': pool.participants,
                    }
                    
                    # Фильтрация по min_apr
                    if min_apr and pool.apr < min_apr:
                        continue
                    
                    stakings.append(staking)
                    logger.info(f"   📌 {pool.stake_coin} → {project.token_symbol}: APR {pool.apr}%")
            
            logger.info(f"📊 BitgetPoolxParser: Конвертировано {len(stakings)} стейкингов")
            
            # Проверяем на новые
            new_stakings = check_and_save_new_stakings(stakings, link_id=link_id, min_apr=min_apr)
            
            if new_stakings:
                logger.info(f"🎉 BitgetPoolxParser: Найдено {len(new_stakings)} НОВЫХ стейкингов")
            else:
                logger.info(f"ℹ️ BitgetPoolxParser: Все стейкинги уже в базе")
            
            return new_stakings
            
        except Exception as e:
            logger.error(f"❌ BitgetPoolxParser: Ошибка парсинга: {e}", exc_info=True)
            return []

    def _group_okx_pools(self, stakings: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Группирует пулы OKX по проектам (по reward_coin + start_time + end_time)

        Args:
            stakings: Список стейкингов OKX

        Returns:
            Список групп (каждая группа = список пулов одного проекта)
        """
        groups = {}
        for staking in stakings:
            # Группируем по награде и датам (одна промоакция = одинаковая награда и даты)
            reward_coin = staking.get('reward_coin', '')
            start_time = staking.get('start_time')
            end_time = staking.get('end_time')

            # Создаем ключ для группировки
            group_key = (reward_coin, start_time, end_time)

            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(staking)

        logger.info(f"📊 Группировка OKX: найдено {len(groups)} уникальных проектов")
        for key, pools in groups.items():
            reward, start, end = key
            logger.debug(f"   Проект: награда={reward}, пулов={len(pools)}, даты={start}-{end}")

        return list(groups.values())

    def reset_stats(self):
        """Сбрасывает статистику"""
        self.stats = {
            'total_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'new_promos_found': 0,
            'fallback_rejected': 0,
            'fallback_accepted': 0,
            'last_check_time': None
        }

    def check_announcement_link(self, link_id: int, url: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет анонс-ссылку на изменения с использованием выбранной стратегии

        Args:
            link_id: ID ссылки в БД
            url: URL страницы для парсинга

        Returns:
            Словарь с результатом проверки или None если не было изменений/ошибка
            {
                'changed': bool,
                'message': str,
                'matched_content': str,
                'strategy': str
            }
        """
        try:
            logger.info(f"🔍 ParserService: Начало проверки announcement ссылки {link_id}")
            logger.info(f"   URL: {url}")

            # Получаем настройки анонса из БД
            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()

                if not link:
                    logger.error(f"❌ Ссылка {link_id} не найдена в БД")
                    return None

                if link.category != 'announcement':
                    logger.error(f"❌ Ссылка {link_id} не является announcement (category={link.category})")
                    return None

                # ПРОВЕРКА НА TELEGRAM ТИП: этот метод не предназначен для Telegram ссылок
                if link.parsing_type == 'telegram':
                    logger.warning(f"⚠️ Ссылка {link_id} имеет тип 'telegram' - используйте TelegramMonitor для проверки")
                    logger.info(f"   Telegram канал: {link.telegram_channel}")
                    logger.info(f"   💡 Для Telegram ссылок используйте принудительную проверку через бота")
                    return None

                # ПРОВЕРЯЕМ СПЕЦИАЛЬНЫЙ ПАРСЕР
                special_parser = link.special_parser
                if special_parser:
                    logger.info(f"🔧 Обнаружен специальный парсер: {special_parser}")
                    logger.info(f"   Переключаемся на check_for_new_promos вместо announcement парсинга")
                    # Используем обычный метод парсинга с специальным парсером
                    return self._check_with_special_parser(link_id, url, special_parser, link)

                # Получаем настройки парсинга
                strategy = link.announcement_strategy
                last_snapshot = link.announcement_last_snapshot
                keywords = link.get_announcement_keywords()
                regex_pattern = link.announcement_regex
                css_selector = link.announcement_css_selector
                use_browser = link.parsing_type == 'browser'  # Используем браузер если тип = browser

                logger.info(f"📊 Настройки парсинга:")
                logger.info(f"   Стратегия: {strategy}")
                logger.info(f"   Тип парсинга: {link.parsing_type}")
                logger.info(f"   Браузерный парсер: {'✅ ДА' if use_browser else '❌ НЕТ'}")
                if keywords:
                    logger.info(f"   Ключевые слова: {keywords}")
                if regex_pattern:
                    logger.info(f"   Regex: {regex_pattern}")
                if css_selector:
                    logger.info(f"   CSS селектор: {css_selector}")

                # Проверяем, что стратегия указана
                if not strategy:
                    logger.error(f"❌ Стратегия парсинга не указана для ссылки {link_id}")
                    return None

                # Создаем парсер анонсов
                parser = AnnouncementParser(url)

                # Выполняем парсинг
                logger.info(f"📡 Запуск парсинга анонсов...")
                result = parser.parse(
                    strategy=strategy,
                    last_snapshot=last_snapshot,
                    keywords=keywords,
                    regex_pattern=regex_pattern,
                    css_selector=css_selector,
                    use_browser=use_browser  # КРИТИЧНО: передаем флаг браузерного парсинга
                )

                logger.info(f"📦 Результат парсинга:")
                logger.info(f"   Изменения: {result['changed']}")
                logger.info(f"   Сообщение: {result['message']}")
                if result['matched_content']:
                    logger.info(f"   Найдено: {result['matched_content'][:200]}...")

                # Обновляем последний снимок и время проверки в БД
                link.announcement_last_snapshot = result['new_snapshot']
                link.announcement_last_check = datetime.utcnow()
                db.commit()

                logger.info(f"✅ Снимок обновлен и сохранен в БД")

                # Если были изменения, возвращаем результат
                if result['changed']:
                    logger.info(f"🎉 Обнаружены изменения в анонсах!")
                    return {
                        'changed': True,
                        'message': result['message'],
                        'matched_content': result['matched_content'],
                        'strategy': strategy,
                        'url': url
                    }
                else:
                    logger.info(f"ℹ️ Изменений не обнаружено")
                    return None

        except Exception as e:
            logger.error(f"❌ Ошибка при проверке announcement ссылки {link_id}: {e}", exc_info=True)
            return None


# ========== ФУНКЦИИ ДЛЯ СТЕЙКИНГОВ ==========

def check_and_save_new_stakings(stakings: List[Dict[str, Any]], link_id: int = None, min_apr: float = None) -> List[Dict[str, Any]]:
    """
    Проверяет стейкинги на новизну и сохраняет новые в БД

    Args:
        stakings: Список распарсенных стейкингов
        link_id: ID ссылки из которой получены стейкинги (опционально)
        min_apr: Минимальный APR для фильтрации (опционально)

    Returns:
        Список НОВЫХ стейкингов (которых не было в БД)
    """
    from data.models import StakingHistory
    from services.staking_snapshot_service import StakingSnapshotService

    # Инициализируем сервисы
    snapshot_service = StakingSnapshotService()
    new_stakings = []
    filtered_count = 0

    # КРИТИЧНО: Логируем параметры фильтрации для отладки
    logger.warning(
        f"🚨 [VERSION 2.1] check_and_save_new_stakings: link_id={link_id}, min_apr={min_apr}, "
        f"stakings_count={len(stakings)}"
    )

    with get_db_session() as session:
        try:
            # Инициализируем StabilityTracker
            stability_tracker = StabilityTrackerService(session)

            # Получаем настройки ссылки для уведомлений
            api_link = None
            if link_id:
                api_link = session.query(ApiLink).filter(ApiLink.id == link_id).first()

            for staking in stakings:
                exchange = staking.get('exchange')
                product_id = staking.get('product_id')

                if not exchange or not product_id:
                    logger.warning(f"⚠️ Пропуск стейкинга: отсутствует exchange или product_id")
                    continue

                # Проверяем, есть ли уже в БД
                existing = session.query(StakingHistory).filter(
                    StakingHistory.exchange == exchange,
                    StakingHistory.product_id == product_id
                ).first()

                if existing:
                    # Стейкинг уже есть, обновляем данные
                    new_apr = staking.get('apr', existing.apr)

                    # Обновляем статус и заполненность
                    existing.status = staking.get('status', existing.status)
                    existing.product_type = staking.get('product_type', existing.product_type)
                    existing.fill_percentage = staking.get('fill_percentage')
                    existing.current_deposit = staking.get('current_deposit')
                    existing.max_capacity = staking.get('max_capacity')
                    existing.token_price_usd = staking.get('token_price_usd')
                    existing.last_updated = datetime.utcnow()
                    
                    # Обновляем поля для объединённых продуктов Fixed/Flexible (Gate.io)
                    if staking.get('fixed_apr') is not None:
                        existing.fixed_apr = staking.get('fixed_apr')
                    if staking.get('fixed_term_days') is not None:
                        existing.fixed_term_days = staking.get('fixed_term_days')
                    if staking.get('fixed_user_limit') is not None:
                        existing.fixed_user_limit = staking.get('fixed_user_limit')
                    if staking.get('flexible_apr') is not None:
                        existing.flexible_apr = staking.get('flexible_apr')
                    if staking.get('flexible_user_limit') is not None:
                        existing.flexible_user_limit = staking.get('flexible_user_limit')

                    # УМНЫЕ УВЕДОМЛЕНИЯ: Проверяем изменение APR и обновляем статус стабильности
                    if api_link:
                        stability_tracker.update_stability_status(
                            staking=existing,
                            new_apr=new_apr,
                            api_link=api_link
                        )

                        # Проверяем, нужно ли уведомлять
                        stability_result = stability_tracker.check_stability(existing, api_link)
                        if stability_result['should_notify']:
                            # КРИТИЧНО: Не отправляем повторно если уже отправлено (кроме изменений APR)
                            if stability_result['notification_type'] != 'apr_change' and existing.notification_sent:
                                logger.debug(f"⏭️ Пропущен (уже отправлено): {exchange} {staking.get('coin')}")
                                continue

                            # КРИТИЧНО: Проверяем фильтр min_apr ПЕРЕД добавлением в new_stakings
                            # Используем явное сравнение: если min_apr установлен, проверяем его
                            apr_passes_filter = (min_apr is None or existing.apr >= min_apr)

                            logger.warning(
                                f"🚨 [VERSION 2.1] Проверка существующего стейкинга: {exchange} {staking.get('coin')} | "
                                f"APR={existing.apr}%, min_apr={min_apr}, "
                                f"passes_filter={apr_passes_filter}, type={stability_result['notification_type']}"
                            )

                            if apr_passes_filter:
                                logger.info(
                                    f"📣 Готово к уведомлению: {exchange} {staking.get('coin')} - "
                                    f"{stability_result['notification_type']} ({stability_result['reason']})"
                                )
                                # Отмечаем для уведомления (будет отправлено в main.py)
                                staking['_should_notify'] = True
                                staking['_notification_type'] = stability_result['notification_type']
                                staking['_notification_reason'] = stability_result['reason']
                                staking['_staking_db_id'] = existing.id  # Сохраняем ID для mark_notification_sent
                                staking['_lock_type'] = existing.lock_type  # Тип блокировки

                                # Дополнительные данные для форматирования уведомлений
                                if stability_result['notification_type'] == 'apr_change':
                                    staking['_previous_apr'] = existing.previous_apr or 0
                                    staking['_apr_threshold'] = api_link.notify_min_apr_change
                                elif stability_result['notification_type'] == 'new' and existing.lock_type == 'Flexible':
                                    staking['_stability_hours'] = api_link.flexible_stability_hours

                                new_stakings.append(staking)
                            else:
                                logger.info(
                                    f"🔽 Пропущен (APR {existing.apr}% < {min_apr}%): {exchange} {staking.get('coin')} "
                                    f"({stability_result['notification_type']})"
                                )
                                filtered_count += 1
                    else:
                        # Без api_link обновляем APR напрямую
                        existing.apr = new_apr

                    logger.debug(f"🔄 Обновлён стейкинг: {exchange} {staking.get('coin')} - {product_id}")

                    # Синхронизируем изменения перед созданием снимка (без commit)
                    session.flush()

                    # Создаем снимок (если прошло >= 1 час)
                    snapshot_service.create_snapshot(existing)

                else:
                    # Новый стейкинг!
                    apr = staking.get('apr', 0)
                    staking_type = staking.get('type', '')

                    # УМНЫЕ УВЕДОМЛЕНИЯ: Определяем тип блокировки
                    lock_type = 'Unknown'
                    is_pending = False
                    stable_since = None

                    if api_link:
                        lock_type = stability_tracker.determine_lock_type(staking_type)

                        # Для Flexible устанавливаем pending и stable_since
                        if lock_type == 'Flexible':
                            is_pending = True
                            stable_since = datetime.utcnow()
                            logger.info(f"⏳ Новый Flexible стейкинг, начинаем отслеживание стабильности: {exchange} {staking.get('coin')}")
                        # Для Fixed и Combined уведомляем сразу
                        elif lock_type in ['Fixed', 'Combined']:
                            is_pending = False
                            logger.info(f"📣 Новый {lock_type} стейкинг, уведомление сразу: {exchange} {staking.get('coin')}")

                    # ФИЛЬТР ПО MIN_APR - проверяем ДО добавления в new_stakings
                    passes_filter = (min_apr is None or apr >= min_apr)

                    # КРИТИЧНО: Логируем все стейкинги для отладки
                    logger.info(
                        f"🔍 Новый стейкинг: {exchange} {staking.get('coin')} | "
                        f"APR={apr}%, lock_type={lock_type}, min_apr={min_apr}, "
                        f"passes_filter={passes_filter}, type='{staking.get('type')}'"
                    )

                    if not passes_filter:
                        logger.info(f"🔽 Пропущен стейкинг (APR {apr}% < {min_apr}%): {exchange} {staking.get('coin')}")
                        filtered_count += 1

                    # Сохраняем в БД всегда (чтобы не считать новым в следующий раз)
                    new_staking_record = StakingHistory(
                        exchange=exchange,
                        product_id=product_id,
                        coin=staking.get('coin'),
                        reward_coin=staking.get('reward_coin'),
                        apr=apr,
                        type=staking_type,
                        product_type=staking.get('product_type'),
                        status=staking.get('status'),
                        category=staking.get('category'),
                        category_text=staking.get('category_text'),
                        term_days=staking.get('term_days'),
                        user_limit_tokens=staking.get('user_limit_tokens'),
                        user_limit_usd=staking.get('user_limit_usd'),
                        total_places=staking.get('total_places'),
                        max_capacity=staking.get('max_capacity'),
                        current_deposit=staking.get('current_deposit'),
                        fill_percentage=staking.get('fill_percentage'),
                        token_price_usd=staking.get('token_price_usd'),
                        reward_token_price_usd=staking.get('reward_token_price_usd'),
                        start_time=staking.get('start_time'),
                        end_time=staking.get('end_time'),
                        notification_sent=False,
                        # Умные уведомления
                        lock_type=lock_type,
                        is_notification_pending=is_pending,
                        stable_since=stable_since,
                        # Поля для объединённых продуктов Fixed/Flexible (Gate.io)
                        fixed_apr=staking.get('fixed_apr'),
                        fixed_term_days=staking.get('fixed_term_days'),
                        fixed_user_limit=staking.get('fixed_user_limit'),
                        flexible_apr=staking.get('flexible_apr'),
                        flexible_user_limit=staking.get('flexible_user_limit')
                    )

                    session.add(new_staking_record)

                    # Синхронизируем чтобы получить ID (без commit)
                    session.flush()

                    # Проверяем готовность к уведомлению
                    should_notify_now = False
                    notification_type = 'new'

                    if api_link and lock_type in ['Fixed', 'Combined']:
                        # Fixed/Combined уведомляем сразу ТОЛЬКО ЕСЛИ прошел фильтр min_apr
                        should_notify_now = passes_filter
                    elif lock_type == 'Flexible':
                        # Flexible проверяем стабильность
                        stability_result = stability_tracker.check_stability(new_staking_record, api_link)
                        # КРИТИЧНО: Для Flexible проверяем и стабильность И min_apr
                        should_notify_now = stability_result['should_notify'] and passes_filter
                        if stability_result['should_notify']:
                            notification_type = stability_result['notification_type']

                    # КРИТИЧНО: Добавляем в список новых ТОЛЬКО если прошел фильтр И готов к уведомлению
                    # Для Fixed/Combined: should_notify_now = passes_filter (установлено выше)
                    # Для Flexible: should_notify_now = stability + passes_filter
                    # Для Unknown: уведомляем как Fixed (сразу)
                    should_add = False

                    if lock_type in ['Fixed', 'Combined']:
                        # Fixed/Combined: уведомляем если прошел фильтр
                        should_add = passes_filter
                    elif lock_type == 'Flexible':
                        # Flexible: уведомляем если готов И прошел фильтр
                        should_add = should_notify_now and passes_filter
                    else:
                        # Unknown и другие: уведомляем как Fixed (если прошел фильтр)
                        should_add = passes_filter

                    if should_add:
                        staking['_should_notify'] = True
                        staking['_notification_type'] = notification_type
                        staking['_lock_type'] = lock_type
                        staking['_staking_db_id'] = new_staking_record.id  # Сохраняем ID для mark_notification_sent

                        # Дополнительные данные для форматирования уведомлений
                        if lock_type == 'Flexible' and api_link:
                            staking['_stability_hours'] = api_link.flexible_stability_hours

                        new_stakings.append(staking)

                        logger.info(
                            f"✅ Добавлен в очередь уведомлений: {exchange} {staking.get('coin')} | "
                            f"APR={apr}%, type={notification_type}, lock={lock_type}"
                        )
                    else:
                        logger.debug(
                            f"⏭️ Не готов к уведомлению: {exchange} {staking.get('coin')} | "
                            f"APR={apr}%, passes_filter={passes_filter}, should_notify={should_notify_now}, lock={lock_type}"
                        )

                    # Создаем первый снимок для нового стейкинга
                    snapshot_service.create_snapshot(new_staking_record)

            # КРИТИЧНО: Один финальный commit в конце транзакции
            session.commit()
            logger.debug("✅ Транзакция успешно завершена")

        except Exception as e:
            logger.error(f"❌ Ошибка в транзакции БД: {e}", exc_info=True)
            session.rollback()
            raise

        if filtered_count > 0:
            logger.info(f"🔽 Отфильтровано {filtered_count} стейкингов по min_apr={min_apr}%")
        logger.info(f"✅ Проверено {len(stakings)} стейкингов, найдено {len(new_stakings)} новых (соответствующих фильтру)")
        return new_stakings