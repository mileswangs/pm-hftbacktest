"""Kalshi order books and trades (kacdata.com ``kalshi/l2`` and ``kalshi/trades``) as
HftBacktest events.

A Kalshi book holds bids only, YES bids and NO bids, a NO bid at ``p`` being a YES ask at
``1 - p``; the events are priced in YES. The L2 file is a book snapshot followed by signed
deltas and is replayed in the order it is in: a snapshot replaces the book and a delta adds its
size to one level. Every row becomes the new size of the levels it changes, with the sizes kept
as exact integers on the way, so a level that a delta empties is gone.
"""

import json
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ...types import BUY_EVENT, DEPTH_EVENT, SELL_EVENT, event_dtype
from .polymarket import (
    SETTLE_BOOKS,
    _local_ts_ns_expr,
    _make_trade_events_from_normalized,
    _to_event_array,
    _ts_ns_expr,
    check_settle_price,
)
from .predict_fun import SETTLE_TS_OFFSET_NS, _level_changes

# Prices and sizes are ``decimal(18, 4)``: both are counted in 1/10,000ths, and a price step is
# the tick size of ``BacktestAssetKalshi`` (a Kalshi market's own tick is 0.01 or 0.001).
UNITS = 10_000
LEVEL_GRID = 1 / UNITS


def _units(expr: pl.Expr) -> pl.Expr:
    return (expr.cast(pl.Float64) * UNITS).round().cast(pl.Int64)


def _list_units(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.List(pl.Float64)).list.eval(_units(pl.element()))


def normalize_kalshi_l2(l2_df: Any) -> pl.DataFrame:
    """The rows in the order given, with prices and sizes in ``UNITS`` and ``ts`` / ``local_ts``
    in nanoseconds. A snapshot has no ``timestamp`` and takes that of the delta before it (of
    the one after it when it comes first); ``ts`` never decreases, so sorting by it keeps the
    file's order, which is the order to replay in."""
    df = pl.DataFrame(l2_df)
    ts_expr = _ts_ns_expr(df)
    local_ts_expr = _local_ts_ns_expr(df, ts_expr)
    return df.select(
        (pl.col("event_type") == "orderbook_snapshot").alias("snapshot"),
        ts_expr.forward_fill().backward_fill().fill_null(local_ts_expr).cum_max().alias("ts"),
        local_ts_expr.alias("local_ts"),
        pl.col("delta_side"),
        _units(pl.col("delta_price")).alias("delta_price"),
        _units(pl.col("delta_size")).alias("delta_size"),
        _list_units("yes_prices"),
        _list_units("yes_sizes"),
        _list_units("no_prices"),
        _list_units("no_sizes"),
    )


def _depth_events(df: pl.DataFrame, settle_price: float | None) -> NDArray:
    bids: dict[int, int] = {}  # YES bids: price step -> size
    asks: dict[int, int] = {}  # NO bids, as YES asks at ``UNITS`` minus their price step
    events: list[tuple[int, int, int, int, int]] = []

    def replace(ts: int, local_ts: int, new_bids: dict[int, int], new_asks: dict[int, int]) -> None:
        nonlocal bids, asks
        for side, previous, current in ((BUY_EVENT, bids, new_bids), (SELL_EVENT, asks, new_asks)):
            events.extend((side, ts, local_ts, t, q) for t, q in _level_changes(previous, current))
        bids, asks = new_bids, new_asks

    for snapshot, ts, local_ts, side, price, size, yes_prices, yes_sizes, no_prices, no_sizes in df.iter_rows():
        if snapshot:
            replace(
                ts,
                local_ts,
                {p: q for p, q in zip(yes_prices or (), yes_sizes or ()) if q > 0},
                {UNITS - p: q for p, q in zip(no_prices or (), no_sizes or ()) if q > 0},
            )
            continue
        if side == "yes":
            flag, book, step = BUY_EVENT, bids, price
        else:
            flag, book, step = SELL_EVENT, asks, UNITS - price
        previous = book.get(step, 0)
        current = max(previous + size, 0)
        if current == previous:
            continue
        if current:
            book[step] = current
        else:
            del book[step]
        events.append((flag, ts, local_ts, step, current))

    if settle_price is not None:
        # 1 ms after the last change to the book: a market's last rows are the empty books of
        # its expiry and the end of its day, which change nothing.
        last_ts, last_local_ts = events[-1][1:3] if events else (df["ts"][-1], df["local_ts"][-1])
        bid_prices, bid_sizes, ask_prices, ask_sizes = (
            [round(v * UNITS) for v in values] for values in SETTLE_BOOKS[settle_price]
        )
        replace(
            last_ts + SETTLE_TS_OFFSET_NS,
            last_local_ts + SETTLE_TS_OFFSET_NS,
            dict(zip(bid_prices, bid_sizes)),
            dict(zip(ask_prices, ask_sizes)),
        )

    out = np.zeros(len(events), dtype=event_dtype)
    if events:
        side, ts, local_ts, step, size = (np.asarray(column) for column in zip(*events))
        out["ev"] = DEPTH_EVENT | side
        out["exch_ts"] = ts
        out["local_ts"] = local_ts
        out["px"] = step / UNITS
        out["qty"] = size / UNITS
    return out


