"""Polymarket US order books and trades (pmdata.dev ``polymarket_us/l2`` and
``polymarket_us/trades``) as HftBacktest events.

Each L2 row is one complete book (Polymarket US sends the whole book in every ``marketData``
message), priced in the market's long outcome (``yes_outcome`` in the pmdata catalog), so the
books are replayed as per-level depth deltas, the way Predict.fun's are. A market is a single
contract: trades are priced in the long outcome as well, and ``taker_side`` is the taker's side
on that book whatever the intent (a taker buying the short outcome is a sell).
"""

from typing import Any

import polars as pl
from numpy.typing import NDArray

from .polymarket import _make_trade_events_from_normalized, _to_event_array, check_settle_price
from .predict_fun import _book_delta_events, normalize_predict_fun_l2

# The grid on which two books' levels are matched and the tick size of ``BacktestAssetPolyUS``:
# a Polymarket US market's own tick is 0.01, 0.005 or 0.0025 (``orderPriceMinTickSize``), so
# Polymarket's 0.001 cannot hold its prices.
LEVEL_GRID = 0.0001


def normalize_polymarket_us_l2(l2_df: Any) -> pl.DataFrame:
    """The books in replay order with ``ts`` / ``local_ts`` in nanoseconds and the offers as
    ``ask_prices`` / ``ask_sizes``: sorted by ``timestamp`` then ``local_timestamp``, one row
    per ``timestamp``."""
    df = pl.DataFrame(l2_df).rename({"offer_prices": "ask_prices", "offer_sizes": "ask_sizes"})
    return normalize_predict_fun_l2(df)


def _trade_events(trade_df: Any) -> NDArray:
    df = pl.DataFrame(trade_df)
    if "taker_side" not in df.columns:
        raise ValueError("trade_df must contain a taker_side column.")
    if "trade_id" in df.columns:
        # a trade can appear in two day files
        df = df.unique(subset=["trade_id"], keep="first", maintain_order=True)
    df = df.with_columns(
        pl.col("taker_side").cast(pl.Utf8).str.strip_prefix("ORDER_SIDE_").alias("side")
    )
    return _make_trade_events_from_normalized(df, "price", "quantity", "side")


def polymarket_us_to_hbt(
    l2_df: Any,
    trade_df: Any | None = None,
    settle_price: float | None = None,
) -> NDArray:
    r"""
    Converts Polymarket US L2 books and trades into an HftBacktest event array; the
    counterpart of ``polymarket_to_hbt``. Every L2 row is a complete book, so the replay starts
    at the first row given: slice ``l2_df`` (and ``trade_df``) to choose where.

    Args:
        l2_df: DataFrame of pmdata ``polymarket_us/l2`` rows: ``timestamp``,
               ``local_timestamp``, ``bid_prices``, ``bid_sizes``, ``offer_prices``,
               ``offer_sizes`` (any number of days; ``market_slug``, ``event_type`` and
               ``state`` are ignored, so a halted market's book is replayed as it was sent).
        trade_df: Optional DataFrame of pmdata ``polymarket_us/trades`` rows: ``timestamp``,
                  ``local_timestamp``, ``price``, ``quantity``, ``taker_side`` (the other
                  columns are ignored, except ``trade_id``, by which rows are deduplicated).
        settle_price: 1.0 when the long outcome won, 0.0 when it lost, 0.5 for a tie: a
                      settlement book is appended 1 ms after the last book so the position
                      settles. ``None`` appends nothing and the stats settle by the last price
                      (the Polymarket US data carries no resolution; it is the ``settlement``
                      of ``GET https://gateway.polymarket.us/v1/markets/{slug}/settlement``).
    """
    check_settle_price(settle_price)
    df = normalize_polymarket_us_l2(l2_df)
    # Trades come first, so that at one exchange timestamp a trade precedes the book it led
    # to: the queue model then counts the traded quantity once, not as a trade and again as
    # the level shrinking.
    parts: list[NDArray] = []
    if trade_df is not None:
        parts.append(_trade_events(trade_df))
    if not df.is_empty():
        parts.append(_book_delta_events(df, settle_price, LEVEL_GRID))

    return _to_event_array(parts)
