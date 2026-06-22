"""Export a PMXT weather replay into the frontend WeatherDataset format."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from pmxt_weather_data import load_catalog
from weather_backtest import _sort_key_for_label


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "research" / "data" / "pmxt_weather"
DEFAULT_OUTPUT = ROOT / "frontend" / "public" / "data" / "weather" / "madrid-pmxt.json"
DEFAULT_MANIFEST = ROOT / "frontend" / "public" / "data" / "weather" / "manifest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="madrid")
    parser.add_argument("--city-label", default="Madrid")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--catalog", default=str(DATA_DIR / "weather_market_catalog.json"))
    parser.add_argument("--summary", default=str(DATA_DIR / "madrid_pmxt_weather_backtest_summary.json"))
    parser.add_argument("--snapshots", default=str(DATA_DIR / "madrid_pmxt_entry_snapshots.parquet"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    return parser.parse_args()


def _number(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _reason(row: dict[str, Any]) -> str:
    labels = row["selected_labels"]
    prices = row["selected_prices"]
    if not labels:
        return "PMXT ask replay found no qualifying entry."
    legs = " + ".join(f"{label} @ {price:.3f}" for label, price in zip(labels, prices))
    return f"PMXT ask replay bought {legs}; total executable ask cost {row['selected_probability_sum']:.3f}."


def _run_payload(row: dict[str, Any], event_snapshots: pd.DataFrame) -> dict[str, Any]:
    entry_hours = float(row["entry_hours"])
    candidates = event_snapshots[event_snapshots["entry_hours"] == entry_hours].copy()
    candidates["entry_price"] = candidates["snapshot_best_ask"].where(
        candidates["snapshot_best_ask"] > 0,
        candidates["snapshot_price"],
    )
    candidates = candidates[candidates["entry_price"].notna()].sort_values(
        ["entry_price", "bucket_label"],
        ascending=[False, True],
    )
    entry_time = dt.datetime.fromisoformat(row["entry_time_utc"])
    return {
        "entryHours": entry_hours,
        "entryTimeUtc": entry_time.isoformat(),
        "entryTimestamp": int(entry_time.timestamp() * 1000),
        "selectionMode": row["selection_mode"],
        "reason": _reason(row),
        "selectedLabels": row["selected_labels"],
        "selectedPrices": row["selected_prices"],
        "selectedProbabilitySum": row["selected_probability_sum"],
        "pnl": row["pnl"],
        "didHit": row["did_hit"],
        "topCandidates": [
            {"label": item.bucket_label, "price": float(item.entry_price)}
            for item in candidates.head(3).itertuples()
        ],
    }


def _outcome_payload(catalog_row: Any, outcome_snapshots: pd.DataFrame) -> dict[str, Any]:
    ordered = outcome_snapshots.sort_values("entry_hours", ascending=False).copy()
    ordered["point_price"] = ordered["snapshot_best_ask"].where(
        ordered["snapshot_best_ask"] > 0,
        ordered["snapshot_price"],
    )
    points = []
    for row in ordered.itertuples():
        if pd.isna(row.point_price):
            continue
        timestamp = pd.to_datetime(row.snapshot_timestamp_received, utc=True, errors="coerce")
        if pd.isna(timestamp):
            timestamp = pd.to_datetime(row.entry_time_utc, utc=True)
        points.append({"t": int(timestamp.timestamp() * 1000), "p": float(row.point_price)})

    latest = ordered.sort_values("entry_hours").iloc[0] if len(ordered) else None
    bid = _number(None if latest is None else latest["snapshot_best_bid"])
    ask = _number(None if latest is None else latest["snapshot_best_ask"])
    spread = None if bid is None or ask is None else max(0.0, (ask - bid) * 100)
    last_price = _number(None if latest is None else latest["snapshot_price"])
    return {
        "label": catalog_row.bucket_label,
        "marketSlug": catalog_row.market_slug,
        "yesTokenId": catalog_row.yes_token_id,
        "isWinner": catalog_row.is_winner,
        "marketStats": {
            "volume": None,
            "volume24hr": None,
            "liquidity": None,
            "spread": spread,
            "bestBid": bid,
            "bestAsk": ask,
            "lastTradePrice": last_price,
            "rewardsMinSize": None,
            "rewardsMaxSpread": None,
            "orderMinSize": None,
            "orderPriceMinTickSize": None,
        },
        "points": points,
    }


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    summary = json.loads(Path(args.summary).read_text())
    snapshots = pd.read_parquet(args.snapshots)
    snapshots = snapshots[snapshots["city_slug"] == args.city].copy()
    catalog = [row for row in load_catalog(Path(args.catalog)) if row.city_slug == args.city]
    catalog_by_event: dict[str, list[Any]] = {}
    for row in catalog:
        catalog_by_event.setdefault(row.event_slug, []).append(row)

    summary_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in summary["events"]:
        if row["city_slug"] == args.city:
            summary_by_event.setdefault(row["event_slug"], []).append(row)

    events = []
    for event_slug, runs in sorted(summary_by_event.items(), key=lambda item: item[1][0]["target_date"]):
        market_rows = catalog_by_event.get(event_slug, [])
        if not market_rows:
            continue
        event_snapshots = snapshots[snapshots["event_slug"] == event_slug]
        outcomes = [
            _outcome_payload(
                market_row,
                event_snapshots[event_snapshots["bucket_label"] == market_row.bucket_label],
            )
            for market_row in sorted(market_rows, key=lambda row: _sort_key_for_label(row.bucket_label))
        ]
        first = market_rows[0]
        events.append(
            {
                "date": first.target_date,
                "eventSlug": event_slug,
                "eventTitle": first.event_title,
                "endTimeUtc": first.end_time_utc,
                "winnerLabel": first.event_winner_label,
                "resolutionSource": "PMXT replay",
                "outcomes": outcomes,
                "runs": [
                    _run_payload(row, event_snapshots)
                    for row in sorted(runs, key=lambda row: float(row["entry_hours"]))
                ],
            }
        )

    entry_hours = sorted({float(row["entry_hours"]) for row in summary["events"] if row["city_slug"] == args.city})
    summaries = []
    for entry_hour in entry_hours:
        rows = [
            row
            for row in summary["events"]
            if row["city_slug"] == args.city and float(row["entry_hours"]) == entry_hour
        ]
        traded = [row for row in rows if row["selected_labels"]]
        summaries.append(
            {
                "entryHours": entry_hour,
                "tradedCount": len(traded),
                "hitRate": sum(bool(row["did_hit"]) for row in traded) / len(traded) if traded else 0.0,
                "totalPnl": sum(float(row["pnl"]) for row in traded),
                "avgPnl": sum(float(row["pnl"]) for row in traded) / len(traded) if traded else 0.0,
                "singleCount": sum(len(row["selected_labels"]) == 1 for row in traded),
                "pairCount": sum(len(row["selected_labels"]) == 2 for row in traded),
                "skipCount": sum(not row["selected_labels"] for row in rows),
                "avgProbabilitySum": sum(float(row["selected_probability_sum"]) for row in traded) / len(traded)
                if traded
                else 0.0,
            }
        )

    dates = [dt.date.fromisoformat(event["date"]) for event in events]
    best = max(summaries, key=lambda row: row["totalPnl"], default=None)
    return {
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "citySlug": args.city,
        "cityLabel": args.city_label,
        "anchorDate": max(dates).isoformat(),
        "days": (max(dates) - min(dates)).days + 1,
        "threshold": args.threshold,
        "entryHours": entry_hours,
        "bestEntryHour": None if best is None else best["entryHours"],
        "summaryByEntryHour": summaries,
        "events": events,
        "dataSource": "PMXT replay",
        "dataSourceDetail": "Execution-aware replay using the latest PMXT best ask at or before each entry timestamp.",
        "timezoneNote": "Entry timestamps are stored in UTC; the UI also renders New York time for verification.",
    }


def update_manifest(path: Path, dataset: dict[str, Any], output_path: Path) -> None:
    manifest = json.loads(path.read_text())
    best = next(
        row for row in dataset["summaryByEntryHour"] if row["entryHours"] == dataset["bestEntryHour"]
    )
    entry = {
        "citySlug": dataset["citySlug"],
        "cityLabel": dataset["cityLabel"],
        "path": f"/data/weather/{output_path.name}",
        "anchorDate": dataset["anchorDate"],
        "days": dataset["days"],
        "entryHours": dataset["entryHours"],
        "threshold": dataset["threshold"],
        "eventCount": len(dataset["events"]),
        "bestEntryHour": dataset["bestEntryHour"],
        "bestTotalPnl": best["totalPnl"],
    }
    manifest["generatedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["cities"] = sorted(
        [row for row in manifest["cities"] if row["citySlug"] != dataset["citySlug"]] + [entry],
        key=lambda row: row["cityLabel"],
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    args = _parse_args()
    dataset = build_dataset(args)
    output_path = Path(args.output)
    output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
    update_manifest(Path(args.manifest), dataset, output_path)
    print(f"output={output_path}")
    print(f"events={len(dataset['events'])} anchor={dataset['anchorDate']} best={dataset['bestEntryHour']}h")


if __name__ == "__main__":
    main()
