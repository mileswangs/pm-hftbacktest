# Polymarket Execution Core + Account Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an idempotent, all-or-nothing order-submission path (`OrderRouter`) and a local SQLite ledger for the existing `py-hftbacktest/hftbacktest/polymarket_live/` package, plus a one-time historical backfill, so that future strategy code can place real Polymarket orders without ever double-submitting or losing track of what actually happened — starting in dry-run mode only.

**Architecture:** All Python, no Rust (see spec §1 revision note — measured signing latency is ~3.4ms, not the ~1s assumed in v1; network RTT dominates regardless of language, so there is nothing for Rust to fix here). `OrderRouter` sits in front of either the existing `PolymarketExecutionClient` (real, unchanged) or a new `DryRunExecutionClient` (same three-method shape: `place_limit_order` / `cancel_order` / `get_order`), and routes every call through a SQLite ledger that is written to *before* the network call so a crash mid-call is always recoverable on restart.

**Tech Stack:** Python 3.11 (project `.venv`), stdlib `sqlite3` + `unittest` (no new test framework — matches the existing convention in `py-hftbacktest/tests/test_hftbacktest.py`), `urllib` for the one new network call (matches `research/predictparity_weather_*.py`'s existing HTTP convention).

## Global Constraints

- Wallet/API credentials come only from the existing env vars in `py-hftbacktest/hftbacktest/polymarket_live/config.py` — no new credential surface.
- Every order placed through `OrderRouter` is forced to `time_in_force=FOK` regardless of what the caller passed (spec §6).
- The real `PolymarketExecutionClient` is never modified — only used as one of two interchangeable backends behind `OrderRouter`.
- This plan does not place any real order. The only thing that ever calls the real SDK in a test is the historical backfill, which is **read-only** (`/activity`, `/positions` on `data-api.polymarket.com` — no auth, no order placement).
- Ledger DB path: `research/data/polymarket_ledger/ledger.sqlite3` (gitignored, same convention as the rest of `research/data/`).

---

## Task 1: `idempotency_key` field on `PolymarketOrderIntent`

**Files:**
- Modify: `py-hftbacktest/hftbacktest/polymarket_live/models.py:60-67` (the `PolymarketOrderIntent` dataclass)
- Test: `py-hftbacktest/tests/test_polymarket_models.py` (new)

**Interfaces:**
- Produces: `PolymarketOrderIntent.idempotency_key: Optional[str] = None` — every later task constructs/reads this field by name.

- [ ] **Step 1: Write the failing test**

```python
# py-hftbacktest/tests/test_polymarket_models.py
import unittest
from decimal import Decimal

from hftbacktest.polymarket_live.models import (
    PolymarketOrderIntent,
    PolymarketSide,
    PolymarketTimeInForce,
)


class TestPolymarketOrderIntent(unittest.TestCase):
    def test_idempotency_key_defaults_to_none(self):
        intent = PolymarketOrderIntent(
            token_id="123",
            side=PolymarketSide.BUY,
            price=Decimal("0.5"),
            size=Decimal("10"),
        )
        self.assertIsNone(intent.idempotency_key)

    def test_idempotency_key_can_be_set(self):
        intent = PolymarketOrderIntent(
            token_id="123",
            side=PolymarketSide.BUY,
            price=Decimal("0.5"),
            size=Decimal("10"),
            idempotency_key="my-key",
        )
        self.assertEqual(intent.idempotency_key, "my-key")
        # existing positional/keyword construction (research/polymarket_live_smoke.py)
        # must still work without passing idempotency_key at all.
        old_style = PolymarketOrderIntent(
            token_id="123",
            side=PolymarketSide.BUY,
            price=Decimal("0.5"),
            size=Decimal("10"),
            time_in_force=PolymarketTimeInForce.GTC,
        )
        self.assertIsNone(old_style.idempotency_key)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_models.py -v`
Expected: FAIL — `TypeError: PolymarketOrderIntent.__init__() got an unexpected keyword argument 'idempotency_key'`

- [ ] **Step 3: Add the field**

In `py-hftbacktest/hftbacktest/polymarket_live/models.py`, change:

```python
@dataclass(frozen=True)
class PolymarketOrderIntent:
    token_id: str
    side: PolymarketSide
    price: Decimal
    size: Decimal
    time_in_force: PolymarketTimeInForce = PolymarketTimeInForce.GTC
    builder_code: Optional[str] = None
```

to:

```python
@dataclass(frozen=True)
class PolymarketOrderIntent:
    token_id: str
    side: PolymarketSide
    price: Decimal
    size: Decimal
    time_in_force: PolymarketTimeInForce = PolymarketTimeInForce.GTC
    builder_code: Optional[str] = None
    idempotency_key: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_models.py -v`
Expected: `OK` (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/hftbacktest/polymarket_live/models.py py-hftbacktest/tests/test_polymarket_models.py
git commit -m "Add idempotency_key field to PolymarketOrderIntent"
```

---

## Task 2: `ledger.py` — SQLite schema + CRUD

**Files:**
- Create: `py-hftbacktest/hftbacktest/polymarket_live/ledger.py`
- Test: `py-hftbacktest/tests/test_polymarket_ledger.py` (new)

**Interfaces:**
- Consumes: `PolymarketOrderIntent` (Task 1) — reads `.token_id`, `.side`, `.price`, `.size`, `.time_in_force`, `.idempotency_key`.
- Produces (used by Task 4 `order_router.py`):
  - `connect(db_path: pathlib.Path) -> sqlite3.Connection`
  - `init_schema(conn: sqlite3.Connection) -> None`
  - `record_intent(conn, intent: PolymarketOrderIntent, status: str) -> None`
  - `find_intent(conn, idempotency_key: str) -> dict | None` — dict keys: `idempotency_key, token_id, side, price, size, order_type, status, order_id, created_at, updated_at`
  - `record_result(conn, idempotency_key: str, status: str, order_id: str | None) -> None`
  - `record_fill(conn, idempotency_key: str, fill_id: str, price, size, fee, filled_at: int) -> None`
  - `derive_idempotency_key(intent: PolymarketOrderIntent, bucket_seconds: int = 1800) -> str`

- [ ] **Step 1: Write the failing test**

```python
# py-hftbacktest/tests/test_polymarket_ledger.py
import sqlite3
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from hftbacktest.polymarket_live import ledger
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide


def _make_intent(idempotency_key=None):
    return PolymarketOrderIntent(
        token_id="111",
        side=PolymarketSide.BUY,
        price=Decimal("0.45"),
        size=Decimal("10"),
        idempotency_key=idempotency_key,
    )


class TestLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "ledger.sqlite3"
        self.conn = ledger.connect(self.db_path)
        ledger.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_record_and_find_intent_round_trip(self):
        intent = _make_intent(idempotency_key="key-1")
        ledger.record_intent(self.conn, intent, status="submitting")

        found = ledger.find_intent(self.conn, "key-1")

        self.assertIsNotNone(found)
        self.assertEqual(found["idempotency_key"], "key-1")
        self.assertEqual(found["token_id"], "111")
        self.assertEqual(found["status"], "submitting")
        self.assertIsNone(found["order_id"])

    def test_find_intent_missing_returns_none(self):
        self.assertIsNone(ledger.find_intent(self.conn, "does-not-exist"))

    def test_record_result_updates_status_and_order_id(self):
        intent = _make_intent(idempotency_key="key-2")
        ledger.record_intent(self.conn, intent, status="submitting")

        ledger.record_result(self.conn, "key-2", status="accepted", order_id="ORDER-9")

        found = ledger.find_intent(self.conn, "key-2")
        self.assertEqual(found["status"], "accepted")
        self.assertEqual(found["order_id"], "ORDER-9")

    def test_record_fill(self):
        intent = _make_intent(idempotency_key="key-3")
        ledger.record_intent(self.conn, intent, status="accepted")
        ledger.record_fill(
            self.conn, "key-3", fill_id="FILL-1", price=Decimal("0.45"),
            size=Decimal("10"), fee=Decimal("0.01"), filled_at=1782200000,
        )

        row = self.conn.execute(
            "SELECT fill_id, idempotency_key, price, size FROM fills WHERE fill_id = ?",
            ("FILL-1",),
        ).fetchone()
        self.assertEqual(row, ("FILL-1", "key-3", "0.45", "10"))

    def test_derive_idempotency_key_is_stable_within_same_bucket(self):
        intent = _make_intent()  # idempotency_key=None
        key_a = ledger.derive_idempotency_key(intent)
        key_b = ledger.derive_idempotency_key(intent)
        self.assertEqual(key_a, key_b)

    def test_derive_idempotency_key_differs_by_price(self):
        intent_a = _make_intent()
        intent_b = PolymarketOrderIntent(
            token_id="111", side=PolymarketSide.BUY, price=Decimal("0.99"), size=Decimal("10"),
        )
        self.assertNotEqual(
            ledger.derive_idempotency_key(intent_a),
            ledger.derive_idempotency_key(intent_b),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hftbacktest.polymarket_live.ledger'`

- [ ] **Step 3: Write the implementation**

```python
# py-hftbacktest/hftbacktest/polymarket_live/ledger.py
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
    conn.row_factory = sqlite3.Row
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
    row = conn.execute(
        "SELECT * FROM order_intents WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return dict(row) if row is not None else None


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_ledger.py -v`
Expected: `OK` (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/hftbacktest/polymarket_live/ledger.py py-hftbacktest/tests/test_polymarket_ledger.py
git commit -m "Add SQLite ledger for Polymarket order intents/fills/reconciliation"
```

---

## Task 3: `dry_run.py` — `DryRunExecutionClient`

**Files:**
- Create: `py-hftbacktest/hftbacktest/polymarket_live/dry_run.py`
- Test: `py-hftbacktest/tests/test_polymarket_dry_run.py` (new)

**Interfaces:**
- Consumes: `PolymarketOrderIntent` (Task 1).
- Produces (used by Task 4 `order_router.py`, and matched in shape by the real `PolymarketExecutionClient`'s SDK calls):
  - `class DryRunOrderResult: ok: bool; order_id: str | None; status: str; making_amount: Decimal; taking_amount: Decimal` — duck-types the real SDK's `AcceptedOrder`/`RejectedOrder` union (`polymarket.models.clob.order_response.OrderResponse`, verified against the installed `polymarket-client==0.1.0b9` package: both real variants expose `.ok`).
  - `class DryRunExecutionClient: place_limit_order(intent) -> DryRunOrderResult; cancel_order(order_id) -> dict; get_order(order_id) -> DryRunOrderResult`

- [ ] **Step 1: Write the failing test**

```python
# py-hftbacktest/tests/test_polymarket_dry_run.py
import unittest
from decimal import Decimal

from hftbacktest.polymarket_live.dry_run import DryRunExecutionClient
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide, PolymarketTimeInForce


class TestDryRunExecutionClient(unittest.TestCase):
    def setUp(self):
        self.client = DryRunExecutionClient()

    def test_place_limit_order_returns_accepted_result(self):
        intent = PolymarketOrderIntent(
            token_id="111", side=PolymarketSide.BUY, price=Decimal("0.5"),
            size=Decimal("10"), time_in_force=PolymarketTimeInForce.FOK,
        )
        result = self.client.place_limit_order(intent)
        self.assertTrue(result.ok)
        self.assertTrue(result.order_id.startswith("DRYRUN-"))
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.making_amount, Decimal("10"))

    def test_place_limit_order_never_calls_network(self):
        # No network library is imported by dry_run.py at all -- this is a
        # structural guarantee, checked by import inspection.
        import hftbacktest.polymarket_live.dry_run as mod
        import inspect
        source = inspect.getsource(mod)
        for forbidden in ("urllib", "httpx", "requests", "import polymarket"):
            self.assertNotIn(forbidden, source)

    def test_get_order_returns_previously_placed_order(self):
        intent = PolymarketOrderIntent(
            token_id="111", side=PolymarketSide.BUY, price=Decimal("0.5"), size=Decimal("10"),
        )
        placed = self.client.place_limit_order(intent)
        fetched = self.client.get_order(placed.order_id)
        self.assertEqual(fetched.order_id, placed.order_id)
        self.assertTrue(fetched.ok)

    def test_cancel_order_returns_success_dict(self):
        intent = PolymarketOrderIntent(
            token_id="111", side=PolymarketSide.BUY, price=Decimal("0.5"), size=Decimal("10"),
        )
        placed = self.client.place_limit_order(intent)
        result = self.client.cancel_order(placed.order_id)
        self.assertEqual(result["canceled"], [placed.order_id])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_dry_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hftbacktest.polymarket_live.dry_run'`

- [ ] **Step 3: Write the implementation**

```python
# py-hftbacktest/hftbacktest/polymarket_live/dry_run.py
from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .models import PolymarketOrderIntent

_counter = itertools.count(1)


@dataclass(frozen=True)
class DryRunOrderResult:
    ok: bool
    order_id: Optional[str]
    status: str
    making_amount: Decimal
    taking_amount: Decimal


class DryRunExecutionClient:
    """Same three-method shape as PolymarketExecutionClient, never touches the network."""

    def __init__(self) -> None:
        self._orders: dict[str, DryRunOrderResult] = {}

    def place_limit_order(self, intent: PolymarketOrderIntent) -> DryRunOrderResult:
        order_id = f"DRYRUN-{next(_counter)}"
        result = DryRunOrderResult(
            ok=True,
            order_id=order_id,
            status="matched",
            making_amount=intent.size,
            taking_amount=intent.size * intent.price,
        )
        self._orders[order_id] = result
        return result

    def cancel_order(self, order_id: str) -> dict:
        self._orders.pop(order_id, None)
        return {"canceled": [order_id]}

    def get_order(self, order_id: str) -> DryRunOrderResult:
        return self._orders[order_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_dry_run.py -v`
Expected: `OK` (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/hftbacktest/polymarket_live/dry_run.py py-hftbacktest/tests/test_polymarket_dry_run.py
git commit -m "Add DryRunExecutionClient for paper trading"
```

---

## Task 4: `order_router.py` — idempotent, atomic, crash-recoverable submission

**Files:**
- Create: `py-hftbacktest/hftbacktest/polymarket_live/order_router.py`
- Test: `py-hftbacktest/tests/test_polymarket_order_router.py` (new)

**Interfaces:**
- Consumes:
  - `ledger.connect/init_schema/record_intent/find_intent/record_result/derive_idempotency_key` (Task 2)
  - `PolymarketOrderIntent`, `PolymarketTimeInForce` (Task 1)
  - Any object with `.place_limit_order(intent)`, `.cancel_order(order_id)`, `.get_order(order_id)` — satisfied by both `DryRunExecutionClient` (Task 3) and the real `PolymarketExecutionClient` (existing `execution.py`, unchanged).
- Produces: `class OrderRouter: __init__(self, execution_client, conn); submit(self, intent) -> dict; cancel(self, order_id) -> dict` — `submit`/`cancel` return the same dict shape as `ledger.find_intent`.

- [ ] **Step 1: Write the failing tests**

```python
# py-hftbacktest/tests/test_polymarket_order_router.py
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from hftbacktest.polymarket_live import ledger
from hftbacktest.polymarket_live.dry_run import DryRunExecutionClient, DryRunOrderResult
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide, PolymarketTimeInForce
from hftbacktest.polymarket_live.order_router import OrderRouter


def _intent(**overrides):
    base = dict(
        token_id="111", side=PolymarketSide.BUY, price=Decimal("0.5"),
        size=Decimal("10"), time_in_force=PolymarketTimeInForce.GTC,
        idempotency_key="fixed-key",
    )
    base.update(overrides)
    return PolymarketOrderIntent(**base)


class TestOrderRouter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = ledger.connect(Path(self._tmp.name) / "ledger.sqlite3")
        ledger.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_submit_forces_fok_even_if_caller_passed_gtc(self):
        client = DryRunExecutionClient()
        router = OrderRouter(client, self.conn)

        router.submit(_intent(time_in_force=PolymarketTimeInForce.GTC))

        row = ledger.find_intent(self.conn, "fixed-key")
        self.assertEqual(row["order_type"], "FOK")

    def test_submit_is_idempotent_on_retry(self):
        client = MagicMock()
        client.place_limit_order.return_value = DryRunOrderResult(
            ok=True, order_id="ORDER-1", status="matched",
            making_amount=Decimal("10"), taking_amount=Decimal("5"),
        )
        router = OrderRouter(client, self.conn)

        first = router.submit(_intent())
        second = router.submit(_intent())  # simulate a retry after a crash

        self.assertEqual(client.place_limit_order.call_count, 1)
        self.assertEqual(first["order_id"], "ORDER-1")
        self.assertEqual(second["order_id"], "ORDER-1")

    def test_submit_resolves_stuck_submitting_row_via_get_order_before_retrying(self):
        # Simulate a crash: an order_id was already learned (the SDK call
        # returned before the process died), but record_result() never ran
        # to mark it accepted/rejected -- it's stuck in "submitting".
        stuck_intent = _intent()
        ledger.record_intent(self.conn, stuck_intent, status="submitting")
        ledger.record_result(self.conn, stuck_intent.idempotency_key, status="submitting", order_id="ORDER-PENDING")

        client = MagicMock()
        client.get_order.return_value = DryRunOrderResult(
            ok=True, order_id="ORDER-RECOVERED", status="matched",
            making_amount=Decimal("10"), taking_amount=Decimal("5"),
        )
        router = OrderRouter(client, self.conn)

        result = router.submit(stuck_intent)

        client.get_order.assert_called_once()
        client.place_limit_order.assert_not_called()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["order_id"], "ORDER-RECOVERED")

    def test_submit_records_rejected_result(self):
        client = MagicMock()
        client.place_limit_order.return_value = DryRunOrderResult(
            ok=False, order_id=None, status="rejected",
            making_amount=Decimal("0"), taking_amount=Decimal("0"),
        )
        router = OrderRouter(client, self.conn)

        result = router.submit(_intent())

        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(result["order_id"])

    def test_cancel_delegates_to_execution_client(self):
        client = DryRunExecutionClient()
        router = OrderRouter(client, self.conn)
        placed = router.submit(_intent())

        result = router.cancel(placed["order_id"])

        self.assertEqual(result["canceled"], [placed["order_id"]])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_order_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hftbacktest.polymarket_live.order_router'`

- [ ] **Step 3: Write the implementation**

```python
# py-hftbacktest/hftbacktest/polymarket_live/order_router.py
from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Optional

from . import ledger
from .models import PolymarketOrderIntent, PolymarketTimeInForce


class OrderRouter:
    """Idempotent, all-or-nothing wrapper around an execution client.

    `execution_client` is either DryRunExecutionClient or the real
    PolymarketExecutionClient -- both expose place_limit_order/cancel_order/get_order.
    """

    def __init__(self, execution_client, conn: sqlite3.Connection) -> None:
        self._client = execution_client
        self._conn = conn

    def submit(self, intent: PolymarketOrderIntent) -> dict:
        key = intent.idempotency_key or ledger.derive_idempotency_key(intent)
        forced = replace(intent, time_in_force=PolymarketTimeInForce.FOK, idempotency_key=key)

        existing = ledger.find_intent(self._conn, key)
        if existing is not None and existing["status"] == "submitting":
            return self._resolve_stuck(key, existing)
        if existing is not None:
            return existing  # already resolved (accepted/rejected) -- do not resubmit

        ledger.record_intent(self._conn, forced, status="submitting")
        result = self._client.place_limit_order(forced)
        status = "accepted" if result.ok else "rejected"
        order_id = result.order_id if result.ok else None
        ledger.record_result(self._conn, key, status=status, order_id=order_id)
        return ledger.find_intent(self._conn, key)

    def cancel(self, order_id: str) -> dict:
        return self._client.cancel_order(order_id)

    def _resolve_stuck(self, key: str, existing: dict) -> dict:
        # Crash recovery: never assume what happened to a "submitting" order --
        # ask Polymarket directly before doing anything else with this key.
        order_id = existing.get("order_id")
        if order_id:
            real = self._client.get_order(order_id)
            status = "accepted" if real.ok else "rejected"
            ledger.record_result(self._conn, key, status=status, order_id=real.order_id)
        else:
            # We never even learned an order_id before crashing -- there is
            # nothing to query, so this requires manual review, not a guess.
            ledger.record_result(self._conn, key, status="unknown_needs_manual_review", order_id=None)
        return ledger.find_intent(self._conn, key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_order_router.py -v`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/hftbacktest/polymarket_live/order_router.py py-hftbacktest/tests/test_polymarket_order_router.py
git commit -m "Add OrderRouter: idempotent FOK submission with crash recovery"
```

---

## Task 5: `reconciliation.py` — compare ledger position vs. real Polymarket position

**Files:**
- Create: `py-hftbacktest/hftbacktest/polymarket_live/reconciliation.py`
- Test: `py-hftbacktest/tests/test_polymarket_reconciliation.py` (new)

**Interfaces:**
- Consumes: `ledger.connect/init_schema/record_fill` (Task 2) for test setup.
- Produces:
  - `local_position(conn, token_id: str) -> Decimal` — sums `fills.size` for that token (positive for BUY, negative for SELL), derived from the joined `order_intents.side`.
  - `fetch_remote_positions(wallet: str) -> dict[str, Decimal]` — calls `https://data-api.polymarket.com/positions?user={wallet}&limit=500`, returns `{asset/token_id: size}`. Verified live against the real endpoint this round: response is a JSON array of objects with `asset` (token id, string) and `size` (float) fields.
  - `reconcile(conn, wallet: str, token_ids: list[str]) -> list[dict]` — for each token id, compares `local_position` vs the matching entry in `fetch_remote_positions`, writes a row to `reconciliation_log`, returns the rows written.

- [ ] **Step 1: Write the failing test**

```python
# py-hftbacktest/tests/test_polymarket_reconciliation.py
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from hftbacktest.polymarket_live import ledger, reconciliation
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = ledger.connect(Path(self._tmp.name) / "ledger.sqlite3")
        ledger.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _seed_fill(self, token_id, side, size, key):
        intent = PolymarketOrderIntent(token_id=token_id, side=side, price=Decimal("0.5"), size=Decimal(size), idempotency_key=key)
        ledger.record_intent(self.conn, intent, status="accepted")
        ledger.record_fill(self.conn, key, fill_id=f"fill-{key}", price=Decimal("0.5"), size=Decimal(size), fee=Decimal("0"), filled_at=1782200000)

    def test_local_position_sums_buys_positive(self):
        self._seed_fill("TOKEN-A", PolymarketSide.BUY, "10", "k1")
        self._seed_fill("TOKEN-A", PolymarketSide.BUY, "5", "k2")
        self.assertEqual(reconciliation.local_position(self.conn, "TOKEN-A"), Decimal("15"))

    def test_local_position_subtracts_sells(self):
        self._seed_fill("TOKEN-A", PolymarketSide.BUY, "10", "k1")
        self._seed_fill("TOKEN-A", PolymarketSide.SELL, "4", "k2")
        self.assertEqual(reconciliation.local_position(self.conn, "TOKEN-A"), Decimal("6"))

    @patch("hftbacktest.polymarket_live.reconciliation.fetch_remote_positions")
    def test_reconcile_flags_mismatch(self, mock_fetch):
        self._seed_fill("TOKEN-A", PolymarketSide.BUY, "10", "k1")
        mock_fetch.return_value = {"TOKEN-A": Decimal("999")}  # deliberately wrong

        rows = reconciliation.reconcile(self.conn, wallet="0xabc", token_ids=["TOKEN-A"])

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["mismatch"])
        logged = self.conn.execute("SELECT mismatch FROM reconciliation_log").fetchone()
        self.assertEqual(logged[0], 1)

    @patch("hftbacktest.polymarket_live.reconciliation.fetch_remote_positions")
    def test_reconcile_no_mismatch_when_equal(self, mock_fetch):
        self._seed_fill("TOKEN-A", PolymarketSide.BUY, "10", "k1")
        mock_fetch.return_value = {"TOKEN-A": Decimal("10")}

        rows = reconciliation.reconcile(self.conn, wallet="0xabc", token_ids=["TOKEN-A"])

        self.assertFalse(rows[0]["mismatch"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_reconciliation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hftbacktest.polymarket_live.reconciliation'`

- [ ] **Step 3: Write the implementation**

```python
# py-hftbacktest/hftbacktest/polymarket_live/reconciliation.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_reconciliation.py -v`
Expected: `OK` (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/hftbacktest/polymarket_live/reconciliation.py py-hftbacktest/tests/test_polymarket_reconciliation.py
git commit -m "Add reconciliation: compare local ledger position vs Polymarket /positions"
```

---

## Task 6: Historical backfill script

**Files:**
- Create: `research/backfill_polymarket_ledger.py`

**Interfaces:**
- Consumes: `ledger.connect/init_schema/record_intent/record_fill` (Task 2); reuses the `get()` HTTP-retry helper pattern already established in `research/predictparity_weather_profile.py:32-44` (urllib + retries, same `data-api.polymarket.com` host).
- Produces: a populated ledger DB at `research/data/polymarket_ledger/ledger.sqlite3` with one `order_intents`/`fills` row per historical `TRADE` activity entry for the given wallet, `idempotency_key="backfill:" + transactionHash`, `status="backfilled"`.

This task has no unit test (it's a one-time, real-network, real-wallet operational script — the thing being tested is "does it run cleanly against the real wallet today," done in Step 3 below, not a mocked unit test). This matches the existing `research/*.py` convention (no test suite for one-shot data scripts, verified earlier in this engagement).

- [ ] **Step 1: Write the script**

```python
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
```

- [ ] **Step 2: Run it against the user's real wallet (read-only)**

Run: `.venv/bin/python3 research/backfill_polymarket_ledger.py --wallet <USER_WALLET_ADDRESS>` (run from repo root; must use the project `.venv` interpreter, not bare `python3`, so `hftbacktest.polymarket_live` resolves to the real installed package)
Expected: prints `backfilled N new fill(s) into research/data/polymarket_ledger/ledger.sqlite3` with `N >= 0`. This is the one place in this plan where real, user-specific input (their wallet address) is required — get it from the user before running, do not guess or reuse a wallet address seen elsewhere in this repo's research data.

- [ ] **Step 3: Spot-check against the real position**

```bash
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'py-hftbacktest')
from pathlib import Path
from hftbacktest.polymarket_live import ledger, reconciliation
conn = ledger.connect(Path('research/data/polymarket_ledger/ledger.sqlite3'))
# pick any token_id this wallet actually holds, from the real /positions response
remote = reconciliation.fetch_remote_positions('<USER_WALLET_ADDRESS>')
for token_id, size in list(remote.items())[:5]:
    local = reconciliation.local_position(conn, token_id)
    print(token_id, 'local=', local, 'remote=', size)
"
```
Expected: `local` and `remote` match (or are close — `/activity` TRADE rows don't include REDEEM/MERGE adjustments, so exact equality isn't guaranteed for every token; large unexplained gaps are worth a manual look, not silently ignored).

- [ ] **Step 4: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add research/backfill_polymarket_ledger.py
git commit -m "Add one-time historical backfill script for the Polymarket ledger"
```

---

## Task 7: End-to-end dry-run smoke test

**Files:**
- Test: `py-hftbacktest/tests/test_polymarket_e2e.py` (new)

**Interfaces:**
- Consumes everything from Tasks 1-4 together; no new production code.

- [ ] **Step 1: Write the test**

```python
# py-hftbacktest/tests/test_polymarket_e2e.py
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from hftbacktest.polymarket_live import ledger
from hftbacktest.polymarket_live.dry_run import DryRunExecutionClient
from hftbacktest.polymarket_live.models import PolymarketOrderIntent, PolymarketSide
from hftbacktest.polymarket_live.order_router import OrderRouter


class TestEndToEndDryRun(unittest.TestCase):
    def test_full_intent_to_ledger_round_trip_with_no_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = ledger.connect(Path(tmp) / "ledger.sqlite3")
            ledger.init_schema(conn)
            router = OrderRouter(DryRunExecutionClient(), conn)

            intent = PolymarketOrderIntent(
                token_id="WEATHER-TOKEN-1", side=PolymarketSide.SELL,
                price=Decimal("0.97"), size=Decimal("5"), idempotency_key="e2e-key",
            )
            result = router.submit(intent)

            self.assertEqual(result["status"], "accepted")
            self.assertTrue(result["order_id"].startswith("DRYRUN-"))

            # Retrying the exact same intent must not place a second order.
            retry_result = router.submit(intent)
            self.assertEqual(retry_result["order_id"], result["order_id"])

            conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_e2e.py -v`
Expected: `OK` (1 test) — this test requires Tasks 1-4 to already be committed; if it fails on import errors, an earlier task was skipped or is broken.

- [ ] **Step 3: Run the full new test suite together**

Run: `cd py-hftbacktest && /Users/jwu104/Desktop/pm-hftbacktest/.venv/bin/python3 -m unittest tests/test_polymarket_models.py tests/test_polymarket_ledger.py tests/test_polymarket_dry_run.py tests/test_polymarket_order_router.py tests/test_polymarket_reconciliation.py tests/test_polymarket_e2e.py -v`
Expected: `OK` (21 tests total)

- [ ] **Step 4: Commit**

```bash
cd /Users/jwu104/Desktop/pm-hftbacktest
git add py-hftbacktest/tests/test_polymarket_e2e.py
git commit -m "Add end-to-end dry-run smoke test for the order router + ledger"
```
