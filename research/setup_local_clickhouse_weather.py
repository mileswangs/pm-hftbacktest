from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "pmxt_weather"
CH_ROOT = ROOT / "data" / "clickhouse_local"
CH_DATA = CH_ROOT / "data"
CH_TMP = CH_ROOT / "tmp"
SCHEMA_SQL = ROOT / "clickhouse_weather_schema.sql"


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"Missing required binary: {name}")
    return path


def _run_clickhouse(query: str) -> str:
    clickhouse = _require_binary("clickhouse")
    cmd = [
        clickhouse,
        "local",
        "--path",
        str(CH_DATA),
        "--tmp-path",
        str(CH_TMP),
        "--query",
        query,
    ]
    proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return proc.stdout


def bootstrap_schema() -> None:
    CH_DATA.mkdir(parents=True, exist_ok=True)
    CH_TMP.mkdir(parents=True, exist_ok=True)
    _run_clickhouse(SCHEMA_SQL.read_text())


def load_catalog() -> None:
    payload = json.loads((DATA_DIR / "weather_market_catalog.json").read_text())
    df = pd.DataFrame(payload["records"])
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    df["end_time_utc"] = pd.to_datetime(df["end_time_utc"], utc=True)
    catalog_path = CH_ROOT / "weather_market_catalog.parquet"
    df.to_parquet(catalog_path, index=False)
    _run_clickhouse(
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
    _run_clickhouse(
        f"""
        INSERT INTO pm_weather.pmxt_weather_ticks
        SELECT
            toDateTime(concat(replaceRegexpOne(_path, '^.*\\/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}})\\.weather\\.parquet$', '\\\\1'), ':00:00'), 'UTC') AS source_hour,
            toDateTime64(timestamp_received, 3, 'UTC'),
            toDateTime64OrNull(timestamp, 3, 'UTC'),
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


def summarize() -> None:
    out = _run_clickhouse(
        """
        SELECT
            (SELECT count() FROM pm_weather.weather_market_catalog) AS catalog_rows,
            (SELECT count() FROM pm_weather.pmxt_weather_ticks) AS tick_rows,
            (SELECT min(target_date) FROM pm_weather.pmxt_weather_ticks) AS min_date,
            (SELECT max(target_date) FROM pm_weather.pmxt_weather_ticks) AS max_date
        FORMAT Vertical
        """
    )
    print(out)


def main() -> None:
    bootstrap_schema()
    _run_clickhouse("TRUNCATE TABLE pm_weather.weather_market_catalog")
    _run_clickhouse("TRUNCATE TABLE pm_weather.pmxt_weather_ticks")
    load_catalog()
    load_ticks()
    summarize()


if __name__ == "__main__":
    main()
