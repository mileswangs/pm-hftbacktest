"""Run the weather alpha backtest across multiple cities."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from weather_backtest import _build_event_slug, backtest_event, fetch_event


DEFAULT_CITIES = [
    ("chengdu", "Chengdu"),
    ("beijing", "Beijing"),
    ("shanghai", "Shanghai"),
    ("guangzhou", "Guangzhou"),
    ("shenzhen", "Shenzhen"),
    ("tokyo", "Tokyo"),
    ("seoul", "Seoul"),
    ("hong-kong", "Hong Kong"),
    ("singapore", "Singapore"),
    ("los-angeles", "Los Angeles"),
    ("london", "London"),
    ("paris", "Paris"),
    ("madrid", "Madrid"),
    ("taipei", "Taipei"),
]


@dataclass(frozen=True)
class CityHourSummary:
    city_slug: str
    city_label: str
    entry_hours: float
    events_found: int
    traded_count: int
    hit_rate: float
    total_pnl: float
    avg_pnl: float
    single_count: int
    pair_count: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-date", default="2026-06-19")
    parser.add_argument("--days", type=int, default=17)
    parser.add_argument("--entry-hours", default="6,12,18,24,36")
    parser.add_argument("--cities", default="")
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


def _parse_entry_hours(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_cities(raw: str) -> list[tuple[str, str]]:
    if not raw.strip():
        return DEFAULT_CITIES
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if not slug:
            continue
        label = " ".join(token.capitalize() for token in slug.split("-"))
        out.append((slug, label))
    return out


def _target_dates(anchor_date: str, days: int) -> list[dt.date]:
    anchor = dt.date.fromisoformat(anchor_date)
    start = anchor - dt.timedelta(days=days - 1)
    return [start + dt.timedelta(days=i) for i in range(days)]


def run_city(city_slug: str, city_label: str, target_dates: list[dt.date], entry_hours: list[float]) -> list[CityHourSummary]:
    per_hour: dict[float, dict[str, float]] = {
        hour: {
            "events_found": 0.0,
            "traded_count": 0.0,
            "hit_count": 0.0,
            "total_pnl": 0.0,
            "single_count": 0.0,
            "pair_count": 0.0,
        }
        for hour in entry_hours
    }

    for target_date in target_dates:
        slug = _build_event_slug(city_slug, target_date)
        event = fetch_event(slug)
        if event is None:
            continue
        for hour in entry_hours:
            result = backtest_event(event, entry_hours_before_end=hour, threshold=0.5)
            acc = per_hour[hour]
            acc["events_found"] += 1
            if result.selected_labels:
                acc["traded_count"] += 1
                acc["hit_count"] += 1 if result.did_hit else 0
                acc["total_pnl"] += result.pnl
                if result.selection_mode == "single_over_threshold":
                    acc["single_count"] += 1
                elif result.selection_mode == "pair_over_threshold":
                    acc["pair_count"] += 1

    summaries: list[CityHourSummary] = []
    for hour in entry_hours:
        acc = per_hour[hour]
        traded = int(acc["traded_count"])
        summaries.append(
            CityHourSummary(
                city_slug=city_slug,
                city_label=city_label,
                entry_hours=hour,
                events_found=int(acc["events_found"]),
                traded_count=traded,
                hit_rate=(acc["hit_count"] / traded) if traded else 0.0,
                total_pnl=acc["total_pnl"],
                avg_pnl=(acc["total_pnl"] / traded) if traded else 0.0,
                single_count=int(acc["single_count"]),
                pair_count=int(acc["pair_count"]),
            )
        )
    return summaries


def _print_report(rows: list[CityHourSummary]) -> None:
    grouped: dict[str, list[CityHourSummary]] = {}
    for row in rows:
        grouped.setdefault(row.city_slug, []).append(row)

    print(
        "city          best_hour  events  traded  hit_rate  total_pnl  avg_pnl"
        "   single  pair"
    )
    print("-" * 96)
    ranked: list[tuple[str, CityHourSummary]] = []
    for city_slug, city_rows in grouped.items():
        best = max(city_rows, key=lambda row: (row.total_pnl, row.hit_rate, -row.entry_hours))
        ranked.append((city_slug, best))

    for _, best in sorted(ranked, key=lambda item: item[1].total_pnl, reverse=True):
        print(
            f"{best.city_label[:12]:<13}"
            f"{int(best.entry_hours):>6}h"
            f"{best.events_found:>8}"
            f"{best.traded_count:>8}"
            f"{best.hit_rate:>10.1%}"
            f"{best.total_pnl:>11.3f}"
            f"{best.avg_pnl:>9.3f}"
            f"{best.single_count:>8}"
            f"{best.pair_count:>6}"
        )


def main() -> None:
    args = _parse_args()
    entry_hours = _parse_entry_hours(args.entry_hours)
    cities = _parse_cities(args.cities)
    dates = _target_dates(args.anchor_date, args.days)

    rows: list[CityHourSummary] = []
    for city_slug, city_label in cities:
        rows.extend(run_city(city_slug, city_label, dates, entry_hours))

    if args.output_json:
        Path(args.output_json).write_text(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))

    _print_report(rows)


if __name__ == "__main__":
    main()
