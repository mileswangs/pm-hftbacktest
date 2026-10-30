"""Predict.fun order books (pmdata.dev ``predict_fun/l2``) as HftBacktest events.

Each recorded row is one complete aggregated book, priced in the market's first outcome
(Up / Yes). Consecutive books are turned into per-level depth deltas: ``DEPTH_CLEAR_EVENT``
cannot be trusted to wipe a side, because a level crossed by the other side's update keeps
its size while only the best-price pointer moves, and a later clear-from-best misses it.
Predict.fun has no public trade channel, so there are no trade events.
"""

from datetime import datetime, timezone
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ...types import BUY_EVENT, DEPTH_EVENT, SELL_EVENT, event_dtype
from ..validation import correct_event_order
from .polymarket import _local_ts_ns_expr, _ts_ns_expr

PREDICT_FUN_TICK_SIZE = 0.01
SETTLE_TS_OFFSET_NS = 1_000_000
# The book appended at settlement: mid above 0.5 when the first outcome won, below when it
# lost, so ``PolyAssetRecord`` (``fix_record_prices``) settles the position at exactly 1 or 0.
SETTLE_BOOKS = {
    1.0: ([0.99], [0.01], [1.0], [0.01]),
    0.0: ([0.01], [0.01], [0.02], [0.01]),
}


def _to_ns(value: Any) -> int:
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return int(np.datetime64(value, "ns").astype(np.int64))
    return int(np.datetime64(value, "ns").astype(np.int64))


def _levels(prices: Any, sizes: Any, tick_size: float) -> dict[int, float]:
    """A side as ``tick -> size`` (empty levels dropped)."""
    prices = np.asarray([] if prices is None else prices, dtype=np.float64)
    sizes = np.asarray([] if sizes is None else sizes, dtype=np.float64)
    n = min(len(prices), len(sizes))
    ticks = np.rint(prices[:n] / tick_size).astype(np.int64)
    return {int(t): float(q) for t, q in zip(ticks, sizes[:n]) if q > 0.0}


def _delta_events(
    ts: int,
    local_ts: int,
    side: int,
    previous: dict[int, float],
    current: dict[int, float],
    tick_size: float,
) -> NDArray:
    """The depth events that turn ``previous`` into ``current``: removed and shrunk levels
    first, then new and grown ones, so the simulated book never crosses on the way."""
    changes = [(t, 0.0) for t in previous if t not in current]
    changes += [(t, q) for t, q in current.items() if q < previous.get(t, 0.0)]
    changes += [(t, q) for t, q in current.items() if q > previous.get(t, 0.0)]
    out = np.zeros(len(changes), dtype=event_dtype)
    if changes:
        out["ev"] = DEPTH_EVENT | side
        out["px"] = np.asarray([t * tick_size for t, _ in changes])
        out["qty"] = np.asarray([q for _, q in changes])
        out["exch_ts"] = ts
        out["local_ts"] = local_ts
    return out


def normalize_predict_fun_l2(l2_df: Any, start: Any | None = None) -> pl.DataFrame:
    """The books in replay order with ``ts`` / ``local_ts`` in nanoseconds: rows without a
    timestamp dropped (a never-updated empty book), sorted by ``timestamp`` then
    ``local_timestamp``, one row per ``timestamp`` (the book is re-sent on every subscription
    and can appear in two day files). With ``start`` (UTC datetime or nanoseconds), rows before
    it are replaced by the last of them, re-stamped to ``start`` with its own receive latency,
    so the replay opens with a full book."""
    df = pl.DataFrame(l2_df).filter(pl.col("timestamp").is_not_null())
    ts_expr = _ts_ns_expr(df)
    df = df.with_columns(ts_expr.alias("ts"), _local_ts_ns_expr(df, ts_expr).alias("local_ts"))
    df = df.sort(["ts", "local_ts"], maintain_order=True).unique(
        subset=["ts"], keep="first", maintain_order=True
    )
    if start is None or df.is_empty():
        return df
    start_ns = _to_ns(start)
    before = df.filter(pl.col("ts") < start_ns)
    after = df.filter(pl.col("ts") >= start_ns)
    if before.is_empty():
        return after
    opening = before.tail(1)
    latency = int(opening["local_ts"][0]) - int(opening["ts"][0])
    opening = opening.with_columns(
        pl.lit(start_ns, dtype=pl.Int64).alias("ts"),
        pl.lit(start_ns + latency, dtype=pl.Int64).alias("local_ts"),
    )
    return pl.concat([opening, after])


def predict_fun_to_hbt(
    l2_df: Any,
    settle_price: float | None = None,
    start: Any | None = None,
    tick_size: float = PREDICT_FUN_TICK_SIZE,
) -> NDArray:
    r"""
    Converts Predict.fun L2 books into an HftBacktest event array.

    Args:
        l2_df: DataFrame of pmdata ``predict_fun/l2`` rows: ``timestamp``, ``local_timestamp``,
               ``bid_prices``, ``bid_sizes``, ``ask_prices``, ``ask_sizes`` (any number of
               days; ``market_id``, ``event_type`` and ``order_count`` are ignored).
        settle_price: 1.0 when the first outcome won, 0.0 when it lost; a settlement book is
                      then appended 1 ms after the last book so the position settles. ``None``
                      appends nothing.
        start: Keep the books from this UTC time on, opening with the last book before it.
        tick_size: The market's price tick (``decimalPrecision`` 2 on crypto Up/Down markets).
    """
    if settle_price is not None and settle_price not in SETTLE_BOOKS:
        raise ValueError(f"settle_price must be 0.0 or 1.0, got {settle_price!r}")
    df = normalize_predict_fun_l2(l2_df, start)
    if df.is_empty():
        return np.zeros(0, dtype=event_dtype)

    bids: dict[int, float] = {}
    asks: dict[int, float] = {}
    parts: list[NDArray] = []

    def book(ts: int, local_ts: int, bid_prices, bid_sizes, ask_prices, ask_sizes) -> None:
        nonlocal bids, asks
        new_bids = _levels(bid_prices, bid_sizes, tick_size)
        new_asks = _levels(ask_prices, ask_sizes, tick_size)
        parts.append(_delta_events(ts, local_ts, BUY_EVENT, bids, new_bids, tick_size))
        parts.append(_delta_events(ts, local_ts, SELL_EVENT, asks, new_asks, tick_size))
        bids, asks = new_bids, new_asks

    rows = zip(
        df["ts"].to_list(),
        df["local_ts"].to_list(),
        df["bid_prices"].to_list(),
        df["bid_sizes"].to_list(),
        df["ask_prices"].to_list(),
        df["ask_sizes"].to_list(),
    )
    for ts, local_ts, bid_prices, bid_sizes, ask_prices, ask_sizes in rows:
        book(int(ts), int(local_ts), bid_prices, bid_sizes, ask_prices, ask_sizes)
    if settle_price is not None:
        last_ts = int(df["ts"][-1]) + SETTLE_TS_OFFSET_NS
        last_local_ts = int(df["local_ts"][-1]) + SETTLE_TS_OFFSET_NS
        book(last_ts, last_local_ts, *SETTLE_BOOKS[settle_price])

    data = np.concatenate(parts)
    if len(data) == 0:
        return data
    data = data[np.argsort(data["exch_ts"], kind="mergesort")]
    return correct_event_order(
        data,
        np.argsort(data["exch_ts"], kind="mergesort"),
        np.argsort(data["local_ts"], kind="mergesort"),
    )
