import unittest
import numpy as np
import polars as pl

from numba import njit

from datetime import datetime

from hftbacktest import (
    BacktestAsset,
    BacktestAssetPoly,
    BacktestAssetPredictFun,
    HashMapMarketDepthBacktest,
    ALL_ASSETS, ROIVectorMarketDepthBacktest,
    DEPTH_EVENT, DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT, BUY_EVENT, SELL_EVENT,
    EXCH_EVENT, LOCAL_EVENT, TRADE_EVENT, polymarket_to_hbt, predict_fun_to_hbt
)
from hftbacktest.stats import PolyAssetRecord, fix_record_prices
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
            predict_fun_to_hbt(l2, settle_price=0.5)

        def sim_book(hbt):
            depth = hbt.depth(0)
            ticks = range(101)
            return (
                {round(t * 0.01, 2): depth.bid_qty_at_tick(t) for t in ticks if depth.bid_qty_at_tick(t) > 0},
                {round(t * 0.01, 2): depth.ask_qty_at_tick(t) for t in ticks if depth.ask_qty_at_tick(t) > 0},
            )

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
            self.assertEqual((hbt.depth(0).best_bid, hbt.depth(0).best_ask), (0.99, 1.0))
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
