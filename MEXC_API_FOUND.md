# MEXC Airdrop API - Найденная информация

## 🎯 Найденный API Endpoint

### Основной endpoint для списка промоакций
```
https://www.mexc.com/api/operateactivity/eftd/list
```

**Параметры:**
- `startTime` - timestamp в миллисекундах (начало периода)
- `endTime` - timestamp в миллисекундах (конец периода)

**Пример запроса:**
```bash
curl "https://www.mexc.com/api/operateactivity/eftd/list?startTime=1766017685898&endTime=1768609685898"
```

### Endpoint статистики
```
https://www.mexc.com/api/operateactivity/eftd/statistics
```

## 📊 Структура ответа

### Statistics Response
```json
{
  "code": 0,
  "data": {
    "totalRewardQuantity": 47087368.8,
    "newUserRewardAvg": 50.04,
    "projectCnt": 703,
    "totalApplyNum": 823790
  }
}
```

### List Response
```json
{
  "code": 0,
  "data": [
    {
      "id": 3107,
      "activityName": null,
      "activityCurrency": "CYS",
      "activityCurrencyFullName": "Cysic",
      "activityCurrencyId": "bba9a154b9db4224b4f9f401fcea5400",
      "state": "AWARDED",  // AWARDED, ACTIVE, END
      "startTime": 1765447200000,
      "endTime": 1766052000000,
      "onlineTime": 1765447200000,
      "settleDays": 10,
      "applyNum": null,
      "applyFlag": false,
      "label": null,
      "introduction": "",
      "websiteUrl": "https://cysic.xyz/",
      "twitterUrl": "https://x.com/cysic_xyz",
      "learnUrl": null,
      "kycLevel": 1,
      "plateType": "AIRDROP+",
      
      // Награды
      "firstProfitCurrency": "",
      "firstProfitCurrencyQuantity": "0",
      "secondProfitCurrency": "",
      "secondProfitCurrencyQuantity": "0",
      "proxyProfitType": "",
      "proxyProfitQuantity": "0",
      
      // Задания
      "taskVOList": null,
      "mainTaskVOList": null,
      "mainTaskRelation": "NONE",
      
      // Логотипы и контент
      "detailLogoWeb": "F20251210173702590ZJJ8TCfwna2PSA",
      "shareLogo": "F20251210173702590ZJJ8TCfwna2PSA",
      "ruleContent": "",
      "coinIntroduction": null,
      
      // Вложенные активности
      "eftdVOS": [...],
      
      // Пулы наград и билеты
      "rewardPoolVOList": [...],
      "ticketRecordVOList": null,
      "drawRecordVOList": null,
      
      // Флаги
      "eftdUserFlag": false,
      "autoSettleActivityFlag": false,
      "activityHasMutexTag": false,
      "timeLineFlag": false,
      "endTimeDownFlag": false
    }
  ]
}
```

## 🔑 Ключевые поля

### Основная информация
- `id` - уникальный ID активности
- `activityCurrency` - символ монеты (BTC, ETH, CYS и т.д.)
- `activityCurrencyFullName` - полное название монеты
- `state` - статус: `ACTIVE`, `AWARDED`, `END`

### Временные метки
- `startTime` - время начала (timestamp ms)
- `endTime` - время окончания (timestamp ms)
- `onlineTime` - время публикации (timestamp ms)
- `settleDays` - дней на расчёты

### Награды
- `firstProfitCurrency` - основная валюта награды
- `firstProfitCurrencyQuantity` - количество основной награды
- `secondProfitCurrency` - дополнительная валюта награды
- `secondProfitCurrencyQuantity` - количество дополнительной награды
- `proxyProfitType` - тип реферальной награды

### Задания
- `taskVOList` - список заданий
- `mainTaskVOList` - список основных заданий
- `mainTaskRelation` - связь заданий (`NONE`, `AND`, `OR`)

### Внешние ссылки
- `websiteUrl` - официальный сайт проекта
- `twitterUrl` - Twitter проекта
- `learnUrl` - ссылка на обучающие материалы

