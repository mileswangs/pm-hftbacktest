import numpy as np
import polars as pl
from numpy.typing import NDArray
from typing import Any

from ...types import (
    BUY_EVENT,
    DEPTH_CLEAR_EVENT,
    DEPTH_EVENT,
    DEPTH_SNAPSHOT_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)
from ..validation import correct_event_order

DEFAULT_LATENCY_NS = 20_000_000
HBT_COLS = ["ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval"]
POLY_MIN_PRICE = 0.0
POLY_MAX_PRICE = 1.0


def _ts_ns_expr(df: pl.DataFrame, col: str = "timestamp") -> pl.Expr:
    """Converts a timestamp column to nanoseconds as int64."""
    dtype = df.schema[col]
    if hasattr(dtype, "time_unit") or str(dtype).startswith("Datetime"):
        return pl.col(col).dt.epoch("ns").cast(pl.Int64)
    return pl.col(col).cast(pl.Int64) * 1_000_000


def _local_ts_ns_expr(
    df: pl.DataFrame,
    exch_ts_expr: pl.Expr,
) -> pl.Expr:
    if "local_timestamp" not in df.columns:
        return exch_ts_expr + DEFAULT_LATENCY_NS
    return _ts_ns_expr(df, "local_timestamp")


def _make_book_events(
    books: pl.DataFrame,
    ts_expr: pl.Expr,
    local_ts_expr: pl.Expr,
) -> NDArray:
    if len(books) == 0:
        return np.zeros(0, dtype=event_dtype)

    prepared = []
    total_rows = 0
    books = books.with_columns(
        ts_expr.alias("ts"),
        local_ts_expr.alias("local_ts"),
    ).sort("ts")

    for row in books.iter_rows(named=True):
        book_ts = int(row["ts"])
        book_local_ts = int(row["local_ts"])

        for px_col, qty_col, side_flag in [
            ("bid_prices", "bid_sizes", BUY_EVENT),
            ("ask_prices", "ask_sizes", SELL_EVENT),
        ]:
            prices = row.get(px_col) or []
            sizes = row.get(qty_col) or []

            n = min(len(prices), len(sizes))
            prepared.append((book_ts, book_local_ts, side_flag, prices, sizes, n))
            total_rows += 1 + n

    out = np.zeros(total_rows, dtype=event_dtype)
    pos = 0
    for book_ts, book_local_ts, side_flag, prices, sizes, n in prepared:
        if prices:
            clear_px = max(prices) if side_flag == BUY_EVENT else min(prices)
        else:
            clear_px = POLY_MIN_PRICE if side_flag == BUY_EVENT else POLY_MAX_PRICE
        out[pos]["ev"] = DEPTH_CLEAR_EVENT | side_flag
        out[pos]["exch_ts"] = book_ts
        out[pos]["local_ts"] = book_local_ts
        out[pos]["px"] = float(clear_px)
        out[pos]["qty"] = 0.0
        pos += 1

        if n == 0:
            continue

        end = pos + n
        sizes = sizes[:n]
        if None in sizes:
            float(None)

        out["ev"][pos:end] = DEPTH_SNAPSHOT_EVENT | side_flag
        out["exch_ts"][pos:end] = book_ts
        out["local_ts"][pos:end] = book_local_ts
        out["px"][pos:end] = prices[:n]
        out["qty"][pos:end] = sizes
        pos = end

    return out


def _settle_price_from_winning_outcome(winning_outcome: Any) -> float | None:
    if winning_outcome is None:
        return None

    if isinstance(winning_outcome, str):
        outcome = winning_outcome.strip().lower()
        if outcome in {"yes", "true", "1", "up"}:
            return 1.0
        if outcome in {"no", "false", "0", "down"}:
            return 0.0
        return None

    try:
        return 1.0 if float(winning_outcome) > 0.5 else 0.0
    except (TypeError, ValueError):
        return None


def _append_resolved_book(df: pl.DataFrame) -> pl.DataFrame:
    resolved = (
        df.filter(pl.col("event_type") == "market_resolved")
        .filter(pl.col("winning_outcome").is_not_null())
        .sort("timestamp")
    )
    if len(resolved) == 0:
        return df

    row = resolved.tail(1).to_dicts()[0]
    settle_price = _settle_price_from_winning_outcome(row["winning_outcome"])
    if settle_price is None:
        return df

    book = {col: None for col in df.columns}
    book["timestamp"] = df.select(pl.col("timestamp").max()).item()
    book["local_timestamp"] = df.select(pl.col("local_timestamp").max()).item()
    book["event_type"] = "book"
    if settle_price == 1.0:
        book["bid_prices"] = [0.998]
        book["bid_sizes"] = [0.01]
        book["ask_prices"] = [1.0]
        book["ask_sizes"] = [0.01]
    else:
        book["bid_prices"] = [0.001]
        book["bid_sizes"] = [0.01]
        book["ask_prices"] = [0.003]
        book["ask_sizes"] = [0.01]

    return pl.concat([df, pl.DataFrame([book], schema=df.schema)], how="vertical")


def _copy_structured(arr: NDArray) -> NDArray:
    out = np.zeros(len(arr), dtype=event_dtype)
    for col in event_dtype.names:
        out[col] = arr[col]
    return out


