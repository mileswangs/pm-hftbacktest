======================
Polymarket HftBacktest
======================

|pypi| |python| |license|

.. |pypi| image:: https://img.shields.io/pypi/v/pm-hftbacktest.svg
   :target: https://pypi.org/project/pm-hftbacktest/
   :alt: PyPI version

.. |python| image:: https://img.shields.io/pypi/pyversions/pm-hftbacktest.svg
   :target: https://pypi.org/project/pm-hftbacktest/
   :alt: Python versions

.. |license| image:: https://img.shields.io/github/license/mileswangs/pm-hftbacktest.svg
   :target: https://github.com/mileswangs/pm-hftbacktest/blob/main/LICENSE
   :alt: License

**High-frequency trading and market-making backtesting for Polymarket, written in Rust.**

Key Features
============

* Tick-level Polymarket backtesting
* Fast execution with `Numba <https://numba.pydata.org/>`_ JIT and Rust
* Supports Polymarket, Polymarket US, Predict.fun and Kalshi, each with its fee model
* Compatible with the hftbacktest ecosystem

Quick Start
===========

Installation
------------

.. code-block:: console

   pip install pm-hftbacktest

Data
----

Polymarket data is available for **free** from pmdata.dev. Get an API key from
`pmdata.dev <https://pmdata.dev/>`_ before running the example.

Example
=======

.. code-block:: python

   from hftbacktest import (
       init_orderbook,
       polymarket_to_hbt,
       BacktestAssetPoly,
       ROIVectorMarketDepthBacktest,
       Recorder,
       GTC,
       LIMIT,
   )
   from hftbacktest.stats import PolyAssetRecord
   from datetime import datetime, timezone
   import pandas as pd
   from numba import njit
   import numpy as np


   # Endgame trading strategy.
   @njit
   def endgame_trading(
       hbt,
       recorder,
       up_trigger: float,
       stop_long: float,
       order_qty: float,
   ):
       asset_no = 0

       if not init_orderbook(hbt, asset_no):
           return

       hbt_tick_size = hbt.depth(asset_no).tick_size
       price_tick_size = 0.01

       # Strategy state: enter once and stop once to avoid repeated
       # open/close cycles in the same endgame move.
       activated = False
       # side=1 means buying UP; side=-1 means buying DOWN, represented
       # as selling the UP contract.
       side = 0
       submitted_once = False
       stop_submitted = False

       up_trigger = min(max(up_trigger, price_tick_size), 1.0 - price_tick_size)
       down_trigger = 1.0 - up_trigger

       # stop_long is the UP long stop level. The DOWN side uses the
       # symmetric stop_short level.
       stop_long = min(max(stop_long, price_tick_size), 1.0 - price_tick_size)
       stop_short = 1.0 - stop_long
       order_qty = np.float64(max(order_qty, 0.0))

       # Run strategy logic every 100ms.
       while hbt.elapse(100_000_000) == 0:
           hbt.clear_inactive_orders(asset_no)
           depth = hbt.depth(asset_no)

           # Use the mid price as the trigger price to reduce one-sided
           # order book noise.
           bid, ask = depth.best_bid, depth.best_ask
           mid = (bid + ask) / 2.0

           # Enter the endgame certainty zone: buy UP on an upside break
           # and buy DOWN on a downside break.
           if not activated:
               if mid >= up_trigger:
                   activated = True
                   side = 1
               elif mid <= down_trigger:
                   activated = True
                   side = -1

           # Submit the entry order only once after the trigger.
           if activated and (not submitted_once):
               if side > 0:
                   p = up_trigger
               else:
                   p = down_trigger

               p = round(p / price_tick_size) * price_tick_size
               p = max(price_tick_size, min(1.0 - price_tick_size, p))

               # For a single-submit example, use the price tick index
               # directly as the order id.
               oid = np.uint64(round(p / hbt_tick_size))

               if side > 0:
                   hbt.submit_buy_order(asset_no, oid, p, order_qty, GTC, LIMIT, False)
               else:
                   hbt.submit_sell_order(asset_no, oid, p, order_qty, GTC, LIMIT, False)
               submitted_once = True

           # position is the net position in the UP contract: positive means
           # holding UP, while negative can be interpreted as holding DOWN.
           pos = hbt.position(asset_no)
           if (not stop_submitted) and (pos != 0):
               need_stop = (pos > 0 and mid <= stop_long) or (
                   pos < 0 and mid >= stop_short
               )
               if need_stop:
                   close_qty = np.float64(np.abs(pos))
                   if pos > 0:
                       px = (
                           round((bid - price_tick_size) / price_tick_size)
                           * price_tick_size
                       )
                       px = max(price_tick_size, min(1.0 - price_tick_size, px))
                       oid = np.uint64(round(px / hbt_tick_size))
                       hbt.submit_sell_order(
                           asset_no, oid, px, close_qty, GTC, LIMIT, False
                       )
                   else:
                       px = (
                           round((ask + price_tick_size) / price_tick_size)
                           * price_tick_size
                       )
                       px = max(price_tick_size, min(1.0 - price_tick_size, px))
                       oid = np.uint64(round(px / hbt_tick_size))
                       hbt.submit_buy_order(
                           asset_no, oid, px, close_qty, GTC, LIMIT, False
                       )
                   stop_submitted = True

           recorder.record(hbt)

       recorder.record(hbt)


   slug = "btc-updown-15m-1778263200"
   # The date in the URL is the UTC day the market opens.
   date = datetime.fromtimestamp(int(slug.rsplit("-", 1)[1]), timezone.utc).strftime("%Y/%m/%d")
   api_key = "<YOUR_API_KEY>"
   storage_options = {"api_key": api_key, "User-Agent": "Mozilla/5.0"}

   l2_df = pd.read_parquet(
       f"https://api.pmdata.dev/v1/polymarket/l2/{date}/{slug}.parquet",
       storage_options=storage_options,
   )
   trade_df = pd.read_parquet(
       f"https://api.pmdata.dev/v1/polymarket/trades/{date}/{slug}.parquet",
       storage_options=storage_options,
   )

   data = polymarket_to_hbt(l2_df, trade_df=trade_df)

   asset = (
       BacktestAssetPoly()
       .data(data)
       .binary_fee_model(
           maker_fee_rate=-0.07 * 0.2,
           taker_fee_rate=0.07,
       )
   )
   hbt = ROIVectorMarketDepthBacktest([asset])
   recorder = Recorder(hbt.num_assets, 5_000_000)

   endgame_trading(
       hbt,
       recorder.recorder,
       up_trigger=0.84,
       stop_long=0.4,
       order_qty=5,
   )
   _ = hbt.close()

   BOOK_SIZE = 100
   stats = PolyAssetRecord(recorder.get(0)).resample("1s").stats(book_size=BOOK_SIZE)
   print(f"earn: {stats.earn}")
   stats.plot()

