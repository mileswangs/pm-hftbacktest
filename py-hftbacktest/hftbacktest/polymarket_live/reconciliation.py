from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from decimal import Decimal

_DATA_API = "https://data-api.polymarket.com"
_USER_AGENT = "pm-hftbacktest-polymarket-live/1.0"


def local_position(conn: sqlite3.Connection, token_id: str) -> Decimal:
    rows = conn.execute(
        """
        SELECT o.side, f.size
        FROM fills f
        JOIN order_intents o ON o.idempotency_key = f.idempotency_key
        WHERE o.token_id = ?
        """,
        (token_id,),
    ).fetchall()
    total = Decimal("0")
    for side, size in rows:
        signed = Decimal(size) if side == "BUY" else -Decimal(size)
        total += signed
    return total


def fetch_remote_positions(wallet: str) -> dict[str, Decimal]:
    params = urllib.parse.urlencode({"user": wallet, "limit": 500})
    req = urllib.request.Request(f"{_DATA_API}/positions?{params}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return {item["asset"]: Decimal(str(item["size"])) for item in data}


def reconcile(conn: sqlite3.Connection, wallet: str, token_ids: list[str]) -> list[dict]:
    remote = fetch_remote_positions(wallet)
    now = int(time.time())
    rows = []
    for token_id in token_ids:
        local = local_position(conn, token_id)
        remote_size = remote.get(token_id, Decimal("0"))
        mismatch = local != remote_size
        conn.execute(
            "INSERT INTO reconciliation_log (checked_at, token_id, local_position, remote_position, mismatch) VALUES (?, ?, ?, ?, ?)",
            (now, token_id, str(local), str(remote_size), int(mismatch)),
        )
        rows.append({
            "token_id": token_id, "local_position": local,
            "remote_position": remote_size, "mismatch": mismatch,
        })
    conn.commit()
    return rows
