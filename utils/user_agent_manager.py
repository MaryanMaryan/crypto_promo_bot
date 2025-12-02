# utils/user_agent_manager.py
import logging
import random
from datetime import datetime
from data.database import get_db_session
from data.models import UserAgent

logger = logging.getLogger(__name__)

class UserAgentManager:
    def __init__(self):
        self.user_agents = []
        self._load_user_agents()
    
    def _load_user_agents(self):
        """Загрузка User-Agent из базы данных"""
        try:
            with get_db_session() as db:
                self.user_agents = db.query(UserAgent).filter(
                    UserAgent.status == "active"
                ).all()
            # Если нет user agents, генерируем начальные
            if not self.user_agents:
                self._generate_initial_user_agents()
                # Повторно загружаем
                with get_db_session() as db:
                    self.user_agents = db.query(UserAgent).filter(
                        UserAgent.status == "active"
                    ).all()
            logger.info(f"✅ Загружено {len(self.user_agents)} User-Agent")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки User-Agent: {e}")
            self.user_agents = []
    
    def get_optimal_user_agent(self, exchange: str = None):
        """Получить оптимальный User-Agent для биржи (пока случайный)"""
        try:
            with get_db_session() as db:
                user_agents = db.query(UserAgent).filter(UserAgent.status == "active").all()

                if user_agents:
                    # Выбираем случайный User-Agent
                    selected = random.choice(user_agents)

                    # Создаем новый объект UserAgent (детачированный) с данными из выбранного
                    return UserAgent(
                        id=selected.id,
                        user_agent_string=selected.user_agent_string,
                        browser_type=selected.browser_type,
                        browser_version=selected.browser_version,
                        platform=selected.platform,
                        device_type=selected.device_type,
                        status=selected.status,
                        success_rate=selected.success_rate,
                        usage_count=selected.usage_count,
                        last_used=selected.last_used
                    )
                else:
                    # Если нет активных, возвращаем заглушку
                    return UserAgent(
                        user_agent_string="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        browser_type="chrome",
                        browser_version="91.0",
                        platform="windows",
                        device_type="desktop"
                    )
        except Exception as e:
            logger.error(f"Ошибка получения User-Agent: {e}")
            # Возвращаем заглушку в случае ошибки
            return UserAgent(
                user_agent_string="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                browser_type="chrome",
                browser_version="91.0",
                platform="windows",
                device_type="desktop"
            )
    
    def get_all_user_agents(self):
        """Получить все User-Agent"""
        try:
            with get_db_session() as db:
                # Загружаем все User-Agent из БД в активной сессии
                user_agents = db.query(UserAgent).all()

                # Преобразуем в список словарей, чтобы избежать проблем с detached объектами
                result = []
                for ua in user_agents:
                    result.append({
                        'id': ua.id,
                        'user_agent_string': ua.user_agent_string,
                        'browser_type': ua.browser_type,
                        'browser_version': ua.browser_version,
                        'platform': ua.platform,
                        'device_type': ua.device_type,
                        'status': ua.status,
                        'success_rate': ua.success_rate if ua.success_rate is not None else 0.0,
                        'usage_count': ua.usage_count if ua.usage_count is not None else 0,
                        'last_used': ua.last_used
                    })
                return result
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка User-Agent: {e}")
            return []
    
    def get_user_agent_stats(self):
        """Получить статистику User-Agent"""
        try:
            with get_db_session() as db:
                all_user_agents = db.query(UserAgent).all()
                active_count = len([ua for ua in all_user_agents if ua.status == 'active'])
                inactive_count = len([ua for ua in all_user_agents if ua.status == 'inactive'])

                # Вычисляем реальную среднюю успешность и использование
                success_rates = [ua.success_rate for ua in all_user_agents if ua.success_rate is not None]
                usage_counts = [ua.usage_count for ua in all_user_agents if ua.usage_count is not None]

                avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0.0
                avg_usage_count = sum(usage_counts) / len(usage_counts) if usage_counts else 0.0

                return {
                    'total': len(all_user_agents),
                    'active': active_count,
                    'inactive': inactive_count,
                    'avg_success_rate': avg_success_rate,
                    'avg_usage_count': avg_usage_count
                }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики User-Agent: {e}")
            return {
                'total': 0,
                'active': 0,
                'inactive': 0,
                'avg_success_rate': 0.0,
                'avg_usage_count': 0.0
            }
    
    def add_user_agent(self, user_agent_string, browser_type, browser_version, platform, device_type):
        """Добавить новый User-Agent"""
        try:
            with get_db_session() as db:
                # Проверяем, не существует ли уже такой User-Agent
                existing = db.query(UserAgent).filter(
                    UserAgent.user_agent_string == user_agent_string
                ).first()
                
                if existing:
                    logger.warning(f"User-Agent уже существует: {user_agent_string}")
                    return False
                
                new_ua = UserAgent(
                    user_agent_string=user_agent_string,
                    browser_type=browser_type,
                    browser_version=browser_version,
                    platform=platform,
                    device_type=device_type,
                    status="active"
                )
                db.add(new_ua)
                db.commit()
            
            self._load_user_agents()  # Перезагружаем список
            logger.info(f"✅ Добавлен новый User-Agent: {browser_type} {browser_version}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления User-Agent: {e}")
            return False
    
    def get_user_agents_to_generate(self):
        """Возвращает список User-Agent для генерации (без добавления в БД)"""
        return [
            ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
             "chrome", "91.0", "windows", "desktop"),
            ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
             "firefox", "89.0", "windows", "desktop"),
            ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
             "chrome", "91.0", "macos", "desktop"),
            ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
             "chrome", "92.0", "linux", "desktop"),
            ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15",
             "safari", "14.1", "macos", "desktop"),
        ]

    def _generate_initial_user_agents(self):
        """Генерация начальных User-Agent и сохранение в БД"""
        initial_user_agents = self.get_user_agents_to_generate()
        for ua_string, browser_type, browser_version, platform, device_type in initial_user_agents:
            self.add_user_agent(ua_string, browser_type, browser_version, platform, device_type)

    def update_success_rate(self, user_agent_id: int, success: bool):
        """Обновление успешности User-Agent после запроса

        Args:
            user_agent_id: ID User-Agent в БД
            success: True если запрос успешен, False если неудача
        """
        try:
            with get_db_session() as db:
                ua = db.query(UserAgent).filter(UserAgent.id == user_agent_id).first()

                if not ua:
                    logger.warning(f"User-Agent с ID {user_agent_id} не найден")
                    return

                # Увеличиваем счетчик использования
                ua.usage_count = (ua.usage_count or 0) + 1

                # Обновляем success_rate с экспоненциальным скользящим средним (EMA)
                # EMA дает больший вес последним запросам
                alpha = 0.1  # Коэффициент сглаживания (чем больше - тем больше вес новых данных)
                new_value = 1.0 if success else 0.0

                if ua.success_rate is None or ua.success_rate == 0:
                    ua.success_rate = new_value
                else:
                    ua.success_rate = alpha * new_value + (1 - alpha) * ua.success_rate

                # Обновляем время последнего использования
                ua.last_used = datetime.utcnow()

                # Деактивируем User-Agent если успешность слишком низкая
                if ua.usage_count >= 10 and ua.success_rate < 0.2:
                    ua.status = 'inactive'
                    logger.warning(f"User-Agent {user_agent_id} деактивирован (низкая успешность: {ua.success_rate:.2%})")

                db.commit()
                logger.debug(f"Обновлена статистика UA {user_agent_id}: success_rate={ua.success_rate:.2%}, usage_count={ua.usage_count}")

        except Exception as e:
            logger.error(f"Ошибка обновления статистики User-Agent {user_agent_id}: {e}")

# Глобальный экземпляр менеджера
_user_agent_manager = None

def get_user_agent_manager():
    global _user_agent_manager
    if _user_agent_manager is None:
        _user_agent_manager = UserAgentManager()
    return _user_agent_manager