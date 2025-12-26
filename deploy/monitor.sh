#!/bin/bash

# ============================================================================
# Скрипт мониторинга Crypto Promo Bot
# ============================================================================

echo "📊 Мониторинг Crypto Promo Bot"
echo "=" * 60
echo ""

# 1. Статус сервиса
echo "🤖 Статус сервиса:"
sudo systemctl status crypto_promo_bot --no-pager | head -10
echo ""

# 2. Использование ресурсов
echo "💻 Использование ресурсов:"
echo "CPU и память процессов Python:"
ps aux | grep python | grep -v grep | awk '{print "  PID: " $2 " | CPU: " $3 "% | MEM: " $4 "% | " $11}'
echo ""

# 3. Использование диска
echo "💾 Использование диска:"
df -h | grep -E "Filesystem|/$"
echo ""
echo "Размер директории проекта:"
du -sh /home/ubuntu/crypto_promo_bot
echo "Размер базы данных:"
du -sh /home/ubuntu/crypto_promo_bot/data/*.db 2>/dev/null || echo "  База данных не найдена"
echo ""

# 4. Последние ошибки в логах
echo "❌ Последние ошибки (за последний час):"
sudo journalctl -u crypto_promo_bot --since "1 hour ago" | grep -i error | tail -5 || echo "  Ошибок не найдено"
echo ""

# 5. Последние 10 строк лога
echo "📝 Последние 10 строк лога:"
sudo journalctl -u crypto_promo_bot -n 10 --no-pager
echo ""

# 6. Uptime бота
echo "⏱️  Uptime бота:"
sudo systemctl show crypto_promo_bot --property=ActiveEnterTimestamp --no-pager
echo ""

# 7. Информация о сети
echo "🌐 Сетевые подключения:"
netstat -tnp 2>/dev/null | grep python || echo "  Нет активных подключений"
echo ""

echo "=" * 60
echo "✅ Мониторинг завершен"
echo ""
echo "💡 Для просмотра логов в реальном времени:"
echo "   sudo journalctl -u crypto_promo_bot -f"
