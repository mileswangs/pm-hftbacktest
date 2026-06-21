from __future__ import annotations

import json
from pathlib import Path

import chdb
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "pmxt_weather"
DB_PATH = ROOT / "data" / "chdb_weather.db"
SCHEMA_SQL = ROOT / "clickhouse_weather_schema.sql"


def _conn():
    return chdb.connect(str(DB_PATH))


def _exec(query: str) -> str:
    conn = _conn()
    return conn.query(query)


def bootstrap_schema() -> None:
    _exec(SCHEMA_SQL.read_text())


def truncate_all() -> None:
    _exec("TRUNCATE TABLE pm_weather.weather_market_catalog")
    _exec("TRUNCATE TABLE pm_weather.pmxt_weather_ticks")
    _exec("TRUNCATE TABLE pm_weather.pmxt_weather_entry_snapshots")
    _exec("TRUNCATE TABLE pm_weather.pmxt_weather_backtests")


def load_catalog() -> None:
    payload = json.loads((DATA_DIR / "weather_market_catalog.json").read_text())
    df = pd.DataFrame(payload["records"])
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    df["end_time_utc"] = pd.to_datetime(df["end_time_utc"], utc=True)
    catalog_path = DATA_DIR / "_catalog_load.parquet"
    df.to_parquet(catalog_path, index=False)
    _exec(
        f"""
        INSERT INTO pm_weather.weather_market_catalog
        SELECT
            city_slug,
            city_label,
            toDate(target_date),
            event_slug,
            event_title,
            toDateTime64(end_time_utc, 3, 'UTC'),
            nullIf(event_winner_label, ''),
            market_slug,
            bucket_label,
            condition_id,
            yes_token_id,
            nullIf(no_token_id, ''),
            is_winner,
            active,
            closed
        FROM file('{catalog_path.as_posix()}', Parquet)
        """
    )


def load_ticks() -> None:
    parquet_glob = (DATA_DIR / "weather_hourly" / "*.weather.parquet").as_posix()
    _exec(
        f"""
        INSERT INTO pm_weather.pmxt_weather_ticks
        SELECT
            parseDateTimeBestEffortOrNull(
                replaceRegexpOne(_path, '^.*\\/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}})\\.weather\\.parquet$', '\\\\1') || ':00:00'
            ) AS source_hour,
            toDateTime64(timestamp_received, 3, 'UTC'),
            timestamp,
            market,
            nullIf(event_type, ''),
            asset_id,
            toString(bids),
            toString(asks),
            price,
            size,
            nullIf(side, ''),
            best_bid,
            best_ask,
            fee_rate_bps,
            nullIf(transaction_hash, ''),
            old_tick_size,
            new_tick_size,
            city_slug,
            city_label,
            toDate(target_date),
            event_slug,
            event_title,
            toDateTime64(end_time_utc, 3, 'UTC'),
            nullIf(event_winner_label, ''),
            market_slug,
            bucket_label,
            condition_id,
            yes_token_id,
            nullIf(no_token_id, ''),
            is_winner,
            active,
            closed
        FROM file('{parquet_glob}', Parquet)
        """
    )


def load_snapshots_and_backtests() -> None:
    snapshot_path = DATA_DIR / "madrid_pmxt_entry_snapshots.parquet"
    summary_path = DATA_DIR / "madrid_pmxt_weather_backtest_summary.json"
    if snapshot_path.exists():
        _exec(
            f"""
            INSERT INTO pm_weather.pmxt_weather_entry_snapshots
            SELECT
                city_slug,
                city_label,
                toDate(target_date),
                event_slug,
                event_title,
                nullIf(event_winner_label, ''),
                entry_hours,
                toDateTime64(entry_time_utc, 3, 'UTC'),
                bucket_label,
                condition_id,
                yes_token_id,
                market_slug,
                is_winner,
                source_hour_key,
                parseDateTime64BestEffortOrNull(snapshot_timestamp_received, 3, 'UTC'),
                parseDateTime64BestEffortOrNull(snapshot_timestamp, 3, 'UTC'),
                nullIf(snapshot_event_type, ''),
                snapshot_price,
                snapshot_best_bid,
                snapshot_best_ask,
                nullIf(snapshot_side, ''),
                snapshot_size,
                snapshot_fee_rate_bps
            FROM file('{snapshot_path.as_posix()}', Parquet)
            """
        )
    if summary_path.exists():
        payload = json.loads(summary_path.read_text())
        events = pd.DataFrame(payload["events"])
        if len(events):
            backtest_path = DATA_DIR / "_madrid_backtests_load.parquet"
            events["target_date"] = pd.to_datetime(events["target_date"]).dt.date
            events["entry_time_utc"] = pd.to_datetime(events["entry_time_utc"], utc=True)
            events.to_parquet(backtest_path, index=False)
            _exec(
                f"""
                INSERT INTO pm_weather.pmxt_weather_backtests
                SELECT
                    city_slug,
                    toDate(target_date),
                    event_slug,
                    entry_hours,
                    entry_time_utc,
                    selection_mode,
                    selected_labels,
                    selected_prices,
                    selected_probability_sum,
                    pnl,
                    did_hit,
                    nullIf(winner_label, '')
                FROM file('{backtest_path.as_posix()}', Parquet)
                """
            )


def summarize() -> None:
    out = _exec(
        """
        SELECT
            (SELECT count() FROM pm_weather.weather_market_catalog) AS catalog_rows,
            (SELECT count() FROM pm_weather.pmxt_weather_ticks) AS tick_rows,
            (SELECT count() FROM pm_weather.pmxt_weather_entry_snapshots) AS snapshot_rows,
            (SELECT count() FROM pm_weather.pmxt_weather_backtests) AS backtest_rows,
            (SELECT min(target_date) FROM pm_weather.pmxt_weather_ticks) AS min_date,
            (SELECT max(target_date) FROM pm_weather.pmxt_weather_ticks) AS max_date
        FORMAT Vertical
        """
    )
    print(out)


def main() -> None:
    bootstrap_schema()
    truncate_all()
    load_catalog()
    load_ticks()
    load_snapshots_and_backtests()
    summarize()


if __name__ == "__main__":
    main()
