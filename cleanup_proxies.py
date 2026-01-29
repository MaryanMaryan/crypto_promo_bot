#!/usr/bin/env python3
"""Удаляем нерабочие прокси"""
import sqlite3

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# Удаляем нерабочие прокси (первая группа с a646a28cc9096abf)
cursor.execute("DELETE FROM proxy_servers WHERE address LIKE '%a646a28cc9096abf%'")
deleted = cursor.rowcount
conn.commit()
print(f'Удалено нерабочих прокси: {deleted}')

# Проверяем оставшиеся
cursor.execute('SELECT id, address, status FROM proxy_servers')
remaining = cursor.fetchall()
print(f'Осталось прокси: {len(remaining)}')
for p in remaining:
    print(f'  [{p[0]}] {p[1]} - {p[2]}')
conn.close()
