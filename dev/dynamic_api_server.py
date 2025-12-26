from flask import Flask, jsonify
import datetime
import time
import random
from threading import Thread
import json

app = Flask(__name__)

# Хранилище промоакций
active_promotions = []
promotion_counter = 1

def create_dynamic_promotions():
    """Создает динамические промоакции, которые появляются со временем"""
    global active_promotions, promotion_counter
    
    # Очищаем старые промоакции
    active_promotions.clear()
    
    # Текущее время
    now = datetime.datetime.now()
    
    # 1. Промоакция, которая уже активна
    promo1 = {
        "id": f"active_{promotion_counter}",
        "title": "🎯 Active Trading Competition",
        "description": "Trade any pair and win up to 5000 USDT! Competition ends in 24 hours.",
        "totalPrizePool": "5,000 USDT",
        "awardToken": "USDT",
        "startTime": (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": (now + datetime.timedelta(hours=22)).strftime("%Y-%m-%d %H:%M:%S"),
        "campaignUrl": "https://test-exchange.com/promo/active",
        "tokenIcon": "https://example.com/usdt.png",
        "status": "active"
    }
    active_promotions.append(promo1)
    promotion_counter += 1
    
    # 2. Промоакция, которая начнется через 1 минуту
    promo2 = {
        "id": f"future_{promotion_counter}",
        "title": "🚀 New Listing Celebration",
        "description": "Celebrate new token listing with bonus rewards for early traders!",
        "totalPrizePool": "2,000 USDT",
        "awardToken": "USDT",
        "startTime": (now + datetime.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": (now + datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
        "campaignUrl": "https://test-exchange.com/promo/newlisting",
        "tokenIcon": "https://example.com/rocket.png",
        "status": "future"
    }
    active_promotions.append(promo2)
    promotion_counter += 1
    
    # 3. Промоакция, которая начнется через 3 минуты
    promo3 = {
        "id": f"special_{promotion_counter}",
        "title": "💰 Staking Festival",
        "description": "Stake your tokens and earn extra APY for limited time!",
        "totalPrizePool": "10,000 USDT",
        "awardToken": "USDT",
        "startTime": (now + datetime.timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": (now + datetime.timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"),
        "campaignUrl": "https://test-exchange.com/promo/staking",
        "tokenIcon": "https://example.com/staking.png",
        "status": "future"
    }
    active_promotions.append(promo3)
    promotion_counter += 1

def check_and_add_new_promotions():
    """Проверяет и добавляет новые промоакции по расписанию"""
    global active_promotions, promotion_counter
    
    while True:
        now = datetime.datetime.now()
        
        # Проверяем будущие промоакции
        for promo in active_promotions[:]:  # Копируем список для безопасной итерации
            if promo.get("status") == "future":
                start_time = datetime.datetime.strptime(promo["startTime"], "%Y-%m-%d %H:%M:%S")
                if now >= start_time:
                    print(f"🆕 НОВАЯ ПРОМОАКЦИЯ АКТИВИРОВАНА: {promo['title']}")
                    promo["status"] = "active"
        
        # Случайно добавляем новую промоакцию каждые 2-5 минут
        if random.random() < 0.1:  # 10% шанс каждую минуту
            new_promo = {
                "id": f"random_{promotion_counter}",
                "title": f"🎁 Flash Promotion {promotion_counter}",
                "description": f"Limited time flash promotion! Don't miss your chance to win rewards!",
                "totalPrizePool": f"{random.randint(500, 3000)} USDT",
                "awardToken": "USDT",
                "startTime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": (now + datetime.timedelta(hours=random.randint(1, 24))).strftime("%Y-%m-%d %H:%M:%S"),
                "campaignUrl": f"https://test-exchange.com/promo/flash{promotion_counter}",
                "tokenIcon": "https://example.com/flash.png",
                "status": "active"
            }
            active_promotions.append(new_promo)
            print(f"🎉 СЛУЧАЙНАЯ ПРОМОАКЦИЯ ДОБАВЛЕНА: {new_promo['title']}")
            promotion_counter += 1
        
        time.sleep(60)  # Проверяем каждую минуту

@app.route('/api/dynamic/promotions')
def dynamic_promotions():
    """API с динамическими промоакциями"""
    now = datetime.datetime.now()
    
    # Фильтруем только активные промоакции
    active_now = []
    for promo in active_promotions:
        start_time = datetime.datetime.strptime(promo["startTime"], "%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.strptime(promo["endTime"], "%Y-%m-%d %H:%M:%S")
        
        if start_time <= now <= end_time:
            active_now.append(promo)
    
    response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": active_now,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "total_active": len(active_now),
            "total_future": len([p for p in active_promotions if p.get("status") == "future"])
        }
    }
    
    return jsonify(response)

@app.route('/api/dynamic/debug')
def debug_info():
    """Отладочная информация о всех промоакциях"""
    return jsonify({
        "all_promotions": active_promotions,
        "total_count": len(active_promotions),
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/api/dynamic/add_promo')
def add_test_promo():
    """Ручное добавление тестовой промоакции"""
    global promotion_counter
    
    now = datetime.datetime.now()
    new_promo = {
        "id": f"manual_{promotion_counter}",
        "title": f"🛠️ Manual Test Promotion {promotion_counter}",
        "description": "This promotion was added manually for testing",
        "totalPrizePool": "1,000 USDT",
        "awardToken": "USDT",
        "startTime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": (now + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "campaignUrl": f"https://test-exchange.com/promo/manual{promotion_counter}",
        "tokenIcon": "https://example.com/test.png",
        "status": "active"
    }
    
    active_promotions.append(new_promo)
    promotion_counter += 1
    
    return jsonify({"status": "added", "promo": new_promo})

# Инициализация
create_dynamic_promotions()

# Запуск фонового потока для добавления новых промоакций
thread = Thread(target=check_and_add_new_promotions, daemon=True)
thread.start()

if __name__ == '__main__':
    print("🚀 ДИНАМИЧЕСКИЙ API СЕРВЕР ЗАПУЩЕН!")
    print("📊 Автоматические промоакции:")
    print("   1. 🎯 Active Trading Competition - АКТИВНА СЕЙЧАС")
    print("   2. 🚀 New Listing Celebration - начнется через 1 МИНУТУ") 
    print("   3. 💰 Staking Festival - начнется через 3 МИНУТЫ")
    print("\n🔄 Бот будет автоматически находить новые промоакции!")
    print("📡 Эндпоинты:")
    print("   http://localhost:5001/api/dynamic/promotions")
    print("   http://localhost:5001/api/dynamic/debug")
    print("   http://localhost:5001/api/dynamic/add_promo")
    print("\n⏰ Авто-проверка бота: каждые 5 минут")
    print("🎁 Случайные промоакции: каждые 2-5 минут")
    
    app.run(debug=False, host='0.0.0.0', port=5001)