def _trade_events(trade_df: Any) -> NDArray:
    df = pl.DataFrame(trade_df)
    if "taker_outcome_side" not in df.columns:
        raise ValueError("trade_df must contain a taker_outcome_side column.")
    if "is_block_trade" in df.columns:
        # negotiated off the book
        df = df.filter(~pl.col("is_block_trade").fill_null(False))
    if "trade_id" in df.columns:
        df = df.unique(subset=["trade_id"], keep="first", maintain_order=True)
    df = df.with_columns(
        pl.when(pl.col("taker_outcome_side") == "yes")
        .then(pl.lit("BUY"))
        .otherwise(pl.lit("SELL"))
        .alias("side")
    )
    return _make_trade_events_from_normalized(df, "yes_price", "count", "side")


def kalshi_settle_price(lifecycle_df: Any, market_ticker: str) -> float | None:
    """The market's settlement value in kacdata ``kalshi/lifecycle`` rows (the
    ``settlement_value`` of its last ``determined`` message), or ``None`` when they have none.
    The file to look in is that of the UTC day the market was determined."""
    df = pl.DataFrame(lifecycle_df).filter(pl.col("market_ticker") == market_ticker)
    value = None
    for message in df["market_lifecycle_json"]:
        message = json.loads(message)
        if message.get("event_type") == "determined":
            value = float(message["settlement_value"])
    return value


def kalshi_to_hbt(
    l2_df: Any,
    trade_df: Any | None = None,
    settle_price: float | None = None,
) -> NDArray:
    r"""
    Converts Kalshi L2 books and trades into an HftBacktest event array; the counterpart of
    ``polymarket_to_hbt``, priced in YES. The L2 rows are replayed in the order given, which
    must be the files': concatenate days in order and do not sort them. A delta is an increment
    to the book before it, so the rows must also start where a file starts: a day's file opens
    with the book at the start of the day, and a slice that starts later has no book to add
    its deltas to. The replay can therefore start at any day, but not within one.

    Args:
        l2_df: DataFrame of kacdata ``kalshi/l2`` rows: ``timestamp``, ``local_timestamp``,
               ``event_type``, ``yes_prices``, ``yes_sizes``, ``no_prices``, ``no_sizes``
               (snapshots) and ``delta_side``, ``delta_price``, ``delta_size`` (deltas).
        trade_df: Optional DataFrame of kacdata ``kalshi/trades`` rows: ``timestamp``,
                  ``local_timestamp``, ``yes_price``, ``count``, ``taker_outcome_side`` (the
                  outcome the taker bought: buying NO is a sell). Block trades
                  (``is_block_trade``) are dropped and rows are deduplicated by ``trade_id``.
        settle_price: 1.0 when YES won, 0.0 when NO won, 0.5 for a market settled half each: a
                      settlement book is appended 1 ms after the book's last change so the
                      position settles. ``None`` appends nothing and the stats settle by the
                      last price (the L2 data carries no resolution; ``kalshi_settle_price``
                      reads it from the lifecycle data).
    """
    check_settle_price(settle_price)
    df = normalize_kalshi_l2(l2_df)
    # Trades come first, so that at one exchange timestamp a trade precedes the deltas it led
    # to: the queue model then counts the traded quantity once, not as a trade and again as
    # the level shrinking.
    parts: list[NDArray] = []
    if trade_df is not None:
        parts.append(_trade_events(trade_df))
    if not df.is_empty():
        parts.append(_depth_events(df, settle_price))

    return _to_event_array(parts)
