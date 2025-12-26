# Деплой Crypto Promo Bot на Oracle Cloud Free Tier

Полная пошаговая инструкция по развертыванию бота на бесплатном сервере Oracle Cloud.

---

## 📋 Содержание

1. [Регистрация в Oracle Cloud](#1-регистрация-в-oracle-cloud)
2. [Создание VM Instance](#2-создание-vm-instance)
3. [Настройка SSH доступа](#3-настройка-ssh-доступа)
4. [Загрузка кода бота](#4-загрузка-кода-бота)
5. [Установка зависимостей](#5-установка-зависимостей)
6. [Настройка бота](#6-настройка-бота)
7. [Запуск бота](#7-запуск-бота)
8. [Управление ботом](#8-управление-ботом)
9. [Решение проблем](#9-решение-проблем)

---

## 1. Регистрация в Oracle Cloud

### Шаг 1.1: Создание аккаунта

1. Перейдите на сайт: https://www.oracle.com/cloud/free/
2. Нажмите **"Start for free"**
3. Заполните форму регистрации:
   - Email
   - Страна
   - Имя и фамилия
4. Подтвердите email
5. Заполните дополнительную информацию:
   - Адрес
   - Номер телефона
   - **Кредитная карта** (деньги НЕ списываются, только верификация)

⚠️ **Важно**: Oracle требует верификацию картой, но это **бесплатный аккаунт навсегда** (Always Free)

### Шаг 1.2: Выбор региона

1. Выберите регион (Home Region) - **это нельзя будет изменить!**
2. Рекомендуемые регионы для СНГ:
   - **Frankfurt, Germany** (eu-frankfurt-1)
   - **Amsterdam, Netherlands** (eu-amsterdam-1)
   - **London, UK** (uk-london-1)

---

## 2. Создание VM Instance

### Шаг 2.1: Переход к созданию Instance

1. Войдите в Oracle Cloud Console: https://cloud.oracle.com/
2. В меню слева выберите **Compute → Instances**
3. Нажмите **"Create Instance"**

### Шаг 2.2: Настройка Instance

#### Основные параметры:

**Name**: `crypto-promo-bot`

**Compartment**: оставьте по умолчанию (root)

#### Image and Shape:

**Image**:
- Нажмите **"Edit"**
- Выберите **Ubuntu 22.04** или **Ubuntu 24.04**
- Нажмите **"Select Image"**

**Shape**:
- Нажмите **"Change Shape"**
- Выберите **Ampere (ARM-based processor)**
- Выберите **VM.Standard.A1.Flex**:
  - **OCPUs**: 2 (можно до 4 бесплатно)
  - **Memory**: 12 GB (можно до 24 GB бесплатно)
- Нажмите **"Select Shape"**

💡 **Совет**: ARM процессоры более эффективны для Always Free tier!

#### Networking:

**Virtual cloud network**: создайте новую или используйте существующую
**Subnet**: Public Subnet
**Public IP**: **Assign a public IPv4 address** ✅

#### SSH Keys:

**ВАЖНО!** Вам нужен SSH ключ для доступа к серверу:

**Вариант A: Генерация в Oracle Cloud**
- Выберите **"Generate a key pair for me"**
- Нажмите **"Save Private Key"** - сохраните файл `ssh-key.key`
- Нажмите **"Save Public Key"** - сохраните файл `ssh-key.pub`

**Вариант B: Использование своего ключа**
- Если у вас уже есть SSH ключ, выберите **"Upload public key files"**
- Загрузите ваш `.pub` файл

#### Boot Volume:

Оставьте по умолчанию (50 GB)

### Шаг 2.3: Создание Instance

1. Нажмите **"Create"**
2. Подождите 1-2 минуты пока Instance создастся
3. Статус изменится с **"PROVISIONING"** на **"RUNNING"** (зеленый)

### Шаг 2.4: Запись Public IP

1. Откройте созданный Instance
2. Скопируйте **Public IP address** (например: `132.145.x.x`)
3. Сохраните этот IP - он понадобится для SSH подключения

---

## 3. Настройка SSH доступа

### Шаг 3.1: Настройка Security List (Firewall)

Oracle Cloud по умолчанию блокирует почти все порты. Нужно открыть необходимые:

1. В меню Instance найдите **"Primary VNIC"**
2. Кликните на **Subnet**
3. Кликните на **Security List** (например: "Default Security List")
4. Нажмите **"Add Ingress Rules"**

Добавьте правила:

**Правило 1: SSH (уже должно быть)**
- Source CIDR: `0.0.0.0/0`
- Destination Port Range: `22`
- Description: `SSH access`

**Правило 2: ICMP (опционально, для ping)**
- Source CIDR: `0.0.0.0/0`
- Protocol: `ICMP`
- Description: `ICMP ping`

### Шаг 3.2: Подключение по SSH

#### Windows (PowerShell):

```powershell
# Переместите ключ в безопасное место
mkdir C:\Users\ВашеИмя\.ssh
move Downloads\ssh-key.key C:\Users\ВашеИмя\.ssh\

# Подключение
ssh -i C:\Users\ВашеИмя\.ssh\ssh-key.key ubuntu@132.145.x.x
```

#### Windows (PuTTY):

1. Скачайте PuTTY: https://www.putty.org/
2. Конвертируйте ключ в формат .ppk через PuTTYgen
3. В PuTTY укажите:
   - Host: `ubuntu@132.145.x.x`
   - Connection → SSH → Auth: укажите путь к .ppk файлу

#### Linux / macOS:

```bash
# Устанавливаем правильные права на ключ
chmod 400 ~/Downloads/ssh-key.key

# Подключение
ssh -i ~/Downloads/ssh-key.key ubuntu@132.145.x.x
```

При первом подключении появится вопрос:
```
Are you sure you want to continue connecting (yes/no)?
```
Введите: `yes`

---

## 4. Загрузка кода бота

### Вариант A: Через Git (рекомендуется)

1. **Создайте приватный репозиторий на GitHub**
2. **Запушьте код бота в репозиторий:**

```bash
# На вашем компьютере (Windows)
cd "C:\Users\Мар'ян\Desktop\Обход защиты парсер.beta\crypto_promo_bot"

# Инициализируйте репозиторий (если еще не сделано)
git init
git add .
git commit -m "Initial commit for Oracle Cloud deployment"

# Добавьте remote и запушьте
git remote add origin https://github.com/ВАШ_USERNAME/crypto_promo_bot.git
git branch -M main
git push -u origin main
```

3. **Склонируйте на сервер Oracle Cloud:**

```bash
# На сервере Oracle Cloud
cd /home/ubuntu
git clone https://github.com/ВАШ_USERNAME/crypto_promo_bot.git

# Если репозиторий приватный, используйте Personal Access Token:
# GitHub → Settings → Developer settings → Personal access tokens → Generate new token
git clone https://ВАШ_TOKEN@github.com/ВАШ_USERNAME/crypto_promo_bot.git
```

### Вариант B: Через SCP (прямая загрузка)

#### Windows (PowerShell):

```powershell
# Перейдите в директорию проекта
cd "C:\Users\Мар'ян\Desktop\Обход защиты парсер.beta"

# Создайте ZIP архив (используя 7-Zip или Windows встроенный архиватор)
Compress-Archive -Path crypto_promo_bot -DestinationPath crypto_promo_bot.zip

# Загрузите на сервер
scp -i C:\Users\ВашеИмя\.ssh\ssh-key.key crypto_promo_bot.zip ubuntu@132.145.x.x:/home/ubuntu/

# Подключитесь к серверу и распакуйте
ssh -i C:\Users\ВашеИмя\.ssh\ssh-key.key ubuntu@132.145.x.x
cd /home/ubuntu
unzip crypto_promo_bot.zip
```

#### Linux / macOS:

```bash
# Создайте архив
cd ~/Desktop
tar -czf crypto_promo_bot.tar.gz crypto_promo_bot/

# Загрузите на сервер
scp -i ~/Downloads/ssh-key.key crypto_promo_bot.tar.gz ubuntu@132.145.x.x:/home/ubuntu/

# Подключитесь к серверу и распакуйте
ssh -i ~/Downloads/ssh-key.key ubuntu@132.145.x.x
cd /home/ubuntu
tar -xzf crypto_promo_bot.tar.gz
```

---

## 5. Установка зависимостей

### Шаг 5.1: Автоматическая установка (рекомендуется)

```bash
# Перейдите в директорию проекта
cd /home/ubuntu/crypto_promo_bot

# Сделайте скрипт исполняемым
chmod +x deploy/setup.sh

# Запустите скрипт установки
./deploy/setup.sh
```

Скрипт автоматически:
- Обновит систему
- Установит Python, pip, venv
- Установит все зависимости из requirements.txt
- Установит Playwright и браузеры
- Создаст .env файл из примера
- Настроит systemd service

### Шаг 5.2: Ручная установка (альтернатива)

Если автоматический скрипт не сработал, выполните вручную:

```bash
# 1. Обновление системы
sudo apt update && sudo apt upgrade -y

# 2. Установка Python и зависимостей
sudo apt install -y python3 python3-pip python3-venv git sqlite3 chromium-browser

# 3. Создание виртуального окружения
cd /home/ubuntu/crypto_promo_bot
python3 -m venv venv

# 4. Активация venv и установка пакетов
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Установка браузеров Playwright
playwright install chromium
playwright install-deps chromium

# 6. Создание директорий
mkdir -p data logs
```

---

## 6. Настройка бота

### Шаг 6.1: Настройка .env файла

```bash
# Откройте .env файл
nano /home/ubuntu/crypto_promo_bot/.env
```

Заполните следующие параметры:

```bash
# Telegram Bot Configuration
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz  # Токен от @BotFather
ADMIN_CHAT_ID=123456789  # Ваш Telegram ID (узнать через @userinfobot)

# Database Configuration
DATABASE_URL=sqlite:///data/database.db

# Parsing Configuration
DEFAULT_CHECK_INTERVAL=300
MAX_CHECK_INTERVAL=86400
MIN_CHECK_INTERVAL=60

# Price Fetcher Configuration (опционально)
COINMARKETCAP_API_KEY=your_api_key_here  # Или оставьте пустым

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

**Как получить BOT_TOKEN:**
1. Откройте Telegram
2. Найдите бота @BotFather
3. Отправьте `/newbot`
4. Следуйте инструкциям
5. Скопируйте токен

**Как получить ADMIN_CHAT_ID:**
1. Найдите бота @userinfobot в Telegram
2. Отправьте `/start`
3. Скопируйте ваш ID

Сохраните файл: `Ctrl + X`, затем `Y`, затем `Enter`

### Шаг 6.2: Проверка настроек

```bash
# Проверьте, что .env файл корректен
cat .env

# Проверьте структуру проекта
ls -la
```

---

## 7. Запуск бота

### Шаг 7.1: Тестовый запуск

Сначала запустите бота вручную, чтобы убедиться, что всё работает:

```bash
cd /home/ubuntu/crypto_promo_bot
source venv/bin/activate
python main.py
```

Вы должны увидеть:
```
INFO - 🤖 Crypto Promo Bot запускается...
INFO - ⏰ Автоматическая проверка активирована
INFO - ✅ Бот инициализирован и готов к запуску
```

Проверьте бота в Telegram - отправьте `/start`

Если всё работает, остановите бота: `Ctrl + C`

### Шаг 7.2: Настройка автозапуска через systemd

```bash
# Установите systemd service
sudo cp deploy/crypto_promo_bot.service /etc/systemd/system/
sudo systemctl daemon-reload

# Включите автозапуск при перезагрузке
sudo systemctl enable crypto_promo_bot

# Запустите бота
sudo systemctl start crypto_promo_bot

# Проверьте статус
sudo systemctl status crypto_promo_bot
```

Вы должны увидеть:
```
● crypto_promo_bot.service - Crypto Promo Bot
   Loaded: loaded (/etc/systemd/system/crypto_promo_bot.service; enabled)
   Active: active (running) since ...
```

---

## 8. Управление ботом

### Основные команды:

```bash
# Проверить статус бота
sudo systemctl status crypto_promo_bot

# Остановить бота
sudo systemctl stop crypto_promo_bot

# Запустить бота
sudo systemctl start crypto_promo_bot

# Перезапустить бота
sudo systemctl restart crypto_promo_bot

# Просмотр логов в реальном времени
sudo journalctl -u crypto_promo_bot -f

# Просмотр последних 100 строк логов
sudo journalctl -u crypto_promo_bot -n 100

# Просмотр логов за сегодня
sudo journalctl -u crypto_promo_bot --since today

# Очистка логов (если занимают много места)
sudo journalctl --vacuum-time=7d  # Удалить логи старше 7 дней
```

### Обновление кода бота:

```bash
# Через Git
cd /home/ubuntu/crypto_promo_bot
git pull

# Обновление зависимостей (если изменились)
source venv/bin/activate
pip install -r requirements.txt

# Перезапуск бота
sudo systemctl restart crypto_promo_bot
```

---

## 9. Решение проблем

### Проблема: Бот не запускается

**Решение:**
```bash
# Проверьте логи
sudo journalctl -u crypto_promo_bot -n 50

# Проверьте .env файл
cat .env

# Проверьте права на файлы
ls -la /home/ubuntu/crypto_promo_bot

# Переустановите зависимости
cd /home/ubuntu/crypto_promo_bot
source venv/bin/activate
pip install --force-reinstall -r requirements.txt
```

### Проблема: "Playwright not found"

**Решение:**
```bash
source /home/ubuntu/crypto_promo_bot/venv/bin/activate
playwright install chromium
playwright install-deps chromium
sudo systemctl restart crypto_promo_bot
```

### Проблема: "Database locked"

**Решение:**
```bash
# Остановите бота
sudo systemctl stop crypto_promo_bot

# Проверьте процессы, использующие базу
lsof /home/ubuntu/crypto_promo_bot/data/database.db

# Убейте зависшие процессы
killall python3

# Запустите снова
sudo systemctl start crypto_promo_bot
```

### Проблема: Нет места на диске

**Решение:**
```bash
# Проверьте использование диска
df -h

# Очистите логи
sudo journalctl --vacuum-time=3d

# Удалите старые бекапы/временные файлы
cd /home/ubuntu/crypto_promo_bot
rm -rf backups/*
```

### Проблема: Высокая нагрузка на CPU/память

**Решение:**
```bash
# Проверьте использование ресурсов
htop  # или top

# Проверьте логи на ошибки
sudo journalctl -u crypto_promo_bot -n 100

# Уменьшите частоту проверок в .env
nano .env
# Увеличьте DEFAULT_CHECK_INTERVAL до 600 (10 минут)

# Перезапустите
sudo systemctl restart crypto_promo_bot
```

---

## 📊 Мониторинг и обслуживание

### Рекомендации:

1. **Проверяйте логи раз в неделю:**
   ```bash
   sudo journalctl -u crypto_promo_bot --since "1 week ago" | grep ERROR
   ```

2. **Следите за использованием диска:**
   ```bash
   df -h
   du -sh /home/ubuntu/crypto_promo_bot/*
   ```

3. **Обновляйте систему раз в месяц:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo systemctl restart crypto_promo_bot
   ```

4. **Делайте бекапы базы данных:**
   ```bash
   cp /home/ubuntu/crypto_promo_bot/data/database.db \
      /home/ubuntu/backup_$(date +%Y%m%d).db
   ```

---

## 🎉 Готово!

Ваш бот теперь работает 24/7 на бесплатном сервере Oracle Cloud!

Если возникли вопросы или проблемы - проверьте логи:
```bash
sudo journalctl -u crypto_promo_bot -f
```

**Полезные ссылки:**
- Oracle Cloud Console: https://cloud.oracle.com/
- Oracle Cloud Docs: https://docs.oracle.com/en-us/iaas/
- Telegram Bot API: https://core.telegram.org/bots/api
