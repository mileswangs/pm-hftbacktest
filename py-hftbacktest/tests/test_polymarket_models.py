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
