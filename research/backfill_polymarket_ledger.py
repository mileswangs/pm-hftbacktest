#!/usr/bin/env python3
"""One-time import of a wallet's historical Polymarket TRADE activity into the
local order/fill ledger (py-hftbacktest/hftbacktest/polymarket_live/ledger.py).

This does not touch /positions for backfill (see predictparity_weather_pnl.py's
docstring on why /positions undercounts hold-to-resolve activity) -- it walks
/activity and inserts one order_intents + fills row per TRADE entry, marked
status="backfilled" so reconciliation.py can tell these apart from orders this
system actually placed.

Usage:
    python3 research/backfill_polymarket_ledger.py --wallet 0xYOURWALLET
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "py-hftbacktest"))
from hftbacktest.polymarket_live import ledger  # noqa: E402
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide  # noqa: E402

DATA_API = "https://data-api.polymarket.com"
DEFAULT_DB = Path(__file__).parent / "data" / "polymarket_ledger" / "ledger.sqlite3"


def _get(url: str, params: dict, retries: int = 3) -> object:
    full_url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url, headers={"User-Agent": "pm-hftbacktest-backfill/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def pull_activity(wallet: str, cap: int = 12000) -> list[dict]:
    out = []
    for offset in range(0, cap, 500):
        page = _get(f"{DATA_API}/activity", {"user": wallet, "limit": 500, "offset": offset})
        if not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
    return out


def backfill(wallet: str, db_path: Path) -> int:
    conn = ledger.connect(db_path)
    ledger.init_schema(conn)
    activity = pull_activity(wallet)
    inserted = 0
    for entry in activity:
        if entry.get("type") != "TRADE":
            continue
        key = f"backfill:{entry['transactionHash']}"
        if ledger.find_intent(conn, key) is not None:
            continue  # already imported
        intent = PolymarketOrderIntent(
            token_id=entry["asset"],
            side=PolymarketSide(entry["side"]),
            price=Decimal(str(entry["price"])),
            size=Decimal(str(entry["size"])),
            idempotency_key=key,
        )
        ledger.record_intent(conn, intent, status="backfilled")
        ledger.record_fill(
            conn, key, fill_id=entry["transactionHash"],
            price=Decimal(str(entry["price"])), size=Decimal(str(entry["size"])),
            fee=None, filled_at=int(entry["timestamp"]),
        )
        inserted += 1
    conn.close()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wallet", required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    count = backfill(args.wallet, args.db)
    print(f"backfilled {count} new fill(s) into {args.db}")


if __name__ == "__main__":
    main()
