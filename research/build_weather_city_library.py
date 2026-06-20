"""Build a local multi-city weather dataset library for the frontend."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from build_weather_dashboard_data import build_weather_dataset
from multi_city_weather_scan import DEFAULT_CITIES


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


def _parse_cities(raw: str) -> list[tuple[str, str]]:
    if not raw.strip():
        return list(DEFAULT_CITIES)
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if not slug:
            continue
        label = " ".join(token.capitalize() for token in slug.split("-"))
        out.append((slug, label))
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-date", default="2026-06-19")
    parser.add_argument("--days", type=int, default=17)
    parser.add_argument("--entry-hours", default="6,12,18,24,36")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--cities", default="")
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir) if args.output_dir else root / "frontend" / "public" / "data" / "weather"
    output_dir.mkdir(parents=True, exist_ok=True)

    entry_hours = _parse_entry_hours(args.entry_hours)
    cities = _parse_cities(args.cities)

    manifest_rows: list[dict[str, object]] = []
    for city_slug, city_label in cities:
        payload = build_weather_dataset(
            city_slug=city_slug,
            city_label=city_label,
            anchor_date_iso=args.anchor_date,
            days=args.days,
            entry_hours=entry_hours,
            threshold=float(args.threshold),
        )
        output_path = output_dir / f"{city_slug}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        best_total_pnl = 0.0
        if payload["bestEntryHour"] is not None:
            for row in payload["summaryByEntryHour"]:
                if row["entryHours"] == payload["bestEntryHour"]:
                    best_total_pnl = float(row["totalPnl"])
                    break

        manifest_rows.append(
            {
                "citySlug": city_slug,
                "cityLabel": city_label,
                "path": f"/data/weather/{city_slug}.json",
                "anchorDate": payload["anchorDate"],
                "days": payload["days"],
                "entryHours": payload["entryHours"],
                "threshold": payload["threshold"],
                "eventCount": len(payload["events"]),
                "bestEntryHour": payload["bestEntryHour"],
                "bestTotalPnl": best_total_pnl,
            }
        )
        print(f"Wrote {output_path}")

    manifest = {
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cities": sorted(manifest_rows, key=lambda row: str(row["cityLabel"])),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
