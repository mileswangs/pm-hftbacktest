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
