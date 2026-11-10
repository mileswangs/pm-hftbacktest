"""Predict.fun order books (pmdata.dev ``predict_fun/l2``) as HftBacktest events.

Each recorded row is one complete aggregated book, priced in the market's first outcome
(Up / Yes). Consecutive books are turned into per-level depth deltas: ``DEPTH_CLEAR_EVENT``
cannot be trusted to wipe a side, because a level crossed by the other side's update keeps
its size while only the best-price pointer moves, and a later clear-from-best misses it.
Predict.fun has no public trade channel, so there are no trade events.
"""

import warnings
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ...types import BUY_EVENT, DEPTH_EVENT, SELL_EVENT, event_dtype
from .polymarket import _local_ts_ns_expr, _to_event_array, _ts_ns_expr, check_settle_price

# The grid on which two books' levels are matched (prices are quoted on a coarser one); it is
# an internal key, not the asset's tick size.
LEVEL_GRID = 0.001
SETTLE_TS_OFFSET_NS = 1_000_000
# The book appended at settlement: mid above 0.5 when the first outcome won, below when it
# lost, exactly 0.5 for a tie, so ``BinaryAssetRecord`` (``fix_record_prices``) settles the
# position at 1, 0 or 0.5.
SETTLE_BOOKS = {
    1.0: ([0.998], [0.01], [1.0], [0.01]),
    0.5: ([0.499], [0.01], [0.501], [0.01]),
    0.0: ([0.001], [0.01], [0.003], [0.01]),
}


def _levels(prices: Any, sizes: Any, grid: float = LEVEL_GRID) -> dict[int, float]:
    """A side as ``grid step -> size`` (empty levels dropped)."""
    prices = np.asarray([] if prices is None else prices, dtype=np.float64)
    sizes = np.asarray([] if sizes is None else sizes, dtype=np.float64)
    n = min(len(prices), len(sizes))
    steps = np.rint(prices[:n] / grid).astype(np.int64)
    return {int(t): float(q) for t, q in zip(steps, sizes[:n]) if q > 0.0}


def _level_changes(previous: dict, current: dict) -> list[tuple]:
    """The ``(grid step, new size)`` updates that turn the side ``previous`` into ``current``:
    removed and shrunk levels first, then new and grown ones, so the simulated book never
    crosses on the way."""
    changes = [(t, 0) for t in previous if t not in current]
    changes += [(t, q) for t, q in current.items() if q < previous.get(t, 0)]
    changes += [(t, q) for t, q in current.items() if q > previous.get(t, 0)]
    return changes


def _delta_events(
    ts: int,
    local_ts: int,
    side: int,
    previous: dict[int, float],
    current: dict[int, float],
    grid: float = LEVEL_GRID,
) -> NDArray:
    """The depth events that turn ``previous`` into ``current`` (``_level_changes``)."""
    changes = _level_changes(previous, current)
    out = np.zeros(len(changes), dtype=event_dtype)
    if changes:
        out["ev"] = DEPTH_EVENT | side
        out["px"] = np.asarray([t * grid for t, _ in changes])
        out["qty"] = np.asarray([q for _, q in changes])
        out["exch_ts"] = ts
        out["local_ts"] = local_ts
    return out


def normalize_predict_fun_l2(l2_df: Any) -> pl.DataFrame:
    """The books in replay order with ``ts`` / ``local_ts`` in nanoseconds: rows without a
    timestamp dropped (a never-updated empty book), sorted by ``timestamp`` then
    ``local_timestamp``, one row per ``timestamp`` (the book is re-sent on every subscription
    and can appear in two day files)."""
    df = pl.DataFrame(l2_df).filter(pl.col("timestamp").is_not_null())
    ts_expr = _ts_ns_expr(df)
    df = df.with_columns(ts_expr.alias("ts"), _local_ts_ns_expr(df, ts_expr).alias("local_ts"))
    return df.sort(["ts", "local_ts"], maintain_order=True).unique(
        subset=["ts"], keep="first", maintain_order=True
    )


def _book_delta_events(
    df: pl.DataFrame,
    settle_price: float | None,
    grid: float = LEVEL_GRID,
) -> NDArray:
    """The depth events that replay ``df``'s books (one complete book per row, with ``ts`` /
    ``local_ts`` in nanoseconds, in replay order) as per-level deltas, followed by the
    settlement book 1 ms after the last one when ``settle_price`` is given. Levels are matched
    on ``grid``."""
    bids: dict[int, float] = {}
    asks: dict[int, float] = {}
    parts: list[NDArray] = []

    def book(ts: int, local_ts: int, bid_prices, bid_sizes, ask_prices, ask_sizes) -> None:
        nonlocal bids, asks
        new_bids = _levels(bid_prices, bid_sizes, grid)
        new_asks = _levels(ask_prices, ask_sizes, grid)
        parts.append(_delta_events(ts, local_ts, BUY_EVENT, bids, new_bids, grid))
        parts.append(_delta_events(ts, local_ts, SELL_EVENT, asks, new_asks, grid))
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

    return np.concatenate(parts)


def predict_fun_to_hbt(
    l2_df: Any,
    trade_df: Any | None = None,
    settle_price: float | None = None,
) -> NDArray:
    r"""
    Converts Predict.fun L2 books into an HftBacktest event array; the counterpart of
    ``polymarket_to_hbt``. Every row is a complete book, so the replay starts at the first row
    given: slice ``l2_df`` to choose where.

    Args:
        l2_df: DataFrame of pmdata ``predict_fun/l2`` rows: ``timestamp``, ``local_timestamp``,
               ``bid_prices``, ``bid_sizes``, ``ask_prices``, ``ask_sizes`` (any number of
               days; ``market_id``, ``event_type`` and ``order_count`` are ignored).
        trade_df: Not implemented: Predict.fun has no public trade channel, so there is no
                  trade data to convert. Passing one warns and ignores it.
        settle_price: 1.0 when the first outcome won, 0.0 when it lost, 0.5 for a tie (a
                      crypto Up/Down market whose start and end prices are equal settles half
                      each): a settlement book is appended 1 ms after the last book so the
                      position settles. ``None`` appends nothing and the stats settle by the
                      last price (the Predict.fun L2 data carries no resolution; it is in
                      pmdata's lifecycle data or the Predict.fun API).
    """
    if trade_df is not None:
        warnings.warn(
            "predict_fun_to_hbt: trade_df is not implemented (Predict.fun has no public trade "
            "channel) and is ignored",
            stacklevel=2,
        )
    check_settle_price(settle_price)
    df = normalize_predict_fun_l2(l2_df)
    if df.is_empty():
        return np.zeros(0, dtype=event_dtype)

    return _to_event_array([_book_delta_events(df, settle_price)])
