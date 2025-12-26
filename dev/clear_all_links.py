#!/usr/bin/env python3
"""
Скрипт для удаления всех ссылок из базы данных
"""
from data.database import get_db_session
from data.models import ApiLink
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(message)s')

def clear_all_links(auto_confirm=False):
    """Удаляет все ссылки из базы данных"""
    try:
        with get_db_session() as session:
            # Получаем количество ссылок
            count = session.query(ApiLink).count()

            if count == 0:
                logging.info("📭 База данных уже пустая - нет ссылок для удаления")
                return

            # Запрашиваем подтверждение
            logging.info(f"\n⚠️  В базе данных найдено {count} ссылок")

            if not auto_confirm:
                logging.info("🗑️  Вы уверены, что хотите удалить ВСЕ ссылки?")
                try:
                    confirmation = input("Введите 'yes' для подтверждения: ").strip().lower()
                    if confirmation != 'yes':
                        logging.info("❌ Удаление отменено")
                        return
                except (EOFError, KeyboardInterrupt):
                    logging.info("\n❌ Удаление отменено")
                    return
            else:
                logging.info("🗑️  Автоматическое подтверждение (флаг --yes)")

            # Удаляем все ссылки
            session.query(ApiLink).delete()
            session.commit()

            logging.info(f"✅ Успешно удалено {count} ссылок из базы данных")
            logging.info("📝 Теперь вы можете добавить ссылки заново через бота")

    except Exception as e:
        logging.error(f"❌ Ошибка при удалении ссылок: {e}")
        raise

if __name__ == "__main__":
    logging.info("="*50)
    logging.info("🗑️  УДАЛЕНИЕ ВСЕХ ССЫЛОК ИЗ БАЗЫ ДАННЫХ")
    logging.info("="*50)

    # Проверяем флаг --yes
    auto_confirm = "--yes" in sys.argv or "-y" in sys.argv
    clear_all_links(auto_confirm=auto_confirm)
