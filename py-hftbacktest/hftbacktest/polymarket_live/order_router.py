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
