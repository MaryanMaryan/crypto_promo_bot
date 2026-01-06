#!/usr/bin/env python3
"""Добавление свежих современных User-Agents"""

from data.database import get_db_session
from data.models import UserAgent
from datetime import datetime

# Современные User-Agents (2025-2026)
FRESH_USER_AGENTS = [
    # Chrome на Windows
    {
        'user_agent_string': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'browser_type': 'Chrome',
        'browser_version': '131.0',
        'platform': 'Windows',
        'device_type': 'Desktop'
    },
    {
        'user_agent_string': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'browser_type': 'Chrome',
        'browser_version': '130.0',
        'platform': 'Windows',
        'device_type': 'Desktop'
    },
    # Chrome на macOS
    {
        'user_agent_string': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'browser_type': 'Chrome',
        'browser_version': '131.0',
        'platform': 'macOS',
        'device_type': 'Desktop'
    },
    # Firefox на Windows
    {
        'user_agent_string': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'browser_type': 'Firefox',
        'browser_version': '133.0',
        'platform': 'Windows',
        'device_type': 'Desktop'
    },
    {
        'user_agent_string': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
        'browser_type': 'Firefox',
        'browser_version': '132.0',
        'platform': 'Windows',
        'device_type': 'Desktop'
    },
    # Firefox на macOS
    {
        'user_agent_string': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0',
        'browser_type': 'Firefox',
        'browser_version': '133.0',
        'platform': 'macOS',
        'device_type': 'Desktop'
    },
    # Safari на macOS
    {
        'user_agent_string': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
        'browser_type': 'Safari',
        'browser_version': '18.0',
        'platform': 'macOS',
        'device_type': 'Desktop'
    },
    # Edge на Windows
    {
        'user_agent_string': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
        'browser_type': 'Edge',
        'browser_version': '131.0',
        'platform': 'Windows',
        'device_type': 'Desktop'
    },
    # Chrome на Linux
    {
        'user_agent_string': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'browser_type': 'Chrome',
        'browser_version': '131.0',
        'platform': 'Linux',
        'device_type': 'Desktop'
    },
    # Chrome на Android
    {
        'user_agent_string': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36',
        'browser_type': 'Chrome',
        'browser_version': '131.0',
        'platform': 'Android',
        'device_type': 'Mobile'
    },
    # Safari на iPhone
    {
        'user_agent_string': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        'browser_type': 'Safari',
        'browser_version': '17.2',
        'platform': 'iOS',
        'device_type': 'Mobile'
    },
    # Chrome на iPad
    {
        'user_agent_string': 'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0.6778.134 Mobile/15E148 Safari/604.1',
        'browser_type': 'Chrome',
        'browser_version': '131.0',
        'platform': 'iOS',
        'device_type': 'Tablet'
    }
]

def main():
    print('\n' + '='*70)
    print('ДОБАВЛЕНИЕ СВЕЖИХ USER-AGENTS')
    print('='*70 + '\n')

    with get_db_session() as db:
        added = 0
        skipped = 0

        for ua_data in FRESH_USER_AGENTS:
            # Проверяем, существует ли уже
            existing = db.query(UserAgent).filter_by(
                user_agent_string=ua_data['user_agent_string']
            ).first()

            if existing:
                skipped += 1
                print(f'[ПРОПУЩЕН] {ua_data["browser_type"]} {ua_data["browser_version"]} - уже существует')
                continue

            # Создаем новый User-Agent
            new_ua = UserAgent(
                user_agent_string=ua_data['user_agent_string'],
                browser_type=ua_data['browser_type'],
                browser_version=ua_data['browser_version'],
                platform=ua_data['platform'],
                device_type=ua_data['device_type'],
                status='active',  # Сразу активный!
                usage_count=0,
                success_rate=0.5,  # Начальное значение 50%
                created_at=datetime.utcnow()
            )

            db.add(new_ua)
            added += 1
            print(f'[ДОБАВЛЕН] {ua_data["browser_type"]} {ua_data["browser_version"]} на {ua_data["platform"]}')

        db.commit()

        print(f'\n' + '='*70)
        print(f'Добавлено: {added}')
        print(f'Пропущено: {skipped}')
        print('='*70 + '\n')

if __name__ == '__main__':
    main()
