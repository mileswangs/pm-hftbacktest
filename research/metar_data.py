"""Fetch METAR temperature observations for an airport station.

Two free, no-auth sources:

- ``live``: aviationweather.gov Data API, latest observations (~5 min refresh).
- ``history``: Iowa Environmental Mesonet ASOS archive, for backtesting.

Both write into the same local SQLite store so downstream signal code does not
care which source a row came from.

Usage:

    python3 research/metar_data.py live --station LEMD --hours 6
    python3 research/metar_data.py history --station LEMD --start-date 2026-03-15 --end-date 2026-06-22
    python3 research/metar_data.py stats --station LEMD
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "data" / "metar" / "metar.sqlite3"

AVIATIONWEATHER_METAR_URL = "https://aviationweather.gov/api/data/metar"
MESONET_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

USER_AGENT = "pm-hftbacktest-research/1.0 (METAR nowcasting research)"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metar_obs (
            station TEXT NOT NULL,
            obs_time_utc INTEGER NOT NULL,
            temp_c REAL,
            raw_metar TEXT,
            source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (station, obs_time_utc)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_metar_obs_station_time ON metar_obs(station, obs_time_utc)"
    )
    return conn


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_live(station: str, hours: int = 6) -> list[tuple[int, float | None, str]]:
    """Return [(obs_time_utc, temp_c, raw_metar), ...] for the last `hours` hours."""
    params = urllib.parse.urlencode({"ids": station, "format": "json", "hours": hours})
    data = json.loads(_http_get(f"{AVIATIONWEATHER_METAR_URL}?{params}"))
    rows = []
    for item in data:
        obs_time = item.get("obsTime")
        if obs_time is None:
            continue
        rows.append((int(obs_time), item.get("temp"), item.get("rawOb", "")))
    return rows


def fetch_history(station: str, start_date: dt.date, end_date: dt.date) -> list[tuple[int, float | None, str]]:
    """Return [(obs_time_utc, temp_c, raw_metar), ...] from the Iowa Mesonet ASOS archive.

    `end_date` is inclusive. Mesonet's API takes exclusive year/month/day2 bounds in
    practice (it is inclusive of day2 itself), so we pass end_date + 1 day to be safe.
    """
    query_end = end_date + dt.timedelta(days=1)
    params = {
        "station": station,
        "data": "tmpc",
        "year1": start_date.year,
        "month1": start_date.month,
        "day1": start_date.day,
        "year2": query_end.year,
        "month2": query_end.month,
        "day2": query_end.day,
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "no",
        "elev": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
    }
    url = f"{MESONET_ASOS_URL}?{urllib.parse.urlencode(params)}"
    text = _http_get(url).decode("utf-8")
    rows = []
    lines = text.strip().splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split(",")
        if len(parts) != 3:
            continue
        _station, valid, tmpc = parts
        if tmpc in ("M", "T", ""):
            continue
        try:
            obs_dt = dt.datetime.strptime(valid, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
            temp_c = float(tmpc)
        except ValueError:
            continue
        rows.append((int(obs_dt.timestamp()), temp_c, ""))
    return rows


def _store(conn: sqlite3.Connection, station: str, source: str, rows: list[tuple[int, float | None, str]]) -> int:
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    written = 0
    for obs_time_utc, temp_c, raw_metar in rows:
        if temp_c is None:
            continue
        conn.execute(
            """
            INSERT INTO metar_obs(station, obs_time_utc, temp_c, raw_metar, source, fetched_at_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(station, obs_time_utc) DO UPDATE SET
                temp_c = excluded.temp_c,
                raw_metar = CASE WHEN excluded.raw_metar != '' THEN excluded.raw_metar ELSE metar_obs.raw_metar END,
                source = excluded.source,
                fetched_at_utc = excluded.fetched_at_utc
            """,
            (station, obs_time_utc, temp_c, raw_metar, source, fetched_at),
        )
        written += 1
    conn.commit()
    return written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite path. Default: {DEFAULT_DB}")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="Fetch latest METAR obs from aviationweather.gov")
    live.add_argument("--station", default="LEMD", help="ICAO station code. Default: LEMD (Madrid-Barajas).")
    live.add_argument("--hours", type=int, default=6, help="Lookback window in hours. Default: 6.")

    history = sub.add_parser("history", help="Backfill historical METAR obs from Iowa Mesonet ASOS archive")
    history.add_argument("--station", default="LEMD")
    history.add_argument("--start-date", required=True, help="YYYY-MM-DD, inclusive.")
    history.add_argument("--end-date", required=True, help="YYYY-MM-DD, inclusive.")

    stats = sub.add_parser("stats", help="Print row counts and date range for a station")
    stats.add_argument("--station", default="LEMD")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    conn = _connect(args.db)

    if args.command == "live":
        rows = fetch_live(args.station, hours=args.hours)
        written = _store(conn, args.station, "aviationweather", rows)
        print(f"station={args.station} source=live fetched={len(rows)} stored={written}")
    elif args.command == "history":
        start = dt.date.fromisoformat(args.start_date)
        end = dt.date.fromisoformat(args.end_date)
        rows = fetch_history(args.station, start, end)
        written = _store(conn, args.station, "mesonet", rows)
        print(f"station={args.station} source=history range={start}..{end} fetched={len(rows)} stored={written}")
    elif args.command == "stats":
        cur = conn.execute(
            "SELECT COUNT(*), MIN(obs_time_utc), MAX(obs_time_utc) FROM metar_obs WHERE station = ?",
            (args.station,),
        )
        count, min_ts, max_ts = cur.fetchone()
        min_str = dt.datetime.fromtimestamp(min_ts, tz=dt.timezone.utc).isoformat() if min_ts else None
        max_str = dt.datetime.fromtimestamp(max_ts, tz=dt.timezone.utc).isoformat() if max_ts else None
        print(f"station={args.station} rows={count} range={min_str}..{max_str}")


if __name__ == "__main__":
    main()
