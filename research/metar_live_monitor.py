"""Read-only live signal monitor: METAR hard-elimination vs current Polymarket prices.

Prints, for a given live "Highest temperature in {city}" event, which buckets are
mathematically dead per the day's METAR observations so far, and whether the
market's current NO price still leaves room (i.e. hasn't fully converged).

This places no orders. It is a signal printer, not an execution path.

Usage:
    python3 research/metar_live_monitor.py --event-slug highest-temperature-in-madrid-on-june-23-2026 --station LEMD
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from metar_data import fetch_live
from metar_nowcast import MetarObs, dead_buckets, parse_bucket, running_max_series, staleness_gaps

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
USER_AGENT = "pm-hftbacktest-research/1.0 (METAR nowcasting research)"


def fetch_event(event_slug: str) -> dict:
    params = urllib.parse.urlencode({"slug": event_slug})
    req = urllib.request.Request(f"{GAMMA_EVENTS_URL}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    if not data:
        raise SystemExit(f"event not found: {event_slug}")
    return data[0]


def target_date_from_slug(event_slug: str, event: dict) -> dt.date:
    # gameStartTime is Madrid local midnight for the target day, expressed in UTC.
    markets = event.get("markets", [])
    if markets and markets[0].get("gameStartTime"):
        # Format observed from Gamma: "2026-06-22 22:00:00+00" (always UTC).
        naive_part = markets[0]["gameStartTime"].split("+")[0].strip()
        game_start = dt.datetime.strptime(naive_part, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        local_midnight = game_start.astimezone(ZoneInfo("Europe/Madrid"))
        return local_midnight.date()
    # Fallback: endDateIso on the event itself.
    return dt.date.fromisoformat(markets[0]["endDateIso"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-slug", required=True)
    parser.add_argument("--station", default="LEMD")
    parser.add_argument("--hours", type=int, default=30, help="METAR lookback window. Default: 30 (covers a full local day).")
    parser.add_argument("--no-price-alert-threshold", type=float, default=0.97, help="Flag dead buckets whose NO price is still below this.")
    args = parser.parse_args()

    event = fetch_event(args.event_slug)
    target_date = target_date_from_slug(args.event_slug, event)

    buckets = []
    bucket_meta = {}
    for market in event.get("markets", []):
        label = market.get("groupItemTitle") or market["question"]
        try:
            bucket = parse_bucket(label)
        except ValueError:
            continue
        buckets.append(bucket)
        prices = json.loads(market.get("outcomePrices", "[1,0]"))
        yes_price = float(prices[0])
        bucket_meta[label] = {"yes_price": yes_price, "no_price": 1.0 - yes_price}

    obs_rows = fetch_live(args.station, hours=args.hours)
    obs = [MetarObs(ts, temp) for ts, temp, _raw in obs_rows if temp is not None]

    series = running_max_series(obs, target_date)
    running_max = series[-1][1] if series else None

    print(f"event={args.event_slug} target_local_date={target_date} station={args.station}")
    if not series:
        print(f"No METAR observations yet for Madrid-local {target_date} (local day starts at 00:00 Europe/Madrid). Nothing to signal yet.")
        return

    gaps = staleness_gaps([o.obs_time_utc for o in obs if _is_target_day(o, target_date)])
    last_obs_age_min = (dt.datetime.now(dt.timezone.utc).timestamp() - series[-1][0]) / 60
    print(f"obs_count={len(series)} running_max_so_far={running_max}C last_obs_age_min={last_obs_age_min:.0f}")
    if gaps:
        print(f"WARNING: {len(gaps)} staleness gap(s) >90min in today's observations -- treat running max with caution.")

    dead = dead_buckets(running_max, buckets)
    print(f"\n{'bucket':<20}{'status':<8}{'yes_px':<10}{'no_px':<10}{'note'}")
    for bucket in sorted(buckets, key=lambda b: b.lower):
        meta = bucket_meta.get(bucket.label, {})
        is_dead = bucket.label in dead
        status = "DEAD" if is_dead else "alive"
        note = ""
        if is_dead and meta.get("no_price", 1.0) < args.no_price_alert_threshold:
            note = f"OPPORTUNITY: NO at {meta['no_price']:.3f} < {args.no_price_alert_threshold}"
        print(f"{bucket.label:<20}{status:<8}{meta.get('yes_price', float('nan')):<10.4f}{meta.get('no_price', float('nan')):<10.4f}{note}")


def _is_target_day(obs: MetarObs, target_date: dt.date) -> bool:
    from metar_nowcast import local_date
    return local_date(obs.obs_time_utc) == target_date


if __name__ == "__main__":
    main()
