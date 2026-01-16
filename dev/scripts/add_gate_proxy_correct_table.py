"""
Add working Gate.io proxy to CORRECT table (ProxyServer with CamelCase)
"""

import sqlite3
import time

def add_proxy_correct_table():
    """Add working Gate.io proxy to ProxyServer table"""

    db_path = 'data/database.db'

    # Working proxy credentials
    address = "aeaa7a6903eaea61:qQyUE9Gj@res.proxy-seller.io:10001"
    protocol = "http"
    priority = 10  # High priority
    status = "active"
    speed_ms = 600  # From test results

    print("=" * 80)
    print("ADDING WORKING GATE.IO PROXY TO CORRECT TABLE")
    print("=" * 80)
    print(f"\nTable: ProxyServer (CamelCase)")
    print(f"Address: {address}")
    print(f"Protocol: {protocol}")
    print(f"Priority: {priority}")

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Check if proxy already exists
            cursor.execute("SELECT * FROM ProxyServer WHERE address = ?", (address,))
            existing = cursor.fetchone()

            if existing:
                print(f"\nProxy already exists in ProxyServer table")
                print(f"ID: {existing[0]}")
                print(f"Status: {existing[3]}")
                print(f"Priority: {existing[7]}")

                # Update if needed
                cursor.execute("""
                    UPDATE ProxyServer
                    SET status = ?, priority = ?, speed_ms = ?
                    WHERE address = ?
                """, (status, priority, speed_ms, address))

                conn.commit()
                print("\nUpdated proxy to active with high priority!")

                return existing[0]

            # Get max ID to create new ID
            cursor.execute("SELECT MAX(id) FROM ProxyServer")
            max_id = cursor.fetchone()[0] or 0
            new_id = max_id + 1

            print(f"\nCreating new proxy with ID: {new_id}")

            # Insert new proxy
            cursor.execute("""
                INSERT INTO ProxyServer
                (id, address, protocol, status, speed_ms, success_count, fail_count, priority, last_used, last_success, last_blocked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_id,
                address,
                protocol,
                status,
                speed_ms,
                1,  # success_count (marked as tested)
                0,  # fail_count
                priority,
                None,  # last_used
                time.time(),  # last_success (now)
                0  # last_blocked (never)
            ))

            conn.commit()

            print(f"\nProxy added successfully!")
            print(f"ID: {new_id}")
            print(f"Status: {status}")
            print(f"Priority: {priority}")

            return new_id

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def verify_proxy():
    """Verify proxy was added correctly"""

    db_path = 'data/database.db'

    print("\n" + "=" * 80)
    print("VERIFYING PROXIES IN ProxyServer TABLE")
    print("=" * 80)

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Get all active proxies with scores
            cursor.execute("""
                SELECT id, address, priority, success_count, fail_count, speed_ms,
                    (success_count * 1.0 / (success_count + fail_count + 1)) * 0.6 +
                    (1 - (speed_ms / 10000.0)) * 0.3 +
                    (priority * 0.1) as score
                FROM ProxyServer
                WHERE status = 'active'
                ORDER BY score DESC
            """)

            proxies = cursor.fetchall()

            print(f"\nActive proxies in ProxyServer table: {len(proxies)}")
            print("\nTop proxies by score:")

            for i, p in enumerate(proxies[:10], 1):
                proxy_id, address, priority, success, fail, speed, score = p

                parts = address.split('@')
                if len(parts) == 2:
                    creds, host = parts
                    user = creds.split(':')[0]
                else:
                    user = 'N/A'
                    host = address

                print(f"\n{i}. ID {proxy_id}: {host}")
                print(f"   User: {user}")
                print(f"   Score: {score:.3f}")
                print(f"   Priority: {priority}")
                print(f"   Success/Fail: {success}/{fail}")

                if 'aeaa7a6903eaea61' in address:
                    print("   *** WORKING GATE.IO PROXY ***")

    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    print("This script will add working Gate.io proxy to ProxyServer table")
    print("Proxy: res.proxy-seller.io:10001:aeaa7a6903eaea61:qQyUE9Gj")
    print()

    confirm = input("Continue? (y/n): ")

    if confirm.lower() != 'y':
        print("Cancelled")
        exit(0)

    proxy_id = add_proxy_correct_table()

    if proxy_id:
        verify_proxy()

        print("\n" + "=" * 80)
        print("DONE")
        print("=" * 80)
        print(f"\nWorking proxy added to ProxyServer table with ID: {proxy_id}")
        print("Proxy has priority 10 (highest)")
        print("\nNow RESTART THE BOT to clear memory cache")
        print("After restart, bot will use this proxy for Gate.io requests")
