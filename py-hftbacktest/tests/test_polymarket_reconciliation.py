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
