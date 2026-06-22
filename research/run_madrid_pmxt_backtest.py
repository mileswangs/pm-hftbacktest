from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from pmxt_weather_data import _extract_hour, _filter_catalog_rows, build_entry_hour_map, load_catalog
from pmxt_weather_backtest import EntrySnapshotRow, run_pmxt_weather_backtest


OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "pmxt_weather"
ENTRY_HOURS = [6.0, 12.0, 18.0, 24.0, 36.0]
START_DATE = dt.date(2026, 4, 13)
MAX_PASSES = 12
WORKERS = 6
DEFAULT_OUTPUT_STEM = "madrid_pmxt"


def _parse_entry_hours(raw: str) -> list[float]:
    hours = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hours.append(float(part))
    if not hours:
        raise ValueError("At least one entry hour is required.")
    return hours


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-hours", default="6,12,18,24,36")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--start-date", default=START_DATE.isoformat())
    parser.add_argument(
        "--end-date",
        default="",
        help="Inclusive end date. Defaults to the latest closed Madrid event with a winner in the catalog.",
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge rebuilt event/hour slices into an existing output stem before recomputing the summary.",
    )
    return parser.parse_args()


def _hour_key(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H")


def _relevant_rows(start_date: dt.date, end_date: dt.date | None):
    rows = load_catalog(OUTPUT_DIR / "weather_market_catalog.json")
    madrid_settled_dates = [
        dt.date.fromisoformat(row.target_date)
        for row in rows
        if row.city_slug == "madrid" and row.closed and row.event_winner_label is not None
    ]
    resolved_end_date = end_date or max(madrid_settled_dates)
    return _filter_catalog_rows(
        rows,
        city_slugs={"madrid"},
        start_date=start_date,
        end_date=resolved_end_date,
    )


def _required_hour_map(rows, entry_hours: list[float]):
    return build_entry_hour_map(rows, entry_hours=entry_hours, include_previous_hour=True)


def _existing_hours() -> set[str]:
    return {path.name.replace(".weather.parquet", "") for path in (OUTPUT_DIR / "weather_hourly").glob("*.weather.parquet")}


def fill_missing_hours(rows, entry_hours: list[float], workers: int) -> None:
    hour_map = _required_hour_map(rows, entry_hours)
    required = set(hour_map)
    for pass_idx in range(1, MAX_PASSES + 1):
        missing = sorted(required - _existing_hours())
        print(
            f"fill pass={pass_idx} required={len(required)} existing={len(required) - len(missing)} missing={len(missing)}",
            flush=True,
        )
        if not missing:
            return

        completed = 0
        failures: list[tuple[str, str]] = []

        def run_one(hour_key: str):
            try:
                result = _extract_hour(
                    hour_key=hour_key,
                    hour_rows=hour_map[hour_key],
                    output_dir=OUTPUT_DIR,
                    keep_raw=False,
                )
                return ("ok", hour_key, result["status"])
            except Exception as exc:  # pragma: no cover - operational recovery
                return ("err", hour_key, repr(exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_one, hour_key) for hour_key in missing]
            for future in concurrent.futures.as_completed(futures):
                status, hour_key, detail = future.result()
                completed += 1
                if status == "err":
                    failures.append((hour_key, detail))
                if completed % 20 == 0 or completed == len(missing):
                    print(
                        f"fill pass={pass_idx} progress={completed}/{len(missing)} failures={len(failures)} last={hour_key}:{detail}",
                        flush=True,
                    )

        new_missing = sorted(required - _existing_hours())
        if failures:
            print(f"fill pass={pass_idx} sample_failures={failures[:5]}", flush=True)
        if len(new_missing) >= len(missing):
            print("fill no_progress_break", flush=True)
            return


def build_fast_snapshots(rows, entry_hours: list[float]) -> list[EntrySnapshotRow]:
    hour_map = _required_hour_map(rows, entry_hours)
    by_event: dict[str, list] = {}
    for row in rows:
        by_event.setdefault(row.event_slug, []).append(row)

    cache: dict[tuple[str, str], pd.DataFrame] = {}
    columns = [
        "timestamp_received",
        "timestamp",
        "event_slug",
        "asset_id",
        "event_type",
        "price",
        "best_bid",
        "best_ask",
        "side",
        "size",
        "fee_rate_bps",
    ]

    def load_event_hour(event_slug: str, hour_key: str) -> pd.DataFrame:
        key = (event_slug, hour_key)
        if key in cache:
            return cache[key]

        path = OUTPUT_DIR / "weather_hourly" / f"{hour_key}.weather.parquet"
        if not path.exists():
            cache[key] = pd.DataFrame(columns=columns)
            return cache[key]

        try:
            df = pd.read_parquet(path, columns=columns, filters=[("event_slug", "==", event_slug)], engine="pyarrow")
        except Exception:
            df = pd.DataFrame(columns=columns)

        if len(df):
            df["timestamp_received"] = pd.to_datetime(df["timestamp_received"], utc=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        cache[key] = df
        return df

    snapshots: list[EntrySnapshotRow] = []
    total_events = len(by_event)
    for idx, (event_slug, event_rows) in enumerate(sorted(by_event.items()), start=1):
        end_time = dt.datetime.fromisoformat(event_rows[0].end_time_utc)
        for entry_hour in entry_hours:
            entry_time = end_time - dt.timedelta(hours=entry_hour)
            hour_keys = {_hour_key(entry_time), _hour_key(entry_time - dt.timedelta(hours=1))}
            frames = []
            for hour_key in hour_keys:
                df = load_event_hour(event_slug, hour_key)
                if len(df):
                    frames.append(df)
            if not frames:
                continue

            combined = pd.concat(frames, ignore_index=True)
            combined = combined[combined["timestamp_received"] <= pd.Timestamp(entry_time.astimezone(dt.timezone.utc))]
            if len(combined) == 0:
                continue

            for market_row in event_rows:
                asset_df = combined[combined["asset_id"] == market_row.yes_token_id]
                if len(asset_df) == 0:
                    continue
                last_row = asset_df.sort_values("timestamp_received").iloc[-1]
                snapshots.append(
                    EntrySnapshotRow(
                        city_slug=market_row.city_slug,
                        city_label=market_row.city_label,
                        target_date=market_row.target_date,
                        event_slug=market_row.event_slug,
                        event_title=market_row.event_title,
                        event_winner_label=market_row.event_winner_label,
                        entry_hours=entry_hour,
                        entry_time_utc=entry_time.isoformat(),
                        bucket_label=market_row.bucket_label,
                        condition_id=market_row.condition_id,
                        yes_token_id=market_row.yes_token_id,
                        market_slug=market_row.market_slug,
                        is_winner=market_row.is_winner,
                        source_hour_key=_hour_key(last_row["timestamp_received"].to_pydatetime()),
                        snapshot_timestamp_received=last_row["timestamp_received"].isoformat(),
                        snapshot_timestamp=last_row["timestamp"].isoformat() if pd.notna(last_row["timestamp"]) else None,
                        snapshot_event_type=None if pd.isna(last_row["event_type"]) else str(last_row["event_type"]),
                        snapshot_price=None if pd.isna(last_row["price"]) else float(last_row["price"]),
                        snapshot_best_bid=None if pd.isna(last_row["best_bid"]) else float(last_row["best_bid"]),
                        snapshot_best_ask=None if pd.isna(last_row["best_ask"]) else float(last_row["best_ask"]),
                        snapshot_side=None if pd.isna(last_row["side"]) else str(last_row["side"]),
                        snapshot_size=None if pd.isna(last_row["size"]) else float(last_row["size"]),
                        snapshot_fee_rate_bps=None
                        if pd.isna(last_row["fee_rate_bps"])
                        else int(last_row["fee_rate_bps"]),
                    )
                )
        if idx % 10 == 0 or idx == total_events:
            print(f"snapshot progress={idx}/{total_events} rows={len(snapshots)}", flush=True)
    return snapshots


def main() -> None:
    args = _parse_args()
    entry_hours = _parse_entry_hours(args.entry_hours)
    start_date = dt.date.fromisoformat(args.start_date)
    end_date = dt.date.fromisoformat(args.end_date) if args.end_date else None
    rows = _relevant_rows(start_date, end_date)
    target_dates = sorted({row.target_date for row in rows})
    print(
        f"madrid_events={len({row.event_slug for row in rows})} "
        f"range={target_dates[0]}..{target_dates[-1]}",
        flush=True,
    )
    fill_missing_hours(rows, entry_hours=entry_hours, workers=max(1, int(args.workers)))
    snapshots = build_fast_snapshots(rows, entry_hours=entry_hours)

    snapshot_path = OUTPUT_DIR / f"{args.output_stem}_entry_snapshots.parquet"
    snapshots_df = pd.DataFrame([asdict(row) for row in snapshots])
    if args.merge_existing and snapshot_path.exists():
        existing_df = pd.read_parquet(snapshot_path)
        if len(snapshots_df):
            rebuilt_slices = set(zip(snapshots_df["event_slug"], snapshots_df["entry_hours"]))
            keep_mask = [
                (event_slug, float(entry_hours)) not in rebuilt_slices
                for event_slug, entry_hours in zip(existing_df["event_slug"], existing_df["entry_hours"])
            ]
            snapshots_df = pd.concat([existing_df[keep_mask], snapshots_df], ignore_index=True)
        else:
            snapshots_df = existing_df
        snapshots_df = snapshots_df.sort_values(["target_date", "entry_hours", "bucket_label"])
    if not len(snapshots_df):
        raise RuntimeError("No PMXT snapshots were available; existing output was left untouched.")
    snapshots_df.to_parquet(snapshot_path, index=False, engine="pyarrow")

    merged_snapshots = [EntrySnapshotRow(**row) for row in snapshots_df.to_dict("records")]
    summary = run_pmxt_weather_backtest(merged_snapshots, threshold=float(args.threshold))
    summary_path = OUTPUT_DIR / f"{args.output_stem}_weather_backtest_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(f"snapshot_rows={len(snapshots_df)}", flush=True)
    print(f"snapshot_path={snapshot_path}", flush=True)
    print(f"summary_path={summary_path}", flush=True)
    for row in summary["summary_by_entry_hour"]:
        print(
            f"entry={row['entry_hours']:>4g}h events={row['events']:>3} traded={row['traded']:>3} "
            f"hit_rate={row['hit_rate']:.2%} total_pnl={row['total_pnl']:.4f} avg_pnl={row['avg_pnl']:.4f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
