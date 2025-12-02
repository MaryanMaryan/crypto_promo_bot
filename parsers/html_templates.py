# parsers/html_templates.py
"""
HTML ШАБЛОНЫ ДЛЯ ПАРСИНГА ПРОМОАКЦИЙ С БИРЖ
Универсальные селекторы для извлечения данных из HTML страниц
"""

HTML_PROMO_STRUCTURE = {
    "bybit": {
        "container": "div.event-item, div.promo-item, div.activity-item, [class*='event'], [class*='promo'], [class*='activity']",
        "title": "h3, h4, .title, .name, [class*='title'], [class*='name']",
        "description": ".description, .desc, .details, .info, [class*='desc'], [class*='detail']",
        "link": "a[href], button[onclick], [class*='btn'], [class*='link'], [class*='join']",
        "time": ".time, .date, .period, [class*='time'], [class*='date']",
        "prize": ".prize, .reward, .pool, [class*='prize'], [class*='reward']",
        "participants": ".participants, .users, .count, [class*='participant']",
        "image": "img[src], [class*='image'], [class*='icon'], [class*='logo']"
    },
    "mexc": {
        "container": "div.launchpad-item, div.project-item, [class*='launchpad'], [class*='project']",
        "title": "h4, h3, .project-name, .project-title, [class*='name'], [class*='title']",
        "description": ".project-desc, .project-info, .description, [class*='desc'], [class*='info']",
        "link": "a.join-button, a[href*='launchpad'], button, [class*='btn'], [class*='join']",
        "progress": ".progress, .progress-bar, [class*='progress']",
        "time": ".time, .date, .period, [class*='time'], [class*='date']",
        "token": ".token, .symbol, [class*='token'], [class*='symbol']"
    },
    "binance": {
        "container": "div.activity-item, div.launchpad-item, [class*='activity'], [class*='launchpad']",
        "title": "h3, h4, .title, .name, [class*='title'], [class*='name']",
        "description": ".description, .desc, .details, [class*='desc'], [class*='detail']",
        "link": "a[href], button, [class*='btn'], [class*='link']",
        "time": ".time, .date, [class*='time'], [class*='date']",
        "status": ".status, .tag, [class*='status'], [class*='tag']"
    },
    "gate": {
        "container": "div.startup-item, div.project-item, [class*='startup'], [class*='project']",
        "title": "h3, h4, .title, .name, [class*='title'], [class*='name']",
        "description": ".description, .info, .details, [class*='desc'], [class*='info']",
        "link": "a[href*='startup'], button, [class*='btn'], [class*='participate']",
        "progress": ".progress, .rate, [class*='progress']",
        "token": ".token, .coin, [class*='token'], [class*='coin']"
    },
    "okx": {
        "container": "div.jumpstart-item, div.project-item, [class*='jumpstart'], [class*='project']",
        "title": "h3, h4, .title, .name, [class*='title'], [class*='name']",
        "description": ".description, .info, [class*='desc'], [class*='info']",
        "link": "a[href*='jumpstart'], button, [class*='btn'], [class*='join']",
        "time": ".time, .date, [class*='time'], [class*='date']",
        "reward": ".reward, .profit, [class*='reward'], [class*='profit']"
    },
    "bitget": {
        "container": "div.promo-item, div.event-item, [class*='promo'], [class*='event']",
        "title": "h3, h4, .title, .name, [class*='title'], [class*='name']",
        "description": ".description, .desc, .details, [class*='desc'], [class*='detail']",
        "link": "a[href], button, [class*='btn'], [class*='join']",
        "time": ".time, .date, [class*='time'], [class*='date']",
        "reward": ".reward, .prize, [class*='reward'], [class*='prize']"
    }
}

HTML_BASE_URLS = {
    "bybit": [
        "https://www.bybit.com/en/trade/spot/token-splash",
    ],
    "mexc": [
        "https://www.mexc.com/launchpad",
        "https://www.mexc.com/activity"
    ],
    "binance": [
        "https://www.binance.com/ru/activity",
        "https://www.binance.com/ru/launchpad",
        "https://www.binance.com/ru/launchpool"
    ],
    "gate": [
        "https://www.gate.io/startup",
        "https://www.gate.io/launchpad"
    ],
    "okx": [
        "https://www.okx.com/ru/jumpstart",
        "https://www.okx.com/ru/earn"
    ],
    "bitget": [
        "https://www.bitget.com/ru/promotion",
        "https://www.bitget.com/ru/events"
    ]
}

def get_html_selectors(exchange: str) -> dict:
    """Возвращает селекторы для указанной биржи"""
    return HTML_PROMO_STRUCTURE.get(exchange, {})

def get_html_urls(exchange: str) -> list:
    """Возвращает HTML URL для указанной биржи"""
    return HTML_BASE_URLS.get(exchange, [])

def add_custom_selectors(exchange: str, selectors: dict):
    """Добавляет кастомные селекторы для биржи"""
    if exchange not in HTML_PROMO_STRUCTURE:
        HTML_PROMO_STRUCTURE[exchange] = {}
    
    HTML_PROMO_STRUCTURE[exchange].update(selectors)
    print(f"✅ Добавлены кастомные селекторы для {exchange}")

def add_custom_urls(exchange: str, urls: list):
    """Добавляет кастомные URL для биржи"""
    if exchange not in HTML_BASE_URLS:
        HTML_BASE_URLS[exchange] = []
    
    HTML_BASE_URLS[exchange].extend(urls)
    print(f"✅ Добавлены кастомные URL для {exchange}")