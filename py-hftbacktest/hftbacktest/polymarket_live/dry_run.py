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
