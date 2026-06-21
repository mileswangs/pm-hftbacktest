"""Build PMXT-derived entry snapshots and run a weather backtest on top of them."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from pmxt_weather_data import (
    PMXT_COVERAGE_START,
    WeatherMarketCatalogRow,
    _extract_hour,
    _filter_catalog_rows,
    _parse_cities,
    build_entry_hour_map,
    default_catalog_path,
    default_output_dir,
    load_catalog,
)
from weather_backtest import OutcomeSnapshot, describe_decision, select_positions


@dataclass(frozen=True)
class EntrySnapshotRow:
    city_slug: str
    city_label: str
    target_date: str
    event_slug: str
    event_title: str
    event_winner_label: str | None
    entry_hours: float
    entry_time_utc: str
    bucket_label: str
    condition_id: str
    yes_token_id: str
    market_slug: str
    is_winner: bool
    source_hour_key: str
    snapshot_timestamp_received: str | None
    snapshot_timestamp: str | None
    snapshot_event_type: str | None
    snapshot_price: float | None
    snapshot_best_bid: float | None
    snapshot_best_ask: float | None
    snapshot_side: str | None
    snapshot_size: float | None
    snapshot_fee_rate_bps: int | None


@dataclass(frozen=True)
class EventBacktestSummary:
    city_slug: str
    target_date: str
    event_slug: str
    entry_hours: float
    entry_time_utc: str
    selection_mode: str
    selected_labels: list[str]
    selected_prices: list[float]
    selected_probability_sum: float
    pnl: float
    did_hit: bool
    winner_label: str | None


def default_snapshot_path() -> Path:
    return default_output_dir() / "pmxt_entry_snapshots.parquet"


def default_backtest_summary_path() -> Path:
    return default_output_dir() / "pmxt_weather_backtest_summary.json"


def _parse_entry_hours(raw: str) -> list[float]:
    out: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    if not out:
        raise ValueError("At least one entry hour is required.")
    return out


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _hour_key(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H")


def _load_hour_df(hour_key: str, output_dir: Path) -> pd.DataFrame:
    path = output_dir / "weather_hourly" / f"{hour_key}.weather.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def ensure_entry_hour_data(
    *,
    catalog_rows: list[WeatherMarketCatalogRow],
    output_dir: Path,
    entry_hours: list[float],
    workers: int,
) -> None:
    hour_map = build_entry_hour_map(catalog_rows, entry_hours=entry_hours, include_previous_hour=True)
    hour_keys = sorted(hour_map)

    def run_one(hour_key: str) -> None:
        _extract_hour(
            hour_key=hour_key,
            hour_rows=hour_map[hour_key],
            output_dir=output_dir,
            keep_raw=False,
        )

    if workers <= 1:
        for hour_key in hour_keys:
            run_one(hour_key)
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_one, hour_key) for hour_key in hour_keys]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def build_entry_snapshots(
    *,
    catalog_rows: list[WeatherMarketCatalogRow],
    output_dir: Path,
    entry_hours: list[float],
) -> list[EntrySnapshotRow]:
    rows: list[EntrySnapshotRow] = []
    catalog_by_event: dict[str, list[WeatherMarketCatalogRow]] = {}
    for row in catalog_rows:
        catalog_by_event.setdefault(row.event_slug, []).append(row)

    for event_slug, event_rows in sorted(catalog_by_event.items()):
        end_time = dt.datetime.fromisoformat(event_rows[0].end_time_utc)
        for entry_hour in entry_hours:
            entry_time = end_time - dt.timedelta(hours=entry_hour)
            if entry_time < PMXT_COVERAGE_START:
                continue
            current_hour = _hour_key(entry_time)
            prev_hour = _hour_key(entry_time - dt.timedelta(hours=1))
            frames = []
            for hour_key in {prev_hour, current_hour}:
                df = _load_hour_df(hour_key, output_dir)
                if len(df):
                    frames.append(df)
            if not frames:
                continue
            combined = pd.concat(frames, ignore_index=True)
            combined["timestamp_received"] = pd.to_datetime(combined["timestamp_received"], utc=True)
            combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
            combined = combined[combined["event_slug"] == event_slug]
            combined = combined[combined["timestamp_received"] <= pd.Timestamp(entry_time.astimezone(dt.timezone.utc))]
            if len(combined) == 0:
                continue

            for market_row in event_rows:
                asset_df = combined[combined["asset_id"] == market_row.yes_token_id]
                if len(asset_df) == 0:
                    rows.append(
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
                            source_hour_key=current_hour,
                            snapshot_timestamp_received=None,
                            snapshot_timestamp=None,
                            snapshot_event_type=None,
                            snapshot_price=None,
                            snapshot_best_bid=None,
                            snapshot_best_ask=None,
                            snapshot_side=None,
                            snapshot_size=None,
                            snapshot_fee_rate_bps=None,
                        )
                    )
                    continue
                last_row = asset_df.sort_values("timestamp_received").iloc[-1]
                rows.append(
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
                        snapshot_timestamp=last_row["timestamp"].isoformat(),
                        snapshot_event_type=None if pd.isna(last_row["event_type"]) else str(last_row["event_type"]),
                        snapshot_price=None if pd.isna(last_row["price"]) else float(last_row["price"]),
                        snapshot_best_bid=None if pd.isna(last_row["best_bid"]) else float(last_row["best_bid"]),
                        snapshot_best_ask=None if pd.isna(last_row["best_ask"]) else float(last_row["best_ask"]),
                        snapshot_side=None if pd.isna(last_row["side"]) else str(last_row["side"]),
                        snapshot_size=None if pd.isna(last_row["size"]) else float(last_row["size"]),
                        snapshot_fee_rate_bps=None if pd.isna(last_row["fee_rate_bps"]) else int(last_row["fee_rate_bps"]),
                    )
                )
    return rows


def _entry_price_from_snapshot(row: EntrySnapshotRow) -> float | None:
    if row.snapshot_best_ask is not None and row.snapshot_best_ask > 0:
        return row.snapshot_best_ask
    if row.snapshot_price is not None and row.snapshot_price > 0:
        return row.snapshot_price
    return None


def run_pmxt_weather_backtest(snapshot_rows: list[EntrySnapshotRow], threshold: float) -> dict[str, Any]:
    grouped: dict[tuple[str, float], list[EntrySnapshotRow]] = {}
    for row in snapshot_rows:
        grouped.setdefault((row.event_slug, row.entry_hours), []).append(row)

    summaries: list[EventBacktestSummary] = []
    summary_by_hour: dict[float, dict[str, float]] = {}

    for (event_slug, entry_hour), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: row.bucket_label)
        winner_label: str | None = None
        outcomes: list[OutcomeSnapshot] = []
        for row in rows:
            outcomes.append(
                OutcomeSnapshot(
                    label=row.bucket_label,
                    market_slug=row.market_slug,
                    yes_token_id=row.yes_token_id,
                    entry_price=_entry_price_from_snapshot(row),
                    history_points=1 if row.snapshot_timestamp_received is not None else 0,
                )
            )
        winner_label = rows[0].event_winner_label
        selection_mode, selected = select_positions(outcomes, threshold)
        selected_labels = [outcome.label for outcome in selected]
        selected_prices = [float(outcome.entry_price) for outcome in selected if outcome.entry_price is not None]
        selected_probability_sum = sum(selected_prices)
        did_hit = bool(selected) and any(outcome.label == winner_label for outcome in selected)
        pnl = (1.0 if did_hit else 0.0) - selected_probability_sum if selected else 0.0

        summaries.append(
            EventBacktestSummary(
                city_slug=rows[0].city_slug,
                target_date=rows[0].target_date,
                event_slug=event_slug,
                entry_hours=entry_hour,
                entry_time_utc=rows[0].entry_time_utc,
                selection_mode=selection_mode,
                selected_labels=selected_labels,
                selected_prices=selected_prices,
                selected_probability_sum=selected_probability_sum,
                pnl=pnl,
                did_hit=did_hit,
                winner_label=winner_label,
            )
        )

        acc = summary_by_hour.setdefault(
            entry_hour,
            {
                "events": 0.0,
                "traded": 0.0,
                "hit_count": 0.0,
                "total_pnl": 0.0,
            },
        )
        acc["events"] += 1
        if selected:
            acc["traded"] += 1
            acc["hit_count"] += 1 if did_hit else 0
            acc["total_pnl"] += pnl

    aggregate = []
    for entry_hour in sorted(summary_by_hour):
        acc = summary_by_hour[entry_hour]
        traded = int(acc["traded"])
        aggregate.append(
            {
                "entry_hours": entry_hour,
                "events": int(acc["events"]),
                "traded": traded,
                "hit_rate": (acc["hit_count"] / traded) if traded else 0.0,
                "total_pnl": acc["total_pnl"],
                "avg_pnl": (acc["total_pnl"] / traded) if traded else 0.0,
            }
        )
    return {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "threshold": threshold,
        "events": [asdict(row) for row in summaries],
        "summary_by_entry_hour": aggregate,
    }


def _save_snapshot_rows(rows: list[EntrySnapshotRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(row) for row in rows]).to_parquet(path, index=False, engine="pyarrow")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(default_catalog_path()))
    parser.add_argument("--cities", default="")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--entry-hours", default="6,12,18,24,36")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output-dir", default=str(default_output_dir()))
    parser.add_argument("--snapshot-output", default=str(default_snapshot_path()))
    parser.add_argument("--summary-output", default=str(default_backtest_summary_path()))
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    catalog_rows = load_catalog(Path(args.catalog))
    city_slugs = {slug for slug, _ in _parse_cities(args.cities)} if args.cities else None
    filtered = _filter_catalog_rows(
        catalog_rows,
        city_slugs=city_slugs,
        start_date=_parse_date(args.start_date),
        end_date=_parse_date(args.end_date),
    )
    entry_hours = _parse_entry_hours(args.entry_hours)
    output_dir = Path(args.output_dir)
    ensure_entry_hour_data(
        catalog_rows=filtered,
        output_dir=output_dir,
        entry_hours=entry_hours,
        workers=max(1, int(args.workers)),
    )
    snapshot_rows = build_entry_snapshots(catalog_rows=filtered, output_dir=output_dir, entry_hours=entry_hours)
    _save_snapshot_rows(snapshot_rows, Path(args.snapshot_output))
    # Winner labels are not yet stored in the PMXT catalog; the event-level backtest still runs but
    # should be treated as a pipeline validation unless winners are injected from a richer source.
    payload = run_pmxt_weather_backtest(snapshot_rows, threshold=float(args.threshold))
    Path(args.summary_output).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"snapshot_rows={len(snapshot_rows)}")
    print(f"snapshot_output={args.snapshot_output}")
    print(f"summary_output={args.summary_output}")
    for row in payload["summary_by_entry_hour"]:
        print(
            f"entry={row['entry_hours']:>4g}h events={row['events']:>3} traded={row['traded']:>3} "
            f"hit_rate={row['hit_rate']:.2%} total_pnl={row['total_pnl']:.4f} avg_pnl={row['avg_pnl']:.4f}"
        )


if __name__ == "__main__":
    main()
