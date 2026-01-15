"""
Включение WAL режима для всех сессионных файлов Telegram
"""
import sqlite3
import os
import glob

def enable_wal_for_sessions():
    """Включить WAL режим для всех .session файлов"""
    
    # Ищем все .session файлы в директории sessions/
    session_files = glob.glob('sessions/*.session')
    
    if not session_files:
        print("⚠️  Не найдено сессионных файлов в директории sessions/")
        return
    
    print(f"🔍 Найдено {len(session_files)} сессионных файлов")
    print("=" * 60)
    
    success_count = 0
    
    for session_file in session_files:
        filename = os.path.basename(session_file)
        try:
            # Проверяем текущий режим
            conn = sqlite3.connect(session_file, timeout=60.0)
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode')
            old_mode = cursor.fetchone()[0]
            
            # Включаем WAL
            cursor.execute('PRAGMA journal_mode=WAL')
            new_mode = cursor.fetchone()[0]
            
            # Устанавливаем timeout
            cursor.execute('PRAGMA busy_timeout=60000')
            
            conn.commit()
            conn.close()
            
            if old_mode.upper() == 'WAL':
                print(f"✅ {filename} - уже в WAL режиме")
            else:
                print(f"✅ {filename} - переведён из {old_mode} → {new_mode}")
            
            success_count += 1
            
        except Exception as e:
            print(f"❌ {filename} - ошибка: {e}")
    
    print("=" * 60)
    print(f"✅ Обработано {success_count} из {len(session_files)} файлов")
    print("\n💡 Теперь сессионные файлы будут лучше работать при конкурентном доступе")

if __name__ == '__main__':
    enable_wal_for_sessions()
