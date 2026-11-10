import unittest
import numpy as np
import polars as pl

from numba import njit

from datetime import datetime

from hftbacktest import (
    BacktestAsset,
    BacktestAssetPoly,
    BacktestAssetPolyUS,
    BacktestAssetPredictFun,
    HashMapMarketDepthBacktest,
    ALL_ASSETS, ROIVectorMarketDepthBacktest,
    DEPTH_EVENT, DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT, BUY_EVENT, SELL_EVENT,
    EXCH_EVENT, LOCAL_EVENT, TRADE_EVENT, polymarket_to_hbt, polymarket_us_to_hbt, predict_fun_to_hbt
)
from hftbacktest.data import correct_local_depth_order
from hftbacktest.stats import BinaryAssetRecord, PolyAssetRecord, fix_record_prices
from hftbacktest.types import event_dtype


@njit
def test_run(hbt):
    order_id = 0
    while hbt.elapse(10_000_000_000) == 0:
        current_timestamp = hbt.current_timestamp
        depth = hbt.depth(0)
        best_bid = depth.best_bid
        best_ask = depth.best_ask

        # trades = hbt.last_trades(0)
        #
        # i = 0
        # for trade in trades:
        #     print(trade.local_ts, trade.px, trade.qty)
        #     i += 1
        #     if i > 5:
        #         break

        hbt.clear_last_trades(ALL_ASSETS)

        cnt = 0
        orders = hbt.orders(0)
        values = orders.values()
        while True:
            order = values.next()
            if order is None:
                break
            cnt += 1
            print(order.order_id, order.side, order.price_tick, order.qty)

        hbt.clear_inactive_orders(ALL_ASSETS)

        if cnt <= 2:
            hbt.submit_buy_order(0, order_id, best_bid, 1, 1, 0, False)
            order_id += 1
            hbt.submit_sell_order(0, order_id, best_ask, 1, 1, 0, False)
            order_id += 1

        print(current_timestamp, best_bid, best_ask)


def sim_book(hbt, ticks_per_unit=1000):
    depth = hbt.depth(0)
    ticks = range(ticks_per_unit + 1)
    return (
        {t / ticks_per_unit: depth.bid_qty_at_tick(t) for t in ticks if depth.bid_qty_at_tick(t) > 0},
        {t / ticks_per_unit: depth.ask_qty_at_tick(t) for t in ticks if depth.ask_qty_at_tick(t) > 0},
    )


