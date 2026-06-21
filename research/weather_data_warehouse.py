"""Local normalized warehouse for Polymarket weather history.

This module stores weather events, outcomes, and YES price history in a local
SQLite database so repeated research runs can reuse the same raw history rather
than rebuilding large frontend JSON blobs from scratch each time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from multi_city_weather_scan import DEFAULT_CITIES
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


def default_db_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "weather_warehouse" / "weather.sqlite3"


def default_metadata_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "weather_warehouse" / "sync_report.txt"


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cities (
            city_slug TEXT PRIMARY KEY,
            city_label TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            event_slug TEXT PRIMARY KEY,
            city_slug TEXT NOT NULL,
            event_title TEXT NOT NULL,
            target_date TEXT NOT NULL,
            end_time_utc TEXT NOT NULL,
            winner_label TEXT,
            resolution_source TEXT,
            fetched_at_utc TEXT NOT NULL,
            FOREIGN KEY (city_slug) REFERENCES cities(city_slug)
        );

        CREATE INDEX IF NOT EXISTS idx_events_city_date
        ON events(city_slug, target_date);

        CREATE TABLE IF NOT EXISTS outcomes (
            event_slug TEXT NOT NULL,
            outcome_label TEXT NOT NULL,
            market_slug TEXT NOT NULL,
            yes_token_id TEXT NOT NULL,
            sort_key REAL NOT NULL,
            is_winner INTEGER NOT NULL,
            volume REAL,
            volume24hr REAL,
            liquidity REAL,
            spread REAL,
            best_bid REAL,
            best_ask REAL,
            last_trade_price REAL,
            rewards_min_size REAL,
            rewards_max_spread REAL,
            order_min_size REAL,
            order_price_min_tick_size REAL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (event_slug, outcome_label),
            FOREIGN KEY (event_slug) REFERENCES events(event_slug) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_outcomes_token
        ON outcomes(yes_token_id);

        CREATE TABLE IF NOT EXISTS price_history (
            yes_token_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            price REAL NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (yes_token_id, ts)
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_token_ts
        ON price_history(yes_token_id, ts);
        """
    )
    conn.commit()


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
        "best_bid": _number_or_none(market.get("bestBid")),
        "best_ask": _number_or_none(market.get("bestAsk")),
        "last_trade_price": _number_or_none(market.get("lastTradePrice")),
        "rewards_min_size": _number_or_none(market.get("rewardsMinSize")),
        "rewards_max_spread": _number_or_none(market.get("rewardsMaxSpread")),
        "order_min_size": _number_or_none(market.get("orderMinSize")),
        "order_price_min_tick_size": _number_or_none(market.get("orderPriceMinTickSize")),
    }


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


