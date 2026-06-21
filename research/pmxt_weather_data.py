"""Build a weather-only local dataset from the public PMXT Polymarket archive.

This script has two jobs:

1. Build a historical weather market catalog from Polymarket Gamma events.
2. Download hourly PMXT v2 parquet files and keep only rows for weather asset_ids.

The resulting parquet files are small, event-aware, and suitable for building
execution-aware backtests over wider windows than the public prices-history API
can support.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
try:
    import duckdb
except ImportError:  # pragma: no cover - optional acceleration path
    duckdb = None

from multi_city_weather_scan import DEFAULT_CITIES
from weather_backtest import _build_event_slug, _parse_json_field, fetch_event


PMXT_BASE_URL = "https://r2v2.pmxt.dev"
PMXT_FILE_TEMPLATE = "polymarket_orderbook_{hour_key}.parquet"
PMXT_COVERAGE_START = dt.datetime(2026, 4, 13, 19, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class WeatherMarketCatalogRow:
    city_slug: str
    city_label: str
    target_date: str
    event_slug: str
    event_title: str
    end_time_utc: str
    event_winner_label: str | None
    market_slug: str
    bucket_label: str
    condition_id: str
    yes_token_id: str
    no_token_id: str | None
    is_winner: bool
    active: bool
    closed: bool


def default_output_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "pmxt_weather"


def default_catalog_path() -> Path:
    return default_output_dir() / "weather_market_catalog.json"


def default_manifest_path() -> Path:
    return default_output_dir() / "pmxt_weather_manifest.json"


def _parse_cities(raw: str) -> list[tuple[str, str]]:
    if not raw.strip():
        return list(DEFAULT_CITIES)
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if not slug:
            continue
        out.append((slug, " ".join(token.capitalize() for token in slug.split("-"))))
    return out


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _iter_dates(start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    days = (end_date - start_date).days + 1
    return [start_date + dt.timedelta(days=i) for i in range(days)]


def _normalize_market_binary(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8")
    return str(value)


def _download_file(url: str, output_path: Path, *, attempts: int = 3) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, output_path.open("wb") as handle:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            last_error = exc
            if output_path.exists():
                output_path.unlink()
            if attempt >= attempts:
                break
            time.sleep(min(5 * attempt, 15))
    if last_error is not None:
        raise last_error


def build_weather_market_catalog(
    *,
    cities: Iterable[tuple[str, str]],
    start_date: dt.date,
    end_date: dt.date,
) -> list[WeatherMarketCatalogRow]:
    rows: list[WeatherMarketCatalogRow] = []
    for city_slug, city_label in cities:
        for target_date in _iter_dates(start_date, end_date):
            event_slug = _build_event_slug(city_slug, target_date)
            event = fetch_event(event_slug)
            if event is None:
                continue
            winner_label = None
            for market in event["markets"]:
                try:
                    prices = _parse_json_field(market["outcomePrices"])
                    if float(prices[0]) > 0.99:
                        winner_label = str(market["groupItemTitle"])
                        break
                except Exception:
                    continue
            for market in event["markets"]:
                token_ids = _parse_json_field(market["clobTokenIds"])
                yes_token_id = str(token_ids[0])
                no_token_id = str(token_ids[1]) if len(token_ids) > 1 else None
                rows.append(
                    WeatherMarketCatalogRow(
                        city_slug=city_slug,
                        city_label=city_label,
                        target_date=target_date.isoformat(),
                        event_slug=str(event["slug"]),
                        event_title=str(event["title"]),
                        end_time_utc=str(event["endDate"]).replace("Z", "+00:00"),
                        event_winner_label=winner_label,
                        market_slug=str(market["slug"]),
                        bucket_label=str(market["groupItemTitle"]),
                        condition_id=str(market["conditionId"]),
                        yes_token_id=yes_token_id,
                        no_token_id=no_token_id,
                        is_winner=str(market["groupItemTitle"]) == winner_label,
                        active=bool(market.get("active")),
                        closed=bool(market.get("closed")),
                    )
                )
    rows.sort(key=lambda row: (row.target_date, row.city_slug, row.bucket_label))
    return rows


def save_catalog(rows: list[WeatherMarketCatalogRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "records": [asdict(row) for row in rows],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_catalog(path: Path) -> list[WeatherMarketCatalogRow]:
    payload = json.loads(path.read_text())
    return [WeatherMarketCatalogRow(**row) for row in payload["records"]]


def _filter_catalog_rows(
    rows: list[WeatherMarketCatalogRow],
    *,
    city_slugs: set[str] | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[WeatherMarketCatalogRow]:
    out: list[WeatherMarketCatalogRow] = []
    for row in rows:
        row_date = dt.date.fromisoformat(row.target_date)
        if city_slugs and row.city_slug not in city_slugs:
            continue
        if start_date and row_date < start_date:
            continue
        if end_date and row_date > end_date:
            continue
        out.append(row)
    return out


def _hour_key(ts: dt.datetime) -> str:
    ts_utc = ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    return ts_utc.strftime("%Y-%m-%dT%H")


def _hour_range(start_ts: dt.datetime, end_ts: dt.datetime) -> list[dt.datetime]:
    start_utc = start_ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_utc = end_ts.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    if end_utc < start_utc:
        return []
    out: list[dt.datetime] = []
    current = start_utc
    while current <= end_utc:
        out.append(current)
        current += dt.timedelta(hours=1)
    return out


def _build_hour_map(
    rows: list[WeatherMarketCatalogRow],
    *,
    lookback_hours: int,
) -> dict[str, list[WeatherMarketCatalogRow]]:
    hour_map: dict[str, list[WeatherMarketCatalogRow]] = {}
    for row in rows:
        end_time = dt.datetime.fromisoformat(row.end_time_utc)
        start_time = max(PMXT_COVERAGE_START, end_time - dt.timedelta(hours=lookback_hours))
        for hour in _hour_range(start_time, end_time):
            hour_map.setdefault(_hour_key(hour), []).append(row)
    return hour_map


def build_entry_hour_map(
    rows: list[WeatherMarketCatalogRow],
    *,
    entry_hours: list[float],
    include_previous_hour: bool,
) -> dict[str, list[WeatherMarketCatalogRow]]:
    hour_map: dict[str, list[WeatherMarketCatalogRow]] = {}
    for row in rows:
        end_time = dt.datetime.fromisoformat(row.end_time_utc)
        for entry_hour in entry_hours:
            entry_time = end_time - dt.timedelta(hours=entry_hour)
            if entry_time < PMXT_COVERAGE_START:
                continue
            hour_keys = [_hour_key(entry_time)]
            if include_previous_hour:
                hour_keys.append(_hour_key(entry_time - dt.timedelta(hours=1)))
            for hour_key in hour_keys:
                hour_map.setdefault(hour_key, []).append(row)
    return hour_map


def _pmxt_url(hour_key: str) -> str:
    return f"{PMXT_BASE_URL}/{PMXT_FILE_TEMPLATE.format(hour_key=hour_key)}"


def _read_remote_filtered_hour(url: str, asset_ids: list[str]) -> pd.DataFrame | None:
    if duckdb is None:
        return None
    if not asset_ids:
        return pd.DataFrame()
    con = duckdb.connect()
    try:
        placeholders = ",".join(["?"] * len(asset_ids))
        query = f"""
            SELECT
                timestamp_received,
                timestamp,
                market,
                event_type,
                asset_id,
                bids,
                asks,
                price,
                size,
                side,
                best_bid,
                best_ask,
                fee_rate_bps,
                transaction_hash,
                old_tick_size,
                new_tick_size
            FROM read_parquet(?, union_by_name=true)
            WHERE asset_id IN ({placeholders})
        """
        return con.execute(query, [url, *asset_ids]).fetch_df()
    finally:
        con.close()


def _extract_hour(
    *,
    hour_key: str,
    hour_rows: list[WeatherMarketCatalogRow],
    output_dir: Path,
    keep_raw: bool,
) -> dict[str, object]:
    raw_dir = output_dir / "raw_cache"
    filtered_dir = output_dir / "weather_hourly"
    raw_path = raw_dir / PMXT_FILE_TEMPLATE.format(hour_key=hour_key)
    filtered_path = filtered_dir / f"{hour_key}.weather.parquet"
    temp_dir: Path | None = None

    if filtered_path.exists():
        try:
            existing = pd.read_parquet(filtered_path, columns=["asset_id"])
            return {
                "hour_key": hour_key,
                "status": "cached",
                "rows": int(len(existing)),
                "assets": int(existing["asset_id"].nunique()) if len(existing) else 0,
                "path": str(filtered_path),
            }
        except Exception:
            filtered_path.unlink(missing_ok=True)

    url = _pmxt_url(hour_key)
    temp_path: Path | None = None
    try:
        asset_ids = sorted({row.yes_token_id for row in hour_rows})
        hour_catalog = pd.DataFrame([asdict(row) for row in hour_rows]).drop_duplicates(subset=["yes_token_id"])
        try:
            df = None if keep_raw else _read_remote_filtered_hour(url, asset_ids)
        except Exception:
            df = None

        if df is None:
            try:
                if keep_raw:
                    if not raw_path.exists():
                        _download_file(url, raw_path)
                    parquet_path = raw_path
                else:
                    temp_dir = Path(tempfile.mkdtemp(prefix="pmxt_weather_"))
                    temp_path = temp_dir / PMXT_FILE_TEMPLATE.format(hour_key=hour_key)
                    _download_file(url, temp_path)
                    parquet_path = temp_path
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return {"hour_key": hour_key, "status": "missing_remote", "rows": 0, "assets": 0, "path": ""}
                raise

            try:
                df = pd.read_parquet(
                    parquet_path,
                    columns=[
                        "timestamp_received",
                        "timestamp",
                        "market",
                        "event_type",
                        "asset_id",
                        "bids",
                        "asks",
                        "price",
                        "size",
                        "side",
                        "best_bid",
                        "best_ask",
                        "fee_rate_bps",
                        "transaction_hash",
                        "old_tick_size",
                        "new_tick_size",
                    ],
                    filters=[("asset_id", "in", asset_ids)],
                    engine="pyarrow",
                )
            except ValueError:
                # Some pandas/pyarrow combinations reject very long IN lists; fall back to post-filter.
                df = pd.read_parquet(parquet_path, engine="pyarrow")
                df = df[df["asset_id"].isin(asset_ids)]

        if len(df) == 0:
            return {"hour_key": hour_key, "status": "empty_filtered", "rows": 0, "assets": 0, "path": ""}

        df["market"] = df["market"].map(_normalize_market_binary)
        merged = df.merge(hour_catalog, how="left", left_on="asset_id", right_on="yes_token_id")
        merged = merged[merged["condition_id"].notna()].copy()
        if len(merged) == 0:
            return {"hour_key": hour_key, "status": "no_catalog_match", "rows": 0, "assets": 0, "path": ""}

        filtered_path.parent.mkdir(parents=True, exist_ok=True)
        temp_filtered_path = filtered_path.with_name(filtered_path.name + ".tmp")
        merged.to_parquet(temp_filtered_path, index=False, engine="pyarrow")
        temp_filtered_path.replace(filtered_path)
        return {
            "hour_key": hour_key,
            "status": "written",
            "rows": int(len(merged)),
            "assets": int(merged["asset_id"].nunique()),
            "path": str(filtered_path),
            "event_types": {str(k): int(v) for k, v in merged["event_type"].value_counts().to_dict().items()},
        }
    finally:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def extract_pmxt_weather(
    *,
    catalog_rows: list[WeatherMarketCatalogRow],
    output_dir: Path,
    lookback_hours: int,
    keep_raw: bool,
    workers: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    hour_map = _build_hour_map(catalog_rows, lookback_hours=lookback_hours)
    manifest_rows: list[dict[str, object]] = []

    def run_one(hour_key: str) -> dict[str, object]:
        return _extract_hour(
            hour_key=hour_key,
            hour_rows=hour_map[hour_key],
            output_dir=output_dir,
            keep_raw=keep_raw,
        )

    hour_keys = sorted(hour_map)
    if workers <= 1:
        manifest_rows = [run_one(hour_key) for hour_key in hour_keys]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_one, hour_key): hour_key for hour_key in hour_keys}
            for future in concurrent.futures.as_completed(futures):
                manifest_rows.append(future.result())

    manifest_rows.sort(key=lambda row: str(row["hour_key"]))
    total_rows = sum(int(row["rows"]) for row in manifest_rows if row["status"] in {"written", "cached"})
    written_hours = sum(1 for row in manifest_rows if row["status"] in {"written", "cached"})

    manifest = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "catalog_records": len(catalog_rows),
        "hours_considered": len(hour_map),
        "hours_with_output": written_hours,
        "total_rows": total_rows,
        "files": manifest_rows,
    }
    (output_dir / "pmxt_weather_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    catalog_parser = sub.add_parser("catalog", help="Build a historical weather market catalog.")
    catalog_parser.add_argument("--cities", default="")
    catalog_parser.add_argument("--start-date", required=True)
    catalog_parser.add_argument("--end-date", required=True)
    catalog_parser.add_argument("--output", default=str(default_catalog_path()))

    extract_parser = sub.add_parser("extract", help="Fetch and clean PMXT weather-only parquet slices.")
    extract_parser.add_argument("--catalog", default=str(default_catalog_path()))
    extract_parser.add_argument("--cities", default="")
    extract_parser.add_argument("--start-date", default="")
    extract_parser.add_argument("--end-date", default="")
    extract_parser.add_argument("--lookback-hours", type=int, default=48)
    extract_parser.add_argument("--output-dir", default=str(default_output_dir()))
    extract_parser.add_argument("--keep-raw", action="store_true")
    extract_parser.add_argument("--workers", type=int, default=4)

    stats_parser = sub.add_parser("stats", help="Summarize the cleaned PMXT weather dataset.")
    stats_parser.add_argument("--manifest", default=str(default_manifest_path()))

    return parser.parse_args()


def _command_catalog(args: argparse.Namespace) -> None:
    cities = _parse_cities(args.cities)
    rows = build_weather_market_catalog(
        cities=cities,
        start_date=_parse_date(args.start_date),
        end_date=_parse_date(args.end_date),
    )
    output_path = Path(args.output)
    save_catalog(rows, output_path)
    print(f"catalog_records={len(rows)}")
    print(f"catalog_path={output_path}")


def _command_extract(args: argparse.Namespace) -> None:
    catalog_rows = load_catalog(Path(args.catalog))
    filtered = _filter_catalog_rows(
        catalog_rows,
        city_slugs={slug for slug, _ in _parse_cities(args.cities)} if args.cities else None,
        start_date=_parse_date(args.start_date) if args.start_date else None,
        end_date=_parse_date(args.end_date) if args.end_date else None,
    )
    manifest = extract_pmxt_weather(
        catalog_rows=filtered,
        output_dir=Path(args.output_dir),
        lookback_hours=args.lookback_hours,
        keep_raw=args.keep_raw,
        workers=max(1, int(args.workers)),
    )
    print(f"catalog_records={manifest['catalog_records']}")
    print(f"hours_considered={manifest['hours_considered']}")
    print(f"hours_with_output={manifest['hours_with_output']}")
    print(f"total_rows={manifest['total_rows']}")
    print(f"manifest_path={Path(args.output_dir) / 'pmxt_weather_manifest.json'}")


def _command_stats(args: argparse.Namespace) -> None:
    manifest = json.loads(Path(args.manifest).read_text())
    print(f"generated_at_utc={manifest['generated_at_utc']}")
    print(f"lookback_hours={manifest['lookback_hours']}")
    print(f"catalog_records={manifest['catalog_records']}")
    print(f"hours_considered={manifest['hours_considered']}")
    print(f"hours_with_output={manifest['hours_with_output']}")
    print(f"total_rows={manifest['total_rows']}")
    by_status: dict[str, int] = {}
    for row in manifest["files"]:
        by_status[str(row["status"])] = by_status.get(str(row["status"]), 0) + 1
    print("status_counts=" + json.dumps(by_status, ensure_ascii=False, sort_keys=True))


def main() -> None:
    args = _parse_args()
    if args.command == "catalog":
        _command_catalog(args)
    elif args.command == "extract":
        _command_extract(args)
    elif args.command == "stats":
        _command_stats(args)
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
