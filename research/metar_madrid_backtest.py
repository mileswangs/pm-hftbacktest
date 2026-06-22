"""Backtest the METAR hard-elimination / NO-convergence signal on historical Madrid events.

For each settled "Highest temperature in Madrid" event already in the local
weather warehouse (research/data/weather_warehouse/weather.sqlite3), replay the
day's METAR observations (research/data/metar/metar.sqlite3) in time order. The
moment a bucket's upper bound is exceeded by the running daily max, it is
mathematically dead. If that bucket's live NO price (1 - YES price, looked up
from the recorded CLOB price history) is still below a threshold, simulate
buying NO there and holding to settlement.

This does not assume METAR ground truth matches Polymarket's actual settlement
source (Wunderground) -- every simulated trade is checked against the market's
real `is_winner` outcome, so any METAR/Wunderground divergence shows up directly
as a degraded hit rate rather than being assumed away.

Usage:
    python3 research/metar_madrid_backtest.py --thresholds 0.80,0.90,0.95,0.97,0.99
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import sqlite3
from pathlib import Path

from metar_nowcast import MADRID_TZ, MetarObs, dead_buckets, parse_bucket, running_max_series, staleness_gaps

WAREHOUSE_DB = Path(__file__).parent / "data" / "weather_warehouse" / "weather.sqlite3"
METAR_DB = Path(__file__).parent / "data" / "metar" / "metar.sqlite3"


def load_metar_obs(db_path: Path, station: str) -> list[MetarObs]:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT obs_time_utc, temp_c FROM metar_obs WHERE station = ? ORDER BY obs_time_utc",
        (station,),
    )
    return [MetarObs(ts, temp) for ts, temp in cur.fetchall()]


def load_settled_events(db_path: Path, city_slug: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT event_slug, target_date, winner_label
        FROM events
        WHERE city_slug = ? AND winner_label IS NOT NULL
        ORDER BY target_date
        """,
        (city_slug,),
    )
    events = [dict(row) for row in cur.fetchall()]
    for event in events:
        outcomes = conn.execute(
            """
            SELECT outcome_label, yes_token_id, is_winner
            FROM outcomes
            WHERE event_slug = ?
            """,
            (event["event_slug"],),
        ).fetchall()
        event["outcomes"] = [dict(row) for row in outcomes]
    return events


def load_price_history(db_path: Path, yes_token_ids: list[str]) -> dict[str, list[tuple[int, float]]]:
    conn = sqlite3.connect(db_path)
    history: dict[str, list[tuple[int, float]]] = {}
    for token_id in yes_token_ids:
        cur = conn.execute(
            "SELECT ts, price FROM price_history WHERE yes_token_id = ? ORDER BY ts",
            (token_id,),
        )
        history[token_id] = cur.fetchall()
    return history


def _price_at_or_after(history: list[tuple[int, float]], ts: int) -> float | None:
    timestamps = [t for t, _ in history]
    idx = bisect.bisect_left(timestamps, ts)
    if idx >= len(history):
        return None
    return history[idx][1]