class TestPyHftBacktest(unittest.TestCase):
    def setUp(self) -> None:
        pass

    def test_polymarket_asset_preset_allows_variable_settings(self):
        asset = (
            BacktestAssetPoly()
                .constant_order_latency(100, 100)
                .trading_value_fee_model(0.0, 0.006)
        )

        self.assertIsInstance(asset, BacktestAsset)

    def test_binary_fee_model_uses_fill_quantity_and_price(self):
        data = np.array(
            [
                (
                    DEPTH_SNAPSHOT_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
                    1_000,
                    1_000,
                    0.3,
                    100.0,
                    0,
                    0,
                    0.0,
                ),
                (
                    DEPTH_SNAPSHOT_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
                    1_000,
                    1_000,
                    0.4,
                    100.0,
                    0,
                    0,
                    0.0,
                ),
                (
                    DEPTH_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
                    1_000_000_000,
                    1_000_000_000,
                    0.3,
                    100.0,
                    0,
                    0,
                    0.0,
                ),
            ],
            dtype=event_dtype,
        )
        for backtest_cls in (HashMapMarketDepthBacktest, ROIVectorMarketDepthBacktest):
            with self.subTest(backtest_cls=backtest_cls.__name__):
                asset = (
                    BacktestAssetPoly()
                        .data(data.copy())
                        .constant_order_latency(0, 0)
                        .no_partial_fill_exchange()
                        .binary_fee_model(-0.01, 0.02)
                )
                hbt = backtest_cls([asset])

                try:
                    self.assertEqual(hbt.elapse(1), 0)
                    self.assertAlmostEqual(hbt.depth(0).best_ask, 0.4)
                    self.assertEqual(
                        hbt.submit_buy_order(0, 1, 0.4, 100.0, 0, 0, True),
                        0,
                    )
                    self.assertAlmostEqual(hbt.state_values(0).fee, 0.48)
                finally:
                    hbt.close()

    def test_fee_curve_is_chosen_by_the_asset_preset(self):
        # A taker buy of 100 at 0.4 with a 2% taker rate: 0.02 * 100 * 0.4 * 0.6 = 0.48 on the
        # quadratic curve (Polymarket), 0.02 * 100 * min(0.4, 0.6) = 0.8 on the linear one
        # (Predict.fun); the preset picks the curve, the rates stay the caller's.
        data = np.array(
            [
                (DEPTH_SNAPSHOT_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT, 1_000, 1_000, 0.3, 100.0, 0, 0, 0.0),
                (DEPTH_SNAPSHOT_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT, 1_000, 1_000, 0.4, 100.0, 0, 0, 0.0),
                (DEPTH_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT, 1_000_000_000, 1_000_000_000, 0.3, 100.0, 0, 0, 0.0),
            ],
            dtype=event_dtype,
        )
        cases = [
            (BacktestAssetPoly, 'auto', 0.48),
            (BacktestAssetPolyUS, 'auto', 0.48),
            (BacktestAssetPredictFun, 'auto', 0.8),
            (BacktestAssetPoly, 'linear', 0.8),
            (BacktestAssetPredictFun, 'quadratic', 0.48),
            (BacktestAsset, 'auto', 0.48),  # no preset: quadratic
        ]
        for asset_cls, fee_curve, expected_fee in cases:
            with self.subTest(asset=asset_cls.__name__, fee_curve=fee_curve):
                asset = (
                    asset_cls()
                        .linear_asset(1.0)
                        .tick_size(0.01)
                        .lot_size(0.01)
                        .roi_lb(0.0)
                        .roi_ub(1.0)
                        .data(data.copy())
                        .constant_order_latency(0, 0)
                        .no_partial_fill_exchange()
                        .binary_fee_model(0.0, 0.02, fee_curve=fee_curve)
                )
                hbt = ROIVectorMarketDepthBacktest([asset])
                try:
                    self.assertEqual(hbt.elapse(1), 0)
                    self.assertEqual(hbt.submit_buy_order(0, 1, 0.4, 100.0, 0, 0, True), 0)
                    self.assertAlmostEqual(hbt.state_values(0).fee, expected_fee)
                finally:
                    hbt.close()

        with self.assertRaises(ValueError):
            BacktestAsset().binary_fee_model(0.0, 0.02, fee_curve='cubic')

    def test_predict_fun_to_hbt_emits_deltas_and_settles(self):
        def book(ts, bids, asks):
            return {
                'market_id': 1,
                'timestamp': ts,
                'local_timestamp': ts + 100_000,  # pmdata stores microseconds
                'event_type': 'predictOrderbook',
                'bid_prices': [p for p, _ in bids],
                'bid_sizes': [s for _, s in bids],
                'ask_prices': [p for p, _ in asks],
                'ask_sizes': [s for _, s in asks],
                'order_count': len(bids) + len(asks),
            }

        t0 = datetime(2026, 10, 1, 0, 5)
        t0_us = int(np.datetime64(t0, 'us').astype(np.int64))
        schema = {
            'market_id': pl.Int64,
            'timestamp': pl.Datetime('us'),
            'local_timestamp': pl.Datetime('us'),
            'event_type': pl.String,
            'bid_prices': pl.List(pl.Float64),
            'bid_sizes': pl.List(pl.Float64),
            'ask_prices': pl.List(pl.Float64),
            'ask_sizes': pl.List(pl.Float64),
            'order_count': pl.Int64,
        }
        stale = book(t0_us - 600_000, [(0.5, 1.0)], [(0.51, 1.0)])  # microseconds: 600 ms before t0
        opening = book(t0_us - 300_000, [(0.49, 10.0), (0.48, 20.0)], [(0.5, 5.0), (0.51, 6.0)])
        second = book(t0_us + 1_000_000, [(0.84, 7.0)], [(0.85, 8.0)])
        resent = dict(second, local_timestamp=second['local_timestamp'] + 1_000_000)
        never = dict(book(t0_us + 2_000_000, [], []), timestamp=None)
        l2 = pl.DataFrame([resent, second, never, stale, opening], schema=schema)

        # The caller slices the books (each row is a complete one); from `opening` on: the
        # opening book (4 adds), the second book (4 removals + 2 adds), and the settlement 1 ms
        # after it (2 removals + 2 adds). `never` is dropped, `resent` deduplicated.
        l2 = l2.filter(pl.col('timestamp').is_null() | (pl.col('timestamp') >= opening['timestamp']))
        books = predict_fun_to_hbt(l2)
        settled = predict_fun_to_hbt(l2, settle_price=1.0)
        self.assertEqual(len(books), 4 + 6)
        self.assertEqual(len(settled), 4 + 6 + 4)
        opening_ns = (t0_us - 300_000) * 1_000
        self.assertEqual(int(books['exch_ts'][0]), opening_ns)
        self.assertEqual(int(books['local_ts'][0]), opening_ns + 100_000_000)
        self.assertEqual(int(settled['exch_ts'][-1]), t0_us * 1_000 + 1_000_000_000 + 1_000_000)
        self.assertTrue((settled['local_ts'] >= settled['exch_ts']).all())
        self.assertEqual(len(predict_fun_to_hbt(l2.head(0))), 0)
        with self.assertRaises(ValueError):
            predict_fun_to_hbt(l2, settle_price=0.7)
        tie = predict_fun_to_hbt(l2, settle_price=0.5)
        self.assertEqual(len(tie), 4 + 6 + 4)
        self.assertEqual(sorted(tie['px'][-4:]), [0.499, 0.501, 0.84, 0.85])
        with self.assertWarns(UserWarning):
            self.assertEqual(len(predict_fun_to_hbt(l2, trade_df=l2.head(0))), 4 + 6)
        self.assertIs(PolyAssetRecord, BinaryAssetRecord)

        # Replay the books (with a later one so the data outlasts the clock): the stale 0.49 /
        # 0.48 levels must be gone once the second book is in.
        later = book(t0_us + 10_000_000, [(0.84, 7.0)], [(0.86, 1.0)])
        with_later = predict_fun_to_hbt(pl.concat([l2, pl.DataFrame([later], schema=schema)]))
        hbt = ROIVectorMarketDepthBacktest(
            [BacktestAssetPredictFun().data(with_later).constant_order_latency(1_000_000, 1_000_000)]
        )
        try:
            self.assertEqual(hbt.elapse(200_000_000), 0)  # the opening book, 300 ms before t0
            self.assertEqual(sim_book(hbt), ({0.49: 10.0, 0.48: 20.0}, {0.5: 5.0, 0.51: 6.0}))
            self.assertEqual(hbt.elapse(1_300_000_000), 0)
            self.assertEqual(sim_book(hbt), ({0.84: 7.0}, {0.85: 8.0}))
        finally:
            hbt.close()

        # Replay to the end of the settled data: the settlement book is the final state.
        hbt = ROIVectorMarketDepthBacktest(
            [BacktestAssetPredictFun().data(settled).constant_order_latency(1_000_000, 1_000_000)]
        )
        try:
            for _ in range(20):
                if hbt.elapse(1_000_000_000) != 0:
                    break
            else:
                self.fail("replay did not reach the end of the data")
            self.assertEqual((hbt.depth(0).best_bid, hbt.depth(0).best_ask), (0.998, 1.0))
        finally:
            hbt.close()

    def test_polymarket_us_to_hbt_replays_books_and_trades(self):
        t0 = int(np.datetime64(datetime(2026, 10, 1, 0, 5), 'ns').astype(np.int64))
        ms = 1_000_000

        def book(ts, latency, bids, offers, state='MARKET_STATE_OPEN'):
            return {
                'market_slug': 'aec-nfl-pit-cle-2026-10-01',
                'timestamp': ts,
                'local_timestamp': ts + latency,
                'event_type': 'marketData',
                'bid_prices': [p for p, _ in bids],
                'bid_sizes': [s for _, s in bids],
                'offer_prices': [p for p, _ in offers],
                'offer_sizes': [s for _, s in offers],
                'state': state,
            }

        def trade(ts, price, quantity, taker_side, taker_intent, trade_id):
            return {
                'market_slug': 'aec-nfl-pit-cle-2026-10-01',
                'timestamp': ts,
                'local_timestamp': ts + 20 * ms,
                'event_type': 'trade',
                'price': price,
                'quantity': quantity,
                'maker_side': 'ORDER_SIDE_SELL' if taker_side == 'ORDER_SIDE_BUY' else 'ORDER_SIDE_BUY',
                'maker_intent': 'ORDER_INTENT_UNDEFINED',
                'taker_side': taker_side,
                'taker_intent': taker_intent,
                'trade_id': trade_id,
                'state': 'TRADE_STATE_NEW',
            }

        l2_schema = {
            'market_slug': pl.String,
            'timestamp': pl.Datetime('ns'),
            'local_timestamp': pl.Datetime('ns'),
            'event_type': pl.String,
            'bid_prices': pl.List(pl.Float64),
            'bid_sizes': pl.List(pl.Float64),
            'offer_prices': pl.List(pl.Float64),
            'offer_sizes': pl.List(pl.Float64),
            'state': pl.String,
        }
        trade_schema = {
            'market_slug': pl.String,
            'timestamp': pl.Datetime('ns'),
            'local_timestamp': pl.Datetime('ns'),
            'event_type': pl.String,
            'price': pl.Float64,
            'quantity': pl.Float64,
            'maker_side': pl.String,
            'maker_intent': pl.String,
            'taker_side': pl.String,
            'taker_intent': pl.String,
            'trade_id': pl.String,
            'state': pl.String,
        }
        # `second` is received 300 ms after it was sent, later than `third` (sent 100 ms after
        # it, received 50 ms after that); the market then closes with an empty book.
        # The market's tick is 0.0025.
        opening = book(t0, 50 * ms, [(0.575, 10.0), (0.57, 20.0)], [(0.58, 5.0), (0.5825, 6.0)])
        second = book(t0 + 1_000 * ms, 300 * ms, [(0.58, 7.0)], [(0.59, 8.0)])
        third = book(t0 + 1_100 * ms, 50 * ms, [(0.58, 7.0)], [(0.5825, 3.0), (0.59, 8.0)])
        closed = book(t0 + 2_000 * ms, 50 * ms, [], [], state='MARKET_STATE_CLOSED')
        l2 = pl.DataFrame([third, closed, opening, second], schema=l2_schema)
        # The taker's side is on the long outcome's book whatever the intent; the first trade is
        # in two day files.
        lifted = trade(t0 + 1_000 * ms, 0.58, 2.5, 'ORDER_SIDE_BUY', 'ORDER_INTENT_SELL_SHORT', 'A')
        hit = trade(t0 + 1_500 * ms, 0.58, 1.0, 'ORDER_SIDE_SELL', 'ORDER_INTENT_BUY_SHORT', 'B')
        trades = pl.DataFrame([lifted, hit, lifted], schema=trade_schema)

        # The opening book (4 adds), the second (4 removals + 2 adds), the third (1 add) and the
        # empty one (3 removals); the settlement book 1 ms after it (2 adds).
        books = polymarket_us_to_hbt(l2)
        self.assertEqual(len(books), 4 + 6 + 1 + 3)
        self.assertTrue((books['ev'] & 0xff == DEPTH_EVENT).all())
        self.assertEqual(int(books['exch_ts'][0]), t0)
        self.assertEqual(int(books['local_ts'][0]), t0 + 50 * ms)
        settled = polymarket_us_to_hbt(l2, trade_df=trades, settle_price=0.0)
        self.assertEqual(len(settled), 14 + 2 + 2)
        self.assertEqual(int(settled['exch_ts'][-1]), t0 + 2_001 * ms)
        self.assertEqual(sorted(settled['px'][-2:]), [0.001, 0.003])
        self.assertEqual(len(polymarket_us_to_hbt(l2.head(0))), 0)
        with self.assertRaises(ValueError):
            polymarket_us_to_hbt(l2, settle_price=0.7)

        trade_events = settled[settled['ev'] & 0xff == TRADE_EVENT]
        self.assertEqual(
            [(int(ev) & (BUY_EVENT | SELL_EVENT), px, qty) for ev, px, qty in trade_events[['ev', 'px', 'qty']]],
            [(BUY_EVENT, 0.58, 2.5), (SELL_EVENT, 0.58, 1.0)],
        )
        # A trade precedes the book sent at its timestamp.
        at_trade = settled[settled['exch_ts'] == t0 + 1_000 * ms]
        self.assertEqual(int(at_trade['ev'][0]) & 0xff, TRADE_EVENT)
        self.assertEqual(len(at_trade), 1 + 6)

        hbt = ROIVectorMarketDepthBacktest(
            [BacktestAssetPolyUS().data(settled).constant_order_latency(1_000_000, 1_000_000)]
        )
        try:
            # Past the third book's receipt and the late second one's: the local book is the
            # third, the newest sent.
            self.assertEqual(hbt.elapse(1_400 * ms), 0)
            self.assertEqual(sim_book(hbt, 10_000), ({0.58: 7.0}, {0.5825: 3.0, 0.59: 8.0}))
            for _ in range(20):
                if hbt.elapse(1_000_000_000) != 0:
                    break
            else:
                self.fail("replay did not reach the end of the data")
            self.assertEqual((hbt.depth(0).best_bid, hbt.depth(0).best_ask), (0.001, 0.003))
        finally:
            hbt.close()

    def test_poly_asset_record_fixes_prices_and_computes_earn(self):
        record = np.array(
            [
                (0, 10.0, 1.0, 0.40, 0.0),
                (1_000_000_000, 10.0, 1.0, 0.60, 0.5),
                (2_000_000_000, 10.0, 1.0, np.nan, 0.5),
            ],
            dtype=[
                ('timestamp', 'i8'),
                ('balance', 'f8'),
                ('position', 'f8'),
                ('price', 'f8'),
                ('fee', 'f8'),
            ],
        )

        fixed = fix_record_prices(record.copy())
        self.assertEqual(fixed['price'][-2], 1.0)
        self.assertEqual(fixed['price'][-1], 1.0)

        stats = PolyAssetRecord(record).resample('1s').stats(book_size=100.0)
        self.assertEqual(stats.earn, 10.5)

    def test_polymarket_to_hbt_uses_winning_outcome_as_final_book(self):
        data = polymarket_to_hbt(
            {
                'market_slug': ['m', 'm'],
                'timestamp': [1_000, 2_000],
                'local_timestamp': [1_100, 2_100],
                'event_type': ['book', 'market_resolved'],
                'ask_prices': [[0.6], None],
                'ask_sizes': [[10.0], None],
                'bid_prices': [[0.4], None],
                'bid_sizes': [[10.0], None],
                'best_ask': [0.6, None],
                'best_bid': [0.4, None],
                'pc_price': [None, None],
                'pc_size': [None, None],
                'pc_side': [None, None],
                'new_tick_size': [None, None],
                'trade_price': [None, None],
                'trade_size': [None, None],
                'trade_side': [None, None],
                'trade_is_mirror': [None, None],
                'winning_outcome': [None, 'Yes'],
            },
        )

        event_mask = np.uint64(
            ~(EXCH_EVENT | LOCAL_EVENT) & np.iinfo(np.uint64).max
        )
        base_ev = data['ev'] & event_mask
        bid_snapshots = data[
            (base_ev == (DEPTH_SNAPSHOT_EVENT | BUY_EVENT))
            & (data['exch_ts'] == 2_000_000_000)
        ]
        ask_snapshots = data[
            (base_ev == (DEPTH_SNAPSHOT_EVENT | SELL_EVENT))
            & (data['exch_ts'] == 2_000_000_000)
        ]

        self.assertEqual(len(bid_snapshots), 1)
        self.assertEqual(len(ask_snapshots), 1)
        self.assertEqual(bid_snapshots['px'][0], 0.998)
        self.assertEqual(bid_snapshots['qty'][0], 0.01)
        self.assertEqual(ask_snapshots['px'][0], 1.0)
        self.assertEqual(ask_snapshots['qty'][0], 0.01)

    def test_polymarket_to_hbt_takes_an_explicit_settle_price(self):
        l2 = pl.DataFrame(
            {
                'timestamp': [1_000, 2_000],
                'local_timestamp': [1_100, 2_100],
                'event_type': ['book', 'book'],
                'bid_prices': [[0.49], [0.49]],
                'bid_sizes': [[10.0], [10.0]],
                'ask_prices': [[0.51], [0.51]],
                'ask_sizes': [[10.0], [10.0]],
                'pc_price': pl.Series([None, None], dtype=pl.Float64),
                'pc_size': pl.Series([None, None], dtype=pl.Float64),
                'pc_side': pl.Series([None, None], dtype=pl.String),
            }
        )
        for settle_price, best in ((1.0, (0.998, 1.0)), (0.5, (0.499, 0.501)), (0.0, (0.001, 0.003))):
            with self.subTest(settle_price=settle_price):
                data = polymarket_to_hbt(l2, settle_price=settle_price)
                last_bid = [e for e in data if e['ev'] & BUY_EVENT and e['ev'] & EXCH_EVENT][-1]
                last_ask = [e for e in data if e['ev'] & SELL_EVENT and e['ev'] & EXCH_EVENT][-1]
                self.assertEqual((float(last_bid['px']), float(last_ask['px'])), best)
        self.assertEqual(len(polymarket_to_hbt(l2)), len(polymarket_to_hbt(l2, settle_price=1.0)) - 4)
        with self.assertRaises(ValueError):
            polymarket_to_hbt(l2, settle_price=0.7)

    def test_polymarket_to_hbt_clears_empty_snapshot_sides(self):
        data = polymarket_to_hbt(
            {
                'market_slug': ['m', 'm'],
                'timestamp': [1_000, 2_000],
                'local_timestamp': [1_100, 2_100],
                'event_type': ['book', 'book'],
                'ask_prices': [[0.6], []],
                'ask_sizes': [[10.0], []],
                'bid_prices': [[0.4], []],
                'bid_sizes': [[10.0], []],
                'best_ask': [0.6, None],
                'best_bid': [0.4, None],
                'pc_price': [None, None],
                'pc_size': [None, None],
                'pc_side': [None, None],
                'new_tick_size': [None, None],
                'trade_price': [None, None],
                'trade_size': [None, None],
                'trade_side': [None, None],
                'trade_is_mirror': [None, None],
                'winning_outcome': [None, None],
            },
        )

        event_mask = np.uint64(
            ~(EXCH_EVENT | LOCAL_EVENT) & np.iinfo(np.uint64).max
        )
        base_ev = data['ev'] & event_mask
        bid_clears = data[
            (base_ev == (DEPTH_CLEAR_EVENT | BUY_EVENT))
            & (data['exch_ts'] == 2_000_000_000)
        ]
        ask_clears = data[
            (base_ev == (DEPTH_CLEAR_EVENT | SELL_EVENT))
            & (data['exch_ts'] == 2_000_000_000)
        ]

        self.assertEqual(len(bid_clears), 1)
        self.assertEqual(len(ask_clears), 1)
        self.assertEqual(bid_clears['px'][0], 0.0)
        self.assertEqual(ask_clears['px'][0], 1.0)

    def test_correct_local_depth_order_moves_a_stale_depth_event_to_its_successor(self):
        # Sent in this order; the first depth event is received after the second, and the trade
        # last of all.
        data = np.array(
            [
                (DEPTH_EVENT | BUY_EVENT, 1, 10, 0.4, 1.0, 0, 0, 0.0),
                (DEPTH_EVENT | BUY_EVENT, 2, 5, 0.4, 2.0, 0, 0, 0.0),
                (TRADE_EVENT | SELL_EVENT, 3, 20, 0.4, 1.0, 0, 0, 0.0),
                (DEPTH_CLEAR_EVENT | BUY_EVENT, 4, 7, 0.4, 0.0, 0, 0, 0.0),
            ],
            dtype=event_dtype,
        )
        self.assertEqual(correct_local_depth_order(data)['local_ts'].tolist(), [5, 5, 20, 7])

    def test_polymarket_to_hbt_applies_a_late_book_in_the_order_sent(self):
        # The second book is received after a price change sent later than it, whose size it
        # must not undo on the local side.
        def row(ts, local_ts, event_type, bids=None, asks=None, pc=(None, None, None)):
            return {
                'market_slug': 'm',
                'timestamp': ts,
                'local_timestamp': local_ts,
                'event_type': event_type,
                'ask_prices': None if asks is None else [p for p, _ in asks],
                'ask_sizes': None if asks is None else [s for _, s in asks],
                'bid_prices': None if bids is None else [p for p, _ in bids],
                'bid_sizes': None if bids is None else [s for _, s in bids],
                'pc_side': pc[0],
                'pc_price': pc[1],
                'pc_size': pc[2],
                'winning_outcome': None,
            }

        schema = {
            'market_slug': pl.String,
            'timestamp': pl.Int64,
            'local_timestamp': pl.Int64,
            'event_type': pl.String,
            'ask_prices': pl.List(pl.Float64),
            'ask_sizes': pl.List(pl.Float64),
            'bid_prices': pl.List(pl.Float64),
            'bid_sizes': pl.List(pl.Float64),
            'pc_side': pl.String,
            'pc_price': pl.Float64,
            'pc_size': pl.Float64,
            'winning_outcome': pl.String,
        }
        bids = [(0.4, 10.0)]
        l2 = pl.DataFrame(
            [
                row(1_000, 1_010, 'book', bids, [(0.6, 10.0), (0.86, 81.0)]),
                row(1_045, 1_075, 'book', bids, [(0.6, 20.0), (0.86, 81.0)]),
                row(1_049, 1_060, 'price_change', pc=('SELL', 0.86, 88.14)),
                row(2_000, 2_010, 'book', bids, [(0.6, 20.0), (0.86, 88.14)]),
            ],
            schema=schema,
        )
        trades = pl.DataFrame(
            {'timestamp': [1_050], 'local_timestamp': [1_090], 'price': [0.6], 'size': [1.0], 'side': ['BUY']}
        )
        data = polymarket_to_hbt(l2, trade_df=trades)

        ms = 1_000_000
        late_book = data[data['exch_ts'] == 1_045 * ms]
        self.assertEqual(set(late_book['local_ts'].tolist()), {1_060 * ms})
        trade = data[data['ev'] & 0xff == TRADE_EVENT]
        self.assertEqual(trade['local_ts'].tolist(), [1_090 * ms])

        hbt = ROIVectorMarketDepthBacktest(
            [BacktestAssetPoly().data(data).constant_order_latency(1_000_000, 1_000_000)]
        )
        try:
            self.assertEqual(hbt.elapse(85 * ms), 0)  # past the late book's receipt
            self.assertEqual(sim_book(hbt), ({0.4: 10.0}, {0.6: 20.0, 0.86: 88.14}))
        finally:
            hbt.close()

    def test_polymarket_to_hbt_accepts_separate_trade_df(self):
        data = polymarket_to_hbt(
            {
                'market_slug': ['m'],
                'timestamp': [1_000],
                'local_timestamp': [1_100],
                'event_type': ['book'],
                'ask_prices': [[0.6]],
                'ask_sizes': [[10.0]],
                'bid_prices': [[0.4]],
                'bid_sizes': [[10.0]],
                'best_ask': [0.6],
                'best_bid': [0.4],
                'pc_price': [None],
                'pc_size': [None],
                'pc_side': [None],
                'new_tick_size': [None],
                'winning_outcome': [None],
            },
            trade_df={
                'market_slug': ['m', 'm'],
                'timestamp': [1_500, 1_600],
                'local_timestamp': [1_550, 1_650],
                'event_type': ['last_trade_price', 'ignored'],
                'outcome': ['Yes', 'No'],
                'price': [0.7, 0.2],
                'size': [3.0, 4.0],
                'side': ['BUY', 'SELL'],
            },
        )

        event_mask = np.uint64(
            ~(EXCH_EVENT | LOCAL_EVENT) & np.iinfo(np.uint64).max
        )
        base_ev = data['ev'] & event_mask
        trades = data[base_ev == (TRADE_EVENT | BUY_EVENT)]

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades['exch_ts'][0], 1_500_000_000)
        self.assertEqual(trades['local_ts'][0], 1_550_000_000)
        self.assertEqual(trades['px'][0], 0.7)
        self.assertEqual(trades['qty'][0], 3.0)
        self.assertEqual(trades['exch_ts'][1], 1_600_000_000)
        self.assertEqual(trades['local_ts'][1], 1_650_000_000)
        self.assertEqual(trades['px'][1], 0.8)
        self.assertEqual(trades['qty'][1], 4.0)

    def test_polymarket_to_hbt_rejects_null_trade_price(self):
        with self.assertRaises(ValueError):
            polymarket_to_hbt(
                {
                    'market_slug': ['m'],
                    'timestamp': [1_000],
                    'local_timestamp': [1_100],
                    'event_type': ['book'],
                    'ask_prices': [[0.6]],
                    'ask_sizes': [[10.0]],
                    'bid_prices': [[0.4]],
                    'bid_sizes': [[10.0]],
                    'best_ask': [0.6],
                    'best_bid': [0.4],
                    'pc_price': [None],
                    'pc_size': [None],
                    'pc_side': [None],
                    'new_tick_size': [None],
                    'winning_outcome': [None],
                },
                trade_df={
                    'timestamp': [1_500],
                    'local_timestamp': [1_550],
                    'outcome': ['Yes'],
                    'price': [None],
                    'size': [3.0],
                    'side': ['BUY'],
                },
            )

    def test_run_backtest(self):
        arr = np.load('tmp_20240501.npz')['data']

        asset = (
            BacktestAsset()
                .linear_asset(1.0)
                .data(['tmp_20240501.npz'])
                .no_partial_fill_exchange()
                .constant_latency(100, 100)
                .power_prob_queue_model3(3.0)
                .tick_size(0.000001)
                .lot_size(1.0)
                .trade_len(1000)
                .roi_lb(0.0)
                .roi_ub(1.0)
        )

        # hbt = HashMapMarketDepthMultiAssetMultiExchangeBacktest([asset])
        hbt = ROIVectorMarketDepthBacktest([asset])
        test_run(hbt)
