======================
Polymarket HftBacktest
======================

Key Features
============

* Tick-level Polymarket backtesting
* Fast execution with `Numba <https://numba.pydata.org/>`_ JIT and Rust
* Built for strategy research and exchange execution simulation
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
   api_key = "<YOUR_API_KEY>"
   storage_options = {"api_key": api_key, "User-Agent": "Mozilla/5.0"}

   l2_df = pd.read_parquet(
       f"https://api.pmdata.dev/download/poly_l2/{slug}.parquet",
       storage_options=storage_options,
   )
   trade_df = pd.read_parquet(
       f"https://api.pmdata.dev/download/poly_trade/{slug}.parquet",
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