def collect_death_instances(city_slug: str, station: str, max_gap_minutes: int = 90) -> dict:
    """Every bucket-death event across all settled days, independent of any threshold.

    Returns {"instances": [...], "no_metar_data_days": [...], "stale_gap_days": [...]}.
    Each instance has the death timestamp, the NO price observed at-or-after it, and
    the bucket's actual settlement outcome -- threshold filtering happens downstream.
    """
    events = load_settled_events(WAREHOUSE_DB, city_slug)
    all_obs = load_metar_obs(METAR_DB, station)

    all_token_ids = [o["yes_token_id"] for e in events for o in e["outcomes"]]
    price_histories = load_price_history(WAREHOUSE_DB, all_token_ids)

    instances: list[dict] = []
    no_metar_data_days = []
    stale_gap_days = []

    for event in events:
        target_date = dt.date.fromisoformat(event["target_date"])
        buckets = []
        bucket_to_outcome = {}
        for outcome in event["outcomes"]:
            try:
                bucket = parse_bucket(outcome["outcome_label"])
            except ValueError:
                continue
            buckets.append(bucket)
            bucket_to_outcome[bucket.label] = outcome

        day_obs = [o for o in all_obs if _same_local_date(o, target_date)]
        if not day_obs:
            no_metar_data_days.append(event["target_date"])
            continue

        gaps = staleness_gaps([o.obs_time_utc for o in day_obs], max_gap_minutes * 60)
        if gaps:
            stale_gap_days.append((event["target_date"], len(gaps)))

        series = running_max_series(all_obs, target_date)
        seen_dead: set[str] = set()
        for obs_time, running_max in series:
            newly_dead = dead_buckets(running_max, buckets) - seen_dead
            for label in newly_dead:
                seen_dead.add(label)
                outcome = bucket_to_outcome[label]
                history = price_histories.get(outcome["yes_token_id"], [])
                yes_price = _price_at_or_after(history, obs_time)
                if yes_price is None:
                    continue
                instances.append(
                    {
                        "event_slug": event["event_slug"],
                        "target_date": event["target_date"],
                        "bucket": label,
                        "death_time_utc": obs_time,
                        "running_max_c": running_max,
                        "no_entry_price": 1.0 - yes_price,
                        "actual_is_winner": bool(outcome["is_winner"]),
                    }
                )

    return {
        "events_total": len(events),
        "instances": instances,
        "no_metar_data_days": no_metar_data_days,
        "stale_gap_days": stale_gap_days,
    }


def summarize_by_threshold(instances: list[dict], thresholds: list[float]) -> list[dict]:
    summary_by_threshold = []
    for threshold in thresholds:
        trades = [inst for inst in instances if inst["no_entry_price"] < threshold]
        if not trades:
            summary_by_threshold.append({"threshold": threshold, "trade_count": 0})
            continue
        wrong = [t for t in trades if t["actual_is_winner"]]
        pnl_per_share = [
            (-1.0 if t["actual_is_winner"] else (1.0 - t["no_entry_price"])) for t in trades
        ]
        summary_by_threshold.append(
            {
                "threshold": threshold,
                "trade_count": len(trades),
                "unique_days": len({t["target_date"] for t in trades}),
                "wrong_count": len(wrong),
                "hit_rate": 1.0 - len(wrong) / len(trades),
                "avg_pnl_per_share": sum(pnl_per_share) / len(pnl_per_share),
                "total_pnl_per_share": sum(pnl_per_share),
                "avg_no_entry_price": sum(t["no_entry_price"] for t in trades) / len(trades),
                "wrong_examples": [t["event_slug"] + ":" + t["bucket"] for t in wrong][:5],
            }
        )
    return summary_by_threshold


def run_backtest(city_slug: str, station: str, thresholds: list[float], max_gap_minutes: int = 90) -> dict:
    collected = collect_death_instances(city_slug, station, max_gap_minutes)
    return {
        "city_slug": city_slug,
        "station": station,
        "events_total": collected["events_total"],
        "no_metar_data_days": collected["no_metar_data_days"],
        "stale_gap_days": collected["stale_gap_days"],
        "summary_by_threshold": summarize_by_threshold(collected["instances"], thresholds),
    }


def _same_local_date(obs: MetarObs, target_date: dt.date) -> bool:
    return dt.datetime.fromtimestamp(obs.obs_time_utc, tz=MADRID_TZ).date() == target_date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-slug", default="madrid")
    parser.add_argument("--station", default="LEMD")
    parser.add_argument("--thresholds", default="0.80,0.85,0.90,0.95,0.97,0.99")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data" / "metar" / "madrid_backtest_results.json")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    thresholds = [float(x) for x in args.thresholds.split(",")]
    result = run_backtest(args.city_slug, args.station, thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
