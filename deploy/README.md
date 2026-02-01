# Deploy Scripts для VPS серверов

Эта директория содержит скрипты и файлы для развертывания Crypto Promo Bot на VPS серверах.

## 🖥️ Текущий Production сервер

- **Провайдер:** Vultr High Frequency
- **IP:** `70.34.246.30`
- **Локация:** Warsaw, Poland
- **Тариф:** vhf-2c-4gb ($24/месяц)
- **Ресурсы:** 4GB RAM, 2 vCPU, 128GB NVMe SSD
- **Путь проекта:** `/opt/crypto_promo_bot`

## 🚀 Быстрый деплой (основной способ)

**Мы используем прямое копирование файлов через SCP** (без git на сервере).

### Деплой одного/нескольких файлов:
```powershell
# Windows PowerShell - копируем изменённые файлы:
scp "bot\notification_service.py" root@70.34.246.30:/opt/crypto_promo_bot/bot/
scp "parsers\staking_parser.py" root@70.34.246.30:/opt/crypto_promo_bot/parsers/

# Перезапускаем бота:
ssh root@70.34.246.30 "sudo systemctl restart crypto_promo_bot"

# Проверяем статус:
ssh root@70.34.246.30 "sudo systemctl status crypto_promo_bot --no-pager"
```

### Деплой всего проекта:
```powershell
# Копируем всю папку (исключая venv, __pycache__, .git):
scp -r bot parsers services utils data config root@70.34.246.30:/opt/crypto_promo_bot/
scp main.py config.py requirements.txt root@70.34.246.30:/opt/crypto_promo_bot/

# Перезапуск
ssh root@70.34.246.30 "sudo systemctl restart crypto_promo_bot"
```

### Однострочный деплой с проверкой:
```powershell
scp "bot\notification_service.py" root@70.34.246.30:/opt/crypto_promo_bot/bot/ ; ssh root@70.34.246.30 "sudo systemctl restart crypto_promo_bot && sleep 2 && sudo systemctl status crypto_promo_bot --no-pager"
```

## 📁 Файлы

### `setup.sh`
Автоматическая установка всех зависимостей и настройка окружения.

**Использование:**
```bash
cd /opt/crypto_promo_bot
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
Скрипт для обновления кода бота.

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
0 3 * * * /opt/crypto_promo_bot/deploy/backup.sh
```

### `monitor.sh`
Мониторинг состояния бота.

**Использование:**
```bash
chmod +x deploy/monitor.sh
./deploy/monitor.sh
```

## 🚀 Быстрый деплой на новый сервер

### 1. Подготовка сервера (Ubuntu 22.04/24.04)
```bash
apt update && apt install -y python3-pip python3-venv git
```

### 2. Загрузка проекта
```bash
mkdir -p /opt/crypto_promo_bot
cd /opt/crypto_promo_bot
# Вариант A: через scp с локальной машины
# scp -r /path/to/project/* root@SERVER_IP:/opt/crypto_promo_bot/

# Вариант B: через архив
# На локальной машине создать архив без venv:
# tar -czvf bot.tar.gz --exclude="venv" --exclude="__pycache__" --exclude=".git" .
# scp bot.tar.gz root@SERVER_IP:/opt/
# На сервере:
# tar -xzf /opt/bot.tar.gz -C /opt/crypto_promo_bot/
```

### 3. Установка зависимостей
```bash
cd /opt/crypto_promo_bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### 4. Конфигурация
```bash
# Создать .env файл
cat > .env << 'EOF'
BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=your_chat_id
DATABASE_URL=sqlite:///data/database.db
TELEGRAM_PARSER_ENABLED=true
BROWSER_POOL_SIZE=4
EXECUTOR_MAX_WORKERS=6
EOF
```

### 5. Установка сервиса
```bash
cp deploy/crypto_promo_bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable crypto_promo_bot
systemctl start crypto_promo_bot
```

### 6. Проверка
```bash
systemctl status crypto_promo_bot
journalctl -u crypto_promo_bot -f
```

## 🔧 Полезные команды

```bash
# Проверить статус
sudo systemctl status crypto_promo_bot

# Просмотр логов в реальном времени
sudo journalctl -u crypto_promo_bot -f

# Последние 100 строк логов
sudo journalctl -u crypto_promo_bot -n 100 --no-pager

# Логи за последний час
sudo journalctl -u crypto_promo_bot --since "1 hour ago"

# Перезапуск бота
sudo systemctl restart crypto_promo_bot

# Остановка бота
sudo systemctl stop crypto_promo_bot

# Проверка ресурсов
htop
free -h
df -h
```

## 🔄 Обновление кода

### Способ 1: SCP отдельных файлов (рекомендуется)
```powershell
# С Windows PowerShell:
scp "bot\handlers.py" root@70.34.246.30:/opt/crypto_promo_bot/bot/
scp "parsers\universal_parser.py" root@70.34.246.30:/opt/crypto_promo_bot/parsers/
ssh root@70.34.246.30 "sudo systemctl restart crypto_promo_bot"
```

### Способ 2: Полная синхронизация через архив
```bash
# На локальной машине:
cd /path/to/crypto_promo_bot
tar -czvf ../bot.tar.gz --exclude="venv" --exclude="__pycache__" --exclude=".git" --exclude="*.pyc" .
scp ../bot.tar.gz root@70.34.246.30:/opt/

# На сервере:
ssh root@70.34.246.30 "cd /opt/crypto_promo_bot && tar -xzf ../bot.tar.gz && systemctl restart crypto_promo_bot"
```

## 📊 Рекомендуемые настройки по RAM

| RAM | BROWSER_POOL_SIZE | EXECUTOR_MAX_WORKERS |
|-----|-------------------|---------------------|
| 2GB | 2 | 4 |
| 4GB | 4 | 6 |
| 8GB | 6 | 8 |

## 💰 Рекомендуемые провайдеры

| Провайдер | Тариф | RAM | Цена | Примечание |
|-----------|-------|-----|------|------------|
| **Vultr HF** | vhf-2c-4gb | 4GB | $24/мес | Рекомендуется, NVMe SSD |
| Hetzner | CX31 | 8GB | €9/мес | Дешевле, но требует KYC |
| DigitalOcean | Basic | 2GB | $18/мес | Может не хватать RAM |
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
