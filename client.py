"""
Updated client.py - Fetches live Nifty 50 Spot, ATM Strike, and Option Chain via HTTP.
"""

import urllib.request
import json
import sys

API_URL = "http://127.0.0.1:5555/"


def fetch_market_data():
    try:
        with urllib.request.urlopen(API_URL, timeout=2.0) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    data = fetch_market_data()
    if "error" in data:
        print(f"Server connection failed: {data['error']}")
        sys.exit(1)

    spot = data.get("spot", {}).get("ltp")
    contracts = data.get("contracts", {})

    print("=" * 60)
    print(f"NIFTY 50 SPOT : {spot if spot else '--'}")
    print(f"TOTAL CONTRACTS: {len(contracts)}")
    print("=" * 60)

    # Filter contracts that have received live LTP
    active = [c for c in contracts.values() if c.get("ltp") is not None]
    active.sort(key=lambda x: x.get("strike", 0))

    for item in active[:15]:
        print(
            f"{item['symbol']:<24} | Strike: {item['strike']:<8.2f} | LTP: ₹{item['ltp']:.2f}"
        )