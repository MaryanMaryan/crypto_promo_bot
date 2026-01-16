"""
Find where proxy ID 40 is mentioned
"""

import sqlite3
import os

def find_proxy_40():
    """Find any references to proxy ID 40"""

    db_path = 'data/database.db'

    print("=" * 80)
    print("SEARCHING FOR PROXY ID 40")
    print("=" * 80)

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Check all ProxyServer tables
            tables_to_check = ['proxy_servers', 'ProxyServer']

            for table in tables_to_check:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]

                    print(f"\nTable: {table}")
                    print(f"Total records: {count}")

                    cursor.execute(f"SELECT MAX(id) as max_id FROM {table}")
                    max_id = cursor.fetchone()[0]
                    print(f"Max ID: {max_id}")

                    if max_id and max_id >= 40:
                        cursor.execute(f"SELECT * FROM {table} WHERE id = 40")
                        result = cursor.fetchone()

                        if result:
                            print(f"\nFOUND in {table}:")
                            cursor.execute(f"PRAGMA table_info({table})")
                            columns = [col[1] for col in cursor.fetchall()]

                            for col, val in zip(columns, result):
                                print(f"  {col}: {val}")
                        else:
                            print(f"ID 40 not found in {table}")

                    # Show IDs 35-45
                    cursor.execute(f"SELECT id FROM {table} WHERE id BETWEEN 35 AND 45 ORDER BY id")
                    ids = cursor.fetchall()
                    if ids:
                        print(f"IDs between 35-45: {[i[0] for i in ids]}")

                except sqlite3.OperationalError:
                    print(f"Table {table} doesn't exist")

            # Check RotationStats for proxy_id=40
            print("\n" + "=" * 80)
            print("CHECKING ROTATION STATS FOR PROXY_ID=40")
            print("=" * 80)

            cursor.execute("""
                SELECT COUNT(*)
                FROM RotationStats
                WHERE proxy_id = 40
            """)
            count = cursor.fetchone()[0]
            print(f"\nRotationStats records with proxy_id=40: {count}")

            if count > 0:
                cursor.execute("""
                    SELECT id, proxy_id, user_agent_id, exchange, request_result, response_code, timestamp
                    FROM RotationStats
                    WHERE proxy_id = 40
                    ORDER BY timestamp DESC
                    LIMIT 5
                """)
                records = cursor.fetchall()

                print("\nRecent stats for proxy_id=40:")
                for r in records:
                    print(f"  ID {r[0]}: proxy={r[1]}, ua={r[2]}, exchange={r[3]}, result={r[4]}, code={r[5]}, time={r[6]}")

            # Check what proxies are actually used in stats
            print("\n" + "=" * 80)
            print("PROXIES USED IN ROTATION STATS")
            print("=" * 80)

            cursor.execute("""
                SELECT proxy_id, COUNT(*) as usage_count
                FROM RotationStats
                GROUP BY proxy_id
                ORDER BY usage_count DESC
                LIMIT 20
            """)
            usage = cursor.fetchall()

            print("\nTop 20 proxies by usage:")
            for proxy_id, count in usage:
                # Try to find proxy info
                cursor.execute("SELECT address FROM proxy_servers WHERE id = ?", (proxy_id,))
                result = cursor.fetchone()

                if result:
                    address = result[0]
                    parts = address.split('@')
                    host = parts[1] if len(parts) == 2 else address
                    print(f"  ID {proxy_id}: {host} ({count} uses)")
                else:
                    print(f"  ID {proxy_id}: [DELETED/NOT FOUND] ({count} uses)")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    find_proxy_40()

    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print("\nIf proxy ID 40 is in RotationStats but not in proxy_servers:")
    print("  -> It was deleted from proxy_servers but stats remain")
    print("  -> Bot may have cached the old proxy object in memory")
    print("  -> SOLUTION: Restart the bot to clear memory cache")
