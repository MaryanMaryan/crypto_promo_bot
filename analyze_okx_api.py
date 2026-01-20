import requests
import json
from datetime import datetime

url = 'https://web3.okx.com/priapi/v1/dapp/boost/launchpool/list'
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
data = r.json()
pools = data.get('data', {}).get('pools', [])

# Показываем все уникальные chain_id
chain_ids = set()
statuses = set()
reward_modes = set()
for p in pools:
    chain_ids.add(p.get('reward', {}).get('chainId'))
    statuses.add(p.get('status'))
    reward_modes.add(p.get('rewardMode'))

print(f'Total pools: {len(pools)}')
print(f'Chain IDs: {chain_ids}')
print(f'Statuses: {statuses}')
print(f'Reward Modes: {reward_modes}')
print()

# Статистика по статусам
status_counts = {}
for p in pools:
    s = p.get('status')
    status_counts[s] = status_counts.get(s, 0) + 1
print(f'Status counts: {status_counts}')
print()

# Подробный анализ одного пула
pool = pools[0]
print('=== DETAILED ANALYSIS ===')
print(f"Name: {pool['name']}")
print(f"homeName: {pool['homeName']}")
print(f"navName: {pool['navName']}")
print(f"Participants: {pool['participants']:,}")
print()
print('Reward:')
print(f"  amount: {pool['reward']['amount']:,.0f}")
print(f"  token: {pool['reward']['token']}")
print(f"  chainId: {pool['reward']['chainId']}")
print()
print('Times (converted):')
times = pool['times']
for k, v in times.items():
    if v:
        dt = datetime.fromtimestamp(v / 1000)
        print(f"  {k}: {dt.strftime('%Y-%m-%d %H:%M')} (ts: {v})")
print()
print(f"Status code: {pool['status']}")
print(f"RewardMode: {pool['rewardMode']}")
print()
print('User info:')
print(json.dumps(pool['user'], indent=2))
print()

# Все поля времени
print('=== ALL TIME FIELDS ACROSS ALL POOLS ===')
all_time_fields = set()
for p in pools:
    all_time_fields.update(p.get('times', {}).keys())
print(f'Time fields: {all_time_fields}')
print()

# Таблица всех пулов
print('=== ALL POOLS SUMMARY ===')
print(f"{'Name':<40} {'Token':<10} {'Amount':>15} {'Chain':>10} {'Status':>8} {'Participants':>12}")
print('-' * 100)
for p in pools[:15]:  # First 15
    name = p['name'][:38]
    token = p['reward']['token']
    amount = f"{p['reward']['amount']:,.0f}"
    chain = p['reward']['chainId']
    status = p['status']
    participants = f"{p['participants']:,}"
    print(f"{name:<40} {token:<10} {amount:>15} {chain:>10} {status:>8} {participants:>12}")
