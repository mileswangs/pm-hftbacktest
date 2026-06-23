from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Optional

from . import ledger
from .models import PolymarketOrderIntent, PolymarketTimeInForce

# ---------------------------------------------------------------------------
# DRY-RUN ONLY -- DO NOT FLIP TO THE REAL EXECUTION CLIENT WITHOUT READING THIS
# ---------------------------------------------------------------------------
# `OrderRouter` is written against a minimal interface
# (place_limit_order/cancel_order/get_order) that is satisfied by both:
#   - DryRunExecutionClient (paper trading, no network, no real money) -- the
#     ONLY client this project is authorized to use right now.
#   - PolymarketExecutionClient (the real client: real orders, real money).
#
# Two separate things must both be true before anyone constructs this router
# with the real client:
#
#   1. This is a deliberate, later decision -- not something this branch (or
#      any branch up to this point) authorizes. Paper trading against
#      DryRunExecutionClient is the only sanctioned mode today. See
#      docs/superpowers/specs/2026-06-22-polymarket-execution-ledger-design.md
#      section 2 ("Constraints & Non-Goals").
#   2. Polymarket prohibits US persons / US-IP trading. The development
#      machine this was built on is US-based. Real order placement must NEVER
#      run from a US IP or on behalf of a US person, and whoever eventually
#      flips this on must re-confirm that this constraint still applies
#      (rules can change) *before* doing so -- not assume the rule that was
#      true when this comment was written still holds.
#
# To make it impossible to slide into live trading by accident, the
# constructor below refuses to accept the real PolymarketExecutionClient
# unless the caller explicitly passes
# `i_confirm_non_us_jurisdiction_and_real_money_risk=True`. Do not set that
# flag unless you have personally re-verified both constraints above. (The
# check below imports PolymarketExecutionClient lazily, inside __init__, to
# avoid a circular import with .execution -- the guard is a blocklist against
# the real client, not an allowlist of DryRunExecutionClient, so plain test
# doubles such as unittest.mock.MagicMock() continue to work unflagged.)
# ---------------------------------------------------------------------------


class OrderRouter:
    """Idempotent, all-or-nothing wrapper around an execution client.

    `execution_client` is either DryRunExecutionClient or the real
    PolymarketExecutionClient -- both expose place_limit_order/cancel_order/get_order.

    See the module docstring/comment above: constructing this with the real
    PolymarketExecutionClient is refused unless
    `i_confirm_non_us_jurisdiction_and_real_money_risk=True` is passed
    explicitly.
    """

    def __init__(
        self,
        execution_client,
        conn: sqlite3.Connection,
        *,
        i_confirm_non_us_jurisdiction_and_real_money_risk: bool = False,
    ) -> None:
        from .execution import PolymarketExecutionClient

        if isinstance(execution_client, PolymarketExecutionClient):
            if not i_confirm_non_us_jurisdiction_and_real_money_risk:
                raise RuntimeError(
                    "OrderRouter is dry-run-only right now: refusing to construct "
                    "with the real PolymarketExecutionClient. Switching from "
                    "DryRunExecutionClient to the real client is a deliberate "
                    "later decision, not something authorized by this code path "
                    "-- see "
                    "docs/superpowers/specs/2026-06-22-polymarket-execution-ledger-design.md "
                    "section 2. Polymarket also prohibits US persons/IPs from "
                    "trading; if you proceed, you must do so from a confirmed "
                    "non-US environment and re-verify that restriction still "
                    "applies (rules can change). If you have read and confirmed "
                    "both of those constraints, pass "
                    "i_confirm_non_us_jurisdiction_and_real_money_risk=True "
                    "explicitly to bypass this guard."
                )
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
            try:
                real = self._client.get_order(order_id)
            except Exception:
                # The exchange lookup itself failed (unknown order_id, transient
                # network error, etc). We still don't know what happened to the
                # order, so do NOT guess accepted/rejected -- leave the row in
                # "submitting" so the next submit() call retries recovery.
                return ledger.find_intent(self._conn, key)
            status = "accepted" if real.ok else "rejected"
            ledger.record_result(self._conn, key, status=status, order_id=real.order_id)
        else:
            # We never even learned an order_id before crashing -- there is
            # nothing to query, so this requires manual review, not a guess.
            ledger.record_result(self._conn, key, status="unknown_needs_manual_review", order_id=None)
        return ledger.find_intent(self._conn, key)
