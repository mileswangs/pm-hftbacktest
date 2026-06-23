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