def _parse_date_range(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    if args.start_date and args.end_date:
        start = dt.date.fromisoformat(args.start_date)
        end = dt.date.fromisoformat(args.end_date)
        if start > end:
            raise ValueError("start-date must be <= end-date")
        return start, end

    anchor = dt.date.fromisoformat(args.anchor_date)
    start = anchor - dt.timedelta(days=args.days - 1)
    return start, anchor


def _iter_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    days = (end - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(days)]


def sync_weather_warehouse(
    *,
    db_path: Path | str,
    cities: Iterable[tuple[str, str]],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, int]:
    conn = connect(db_path)
    fetched_events = 0
    missing_events = 0
    fetched_tokens = 0
    total_points = 0
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat()

    with conn:
        for city_slug, city_label in cities:
            conn.execute(
                """
                INSERT INTO cities(city_slug, city_label, updated_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(city_slug) DO UPDATE SET
                    city_label = excluded.city_label,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (city_slug, city_label, now_utc),
            )

            for target_date in _iter_dates(start_date, end_date):
                event_slug = _build_event_slug(city_slug, target_date)
                event = fetch_event(event_slug)
                if event is None:
                    missing_events += 1
                    continue

                fetched_events += 1
                end_dt = dt.datetime.fromisoformat(str(event["endDate"]).replace("Z", "+00:00"))
                markets = sorted(event["markets"], key=lambda market: _sort_key_for_label(market["groupItemTitle"]))
                winner_label = _winner_label(markets)
                resolution_source = markets[0].get("resolutionSource") if markets else None

                conn.execute(
                    """
                    INSERT INTO events(
                        event_slug, city_slug, event_title, target_date, end_time_utc,
                        winner_label, resolution_source, fetched_at_utc
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_slug) DO UPDATE SET
                        city_slug = excluded.city_slug,
                        event_title = excluded.event_title,
                        target_date = excluded.target_date,
                        end_time_utc = excluded.end_time_utc,
                        winner_label = excluded.winner_label,
                        resolution_source = excluded.resolution_source,
                        fetched_at_utc = excluded.fetched_at_utc
                    """,
                    (
                        event_slug,
                        city_slug,
                        str(event["title"]),
                        target_date.isoformat(),
                        end_dt.isoformat(),
                        winner_label,
                        resolution_source,
                        now_utc,
                    ),
                )

                for market in markets:
                    label = str(market["groupItemTitle"])
                    yes_token_id = str(_parse_json_field(market["clobTokenIds"])[0])
                    stats = _market_stats_payload(market)
                    conn.execute(
                        """
                        INSERT INTO outcomes(
                            event_slug, outcome_label, market_slug, yes_token_id, sort_key, is_winner,
                            volume, volume24hr, liquidity, spread, best_bid, best_ask, last_trade_price,
                            rewards_min_size, rewards_max_spread, order_min_size, order_price_min_tick_size, fetched_at_utc
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(event_slug, outcome_label) DO UPDATE SET
                            market_slug = excluded.market_slug,
                            yes_token_id = excluded.yes_token_id,
                            sort_key = excluded.sort_key,
                            is_winner = excluded.is_winner,
                            volume = excluded.volume,
                            volume24hr = excluded.volume24hr,
                            liquidity = excluded.liquidity,
                            spread = excluded.spread,
                            best_bid = excluded.best_bid,
                            best_ask = excluded.best_ask,
                            last_trade_price = excluded.last_trade_price,
                            rewards_min_size = excluded.rewards_min_size,
                            rewards_max_spread = excluded.rewards_max_spread,
                            order_min_size = excluded.order_min_size,
                            order_price_min_tick_size = excluded.order_price_min_tick_size,
                            fetched_at_utc = excluded.fetched_at_utc
                        """,
                        (
                            event_slug,
                            label,
                            str(market["slug"]),
                            yes_token_id,
                            _sort_key_for_label(label),
                            1 if label == winner_label else 0,
                            stats["volume"],
                            stats["volume24hr"],
                            stats["liquidity"],
                            stats["spread"],
                            stats["best_bid"],
                            stats["best_ask"],
                            stats["last_trade_price"],
                            stats["rewards_min_size"],
                            stats["rewards_max_spread"],
                            stats["order_min_size"],
                            stats["order_price_min_tick_size"],
                            now_utc,
                        ),
                    )

                    history = fetch_yes_price_history(yes_token_id)
                    fetched_tokens += 1
                    total_points += len(history)
                    conn.execute("DELETE FROM price_history WHERE yes_token_id = ?", (yes_token_id,))
                    conn.executemany(
                        """
                        INSERT INTO price_history(yes_token_id, ts, price, fetched_at_utc)
                        VALUES (?, ?, ?, ?)
                        """,
                        [(yes_token_id, ts, price, now_utc) for ts, price in history],
                    )

    conn.close()
    return {
        "fetched_events": fetched_events,
        "missing_events": missing_events,
        "fetched_tokens": fetched_tokens,
        "total_points": total_points,
    }


def _last_price_at_or_before(history: list[tuple[int, float]], entry_ts: int) -> float | None:
    if not history:
        return None
    lo = 0
    hi = len(history) - 1
    answer = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if history[mid][0] <= entry_ts:
            answer = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return history[answer][1] if answer >= 0 else None


def build_weather_dataset_from_warehouse(
    *,
    db_path: Path | str,
    city_slug: str,
    city_label: str,
    anchor_date_iso: str,
    days: int,
    entry_hours: list[float],
    threshold: float,
) -> dict[str, Any]:
    conn = connect(db_path)
    anchor = dt.date.fromisoformat(anchor_date_iso)
    target_dates = {day.isoformat() for day in daterange(anchor, days)}
    event_rows = conn.execute(
        """
        SELECT event_slug, event_title, target_date, end_time_utc, winner_label, resolution_source
        FROM events
        WHERE city_slug = ?
          AND target_date >= ?
          AND target_date <= ?
        ORDER BY target_date
        """,
        (city_slug, min(target_dates), max(target_dates)),
    ).fetchall()

    summary_acc: dict[float, dict[str, float]] = {
        hour: {
            "tradedCount": 0.0,
            "hitCount": 0.0,
            "totalPnl": 0.0,
            "singleCount": 0.0,
            "pairCount": 0.0,
            "skipCount": 0.0,
            "probabilitySumTotal": 0.0,
        }
        for hour in entry_hours
    }
    events_payload: list[dict[str, Any]] = []

    for event_row in event_rows:
        if event_row["target_date"] not in target_dates:
            continue
        outcome_rows = conn.execute(
            """
            SELECT outcome_label, market_slug, yes_token_id, sort_key, is_winner,
                   volume, volume24hr, liquidity, spread, best_bid, best_ask, last_trade_price,
                   rewards_min_size, rewards_max_spread, order_min_size, order_price_min_tick_size
            FROM outcomes
            WHERE event_slug = ?
            ORDER BY sort_key
            """,
            (event_row["event_slug"],),
        ).fetchall()
        outcomes_payload: list[dict[str, Any]] = []
        history_map: dict[str, list[tuple[int, float]]] = {}
        for outcome_row in outcome_rows:
            history = conn.execute(
                """
                SELECT ts, price
                FROM price_history
                WHERE yes_token_id = ?
                ORDER BY ts
                """,
                (outcome_row["yes_token_id"],),
            ).fetchall()
            points = [(int(row["ts"]), float(row["price"])) for row in history]
            history_map[str(outcome_row["outcome_label"])] = points
            outcomes_payload.append(
                {
                    "label": str(outcome_row["outcome_label"]),
                    "marketSlug": str(outcome_row["market_slug"]),
                    "yesTokenId": str(outcome_row["yes_token_id"]),
                    "isWinner": bool(outcome_row["is_winner"]),
                    "marketStats": {
                        "volume": outcome_row["volume"],
                        "volume24hr": outcome_row["volume24hr"],
                        "liquidity": outcome_row["liquidity"],
                        "spread": outcome_row["spread"],
                        "bestBid": outcome_row["best_bid"],
                        "bestAsk": outcome_row["best_ask"],
                        "lastTradePrice": outcome_row["last_trade_price"],
                        "rewardsMinSize": outcome_row["rewards_min_size"],
                        "rewardsMaxSpread": outcome_row["rewards_max_spread"],
                        "orderMinSize": outcome_row["order_min_size"],
                        "orderPriceMinTickSize": outcome_row["order_price_min_tick_size"],
                    },
                    "points": [{"t": ts * 1000, "p": price} for ts, price in points],
                }
            )

        end_dt = dt.datetime.fromisoformat(str(event_row["end_time_utc"]))
        runs_payload: list[dict[str, Any]] = []
        for hours in entry_hours:
            entry_dt = end_dt - dt.timedelta(hours=hours)
            entry_ts = int(entry_dt.timestamp())
            snapshots = [
                OutcomeSnapshot(
                    label=outcome["label"],
                    market_slug=outcome["marketSlug"],
                    yes_token_id=outcome["yesTokenId"],
                    entry_price=_last_price_at_or_before(history_map[outcome["label"]], entry_ts),
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
                (1.0 if any(snapshot.label == event_row["winner_label"] for snapshot in selected) else 0.0)
                - sum(float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None)
            )
            did_hit = bool(selected) and any(snapshot.label == event_row["winner_label"] for snapshot in selected)

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
                    "selectedPrices": [float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None],
                    "selectedProbabilitySum": sum(
                        float(snapshot.entry_price) for snapshot in selected if snapshot.entry_price is not None
                    ),
                    "pnl": pnl,
                    "didHit": did_hit,
                    "topCandidates": [{"label": snapshot.label, "price": float(snapshot.entry_price)} for snapshot in ranked[:3]],
                }
            )

        events_payload.append(
            {
                "date": str(event_row["target_date"]),
                "eventSlug": str(event_row["event_slug"]),
                "eventTitle": str(event_row["event_title"]),
                "endTimeUtc": end_dt.isoformat(),
                "winnerLabel": event_row["winner_label"],
                "resolutionSource": event_row["resolution_source"],
                "outcomes": outcomes_payload,
                "runs": sorted(runs_payload, key=lambda run: float(run["entryHours"])),
            }
        )

    conn.close()

    summary_payload: list[dict[str, Any]] = []
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="Fetch weather event/outcome/history data into the local warehouse.")
    sync_parser.add_argument("--db", default=str(default_db_path()))
    sync_parser.add_argument("--cities", default="")
    sync_parser.add_argument("--anchor-date", default="2026-06-19")
    sync_parser.add_argument("--days", type=int, default=96)
    sync_parser.add_argument("--start-date", default="")
    sync_parser.add_argument("--end-date", default="")

    stats_parser = sub.add_parser("stats", help="Print row counts for the local warehouse.")
    stats_parser.add_argument("--db", default=str(default_db_path()))
    return parser.parse_args()


def _command_sync(args: argparse.Namespace) -> None:
    start_date, end_date = _parse_date_range(args)
    cities = _parse_cities(args.cities)
    summary = sync_weather_warehouse(
        db_path=args.db,
        cities=cities,
        start_date=start_date,
        end_date=end_date,
    )
    report = (
        f"db={args.db}\n"
        f"range={start_date.isoformat()}..{end_date.isoformat()}\n"
        f"cities={len(cities)}\n"
        f"fetched_events={summary['fetched_events']}\n"
        f"missing_events={summary['missing_events']}\n"
        f"fetched_tokens={summary['fetched_tokens']}\n"
        f"total_points={summary['total_points']}\n"
    )
    metadata_path = default_metadata_path()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(report)
    print(report, end="")
    print(f"report={metadata_path}")


def _command_stats(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    for table in ("cities", "events", "outcomes", "price_history"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:>13}: {count}")
    by_city = conn.execute(
        """
        SELECT city_slug, COUNT(*) AS event_count, MIN(target_date) AS first_date, MAX(target_date) AS last_date
        FROM events
        GROUP BY city_slug
        ORDER BY city_slug
        """
    ).fetchall()
    if by_city:
        print("\nper-city:")
        for row in by_city:
            print(
                f"  {row['city_slug']:<12} events={row['event_count']:<4} "
                f"range={row['first_date']}..{row['last_date']}"
            )
    conn.close()


def main() -> None:
    args = _parse_args()
    if args.command == "sync":
        _command_sync(args)
    elif args.command == "stats":
        _command_stats(args)
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
