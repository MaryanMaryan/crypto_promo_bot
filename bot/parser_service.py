# bot/parser_service.py
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from data.database import get_db, get_db_session, PromoHistory, ApiLink
from parsers.universal_fallback_parser import UniversalFallbackParser

logger = logging.getLogger(__name__)

class ParserService:
    """Сервис для управления парсерами с улучшенной обработкой ошибок"""

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

            with get_db_session() as db:
                link = db.query(ApiLink).filter(ApiLink.id == link_id).first()
                if link:
                    api_url = link.get_primary_api_url()
                    html_url = link.get_primary_html_url()
                    parsing_type = link.parsing_type or 'combined'

            logger.info(f"📡 API URL: {api_url or 'Не указан'}")
            logger.info(f"🌐 HTML URL (fallback): {html_url or 'Не указан'}")
            logger.info(f"🎯 Тип парсинга: {parsing_type}")

            # Создаем парсер с одиночными URL и типом парсинга
            logger.debug(f"🔧 Создание UniversalFallbackParser")
            parser = UniversalFallbackParser(url, api_url=api_url, html_url=html_url, parsing_type=parsing_type)

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
        """Фильтрует только новые промоакции"""
        try:
            logger.debug(f"🔍 Начало фильтрации промоакций для ссылки {link_id}")

            # Статистика фильтрации
            stats = {
                'total': len(promotions),
                'existing': 0,
                'new': 0,
                'invalid': 0,
                'fallback_rejected': 0
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
                        logger.debug(f"   ⏭️ Пропускаем существующую промоакцию: {promo.get('title', 'Без названия')} ({promo_id})")
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

                return new_promos

        except Exception as e:
            logger.error(f"❌ Ошибка фильтрации промоакций: {e}", exc_info=True)
            return []  # В случае ошибки возвращаем пустой список
    
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
                            icon=promo.get('icon', '')
                        )
                        db.add(history_item)
                        saved_count += 1

                    except Exception as e:
                        logger.error(f"❌ Ошибка сохранения промоакции {promo.get('title')}: {e}")
                        continue

                # Явный commit для уверенности
                db.commit()
                logger.info(f"💾 Успешно сохранено {saved_count} промоакций")

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