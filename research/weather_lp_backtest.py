"""Approximate LP backtest for reward-bearing weather markets.

This model is intentionally simplified and uses only public price history plus
current reward configuration. It is not a full order-book replay.

What it estimates:
* mark-to-market trading PnL of a symmetric passive quoting policy
* reward pool capacity over the sample window
* breakeven reward share required to offset trading losses
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from weather_backtest import fetch_yes_price_history
from weather_lp_scanner import RewardMarketRecord, scan_reward_weather_markets


SCALING_FACTOR = 3.0


@dataclass(frozen=True)
class LPSimResult:
    event_slug: str | None
    market_slug: str
    bucket: str | None
    viability: str
    total_daily_rate: float
    quote_width_cents: float
    order_size: float
    sample_start_utc: str
    sample_end_utc: str
    sample_days: float
    samples: int
    fills_bid: int
    fills_ask: int
    ending_inventory: float
    trading_pnl_markout: float
    raw_reward_pool: float
    avg_score_fraction: float
    score_adjusted_reward_pool: float
    breakeven_share_raw: float | None
    breakeven_share_score_adjusted: float | None
    pnl_with_10pct_share: float
    pnl_with_20pct_share: float
    pnl_with_50pct_share: float
    notes: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-daily-rate", type=float, default=1.0)
    parser.add_argument("--days-lookback", type=float, default=30.0)
    parser.add_argument("--quote-width-cents", type=float, default=1.5)
    parser.add_argument("--size-multiplier", type=float, default=1.0)
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


def _score_fraction(v_cents: float, s_cents: float) -> float:
    if v_cents <= 0 or s_cents >= v_cents:
        return 0.0
    return ((v_cents - s_cents) / v_cents) ** 2


def _simulate_market(
    market: RewardMarketRecord,
    *,
    days_lookback: float,
    quote_width_cents: float,
    size_multiplier: float,
) -> LPSimResult:
    if not market.yes_token_id:
        raise ValueError(f"No YES token id for {market.slug}")
    history = fetch_yes_price_history(market.yes_token_id)
    if not history:
        raise ValueError(f"No price history for {market.slug}")

    end_ts = history[-1][0]
    start_ts = max(history[0][0], int(end_ts - days_lookback * 24 * 60 * 60))
    sample = [(ts, px) for ts, px in history if ts >= start_ts]
    if len(sample) < 2:
        raise ValueError(f"Not enough price history for {market.slug}")

    order_size = float((market.rewards_min_size or 50.0) * size_multiplier)
    inventory_cap = order_size * 2.0
    max_spread = float(market.rewards_max_spread or 4.5)

    cash = 0.0
    inventory = 0.0
    fills_bid = 0
    fills_ask = 0
    score_total = 0.0

    for idx in range(len(sample) - 1):
        _, mid = sample[idx]
        _, next_mid = sample[idx + 1]
        bid = max(0.001, mid - quote_width_cents / 100.0)
        ask = min(0.999, mid + quote_width_cents / 100.0)

        if inventory < inventory_cap and next_mid <= bid:
            inventory += order_size
            cash -= bid * order_size
            fills_bid += 1
        elif inventory > -inventory_cap and next_mid >= ask:
            inventory -= order_size
            cash += ask * order_size
            fills_ask += 1

        score = _score_fraction(max_spread, quote_width_cents)
        if mid < 0.10 or mid > 0.90:
            # Extreme midpoint requires balanced liquidity to score under the
            # official formula. We downweight by the chance our inventory is
            # already skewed and cannot maintain both sides well.
            balance_penalty = max(0.0, 1.0 - abs(inventory) / max(inventory_cap, 1.0))
            score_total += score * balance_penalty
        else:
            # Central regime still rewards single-sided liquidity at reduced rate.
            single_sided_relief = max(1.0 / SCALING_FACTOR, 1.0 - abs(inventory) / max(inventory_cap, 1.0))
            score_total += score * single_sided_relief

    last_mid = sample[-1][1]
    trading_pnl = cash + inventory * last_mid
    sample_days = max((sample[-1][0] - sample[0][0]) / 86400.0, 1 / 1440.0)
    raw_reward_pool = market.total_daily_rate * sample_days
    avg_score_fraction = score_total / max(len(sample) - 1, 1)
    score_adjusted_pool = raw_reward_pool * avg_score_fraction

    def breakeven(pool: float) -> float | None:
        if trading_pnl >= 0:
            return 0.0
        if pool <= 0:
            return None
        return abs(trading_pnl) / pool

    return LPSimResult(
        event_slug=market.event_slug,
        market_slug=market.slug,
        bucket=market.group_item_title,
        viability=market.viability,
        total_daily_rate=market.total_daily_rate,
        quote_width_cents=quote_width_cents,
        order_size=order_size,
        sample_start_utc=dt.datetime.utcfromtimestamp(sample[0][0]).isoformat() + "Z",
        sample_end_utc=dt.datetime.utcfromtimestamp(sample[-1][0]).isoformat() + "Z",
        sample_days=sample_days,
        samples=len(sample),
        fills_bid=fills_bid,
        fills_ask=fills_ask,
        ending_inventory=inventory,
        trading_pnl_markout=trading_pnl,
        raw_reward_pool=raw_reward_pool,
        avg_score_fraction=avg_score_fraction,
        score_adjusted_reward_pool=score_adjusted_pool,
        breakeven_share_raw=breakeven(raw_reward_pool),
        breakeven_share_score_adjusted=breakeven(score_adjusted_pool),
        pnl_with_10pct_share=trading_pnl + raw_reward_pool * 0.10 * avg_score_fraction,
        pnl_with_20pct_share=trading_pnl + raw_reward_pool * 0.20 * avg_score_fraction,
        pnl_with_50pct_share=trading_pnl + raw_reward_pool * 0.50 * avg_score_fraction,
        notes=(
            "Approximate model: public last-price history used as midpoint proxy; "
            "current reward config assumed constant over the sample; normalized reward share "
            "against other makers is not observed."
        ),
    )


def _print(results: list[LPSimResult]) -> None:
    print(
        "event                                         bucket                rate/day  "
        "trade_pnl  raw_pool  score_pool  breakeven(raw)  breakeven(score)"
    )
    print("-" * 150)
    for row in results:
        def fmt(v: float | None) -> str:
            return "-" if v is None else f"{v:.2f}"
        print(
            f"{(row.event_slug or '-')[:44]:<44}"
            f"{(row.bucket or '-')[:20]:<22}"
            f"{row.total_daily_rate:>8.3f}  "
            f"{row.trading_pnl_markout:>9.2f}  "
            f"{row.raw_reward_pool:>8.2f}  "
            f"{row.score_adjusted_reward_pool:>10.2f}  "
            f"{fmt(row.breakeven_share_raw):>14}  "
            f"{fmt(row.breakeven_share_score_adjusted):>16}"
        )


def main() -> None:
    args = _parse_args()
    markets = [
        market
        for market in scan_reward_weather_markets(page_size=100, max_pages=60)
        if market.total_daily_rate >= args.min_daily_rate
    ]
    results = [
        _simulate_market(
            market,
            days_lookback=args.days_lookback,
            quote_width_cents=args.quote_width_cents,
            size_multiplier=args.size_multiplier,
        )
        for market in markets
    ]
    results.sort(key=lambda row: row.pnl_with_20pct_share, reverse=True)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps([asdict(row) for row in results], ensure_ascii=False, indent=2))

    _print(results)


if __name__ == "__main__":
    main()
