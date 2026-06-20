"""Build a static JSON dataset for the weather backtest frontend."""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from weather_backtest import (
    OutcomeSnapshot,
    _build_event_slug,
    _parse_json_field,
    _sort_key_for_label,
    _winner_label,
    daterange,
    describe_decision,
    fetch_event,
    fetch_yes_price_history,
    select_positions,
)


DEFAULT_ENTRY_HOURS = [6, 12, 18, 24, 36]


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


def _entry_price_from_history(history: list[tuple[int, float]], entry_ts: int) -> float | None:
    if not history:
        return None
    timestamps = [point[0] for point in history]
    idx = bisect.bisect_right(timestamps, entry_ts) - 1
    if idx < 0:
        return None
    return float(history[idx][1])


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _market_stats_payload(market: dict[str, Any]) -> dict[str, float | None]:
    return {
        "volume": _number_or_none(market.get("volume")),
        "volume24hr": _number_or_none(market.get("volume24hr")),
        "liquidity": _number_or_none(market.get("liquidity")),
        "spread": _number_or_none(market.get("spread")),
        "bestBid": _number_or_none(market.get("bestBid")),
        "bestAsk": _number_or_none(market.get("bestAsk")),
        "lastTradePrice": _number_or_none(market.get("lastTradePrice")),
        "rewardsMinSize": _number_or_none(market.get("rewardsMinSize")),
        "rewardsMaxSpread": _number_or_none(market.get("rewardsMaxSpread")),
        "orderMinSize": _number_or_none(market.get("orderMinSize")),
        "orderPriceMinTickSize": _number_or_none(market.get("orderPriceMinTickSize")),
    }


def _event_target_date(event: dict[str, Any], end_dt: dt.datetime) -> str:
    slug = str(event.get("slug") or "")
    match = re.search(r"-on-([a-z]+)-(\d{1,2})-(\d{4})$", slug)
    if not match:
        return end_dt.date().isoformat()
    month_name, day_text, year_text = match.groups()
    parsed = dt.datetime.strptime(f"{month_name} {day_text} {year_text}", "%B %d %Y")
    return parsed.date().isoformat()


def _output_default_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "frontend" / "public" / "data" / "chengdu-weather-backtest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-slug", default="chengdu")
    parser.add_argument("--city-label", default="Chengdu")
    parser.add_argument("--anchor-date", default="2026-06-19")
    parser.add_argument("--days", type=int, default=17)
    parser.add_argument("--entry-hours", default="6,12,18,24,36")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output", default=str(_output_default_path()))
    return parser.parse_args()


