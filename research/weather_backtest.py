"""Backtest a multi-outcome Polymarket weather event strategy.

This script discovers daily "Highest temperature in <city>" events from the
public Gamma API, fetches each outcome token's historical YES price series from
the public CLOB API, and evaluates a simple entry rule at a fixed number of
hours before the event end:

1. If any single outcome has implied probability > 50%, buy that outcome.
2. Otherwise, buy the top two outcomes if their combined probability > 50%.
3. Hold through settlement and score against the resolved winning bucket.

The implementation is event-level rather than order-book-level: it uses the
public last-price history as a proxy for the tradable probability snapshot.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


USER_AGENT = "Mozilla/5.0 (pm-hftbacktest weather_backtest)"
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
CACHE_DIR = Path(tempfile.gettempdir()) / "pm_weather_backtest"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class OutcomeSnapshot:
    label: str
    market_slug: str
    yes_token_id: str
    entry_price: Optional[float]
    history_points: int


@dataclass(frozen=True)
class EventBacktestResult:
    event_slug: str
    event_title: str
    date: str
    entry_time_utc: str
    winner_label: Optional[str]
    selection_mode: str
    selected_labels: list[str]
    selected_prices: list[float]
    selected_probability_sum: float
    pnl: float
    did_hit: bool
    outcomes: list[OutcomeSnapshot]


def _http_get_json(url: str, *, cache_key: Optional[str] = None) -> Any:
    cache_path = None
    if cache_key:
        digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
        cache_path = CACHE_DIR / f"{digest}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read().decode("utf-8")

    if cache_path is not None:
        cache_path.write_text(payload)
    return json.loads(payload)


def _build_event_slug(city_slug: str, target_date: dt.date) -> str:
    return (
        f"highest-temperature-in-{city_slug}-on-"
        f"{target_date.strftime('%B').lower()}-{target_date.day}-{target_date.year}"
    )


def _parse_json_field(raw: Any) -> Any:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _sort_key_for_label(label: str) -> float:
    match = re.search(r"(-?\d+)", label)
    if not match:
        return math.inf
    value = float(match.group(1))
    lowered = label.lower()
    if "or below" in lowered:
        return value - 0.5
    if "or higher" in lowered:
        return value + 0.5
    return value


def _fetch_event(event_slug: str) -> Optional[dict[str, Any]]:
    url = f"{GAMMA_BASE}/events?slug={urllib.parse.quote(event_slug)}"
    try:
        data = _http_get_json(url, cache_key=f"event:{event_slug}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not data:
        return None
    return data[0]


def _fetch_yes_price_history(token_id: str) -> list[tuple[int, float]]:
    params = urllib.parse.urlencode({"market": token_id, "interval": "max"})
    url = f"{CLOB_BASE}/prices-history?{params}"
    data = _http_get_json(url, cache_key=f"prices:{token_id}")
    history = data.get("history", [])
    return [(int(point["t"]), float(point["p"])) for point in history]


def _last_price_at_or_before(history: list[tuple[int, float]], ts: int) -> Optional[float]:
    if not history:
        return None
    timestamps = [point[0] for point in history]
    idx = bisect.bisect_right(timestamps, ts) - 1
    if idx < 0:
        return None
    return history[idx][1]


def _winner_label(markets: Iterable[dict[str, Any]]) -> Optional[str]:
    for market in markets:
        prices = _parse_json_field(market["outcomePrices"])
        if float(prices[0]) > 0.99:
            return str(market["groupItemTitle"])
    return None


def _event_outcomes_at_entry(event: dict[str, Any], entry_ts: int) -> list[OutcomeSnapshot]:
    outcomes: list[OutcomeSnapshot] = []
    markets = sorted(event["markets"], key=lambda market: _sort_key_for_label(market["groupItemTitle"]))
    for market in markets:
        token_ids = _parse_json_field(market["clobTokenIds"])
        yes_token_id = str(token_ids[0])
        history = _fetch_yes_price_history(yes_token_id)
        outcomes.append(
            OutcomeSnapshot(
                label=str(market["groupItemTitle"]),
                market_slug=str(market["slug"]),
                yes_token_id=yes_token_id,
                entry_price=_last_price_at_or_before(history, entry_ts),
                history_points=len(history),
            )
        )
    return outcomes


def select_positions(outcomes: list[OutcomeSnapshot], threshold: float = 0.5) -> tuple[str, list[OutcomeSnapshot]]:
    tradable = [outcome for outcome in outcomes if outcome.entry_price is not None]
    tradable.sort(key=lambda outcome: (-float(outcome.entry_price), _sort_key_for_label(outcome.label)))
    if not tradable:
        return "skip_no_prices", []

    top = tradable[0]
    if float(top.entry_price) > threshold:
        return "single_over_threshold", [top]

    if len(tradable) < 2:
        return "skip_not_enough_prices", []

    top_two = tradable[:2]
    if sum(float(outcome.entry_price) for outcome in top_two) > threshold:
        return "pair_over_threshold", top_two
    return "skip_pair_below_threshold", []


def describe_decision(
    outcomes: list[OutcomeSnapshot],
    selection_mode: str,
    selected: list[OutcomeSnapshot],
    threshold: float = 0.5,
) -> str:
    tradable = [outcome for outcome in outcomes if outcome.entry_price is not None]
    tradable.sort(key=lambda outcome: (-float(outcome.entry_price), _sort_key_for_label(outcome.label)))
    if not tradable:
        return "No tradable outcome had a price snapshot at the requested entry time."

    top = tradable[0]
    if selection_mode == "single_over_threshold" and selected:
        return (
            f"Bought only {selected[0].label} because its implied probability was "
            f"{float(selected[0].entry_price):.1%}, above the {threshold:.0%} threshold."
        )
    if selection_mode == "pair_over_threshold" and len(selected) == 2:
        return (
            f"No single outcome cleared {threshold:.0%}. Bought {selected[0].label} "
            f"({float(selected[0].entry_price):.1%}) and {selected[1].label} "
            f"({float(selected[1].entry_price):.1%}) because together they reached "
            f"{sum(float(outcome.entry_price) for outcome in selected):.1%}."
        )
    if selection_mode == "skip_pair_below_threshold":
        second = tradable[1] if len(tradable) > 1 else None
        if second is None:
            return (
                f"Skipped because only {top.label} had a usable price snapshot "
                f"({float(top.entry_price):.1%})."
            )
        return (
            f"Skipped because {top.label} ({float(top.entry_price):.1%}) and {second.label} "
            f"({float(second.entry_price):.1%}) only summed to "
            f"{float(top.entry_price) + float(second.entry_price):.1%}, below {threshold:.0%}."
        )
    if selection_mode == "skip_not_enough_prices":
        return "Skipped because fewer than two outcomes had usable price history at the entry time."
    return "Skipped because no outcome satisfied the strategy's entry rule."


def settle_pnl(selected: list[OutcomeSnapshot], winner_label: Optional[str]) -> float:
    if not selected:
        return 0.0
    payout = 1.0 if any(outcome.label == winner_label for outcome in selected) else 0.0
    cost = sum(float(outcome.entry_price) for outcome in selected if outcome.entry_price is not None)
    return payout - cost


def backtest_event(event: dict[str, Any], entry_hours_before_end: float, threshold: float) -> EventBacktestResult:
    end_dt = dt.datetime.fromisoformat(str(event["endDate"]).replace("Z", "+00:00"))
    entry_dt = end_dt - dt.timedelta(hours=entry_hours_before_end)
    entry_ts = int(entry_dt.timestamp())
    outcomes = _event_outcomes_at_entry(event, entry_ts)
    winner = _winner_label(event["markets"])
    selection_mode, selected = select_positions(outcomes, threshold=threshold)
    pnl = settle_pnl(selected, winner)
    return EventBacktestResult(
        event_slug=str(event["slug"]),
        event_title=str(event["title"]),
        date=end_dt.date().isoformat(),
        entry_time_utc=entry_dt.isoformat(),
        winner_label=winner,
        selection_mode=selection_mode,
        selected_labels=[outcome.label for outcome in selected],
        selected_prices=[float(outcome.entry_price) for outcome in selected if outcome.entry_price is not None],
        selected_probability_sum=sum(
            float(outcome.entry_price) for outcome in selected if outcome.entry_price is not None
        ),
        pnl=pnl,
        did_hit=bool(selected) and any(outcome.label == winner for outcome in selected),
        outcomes=outcomes,
    )


def _daterange(anchor_date: dt.date, days: int) -> list[dt.date]:
    start = anchor_date - dt.timedelta(days=days - 1)
    return [start + dt.timedelta(days=offset) for offset in range(days)]


def fetch_event(event_slug: str) -> Optional[dict[str, Any]]:
    return _fetch_event(event_slug)


def fetch_yes_price_history(token_id: str) -> list[tuple[int, float]]:
    return _fetch_yes_price_history(token_id)


def daterange(anchor_date: dt.date, days: int) -> list[dt.date]:
    return _daterange(anchor_date, days)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-slug", default="chengdu", help="Slug fragment used in the event URL.")
    parser.add_argument(
        "--anchor-date",
        default="2026-06-15",
        help="Inclusive final event date in YYYY-MM-DD format. Default: 2026-06-15.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="How many consecutive dates to backfill, inclusive of the anchor date.",
    )
    parser.add_argument(
        "--entry-hours",
        type=float,
        default=12.0,
        help="Enter this many hours before the event end timestamp.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Selection threshold for single outcome or top-two combined probability.",
    )
    parser.add_argument(
        "--csv",
        default="",
        help="Optional path to write a flat CSV summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full result payload as JSON instead of the text table.",
    )
    return parser.parse_args()


def _write_csv(path: str, results: list[EventBacktestResult]) -> None:
    fieldnames = [
        "date",
        "event_slug",
        "winner_label",
        "selection_mode",
        "selected_labels",
        "selected_prices",
        "selected_probability_sum",
        "pnl",
        "did_hit",
        "entry_time_utc",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "date": result.date,
                    "event_slug": result.event_slug,
                    "winner_label": result.winner_label,
                    "selection_mode": result.selection_mode,
                    "selected_labels": " | ".join(result.selected_labels),
                    "selected_prices": " | ".join(f"{price:.4f}" for price in result.selected_prices),
                    "selected_probability_sum": f"{result.selected_probability_sum:.4f}",
                    "pnl": f"{result.pnl:.4f}",
                    "did_hit": result.did_hit,
                    "entry_time_utc": result.entry_time_utc,
                }
            )


def _print_text_report(results: list[EventBacktestResult]) -> None:
    print(
        "date        winner            mode                   picks"
        "                                   prob_sum   pnl"
    )
    print("-" * 108)
    for result in results:
        picks = ", ".join(
            f"{label}@{price:.3f}" for label, price in zip(result.selected_labels, result.selected_prices)
        ) or "-"
        print(
            f"{result.date:<11}"
            f"{(result.winner_label or '-')[:17]:<18}"
            f"{result.selection_mode[:22]:<23}"
            f"{picks[:41]:<42}"
            f"{result.selected_probability_sum:>8.3f}"
            f"{result.pnl:>8.3f}"
        )

    traded = [result for result in results if result.selected_labels]
    total_pnl = sum(result.pnl for result in traded)
    hit_rate = (
        sum(1 for result in traded if result.did_hit) / len(traded)
        if traded
        else 0.0
    )
    print()
    print(
        f"summary: events={len(results)} traded={len(traded)} "
        f"hit_rate={hit_rate:.2%} total_pnl={total_pnl:.4f} "
        f"avg_pnl={(total_pnl / len(traded)) if traded else 0.0:.4f}"
    )


def main() -> None:
    args = _parse_args()
    anchor_date = dt.date.fromisoformat(args.anchor_date)
    results: list[EventBacktestResult] = []

    for target_date in _daterange(anchor_date, args.days):
        event_slug = _build_event_slug(args.city_slug, target_date)
        event = _fetch_event(event_slug)
        if event is None:
            continue
        results.append(
            backtest_event(
                event,
                entry_hours_before_end=float(args.entry_hours),
                threshold=float(args.threshold),
            )
        )

    if args.csv:
        _write_csv(args.csv, results)

    if args.json:
        payload = {
            "anchor_date": args.anchor_date,
            "days": args.days,
            "entry_hours": args.entry_hours,
            "threshold": args.threshold,
            "results": [asdict(result) for result in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text_report(results)


if __name__ == "__main__":
    main()
