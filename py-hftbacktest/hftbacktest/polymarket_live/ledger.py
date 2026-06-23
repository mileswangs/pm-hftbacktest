from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import PolymarketOrderIntent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_intents (
    idempotency_key TEXT PRIMARY KEY,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL,
    order_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL REFERENCES order_intents(idempotency_key),
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    fee TEXT,
    filled_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at INTEGER NOT NULL,
    token_id TEXT NOT NULL,
    local_position TEXT NOT NULL,
    remote_position TEXT NOT NULL,
    mismatch INTEGER NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def record_intent(conn: sqlite3.Connection, intent: PolymarketOrderIntent, status: str) -> None:
    now = int(time.time())
    key = intent.idempotency_key or derive_idempotency_key(intent)
    conn.execute(
        """
        INSERT INTO order_intents
            (idempotency_key, token_id, side, price, size, order_type, status, order_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (key, intent.token_id, intent.side.value, str(intent.price), str(intent.size),
         intent.time_in_force.value, status, now, now),
    )
    conn.commit()


def find_intent(conn: sqlite3.Connection, idempotency_key: str) -> Optional[dict]:
    cursor = conn.execute(
        "SELECT * FROM order_intents WHERE idempotency_key = ?", (idempotency_key,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row))


def record_result(conn: sqlite3.Connection, idempotency_key: str, status: str, order_id: Optional[str]) -> None:
    conn.execute(
        "UPDATE order_intents SET status = ?, order_id = ?, updated_at = ? WHERE idempotency_key = ?",
        (status, order_id, int(time.time()), idempotency_key),
    )
    conn.commit()


def record_fill(conn: sqlite3.Connection, idempotency_key: str, fill_id: str, price, size, fee, filled_at: int) -> None:
    conn.execute(
        "INSERT INTO fills (fill_id, idempotency_key, price, size, fee, filled_at) VALUES (?, ?, ?, ?, ?, ?)",
        (fill_id, idempotency_key, str(price), str(size), str(fee) if fee is not None else None, filled_at),
    )
    conn.commit()


def derive_idempotency_key(intent: PolymarketOrderIntent, bucket_seconds: int = 1800) -> str:
    bucket = int(time.time()) // bucket_seconds
    raw = f"{intent.token_id}:{intent.side.value}:{intent.price}:{intent.size}:{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
