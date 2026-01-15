"""
Диагностика проблемы с парсингом MEXC анонсов
"""
import sys
sys.path.insert(0, '.')

import logging
import requests
from data.database import get_db_session
from data.models import ApiLink, ProxyServer
from parsers.announcement_parser import AnnouncementParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_direct_access(url):
    """Тест прямого доступа без прокси"""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 1: Прямой доступ без прокси")
    logger.info(f"{'='*60}")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }

        logger.info(f"Запрос к {url}...")
        response = requests.get(url, headers=headers, timeout=30)
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Content-Length: {len(response.content)} bytes")

        if response.status_code == 200:
            logger.info("✅ Прямой доступ работает!")
            return True
        else:
            logger.error(f"❌ Код ответа: {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


def test_with_proxy(url, proxy_address, proxy_protocol):
    """Тест доступа через указанный прокси"""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 2: Доступ через прокси")
    logger.info(f"{'='*60}")

    try:
        proxies = {
            'http': f"{proxy_protocol}://{proxy_address}",
            'https': f"{proxy_protocol}://{proxy_address}"
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        logger.info(f"Прокси: {proxy_protocol}://{proxy_address}")
        logger.info(f"Запрос к {url}...")

        response = requests.get(url, headers=headers, proxies=proxies, timeout=30)
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Content-Length: {len(response.content)} bytes")

        if response.status_code == 200:
            logger.info("✅ Прокси работает!")
            return True
        else:
            logger.error(f"❌ Код ответа: {response.status_code}")
            return False

    except requests.exceptions.ProxyError as e:
        logger.error(f"❌ Ошибка прокси: {e}")
        return False
    except requests.exceptions.Timeout:
        logger.error(f"❌ Таймаут прокси")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


def test_announcement_parser(url, keywords):
    """Тест AnnouncementParser"""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 3: AnnouncementParser с fallback режимом")
    logger.info(f"{'='*60}")

    try:
        parser = AnnouncementParser(url)

        logger.info(f"Парсинг с стратегией 'any_keyword'")
        logger.info(f"Ключевые слова: {keywords}")

        result = parser.parse(
            strategy='any_keyword',
            keywords=keywords
        )

        logger.info(f"\nРезультат:")
        logger.info(f"  Changed: {result['changed']}")
        logger.info(f"  Message: {result['message']}")
        logger.info(f"  Matched content: {result['matched_content']}")

        if result['changed']:
            logger.info("✅ AnnouncementParser работает!")
            return True
        else:
            logger.warning("⚠️ Изменения не обнаружены (может быть нормально)")
            return True

    except Exception as e:
        logger.error(f"❌ Ошибка AnnouncementParser: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("ДИАГНОСТИКА MEXC ANNOUNCEMENTS ПАРСИНГА")
    logger.info("="*60)

    # Получаем данные из БД
    with get_db_session() as session:
        # Получаем ссылку MEXC announcements
        link = session.query(ApiLink).filter(ApiLink.id == 14).first()

        if not link:
            logger.error("❌ Ссылка с ID=14 не найдена")
            sys.exit(1)

        logger.info(f"\nИнформация о ссылке:")
        logger.info(f"  ID: {link.id}")
        logger.info(f"  Name: {link.name}")
        logger.info(f"  URL: {link.url}")
        logger.info(f"  Strategy: {link.announcement_strategy}")

        # Получаем ключевые слова
        keywords = link.get_announcement_keywords()
        logger.info(f"  Keywords: {keywords}")

        url = link.url

        # Получаем активный прокси
        proxy_obj = session.query(ProxyServer).filter(ProxyServer.status == 'active').first()
        if proxy_obj:
            # Сохраняем данные прокси в переменные перед выходом из сессии
            proxy_address = proxy_obj.address
            proxy_protocol = proxy_obj.protocol
            logger.info(f"\nАктивный прокси найден:")
            logger.info(f"  Address: {proxy_address}")
            logger.info(f"  Protocol: {proxy_protocol}")
            proxy = {'address': proxy_address, 'protocol': proxy_protocol}
        else:
            proxy = None

    # Тест 1: Прямой доступ
    test_direct_access(url)

    # Тест 2: Доступ через прокси (если есть)
    if proxy:
        test_with_proxy(url, proxy['address'], proxy['protocol'])

    # Тест 3: AnnouncementParser (будет использовать fallback если прокси не работают)
    if keywords:
        test_announcement_parser(url, keywords)
    else:
        logger.warning("⚠️ Ключевые слова не указаны, пропускаем тест парсера")

    logger.info(f"\n{'='*60}")
    logger.info("ДИАГНОСТИКА ЗАВЕРШЕНА")
    logger.info(f"{'='*60}\n")
