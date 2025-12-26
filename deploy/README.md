# Deploy Scripts для Oracle Cloud

Эта директория содержит скрипты и файлы для развертывания Crypto Promo Bot на Oracle Cloud Free Tier.

## 📁 Файлы

### `setup.sh`
Автоматическая установка всех зависимостей и настройка окружения.

**Использование:**
```bash
cd /home/ubuntu/crypto_promo_bot
chmod +x deploy/setup.sh
./deploy/setup.sh
```

### `crypto_promo_bot.service`
Systemd service файл для автоматического запуска бота.

**Установка:**
```bash
sudo cp deploy/crypto_promo_bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto_promo_bot
sudo systemctl start crypto_promo_bot
```

### `update.sh`
Скрипт для обновления кода бота из Git репозитория.

**Использование:**
```bash
chmod +x deploy/update.sh
./deploy/update.sh
```

### `backup.sh`
Создание бекапа базы данных.

**Использование:**
```bash
chmod +x deploy/backup.sh
./deploy/backup.sh
```

**Автоматические бекапы (cron):**
```bash
# Бекап каждый день в 3:00 ночи
crontab -e
# Добавьте строку:
0 3 * * * /home/ubuntu/crypto_promo_bot/deploy/backup.sh
```

### `monitor.sh`
Мониторинг состояния бота.

**Использование:**
```bash
chmod +x deploy/monitor.sh
./deploy/monitor.sh
```

## 🚀 Быстрый старт

1. **Склонируйте репозиторий на Oracle Cloud VM:**
   ```bash
   cd /home/ubuntu
   git clone https://github.com/YOUR_USERNAME/crypto_promo_bot.git
   cd crypto_promo_bot
   ```

2. **Запустите автоматическую установку:**
   ```bash
   chmod +x deploy/setup.sh
   ./deploy/setup.sh
   ```

3. **Настройте .env файл:**
   ```bash
   nano .env
   # Добавьте BOT_TOKEN и ADMIN_CHAT_ID
   ```

4. **Запустите бота:**
   ```bash
   sudo systemctl start crypto_promo_bot
   sudo systemctl status crypto_promo_bot
   ```

## 📖 Полная инструкция

Смотрите файл `ORACLE_CLOUD_DEPLOY.md` в корне проекта для полной пошаговой инструкции по развертыванию на Oracle Cloud.

## 🔧 Полезные команды

```bash
# Проверить статус
sudo systemctl status crypto_promo_bot

# Просмотр логов
sudo journalctl -u crypto_promo_bot -f

# Перезапуск
sudo systemctl restart crypto_promo_bot

# Остановка
sudo systemctl stop crypto_promo_bot

# Обновление кода
./deploy/update.sh

# Мониторинг
./deploy/monitor.sh

# Бекап
./deploy/backup.sh
```
