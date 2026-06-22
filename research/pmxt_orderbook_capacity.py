"""Inspect historical PMXT orderbook depth for selected weather backtest entries.

This script reconstructs the latest known PMXT `book` snapshot at or before each
strategy entry time, then estimates how much YES size could have been bought
from the ask ladder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("research/data/pmxt_weather")


@dataclass(frozen=True)
class CapacityRow:
    city_slug: str
    target_date: str
    event_slug: str
    bucket_label: str
    entry_hours: float
    entry_time_utc: str
    selected_probability: float
    snapshot_best_ask: float | None
    snapshot_best_bid: float | None
    book_timestamp_received: str | None
    book_age_minutes: float | None
    ask_levels: int
    top_ask_price: float | None
    top_ask_size: float
    cum_size_at_top_ask: float
    cum_size_plus_1c: float
    cum_size_plus_2c: float
    cum_size_plus_5c: float
    notional_at_top_ask: float
    notional_plus_1c: float
    notional_plus_2c: float
    notional_plus_5c: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True, help="City slug, e.g. madrid")
    parser.add_argument("--entry-hours", type=float, required=True, help="Entry hour to inspect, e.g. 36")
    parser.add_argument("--target-date", default="", help="Optional YYYY-MM-DD filter for one day.")
    parser.add_argument("--book-lookback-hours", type=int, default=6, help="How far back to search for the latest book snapshot.")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing weather_hourly/ and PMXT backtest artifacts",
    )
    parser.add_argument(
        "--summary-json",
        default="",
        help="Backtest summary JSON. Defaults to <city>_pmxt_weather_backtest_summary.json in data-dir if present.",
    )
    parser.add_argument(
        "--snapshots-parquet",
        default="",
        help="Entry snapshots parquet. Defaults to <city>_pmxt_entry_snapshots.parquet in data-dir if present.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write the detailed capacity rows as JSON.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on number of rows printed.")
    return parser.parse_args()


def _default_summary_path(data_dir: Path, city_slug: str) -> Path:
    specific = data_dir / f"{city_slug}_pmxt_weather_backtest_summary.json"
    return specific if specific.exists() else data_dir / "pmxt_weather_backtest_summary.json"


def _default_snapshot_path(data_dir: Path, city_slug: str) -> Path:
    specific = data_dir / f"{city_slug}_pmxt_entry_snapshots.parquet"
    return specific if specific.exists() else data_dir / "pmxt_entry_snapshots.parquet"


def _load_selected_rows(summary_path: Path, city_slug: str, entry_hours: float, target_date: str = "") -> list[dict[str, Any]]:
    payload = json.loads(summary_path.read_text())
    out: list[dict[str, Any]] = []
    for row in payload["events"]:
        if row["city_slug"] != city_slug:
            continue
        if float(row["entry_hours"]) != float(entry_hours):
            continue
        if target_date and row["target_date"] != target_date:
            continue
        if not row["selected_labels"]:
            continue
        out.append(row)
    return out


def _hour_key(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H")


def _load_hour_df(
    hour_key: str,
    output_dir: Path,
    *,
    cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if hour_key in cache:
        return cache[hour_key]
    path = output_dir / "weather_hourly" / f"{hour_key}.weather.parquet"
    if not path.exists():
        cache[hour_key] = pd.DataFrame()
        return cache[hour_key]
    df = pd.read_parquet(path, columns=["timestamp_received", "event_slug", "event_type", "asset_id", "asks"])
    if len(df) and not pd.api.types.is_datetime64tz_dtype(df["timestamp_received"]):
        df["timestamp_received"] = pd.to_datetime(df["timestamp_received"], utc=True)
    cache[hour_key] = df
    return df


def _load_context_frames(
    entry_time: dt.datetime,
    output_dir: Path,
    *,
    event_slug: str,
    asset_ids: list[str],
    lookback_hours: int,
    cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    frames = []
    for offset in range(max(1, lookback_hours) + 1):
        hour_key = _hour_key(entry_time - dt.timedelta(hours=offset))
        df = _load_hour_df(hour_key, output_dir, cache=cache)
        if len(df):
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined[
        (combined["event_slug"] == event_slug)
        & (combined["event_type"] == "book")
        & (combined["asset_id"].astype(str).isin(asset_ids))
    ]


def _parse_levels(raw: Any) -> list[tuple[float, float]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        if not raw:
            return []
        raw = json.loads(raw)
    out: list[tuple[float, float]] = []
    for item in raw:
        if len(item) < 2:
            continue
        out.append((float(item[0]), float(item[1])))
    return out


def _capacity_from_asks(asks: list[tuple[float, float]]) -> dict[str, float | int | None]:
    if not asks:
        return {
            "ask_levels": 0,
            "top_ask_price": None,
            "top_ask_size": 0.0,
            "cum_size_at_top_ask": 0.0,
            "cum_size_plus_1c": 0.0,
            "cum_size_plus_2c": 0.0,
            "cum_size_plus_5c": 0.0,
            "notional_at_top_ask": 0.0,
            "notional_plus_1c": 0.0,
            "notional_plus_2c": 0.0,
            "notional_plus_5c": 0.0,
        }

    asks = sorted(asks, key=lambda item: item[0])
    top = asks[0][0]

    def accumulate(max_price: float) -> tuple[float, float]:
        size = 0.0
        notional = 0.0
        for price, qty in asks:
            if price > max_price + 1e-12:
                break
            size += qty
            notional += price * qty
        return size, notional

    top_size, top_notional = accumulate(top)
    plus_1c_size, plus_1c_notional = accumulate(top + 0.01)
    plus_2c_size, plus_2c_notional = accumulate(top + 0.02)
    plus_5c_size, plus_5c_notional = accumulate(top + 0.05)
    return {
        "ask_levels": len(asks),
        "top_ask_price": top,
        "top_ask_size": top_size,
        "cum_size_at_top_ask": top_size,
        "cum_size_plus_1c": plus_1c_size,
        "cum_size_plus_2c": plus_2c_size,
        "cum_size_plus_5c": plus_5c_size,
        "notional_at_top_ask": top_notional,
        "notional_plus_1c": plus_1c_notional,
        "notional_plus_2c": plus_2c_notional,
        "notional_plus_5c": plus_5c_notional,
    }


def build_capacity_rows(
    *,
    city_slug: str,
    entry_hours: float,
    summary_rows: list[dict[str, Any]],
    snapshots_df: pd.DataFrame,
    output_dir: Path,
    book_lookback_hours: int,
) -> list[CapacityRow]:
    rows: list[CapacityRow] = []
    hour_cache: dict[str, pd.DataFrame] = {}
    snapshots_df = snapshots_df.copy()
    snapshots_df["entry_hours"] = snapshots_df["entry_hours"].astype(float)

    for event in summary_rows:
        entry_time = dt.datetime.fromisoformat(event["entry_time_utc"])
        event_slug = event["event_slug"]
        selected_price_by_label = dict(zip(event["selected_labels"], event["selected_prices"]))
        event_snapshots = snapshots_df[
            (snapshots_df["city_slug"] == city_slug)
            & (snapshots_df["event_slug"] == event_slug)
            & (snapshots_df["entry_hours"] == float(entry_hours))
            & (snapshots_df["bucket_label"].isin(event["selected_labels"]))
        ]
        context = _load_context_frames(
            entry_time,
            output_dir,
            event_slug=event_slug,
            asset_ids=[str(value) for value in event_snapshots["yes_token_id"].tolist()],
            lookback_hours=book_lookback_hours,
            cache=hour_cache,
        )
        if len(context):
            context = context[
                (context["event_slug"] == event_slug)
                & (context["event_type"] == "book")
                & (context["timestamp_received"] <= pd.Timestamp(entry_time.astimezone(dt.timezone.utc)))
            ]

        for snap in event_snapshots.to_dict("records"):
            token_id = str(snap["yes_token_id"])
            asset_df = context[context["asset_id"].astype(str) == token_id] if len(context) else pd.DataFrame()
            book_row = asset_df.sort_values("timestamp_received").iloc[-1] if len(asset_df) else None
            asks = _parse_levels(None if book_row is None else book_row["asks"])
            capacity = _capacity_from_asks(asks)
            book_age_minutes = None
            if book_row is not None:
                book_age_minutes = (
                    pd.Timestamp(entry_time.astimezone(dt.timezone.utc)) - book_row["timestamp_received"]
                ).total_seconds() / 60.0
            rows.append(
                CapacityRow(
                    city_slug=city_slug,
                    target_date=str(snap["target_date"]),
                    event_slug=event_slug,
                    bucket_label=str(snap["bucket_label"]),
                    entry_hours=float(entry_hours),
                    entry_time_utc=str(event["entry_time_utc"]),
                    selected_probability=float(selected_price_by_label.get(str(snap["bucket_label"]), 0.0)),
                    snapshot_best_ask=None if pd.isna(snap["snapshot_best_ask"]) else float(snap["snapshot_best_ask"]),
                    snapshot_best_bid=None if pd.isna(snap["snapshot_best_bid"]) else float(snap["snapshot_best_bid"]),
                    book_timestamp_received=None if book_row is None else book_row["timestamp_received"].isoformat(),
                    book_age_minutes=book_age_minutes,
                    ask_levels=int(capacity["ask_levels"]),
                    top_ask_price=capacity["top_ask_price"],
                    top_ask_size=float(capacity["top_ask_size"]),
                    cum_size_at_top_ask=float(capacity["cum_size_at_top_ask"]),
                    cum_size_plus_1c=float(capacity["cum_size_plus_1c"]),
                    cum_size_plus_2c=float(capacity["cum_size_plus_2c"]),
                    cum_size_plus_5c=float(capacity["cum_size_plus_5c"]),
                    notional_at_top_ask=float(capacity["notional_at_top_ask"]),
                    notional_plus_1c=float(capacity["notional_plus_1c"]),
                    notional_plus_2c=float(capacity["notional_plus_2c"]),
                    notional_plus_5c=float(capacity["notional_plus_5c"]),
                )
            )
    return rows


def main() -> None:
    args = _parse_args()
    data_dir = Path(args.data_dir)
    summary_path = Path(args.summary_json) if args.summary_json else _default_summary_path(data_dir, args.city)
    snapshot_path = Path(args.snapshots_parquet) if args.snapshots_parquet else _default_snapshot_path(data_dir, args.city)
    summary_rows = _load_selected_rows(summary_path, args.city, args.entry_hours, target_date=args.target_date)
    snapshots_df = pd.read_parquet(snapshot_path)
    rows = build_capacity_rows(
        city_slug=args.city,
        entry_hours=float(args.entry_hours),
        summary_rows=summary_rows,
        snapshots_df=snapshots_df,
        output_dir=data_dir,
        book_lookback_hours=int(args.book_lookback_hours),
    )

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))

    print(f"rows={len(rows)}")
    if rows:
        df = pd.DataFrame([asdict(row) for row in rows]).sort_values(["target_date", "bucket_label"])
        if args.limit > 0:
            df = df.head(args.limit)
        print(
            df[
                [
                    "target_date",
                    "bucket_label",
                    "selected_probability",
                    "snapshot_best_ask",
                    "top_ask_price",
                    "top_ask_size",
                    "cum_size_plus_1c",
                    "cum_size_plus_2c",
                    "cum_size_plus_5c",
                    "book_age_minutes",
                    "book_timestamp_received",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
