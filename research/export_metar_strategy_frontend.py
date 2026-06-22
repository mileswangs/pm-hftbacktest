"""Export the METAR hard-elimination backtest as static JSON for the frontend.

The frontend does no backtest computation of its own -- this script does all the
work (reusing metar_madrid_backtest.py) and writes a precomputed dataset that a
display-only React page reads. Output is keyed by station, not city, so adding a
new station later is just: run this script with different args, drop the JSON in
the same directory, add one entry to frontend/src/metar/stationCatalog.ts.

Usage:
    python3 research/export_metar_strategy_frontend.py \
        --city-slug madrid --station LEMD \
        --output ../frontend/public/data/metar/lemd.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from metar_madrid_backtest import WAREHOUSE_DB, collect_death_instances, load_settled_events, summarize_by_threshold
from metar_nowcast import MADRID_TZ

DEFAULT_THRESHOLDS = [0.80, 0.85, 0.90, 0.95, 0.97, 0.99]
DEFAULT_OUTPUT = Path(__file__).parent.parent / "frontend" / "public" / "data" / "metar" / "lemd.json"

RESOLUTION_SOURCES = {
    "madrid": "https://www.wunderground.com/history/daily/es/madrid/LEMD",
}
STATION_LABELS = {
    "LEMD": "Madrid-Barajas Airport (LEMD)",
}
CITY_LABELS = {
    "madrid": "Madrid",
}


def build_dataset(city_slug: str, station: str, thresholds: list[float]) -> dict:
    collected = collect_death_instances(city_slug, station)
    instances = collected["instances"]

    trades = []
    for inst in instances:
        death_local = dt.datetime.fromtimestamp(inst["death_time_utc"], tz=MADRID_TZ)
        pnl_per_share = -1.0 if inst["actual_is_winner"] else (1.0 - inst["no_entry_price"])
        trades.append(
            {
                "eventSlug": inst["event_slug"],
                "targetDate": inst["target_date"],
                "bucketLabel": inst["bucket"],
                "deathTimeUtc": dt.datetime.fromtimestamp(inst["death_time_utc"], tz=dt.timezone.utc).isoformat(),
                "deathLocalHour": death_local.hour + death_local.minute / 60,
                "runningMaxC": inst["running_max_c"],
                "noEntryPrice": round(inst["no_entry_price"], 4),
                "actualIsWinner": inst["actual_is_winner"],
                "pnlPerShare": round(pnl_per_share, 4),
            }
        )
    trades.sort(key=lambda t: (t["targetDate"], t["deathTimeUtc"]))

    summary = summarize_by_threshold(instances, thresholds)
    summary_camel = [
        {
            "threshold": row["threshold"],
            "tradeCount": row.get("trade_count", 0),
            "uniqueDays": row.get("unique_days", 0),
            "hitRate": row.get("hit_rate"),
            "avgPnlPerShare": row.get("avg_pnl_per_share"),
            "totalPnlPerShare": row.get("total_pnl_per_share"),
            "avgNoEntryPrice": row.get("avg_no_entry_price"),
        }
        for row in summary
    ]

    all_dates = [e["target_date"] for e in load_settled_events(WAREHOUSE_DB, city_slug)]
    date_range = {"start": min(all_dates), "end": max(all_dates)} if all_dates else None

    return {
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "citySlug": city_slug,
        "cityLabel": CITY_LABELS.get(city_slug, city_slug.title()),
        "station": station,
        "stationLabel": STATION_LABELS.get(station, station),
        "resolutionSource": RESOLUTION_SOURCES.get(city_slug),
        "eventsTotal": collected["events_total"],
        "dateRange": date_range,
        "thresholds": thresholds,
        "summaryByThreshold": summary_camel,
        "trades": trades,
        "noMetarDataDays": collected["no_metar_data_days"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-slug", default="madrid")
    parser.add_argument("--station", default="LEMD")
    parser.add_argument("--thresholds", default=",".join(str(t) for t in DEFAULT_THRESHOLDS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    thresholds = [float(x) for x in args.thresholds.split(",")]
    dataset = build_dataset(args.city_slug, args.station, thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2))
    print(f"wrote {args.output} ({len(dataset['trades'])} trades, {dataset['eventsTotal']} events)")


if __name__ == "__main__":
    main()