def build_weather_dataset(
    *,
    city_slug: str,
    city_label: str,
    anchor_date_iso: str,
    days: int,
    entry_hours: list[float],
    threshold: float,
) -> dict[str, Any]:
    anchor_date = dt.date.fromisoformat(anchor_date_iso)

    summary_acc: dict[float, dict[str, float]] = defaultdict(
        lambda: {
            "tradedCount": 0.0,
            "hitCount": 0.0,
            "totalPnl": 0.0,
            "singleCount": 0.0,
            "pairCount": 0.0,
            "skipCount": 0.0,
            "probabilitySumTotal": 0.0,
        }
    )

    events_payload: list[dict[str, Any]] = []

    for target_date in daterange(anchor_date, days):
        event_slug = _build_event_slug(city_slug, target_date)
        event = fetch_event(event_slug)
        if event is None:
            continue

        end_dt = dt.datetime.fromisoformat(str(event["endDate"]).replace("Z", "+00:00"))
        markets = sorted(event["markets"], key=lambda market: _sort_key_for_label(market["groupItemTitle"]))
        winner_label = _winner_label(markets)

        history_map: dict[str, list[tuple[int, float]]] = {}
        outcomes_payload: list[dict[str, Any]] = []
        for market in markets:
            label = str(market["groupItemTitle"])
            yes_token_id = str(_parse_json_field(market["clobTokenIds"])[0])
            history = fetch_yes_price_history(yes_token_id)
            history_map[label] = history
            outcomes_payload.append(
                {
                    "label": label,
                    "marketSlug": str(market["slug"]),
                    "yesTokenId": yes_token_id,
                    "isWinner": label == winner_label,
                    "marketStats": _market_stats_payload(market),
                    "points": [{"t": ts * 1000, "p": price} for ts, price in history],
                }
            )

        runs_payload: list[dict[str, Any]] = []
        for hours in entry_hours:
            entry_dt = end_dt - dt.timedelta(hours=hours)
            entry_ts = int(entry_dt.timestamp())
            snapshots = [
                OutcomeSnapshot(
                    label=outcome["label"],
                    market_slug=outcome["marketSlug"],
                    yes_token_id=outcome["yesTokenId"],
                    entry_price=_entry_price_from_history(history_map[outcome["label"]], entry_ts),
                    history_points=len(history_map[outcome["label"]]),
                )
                for outcome in outcomes_payload
            ]
            selection_mode, selected = select_positions(snapshots, threshold)
            reason = describe_decision(snapshots, selection_mode, selected, threshold)
            ranked = sorted(
                [snapshot for snapshot in snapshots if snapshot.entry_price is not None],
                key=lambda snapshot: (-float(snapshot.entry_price), _sort_key_for_label(snapshot.label)),
            )
            pnl = (
                (1.0 if any(snapshot.label == winner_label for snapshot in selected) else 0.0)
                - sum(float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None)
            )
            did_hit = bool(selected) and any(snapshot.label == winner_label for snapshot in selected)

            acc = summary_acc[hours]
            if selected:
                acc["tradedCount"] += 1
                acc["hitCount"] += 1 if did_hit else 0
                acc["totalPnl"] += pnl
                acc["probabilitySumTotal"] += sum(
                    float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None
                )
                if selection_mode == "single_over_threshold":
                    acc["singleCount"] += 1
                elif selection_mode == "pair_over_threshold":
                    acc["pairCount"] += 1
            else:
                acc["skipCount"] += 1

            runs_payload.append(
                {
                    "entryHours": hours,
                    "entryTimeUtc": entry_dt.isoformat(),
                    "entryTimestamp": entry_ts * 1000,
                    "selectionMode": selection_mode,
                    "reason": reason,
                    "selectedLabels": [snapshot.label for snapshot in selected],
                    "selectedPrices": [
                        float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None
                    ],
                    "selectedProbabilitySum": sum(
                        float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None
                    ),
                    "pnl": pnl,
                    "didHit": did_hit,
                    "topCandidates": [
                        {"label": snapshot.label, "price": float(snapshot.entry_price)}
                        for snapshot in ranked[:3]
                    ],
                }
            )

        events_payload.append(
            {
                "date": _event_target_date(event, end_dt),
                "eventSlug": str(event["slug"]),
                "eventTitle": str(event["title"]),
                "endTimeUtc": end_dt.isoformat(),
                "winnerLabel": winner_label,
                "resolutionSource": markets[0].get("resolutionSource"),
                "outcomes": outcomes_payload,
                "runs": sorted(runs_payload, key=lambda run: float(run["entryHours"])),
            }
        )

    summary_payload = []
    for hours in sorted(summary_acc):
        acc = summary_acc[hours]
        traded = int(acc["tradedCount"])
        summary_payload.append(
            {
                "entryHours": hours,
                "tradedCount": traded,
                "hitRate": (acc["hitCount"] / traded) if traded else 0.0,
                "totalPnl": acc["totalPnl"],
                "avgPnl": (acc["totalPnl"] / traded) if traded else 0.0,
                "singleCount": int(acc["singleCount"]),
                "pairCount": int(acc["pairCount"]),
                "skipCount": int(acc["skipCount"]),
                "avgProbabilitySum": (acc["probabilitySumTotal"] / traded) if traded else 0.0,
            }
        )

    best_entry = max(summary_payload, key=lambda item: item["totalPnl"], default=None)
    return {
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "citySlug": city_slug,
        "cityLabel": city_label,
        "anchorDate": anchor_date_iso,
        "days": days,
        "threshold": threshold,
        "entryHours": entry_hours,
        "bestEntryHour": None if best_entry is None else best_entry["entryHours"],
        "summaryByEntryHour": summary_payload,
        "events": events_payload,
    }


def main() -> None:
    args = _parse_args()
    entry_hours = _parse_entry_hours(args.entry_hours)
    threshold = float(args.threshold)
    payload = build_weather_dataset(
        city_slug=args.city_slug,
        city_label=args.city_label,
        anchor_date_iso=args.anchor_date,
        days=args.days,
        entry_hours=entry_hours,
        threshold=threshold,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"Wrote {output_path}")
    for item in payload["summaryByEntryHour"]:
        print(
            f"entry={item['entryHours']:>4g}h traded={item['tradedCount']:>2} "
            f"hit_rate={item['hitRate']:.2%} total_pnl={item['totalPnl']:.4f} "
            f"avg_pnl={item['avgPnl']:.4f}"
        )


if __name__ == "__main__":
    main()
