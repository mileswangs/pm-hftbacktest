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

    def test_submit_marks_stuck_row_with_no_order_id_as_needs_manual_review(self):
        # Simulate a crash that happened *before* place_limit_order ever
        # returned (or before its result was recorded): the row exists and is
        # stuck in "submitting", but order_id is still NULL. There is nothing
        # to query the exchange about, so the router must not guess -- it
        # should flag this for manual review without calling place_limit_order
        # or get_order at all.
        stuck_intent = _intent()
        ledger.record_intent(self.conn, stuck_intent, status="submitting")
        # order_id stays NULL (the default from record_intent's INSERT).

        client = MagicMock()
        router = OrderRouter(client, self.conn)

        result = router.submit(stuck_intent)

        client.get_order.assert_not_called()
        client.place_limit_order.assert_not_called()
        self.assertEqual(result["status"], "unknown_needs_manual_review")
        self.assertIsNone(result["order_id"])

    def test_submit_leaves_row_submitting_if_get_order_raises_during_recovery(self):
        # Simulate a crash where an order_id was learned before the process
        # died, but when we try to recover by asking the exchange about it,
        # the get_order() call itself fails (unknown order_id on the exchange
        # side, transient network error, etc). We must not guess
        # accepted/rejected in this case -- the row should remain
        # "submitting" so a later submit() call retries recovery, and the
        # exception must not propagate out of submit().
        stuck_intent = _intent()
        ledger.record_intent(self.conn, stuck_intent, status="submitting")
        ledger.record_result(self.conn, stuck_intent.idempotency_key, status="submitting", order_id="ORDER-PENDING")

        client = MagicMock()
        client.get_order.side_effect = RuntimeError("exchange lookup failed")
        router = OrderRouter(client, self.conn)

        result = router.submit(stuck_intent)

        client.get_order.assert_called_once()
        client.place_limit_order.assert_not_called()
        self.assertEqual(result["status"], "submitting")
        self.assertEqual(result["order_id"], "ORDER-PENDING")

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


class TestOrderRouterRealClientGuard(unittest.TestCase):
    """Covers the dry-run-only guard described at the top of order_router.py:
    OrderRouter must refuse the real PolymarketExecutionClient unless the
    caller explicitly confirms the US-jurisdiction and real-money risk.
    Plain test doubles (e.g. bare MagicMock(), as used throughout
    TestOrderRouter above) are not the real client and remain unaffected.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = ledger.connect(Path(self._tmp.name) / "ledger.sqlite3")
        ledger.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _real_client(self):
        from hftbacktest.polymarket_live.config import PolymarketSettings
        from hftbacktest.polymarket_live.execution import PolymarketExecutionClient

        # Constructing PolymarketExecutionClient does not touch the network
        # (the SDK is imported lazily inside its methods), so this is safe to
        # instantiate directly in a test as a stand-in for "the real client".
        return PolymarketExecutionClient(settings=PolymarketSettings(private_key="test-key"))

    def test_dry_run_client_is_allowed_with_no_flag(self):
        client = DryRunExecutionClient()

        router = OrderRouter(client, self.conn)

        self.assertIs(router._client, client)

    def test_plain_mock_client_is_allowed_with_no_flag(self):
        # A bare MagicMock() standing in for "not the real client" (as used
        # throughout TestOrderRouter) must keep working unflagged -- the
        # guard targets the real PolymarketExecutionClient specifically, not
        # every object that isn't literally a DryRunExecutionClient.
        not_dry_run = MagicMock()

        router = OrderRouter(not_dry_run, self.conn)

        self.assertIs(router._client, not_dry_run)

    def test_real_execution_client_without_flag_raises(self):
        real_client = self._real_client()

        with self.assertRaises(RuntimeError):
            OrderRouter(real_client, self.conn)

    def test_real_execution_client_with_flag_true_is_allowed(self):
        real_client = self._real_client()

        router = OrderRouter(
            real_client,
            self.conn,
            i_confirm_non_us_jurisdiction_and_real_money_risk=True,
        )

        self.assertIs(router._client, real_client)


if __name__ == "__main__":
    unittest.main()
