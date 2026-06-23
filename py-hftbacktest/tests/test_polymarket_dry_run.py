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

    def test_get_order_raises_for_unknown_order_id(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_order("NONEXISTENT-123")
        self.assertIn("not found", str(cm.exception))

    def test_cancel_order_raises_for_unknown_order_id(self):
        with self.assertRaises(ValueError) as cm:
            self.client.cancel_order("NONEXISTENT-456")
        self.assertIn("not found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
