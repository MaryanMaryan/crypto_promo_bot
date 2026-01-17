# 🚀 Быстрая интеграция MEXC Airdrops в бот

## 📌 API URL для добавления в бот

### Основной endpoint промоакций:
```
https://www.mexc.com/api/operateactivity/eftd/list
```

**Параметры:**
- `startTime` - timestamp начала периода в миллисекундах
- `endTime` - timestamp конца периода в миллисекундах

### Endpoint статистики:
```
https://www.mexc.com/api/operateactivity/eftd/statistics
```

## 🔧 Как добавить в бот

### Вариант 1: Через config/url_templates.json

Добавьте в секцию `"mexc"`:

```json
"mexc": {
  "launchpad": { ... существующий код ... },
  "jggl": { ... существующий код ... },
  
  "token-airdrop": {
    "pattern": "/token-airdrop",
    "pattern_type": "api",
    "base_url": "https://www.mexc.com",
    "api_url": "https://www.mexc.com/api/operateactivity/eftd/list",
    "method": "GET",
    "params": {
      "startTime": "{timestamp_start_ms}",
      "endTime": "{timestamp_end_ms}"
    },
    "fields": {
      "activityCurrency": ["activityCurrency", "coin", "symbol"],
      "id": ["id", "_id", "activityId"]
    },
    "static_segments": ["token-airdrop"]
  }
}
```

### Вариант 2: Напрямую в config.py

Добавьте в конец файла `config.py`:

```python
# =============================================================================
# MEXC AIRDROP CONFIGURATION
# =============================================================================
MEXC_AIRDROP_API_URL = 'https://www.mexc.com/api/operateactivity/eftd/list'
MEXC_AIRDROP_STATS_URL = 'https://www.mexc.com/api/operateactivity/eftd/statistics'

# Период для получения аирдропов (в днях)
MEXC_AIRDROP_DAYS_BACK = 30   # 30 дней назад
MEXC_AIRDROP_DAYS_FORWARD = 30  # 30 дней вперед
```

### Вариант 3: Создать отдельный парсер (рекомендуется)

Создайте файл `parsers/mexc_airdrop_parser.py`:

```python
"""
MEXC Airdrop Parser - парсер промоакций MEXC
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

class MexcAirdropParser(BaseParser):
    """Парсер промоакций MEXC через API"""
    
    API_URL = 'https://www.mexc.com/api/operateactivity/eftd/list'
    STATS_URL = 'https://www.mexc.com/api/operateactivity/eftd/statistics'
    
    def __init__(self, days_back: int = 30, days_forward: int = 30):
        """
        Args:
            days_back: сколько дней назад включать
            days_forward: сколько дней вперед включать
        """
        super().__init__(self.API_URL)
        self.days_back = days_back
        self.days_forward = days_forward
    
    def parse(self) -> List[Dict[str, Any]]:
        """Получить список промоакций"""
        try:
            # Вычисляем временной диапазон
            now = datetime.now()
            start_date = now - timedelta(days=self.days_back)
            end_date = now + timedelta(days=self.days_forward)
            
            start_time = int(start_date.timestamp() * 1000)
            end_time = int(end_date.timestamp() * 1000)
            
            # Запрос к API
            params = {
                'startTime': start_time,
                'endTime': end_time
            }
            
            response = self.session.get(self.url, params=params, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') != 0:
                logger.error(f"API error: {result.get('msg', 'Unknown')}")
                return []
            
            airdrops = result.get('data', [])
            logger.info(f"✅ Получено {len(airdrops)} промоакций MEXC")
            
            # Преобразуем в стандартный формат
            return [self._transform_airdrop(a) for a in airdrops]
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга MEXC airdrops: {e}")
            return []
    
    def _transform_airdrop(self, airdrop: Dict[str, Any]) -> Dict[str, Any]:
        """Преобразовать аирдроп в стандартный формат"""
        return {
            'exchange': 'MEXC',
            'type': 'airdrop',
            'id': airdrop.get('id'),
            'coin': airdrop.get('activityCurrency'),
            'name': airdrop.get('activityCurrencyFullName'),
            'status': airdrop.get('state'),  # ACTIVE, AWARDED, END
            'start_time': airdrop.get('startTime'),
            'end_time': airdrop.get('endTime'),
            'url': f"https://www.mexc.com/token-airdrop/{airdrop.get('activityCurrency')}/{airdrop.get('id')}" if airdrop.get('activityCurrency') and airdrop.get('id') else None,
            'website_url': airdrop.get('websiteUrl'),
            'twitter_url': airdrop.get('twitterUrl'),
            'rewards': {
                'first': {
                    'currency': airdrop.get('firstProfitCurrency'),
                    'amount': airdrop.get('firstProfitCurrencyQuantity')
                },
                'second': {
                    'currency': airdrop.get('secondProfitCurrency'),
                    'amount': airdrop.get('secondProfitCurrencyQuantity')
                }
            },
            'participants': airdrop.get('applyNum'),
            'kyc_level': airdrop.get('kycLevel'),
            'tasks': airdrop.get('taskVOList', []),
            'raw_data': airdrop  # Сохраняем полные данные
        }
    
    def get_active_airdrops(self) -> List[Dict[str, Any]]:
        """Получить только активные аирдропы"""
        all_airdrops = self.parse()
        return [a for a in all_airdrops if a['status'] == 'ACTIVE']
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получить общую статистику"""
        try:
            response = self.session.get(self.STATS_URL, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            if result.get('code') == 0:
                return result.get('data', {})
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
        
        return {}
```

## 📝 Пример использования

```python
from parsers.mexc_airdrop_parser import MexcAirdropParser

# Создать парсер
parser = MexcAirdropParser(days_back=30, days_forward=30)

# Получить все промоакции
all_airdrops = parser.parse()
print(f"Всего: {len(all_airdrops)}")

# Получить только активные
active = parser.get_active_airdrops()
print(f"Активных: {len(active)}")

# Показать активные
for airdrop in active:
    print(f"- {airdrop['coin']}: {airdrop['name']}")
    print(f"  Статус: {airdrop['status']}")
    print(f"  URL: {airdrop['url']}")
    print(f"  Website: {airdrop['website_url']}")
```

## 🎯 Что даёт этот API

✅ **Полная информация о промоакциях:**
- Название и символ монеты
- Статусы (ACTIVE, AWARDED, END)
- Временные рамки (начало, конец)
- Награды (тип и количество)
- Внешние ссылки (сайт, Twitter)
- Условия участия (задания)
- KYC требования
- Количество участников

✅ **Преимущества:**
- Официальный API MEXC
- Без Playwright/Selenium
- Быстрый ответ (<1 сек)
- JSON формат
- Исторические данные
- Фильтрация по периоду

## ⚡ Быстрый старт

**Минимальный код для теста:**

```python
import requests
from datetime import datetime

# API URL
url = 'https://www.mexc.com/api/operateactivity/eftd/list'

# Временной диапазон
now = int(datetime.now().timestamp() * 1000)
params = {
    'startTime': now - (30 * 24 * 60 * 60 * 1000),  # 30 дней назад
    'endTime': now + (30 * 24 * 60 * 60 * 1000)      # 30 дней вперёд
}

# Запрос
response = requests.get(url, params=params)
airdrops = response.json()['data']

# Фильтр активных
active = [a for a in airdrops if a['state'] == 'ACTIVE']

print(f"Активных промоакций: {len(active)}")
for a in active:
    print(f"- {a['activityCurrency']}: {a['activityCurrencyFullName']}")
```

---

**Готово! Просто добавьте эту ссылку в бот и всё заработает! 🚀**