Fee curves
----------

``binary_fee_model(maker_fee_rate, taker_fee_rate, fee_curve="auto")`` charges
``quantity * rate * weight(price)`` on every fill. The weight is the fee curve, which ``"auto"``
takes from the preset:

* ``BacktestAssetPoly``: ``quadratic``, ``price * (1 - price)`` (Polymarket)
* ``BacktestAssetPolyUS``: ``quadratic``, ``price * (1 - price)`` (Polymarket US)
* ``BacktestAssetKalshi``: ``quadratic``, ``price * (1 - price)`` (Kalshi)
* ``BacktestAssetPredictFun``: ``linear``, ``min(price, 1 - price)`` (Predict.fun)

Pass ``fee_curve="linear"`` or ``"quadratic"`` to override it.

Predict.fun
===========

pmdata.dev also records Predict.fun (``predict_fun/l2``: one complete book per row, priced in
the market's first outcome, no public trade channel). ``predict_fun_to_hbt`` turns the books
into depth deltas and appends the settlement book once you know the winner (the Predict.fun
REST API, ``GET /v1/markets/{id}``):

.. code-block:: python

   from hftbacktest import BacktestAssetPredictFun, predict_fun_to_hbt

   market_id = 2792904  # btc-updown-5m-1790813400 (the pmdata markets catalog maps slugs to ids)
   l2_df = pd.concat(
       pd.read_parquet(
           f"https://api.pmdata.dev/v1/predict_fun/l2/{day}/{market_id}.parquet",
           storage_options=storage_options,
       )
       for day in ("2026/09/30", "2026/10/01")  # a market is created the day before its slot
   )
   # every row is a complete book, so slice l2_df to choose where the replay starts
   l2_df = l2_df[l2_df["timestamp"] >= "2026-10-01 00:05"]
   data = predict_fun_to_hbt(l2_df, settle_price=1.0)  # the first outcome (Up) won
   asset = BacktestAssetPredictFun().data(data).binary_fee_model(0.0, 0.02)  # taker 2%, maker 0

``predict_fun_to_hbt(l2_df, trade_df=None, settle_price=None)`` has the shape of
``polymarket_to_hbt``: there is no Predict.fun trade data (passing ``trade_df`` warns), and
``settle_price`` (1, 0, or 0.5 for a tie) must be given because the Predict.fun L2 data carries no
resolution (Polymarket's does, so there it is optional; without one the stats settle by the last
price). ``BinaryAssetRecord`` (``PolyAssetRecord`` is the same class)
computes the stats for both.

Polymarket US
=============

pmdata.dev also records Polymarket US (polymarket.us): ``polymarket_us/l2`` (one complete book
per row) and ``polymarket_us/trades``, one file per market per UTC day, both priced in the
market's long outcome (``yes_outcome`` in the
`markets catalog <https://public-data.pmdata.dev/v1/polymarket_us/markets.parquet>`_).
``polymarket_us_to_hbt`` turns the books into depth deltas, adds the trades by the taker's side
and appends the settlement book once you know the winner (the Polymarket US API, no key
needed):