### Участие
- `applyNum` - количество участников
- `applyFlag` - флаг участия пользователя
- `applyTime` - время подачи заявки
- `kycLevel` - требуемый уровень KYC (0, 1, 2)

### Вложенные структуры

#### eftdVOS
Массив вложенных активностей с той же структурой

#### taskVOList
```json
{
  "id": 4260,
  "activityId": 3108,
  "taskType": "PRE",
  "state": "FINISH",
  "firstProfitCurrency": "USDT",
  "firstProfitCurrencyQuantity": "25000",
  "startTime": 1765447200000,
  "endTime": 1766052000000,
  "completeType": "FINISH_LOTTERY",
  "ruleVOList": null
}
```

#### rewardPoolVOList
```json
{
  "id": 40,
  "currency": "CYS",
  "rewardQuantity": "0",
  "eftdState": "ACTIVE",
  "receiveAmount": "0",
  "drawRecordNum": 0
}
```

## 📝 Статусы активности

- `ACTIVE` - активна, идёт приём заявок
- `AWARDED` - завершена, награды распределены
- `END` - завершена

## 🎫 Типы активностей (plateType)

- `AIRDROP+` - стандартный аирдроп
- Другие типы могут быть добавлены

## 🔍 Дополнительные endpoint'ы

### Загрузка файлов (логотипы)
```
https://www.mexc.com/api/file/download/{fileId}
```

Где `fileId` берётся из полей:
- `detailLogoWeb`
- `detailLogoReact`
- `shareLogo`
- `shareLogoRtl`

## 💡 Использование в парсере

```python
import requests
from datetime import datetime

def get_mexc_airdrops():
    """Получить список аирдропов MEXC"""
    
    # Период: 30 дней назад - 30 дней вперёд
    now = int(datetime.now().timestamp() * 1000)
    start_time = now - (30 * 24 * 60 * 60 * 1000)
    end_time = now + (30 * 24 * 60 * 60 * 1000)
    
    url = 'https://www.mexc.com/api/operateactivity/eftd/list'
    params = {
        'startTime': start_time,
        'endTime': end_time
    }
    
    response = requests.get(url, params=params, timeout=10)
    result = response.json()
    
    if result.get('code') == 0:
        return result.get('data', [])
    
    return []

# Использование
airdrops = get_mexc_airdrops()

for airdrop in airdrops:
    if airdrop.get('state') == 'ACTIVE':
        print(f"Active: {airdrop.get('activityCurrency')} - {airdrop.get('activityCurrencyFullName')}")
        print(f"Website: {airdrop.get('websiteUrl')}")
        print(f"Twitter: {airdrop.get('twitterUrl')}")
```

## ✅ Преимущества найденного API

1. **Официальный API** - используется самим сайтом MEXC
2. **Полные данные** - вся информация о промоакциях
3. **Структурированный JSON** - легко парсить
4. **Без авторизации** - не требуется API ключ
5. **Быстрый ответ** - обычно < 1 секунды
6. **Фильтрация по времени** - можно запрашивать только актуальные

## 📋 Примеры полей для базы данных

**Минимальный набор:**
- exchange = 'MEXC'
- coin = activityCurrency
- title = activityCurrencyFullName
- status = state (ACTIVE/AWARDED/END)
- start_date = startTime
- end_date = endTime
- url = websiteUrl
- details = introduction

**Расширенный набор:**
- twitter_url = twitterUrl
- learn_url = learnUrl
- kyc_level = kycLevel
- participants = applyNum
- reward_currency = firstProfitCurrency
- reward_amount = firstProfitCurrencyQuantity
- tasks_count = len(taskVOList)

## 🚀 Готовый пример

См. файлы:
- `test_mexc_airdrop_api.py` - тестовый скрипт
- `mexc_airdrop_example.json` - пример полного ответа
- `find_mexc_api.py` - скрипт поиска API через Playwright
