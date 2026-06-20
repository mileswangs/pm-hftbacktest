"""Scan Polymarket for reward-active weather markets and assess LP viability.

This scanner joins the public rewards endpoints with Gamma market metadata,
filters for weather-style markets, and emits a compact feasibility report.

It is intentionally conservative:
* "feasible now" means reward-active + tradable + quoteable within current
  visible spread constraints.
* "feasible in principle" means the reward program and public APIs support the
  strategy shape, even if no current weather rewards are active.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
import urllib.error
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from weather_backtest import CLOB_BASE, GAMMA_BASE, _http_get_json


CACHE_DIR = Path(tempfile.gettempdir()) / "pm_weather_lp_scanner"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

WEATHER_KEYWORDS = (
    "temperature",
    "weather",
    "snow",
    "rain",
    "wind",
    "hurricane",
    "storm",
    "climate",
)


@dataclass(frozen=True)
class RewardMarketRecord:
    condition_id: str
    slug: str
    question: str
    event_slug: str | None
    event_title: str | None
    group_item_title: str | None
    rewards_min_size: float | None
    rewards_max_spread: float | None
    total_daily_rate: float
    native_daily_rate: float
    sponsored_daily_rate: float
    sponsors_count: int
    best_bid: float | None
    best_ask: float | None
    midpoint: float | None
    visible_spread_cents: float | None
    liquidity_clob: float | None
    volume_clob: float | None
    fee_type: str | None
    active: bool
    closed: bool
    classification: str
    viability: str
    viability_reason: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write the full scanner payload as JSON.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=60,
        help="Maximum number of Gamma pages to scan while joining reward configs to markets.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Gamma page size while joining reward configs to markets.",
    )
    return parser.parse_args()


def _reward_current_url(*, sponsored: bool, next_cursor: str | None = None) -> str:
    params: dict[str, str] = {}
    if sponsored:
        params["sponsored"] = "true"
    if next_cursor:
        params["next_cursor"] = next_cursor
    query = urllib.parse.urlencode(params)
    return f"{CLOB_BASE}/rewards/markets/current" + (f"?{query}" if query else "")


def _fetch_current_rewards(*, sponsored: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    next_cursor: str | None = None
    while True:
        url = _reward_current_url(sponsored=sponsored, next_cursor=next_cursor)
        data = _http_get_json(url, cache_key=f"reward-current:{sponsored}:{next_cursor or 'first'}")
        batch = data.get("data", [])
        out.extend(batch)
        next_cursor = data.get("next_cursor")
        if not next_cursor or next_cursor == "LTE=":
            break
    return out


def _fetch_markets_map(condition_ids: Iterable[str], *, page_size: int, max_pages: int) -> dict[str, dict[str, Any]]:
    remaining = set(condition_ids)
    found: dict[str, dict[str, Any]] = {}
    page_size = max(1, min(page_size, 100))

    for page in range(max_pages):
        offset = page * page_size
        url = f"{GAMMA_BASE}/markets?limit={page_size}&offset={offset}"
        try:
            markets = _http_get_json(url, cache_key=f"gamma-markets:{page_size}:{offset}")
        except urllib.error.HTTPError as exc:
            if exc.code == 422:
                break
            raise
        if not markets:
            break
        for market in markets:
            cid = market.get("conditionId")
            if cid in remaining:
                found[cid] = market
                remaining.remove(cid)
        if not remaining:
            break

    return found


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reward_total_rate(row: dict[str, Any]) -> float:
    direct = _parse_float(row.get("total_daily_rate"))
    if direct is not None:
        return direct
    native = _parse_float(row.get("native_daily_rate")) or 0.0
    sponsored = _parse_float(row.get("sponsored_daily_rate")) or 0.0
    return native + sponsored


def _classification(market: dict[str, Any]) -> str:
    fee_type = str(market.get("feeType") or "")
    if fee_type == "weather_fees":
        return "weather"

    haystack = " ".join(
        str(value or "")
        for value in (
            market.get("slug"),
            market.get("question"),
            market.get("groupItemTitle"),
            ((market.get("events") or [{}])[0]).get("slug"),
            ((market.get("events") or [{}])[0]).get("title"),
        )
    ).lower()
    for keyword in WEATHER_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", haystack):
            return "weather"
    return "non_weather"


def _midpoint(best_bid: float | None, best_ask: float | None, last_trade: float | None) -> float | None:
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
        return (best_bid + best_ask) / 2.0
    return last_trade


def _visible_spread_cents(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    return (best_ask - best_bid) * 100.0


def _viability(row: dict[str, Any], market: dict[str, Any]) -> tuple[str, str]:
    total_daily_rate = _reward_total_rate(row)
    best_bid = _parse_float(market.get("bestBid"))
    best_ask = _parse_float(market.get("bestAsk"))
    last_trade = _parse_float(market.get("lastTradePrice"))
    midpoint = _midpoint(best_bid, best_ask, last_trade)
    spread_cents = _visible_spread_cents(best_bid, best_ask)
    max_spread = _parse_float(row.get("rewards_max_spread"))

    if not bool(market.get("active")) or bool(market.get("closed")):
        return "inactive", "Reward config exists but the market is not actively tradable."
    if total_daily_rate <= 0:
        return "inactive", "Reward config has zero visible daily rate."
    if midpoint is None:
        return "unknown", "Reward is active, but there is no visible bid/ask or last trade to assess the book."

    extreme = midpoint < 0.10 or midpoint > 0.90
    if spread_cents is None:
        if extreme:
            return "watch_only", "Book is extreme and thin; two-sided quoting would be required once visible liquidity appears."
        return "possible", "Reward is active but the visible book is too sparse to judge execution risk."

    if max_spread is not None and spread_cents > max_spread:
        return "needs_improvement", (
            f"Visible spread is {spread_cents:.2f}c, wider than the current reward cutoff "
            f"of {max_spread:.2f}c. You would need to quote inside the displayed spread to score well."
        )

    if extreme:
        return "inventory_sensitive", (
            f"Reward is active and the visible spread ({spread_cents:.2f}c) is within cutoff, "
            "but midpoint is in an extreme bucket where the official rules require effectively "
            "double-sided liquidity."
        )

    return "good_candidate", (
        f"Reward is active, visible spread ({spread_cents:.2f}c) is inside the reward cutoff, "
        "and midpoint is still in the central zone where one-sided quotes can still score, "
        "though balanced quoting remains better."
    )


def scan_reward_weather_markets(*, page_size: int, max_pages: int) -> list[RewardMarketRecord]:
    standard = _fetch_current_rewards(sponsored=False)
    sponsored = _fetch_current_rewards(sponsored=True)

    merged: dict[str, dict[str, Any]] = {}
    for row in standard + sponsored:
        cid = row["condition_id"]
        existing = merged.get(cid)
        if existing is None:
            merged[cid] = dict(row)
            continue
        for key in ("native_daily_rate", "sponsored_daily_rate", "total_daily_rate"):
            a = _parse_float(existing.get(key)) or 0.0
            b = _parse_float(row.get(key)) or 0.0
            existing[key] = a + b
        existing["sponsors_count"] = int(existing.get("sponsors_count", 0)) + int(row.get("sponsors_count", 0) or 0)
        if not existing.get("rewards_config") and row.get("rewards_config"):
            existing["rewards_config"] = row["rewards_config"]

    markets_map = _fetch_markets_map(merged.keys(), page_size=page_size, max_pages=max_pages)

    out: list[RewardMarketRecord] = []
    for cid, row in merged.items():
        market = markets_map.get(cid)
        if market is None:
            continue
        if _classification(market) != "weather":
            continue
        if _reward_total_rate(row) <= 0:
            continue

        best_bid = _parse_float(market.get("bestBid"))
        best_ask = _parse_float(market.get("bestAsk"))
        midpoint = _midpoint(best_bid, best_ask, _parse_float(market.get("lastTradePrice")))
        spread_cents = _visible_spread_cents(best_bid, best_ask)
        viability, reason = _viability(row, market)
        event = (market.get("events") or [{}])[0]

        out.append(
            RewardMarketRecord(
                condition_id=cid,
                slug=str(market.get("slug") or ""),
                question=str(market.get("question") or ""),
                event_slug=event.get("slug"),
                event_title=event.get("title"),
                group_item_title=market.get("groupItemTitle"),
                rewards_min_size=_parse_float(row.get("rewards_min_size") or market.get("rewardsMinSize")),
                rewards_max_spread=_parse_float(row.get("rewards_max_spread") or market.get("rewardsMaxSpread")),
                total_daily_rate=_reward_total_rate(row),
                native_daily_rate=_parse_float(row.get("native_daily_rate")) or 0.0,
                sponsored_daily_rate=_parse_float(row.get("sponsored_daily_rate")) or 0.0,
                sponsors_count=int(row.get("sponsors_count") or 0),
                best_bid=best_bid,
                best_ask=best_ask,
                midpoint=midpoint,
                visible_spread_cents=spread_cents,
                liquidity_clob=_parse_float(market.get("liquidityClob")),
                volume_clob=_parse_float(market.get("volumeClob")),
                fee_type=market.get("feeType"),
                active=bool(market.get("active")),
                closed=bool(market.get("closed")),
                classification="weather",
                viability=viability,
                viability_reason=reason,
            )
        )

    out.sort(key=lambda row: (-row.total_daily_rate, row.event_slug or "", row.group_item_title or ""))
    return out


def _print_report(records: list[RewardMarketRecord]) -> None:
    print(f"reward-active weather markets found: {len(records)}")
    if not records:
        print("No current reward-active weather markets were found.")
        return

    print(
        "daily_rate  viability            spread(c)  midpoint  event"
        "                                            bucket"
    )
    print("-" * 132)
    for row in records:
        spread = "-" if row.visible_spread_cents is None else f"{row.visible_spread_cents:.2f}"
        midpoint = "-" if row.midpoint is None else f"{row.midpoint:.3f}"
        rate = f"{row.total_daily_rate:.3f}" if row.total_daily_rate < 0.01 else f"{row.total_daily_rate:.2f}"
        print(
            f"{rate:>9}  "
            f"{row.viability:<19}"
            f"{spread:>9}  "
            f"{midpoint:>8}  "
            f"{(row.event_slug or '-')[:46]:<46}"
            f"{(row.group_item_title or '-')[:22]}"
        )


def main() -> None:
    args = _parse_args()
    records = scan_reward_weather_markets(page_size=args.page_size, max_pages=args.max_pages)

    payload = {
        "weather_reward_markets_found": len(records),
        "records": [asdict(record) for record in records],
        "summary": {
            "good_candidate": sum(record.viability == "good_candidate" for record in records),
            "inventory_sensitive": sum(record.viability == "inventory_sensitive" for record in records),
            "needs_improvement": sum(record.viability == "needs_improvement" for record in records),
            "possible": sum(record.viability == "possible" for record in records),
            "watch_only": sum(record.viability == "watch_only" for record in records),
            "inactive": sum(record.viability == "inactive" for record in records),
            "unknown": sum(record.viability == "unknown" for record in records),
        },
    }

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    _print_report(records)


if __name__ == "__main__":
    main()
