"""
Add working Gate.io proxy to database
"""

import sys
import os

# Add root directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data.database import get_db_session, init_database
from data.models import ProxyServer
from datetime import datetime

def add_proxy():
    """Add working Gate.io proxy to database"""

    # Working proxy credentials
    host = "res.proxy-seller.io:10001"
    user = "aeaa7a6903eaea61"
    password = "qQyUE9Gj"
    protocol = "http"

    # Build address string
    address = f"{user}:{password}@{host}"

    print("=" * 80)
    print("ADDING WORKING GATE.IO PROXY")
    print("=" * 80)
    print(f"\nProxy address: {address}")
    print(f"Protocol: {protocol}")

    init_database()

    with get_db_session() as db:
        # Check if already exists
        existing = db.query(ProxyServer).filter(ProxyServer.address == address).first()

        if existing:
            print(f"\nProxy already exists in database (ID: {existing.id})")
            print(f"Status: {existing.status}")
            print(f"Priority: {existing.priority}")

            # Update if needed
            if existing.status != 'active':
                print("\nUpdating status to 'active'...")
                existing.status = 'active'
                db.commit()
                print("Updated!")

            if existing.priority != 10:
                print("\nSetting high priority (10) for Gate.io...")
                existing.priority = 10
                db.commit()
                print("Priority updated!")

            return existing.id

        # Create new proxy
        print("\nCreating new proxy entry...")
        new_proxy = ProxyServer(
            address=address,
            protocol=protocol,
            status='active',
            speed_ms=600,  # Based on test results (~0.6s)
            success_count=1,  # Mark as tested and working
            fail_count=0,
            priority=10,  # High priority for working proxy
            last_success=datetime.utcnow(),
            created_at=datetime.utcnow()
        )

        db.add(new_proxy)
        db.commit()

        print(f"\nProxy added successfully!")
        print(f"ID: {new_proxy.id}")
        print(f"Status: {new_proxy.status}")
        print(f"Priority: {new_proxy.priority}")

        return new_proxy.id


def verify_proxy():
    """Verify proxy was added"""

    init_database()

    with get_db_session() as db:
        proxies = db.query(ProxyServer).filter(ProxyServer.status == 'active').order_by(ProxyServer.priority.desc()).all()

        print("\n" + "=" * 80)
        print("ACTIVE PROXIES (sorted by priority)")
        print("=" * 80)

        for p in proxies:
            parts = p.address.split('@')
            if len(parts) == 2:
                creds, host = parts
                user = creds.split(':')[0] if ':' in creds else 'N/A'
                print(f"\nID {p.id}: {host}")
                print(f"  User: {user}")
                print(f"  Status: {p.status}")
                print(f"  Priority: {p.priority} {'<--- HIGH PRIORITY' if p.priority >= 10 else ''}")
                print(f"  Success/Fail: {p.success_count}/{p.fail_count}")


if __name__ == "__main__":
    print("This script will add working Gate.io proxy to database")
    print("Proxy: res.proxy-seller.io:10001:aeaa7a6903eaea61:qQyUE9Gj")
    print()

    confirm = input("Continue? (y/n): ")

    if confirm.lower() != 'y':
        print("Cancelled")
        exit(0)

    proxy_id = add_proxy()
    verify_proxy()

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print(f"\nWorking proxy added with ID: {proxy_id}")
    print("Bot will now use this proxy for Gate.io requests")
    print("\nNOTE: Proxy has priority 10 (highest), so it will be selected first")