.. code-block:: python

   import requests
   from hftbacktest import BacktestAssetPolyUS, polymarket_us_to_hbt

   slug = "aec-nfl-pit-cle-2026-10-01"  # Steelers (the long outcome) at Browns
   days = ("2026/10/01", "2026/10/02")  # the UTC days to replay, within the catalog's record_start..record_end

   def read(data_type):
       return pd.concat(
           pd.read_parquet(
               f"https://api.pmdata.dev/v1/polymarket_us/{data_type}/{day}/{slug}.parquet",
               storage_options=storage_options,
           )
           for day in days
       )

   l2_df, trade_df = read("l2"), read("trades")  # a trades file exists only for a day with trades
   settlement = requests.get(f"https://gateway.polymarket.us/v1/markets/{slug}/settlement").json()
   data = polymarket_us_to_hbt(l2_df, trade_df=trade_df, settle_price=float(settlement["settlement"]))
   asset = BacktestAssetPolyUS().data(data).binary_fee_model(0.0, 0.095)

``polymarket_us_to_hbt(l2_df, trade_df=None, settle_price=None)`` has the shape of
``polymarket_to_hbt``. ``settle_price`` (1, 0, or 0.5 for a tie) must be given because the
Polymarket US data carries no resolution; without one the stats settle by the last price. The
market ``state`` column (open, halted, closed, ...) is not modelled: a halted market's book is
replayed as it was sent. A Polymarket US market quotes on its own tick of 0.01, 0.005 or 0.0025
(``orderPriceMinTickSize`` of ``GET https://gateway.polymarket.us/v1/market/slug/{slug}``), so
``BacktestAssetPolyUS`` has a ``tick_size`` of 0.0001 where ``BacktestAssetPoly`` has 0.001:
quote on the market's tick, not the preset's.

Polymarket US charges the taker ``coefficient * contracts * price * (1 - price)``, with a
coefficient of 0.095 falling to 0.0695 as 30-day volume grows, and pays makers a rebate of up to
0.0104 on the same curve (`fee schedule <https://docs.polymarket.us/fees>`_, as of November
2026), hence the ``quadratic`` curve and ``binary_fee_model(0.0, 0.095)`` above.

Up/Down market files from before 2026-11-08 are incomplete and pmdata serves them only with
``?include_incomplete=true`` appended to the URL.

Kalshi
======

`kacdata.com <https://kacdata.com/>`_ records Kalshi: ``kalshi/l2`` (a book snapshot followed by
signed deltas) and ``kalshi/trades``, one file per market per UTC day, and ``kalshi/lifecycle``,
one file per UTC day for all markets (the
`markets catalog <https://api.kacdata.com/v1/kalshi/markets.parquet>`_ lists the tickers and
their days). A Kalshi book holds YES bids and NO bids. ``kalshi_to_hbt`` prices it in YES (a NO
bid at ``p`` is a YES ask at ``1 - p``), replays the L2 file in its own order, adds the trades
by the outcome the taker bought and appends the settlement book for the settlement value in the
lifecycle data:

.. code-block:: python

   from hftbacktest import BacktestAssetKalshi, kalshi_to_hbt
   from hftbacktest.data.utils.kalshi import kalshi_settle_price

   ticker = "KXMLBGAME-26OCT132000CLETB-CLE"  # Cleveland wins
   days = ("2026/10/13", "2026/10/14")  # UTC days in order, within the catalog's record_start..record_end
   storage_options = {"api_key": "<YOUR_KACDATA_API_KEY>"}

   def read(data_type, day, name):
       return pd.read_parquet(
           f"https://api.kacdata.com/v1/kalshi/{data_type}/{day}/{name}.parquet",
           storage_options=storage_options,
       )

   l2_df = pd.concat(read("l2", day, ticker) for day in days)  # keep the files' order: do not sort
   trade_df = pd.concat(read("trades", day, ticker) for day in days)  # a trades file exists only for a day with trades
   # the lifecycle file of the UTC day the market was determined
   settle_price = kalshi_settle_price(read("lifecycle", days[-1], "markets_lifecycle"), ticker)
   data = kalshi_to_hbt(l2_df, trade_df=trade_df, settle_price=settle_price)
   asset = BacktestAssetKalshi().data(data).binary_fee_model(0.0175, 0.07)

``kalshi_to_hbt(l2_df, trade_df=None, settle_price=None)`` has the shape of
``polymarket_to_hbt``. The deltas are increments to the book before them, not new sizes, so the
rows must stay in the files' order and start where a file starts: every day's L2 file opens with
the book at the start of that day, so the replay can start at any day but not within one (a
slice that starts later has no book to add its deltas to). ``settle_price`` is 1, 0,
or 0.5; a market settled at another value is not supported, and without one the stats settle by
the last price. Kalshi prices have four decimals, so ``BacktestAssetKalshi`` has a ``tick_size``
of 0.0001, while a market quotes on its own tick of 0.01 or 0.001: quote on that.

Kalshi charges the taker ``0.07 * contracts * price * (1 - price)`` and, in the series with
maker fees, the maker ``0.0175 * contracts * price * (1 - price)``, both times the event's fee
multiplier (the lifecycle data's ``event_fee_update`` messages carry an event's fee type and
multiplier), hence the ``quadratic`` curve. Kalshi rounds an order's fees up to its balance
precision, which is not modelled.