def _normalize_trade_outcome(trade_df: pl.DataFrame) -> pl.DataFrame:
    if "price" not in trade_df.columns:
        raise ValueError("trade_df must contain a price column.")
    if trade_df["price"].null_count() > 0:
        raise ValueError("trade_df price cannot contain null values.")

    if "outcome" not in trade_df.columns:
        return trade_df

    side_expr = pl.col("side").cast(pl.Utf8).str.to_uppercase()
    outcome_expr = pl.col("outcome").cast(pl.Utf8).str.to_lowercase()
    is_no_expr = outcome_expr.is_in(["no", "false", "0", "down"])

    return trade_df.with_columns(
        pl.when(is_no_expr)
        .then(1.0 - pl.col("price").cast(pl.Float64))
        .otherwise(pl.col("price").cast(pl.Float64))
        .alias("price"),
        pl.when(is_no_expr & (side_expr == "BUY"))
        .then(pl.lit("SELL"))
        .when(is_no_expr & (side_expr == "SELL"))
        .then(pl.lit("BUY"))
        .otherwise(side_expr)
        .alias("side"),
    )


def _make_trade_events_from_normalized(
    trade_data: pl.DataFrame,
    price_col: str,
    size_col: str,
    side_col: str,
) -> NDArray:
    if len(trade_data) == 0:
        return np.zeros(0, dtype=event_dtype)
    for col in [price_col, size_col, side_col]:
        if col not in trade_data.columns:
            raise ValueError(f"trade_df must contain a {col} column.")

    ts_expr = _ts_ns_expr(trade_data)
    local_ts_expr = _local_ts_ns_expr(trade_data, ts_expr)
    side_expr = pl.col(side_col).cast(pl.Utf8).str.to_uppercase()
    is_buy_expr = side_expr == "BUY"

    arr = (
        trade_data.with_columns(
            pl.when(is_buy_expr)
            .then(pl.lit(TRADE_EVENT | BUY_EVENT))
            .otherwise(pl.lit(TRADE_EVENT | SELL_EVENT))
            .cast(pl.UInt64)
            .alias("ev"),
            ts_expr.alias("exch_ts"),
            local_ts_expr.alias("local_ts"),
            pl.col(price_col).cast(pl.Float64).alias("px"),
            pl.col(size_col).cast(pl.Float64).alias("qty"),
            pl.lit(0).cast(pl.UInt64).alias("order_id"),
            pl.lit(0).cast(pl.Int64).alias("ival"),
            pl.lit(0.0).alias("fval"),
        )
        .select(HBT_COLS)
        .to_numpy(structured=True)
    )
    return _copy_structured(arr)


def polymarket_to_hbt(
    l2_df: Any,
    trade_df: Any | None = None,
) -> NDArray:
    r"""
    Converts Polymarket L2 and trade DataFrames into an HftBacktest event array.

    Args:
        l2_df: DataFrame containing the Polymarket L2 data.
        trade_df: Optional DataFrame containing Polymarket trade data. Expected
                  columns are timestamp, local_timestamp, outcome, price, size,
                  and side. market_slug and event_type are ignored.
    """
    l2_df = pl.DataFrame(l2_df)
    l2_df = _append_resolved_book(l2_df)

    ts_expr = _ts_ns_expr(l2_df)
    local_ts_expr = _local_ts_ns_expr(l2_df, ts_expr)
    parts: list[NDArray] = []

    books = l2_df.filter(pl.col("event_type") == "book")
    if len(books) > 0:
        book_events = _make_book_events(books, ts_expr, local_ts_expr)
        if len(book_events) > 0:
            parts.append(book_events)

    price_changes = l2_df.filter(
        (pl.col("event_type") == "price_change") & pl.col("pc_price").is_not_null()
    )
    if len(price_changes) > 0:
        arr = (
            price_changes.with_columns(
                pl.when(pl.col("pc_side") == "BUY")
                .then(pl.lit(DEPTH_EVENT | BUY_EVENT))
                .otherwise(pl.lit(DEPTH_EVENT | SELL_EVENT))
                .cast(pl.UInt64)
                .alias("ev"),
                ts_expr.alias("exch_ts"),
                local_ts_expr.alias("local_ts"),
                pl.col("pc_price").cast(pl.Float64).alias("px"),
                pl.col("pc_size").cast(pl.Float64).alias("qty"),
                pl.lit(0).cast(pl.UInt64).alias("order_id"),
                pl.lit(0).cast(pl.Int64).alias("ival"),
                pl.lit(0.0).alias("fval"),
            )
            .select(HBT_COLS)
            .to_numpy(structured=True)
        )
        parts.append(_copy_structured(arr))

    if trade_df is not None:
        normalized_trade_df = _normalize_trade_outcome(pl.DataFrame(trade_df))
        trade_events = _make_trade_events_from_normalized(
            normalized_trade_df,
            "price",
            "size",
            "side",
        )
        if len(trade_events) > 0:
            parts.append(trade_events)

    if not parts:
        return np.zeros(0, dtype=event_dtype)

    data = np.concatenate(parts)
    data = data[np.argsort(data["exch_ts"], kind="mergesort")]
    return correct_event_order(
        data,
        np.argsort(data["exch_ts"], kind="mergesort"),
        np.argsort(data["local_ts"], kind="mergesort"),
    )
