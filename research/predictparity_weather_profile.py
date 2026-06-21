#!/usr/bin/env python3
"""Profile the trading habits of the top recurring weather wallets found by
predictparity_weather_discover.py.

For each wallet we pull full /activity (paginated) and current /positions, then
compute behavioural features used by research/POLYMARKET_TRADER_PROFILING.md:

  - weather concentration (% of trades in temperature markets)
  - buy/sell ratio & sell notional ratio  (active exit vs hold-to-resolve)
  - REDEEM count                          (hold-to-resolution signal)
  - avg trade size, total weather volume
  - entry-price regime distribution       (cheap tail / mid / near-certain)
  - city concentration, highest vs lowest temp, Yes/No direction
  - timing: hours before event date that trades are placed
  - PnL snapshot from current positions (realized + unrealized on weather)

Output: research/data/weather_traders/profiles.json (gitignored)
"""
import json, time, os, re, datetime
from collections import Counter, defaultdict
import urllib.request, urllib.parse

DATA = "https://data-api.polymarket.com"
HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "data", "weather_traders")

MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}


def get(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def pull_activity(wallet, cap=6000):
    out = []
    for offset in range(0, cap, 500):
        d = get(f"{DATA}/activity", {"user": wallet, "limit": 500, "offset": offset})
        if not d:
            break
        out.extend(d)
        if len(d) < 500:
            break
    return out


def is_weather(a):
    s = (a.get("eventSlug") or a.get("slug") or "")
    return "temperature-in-" in s or "temperature in" in (a.get("title") or "").lower()


def parse_event(slug):
    """('highest'|'lowest', city, date) from an eventSlug like
    highest-temperature-in-hong-kong-on-june-22-2026"""
    m = re.match(r"(highest|lowest)-temperature-in-(.+?)-on-([a-z]+)-(\d+)-(\d+)", slug or "")
    if not m:
        return None, None, None
    kind, city, mon, day, year = m.groups()
    city = city.replace("-", " ").title()
    dt = None
    if mon in MONTHS:
        try:
            dt = datetime.date(int(year), MONTHS[mon], int(day))
        except ValueError:
            dt = None
    return kind, city, dt


def price_bucket(p):
    if p < 0.10: return "<10c (tail)"
    if p < 0.40: return "10-40c"
    if p < 0.60: return "40-60c (mid)"
    if p < 0.90: return "60-90c"
    return ">90c (near-certain)"


def profile(wallet, name):
    acts = pull_activity(wallet)
    trades = [a for a in acts if a.get("type") == "TRADE"]
    wx = [a for a in trades if is_weather(a)]
    wx_redeem = [a for a in acts if a.get("type") == "REDEEM" and is_weather(a)]

    n_all_trades = len(trades)
    n_wx = len(wx)
    res = {
        "wallet": wallet, "name": name,
        "n_activity": len(acts),
        "n_trades_total": n_all_trades,
        "n_weather_trades": n_wx,
        "weather_trade_pct": round(100 * n_wx / n_all_trades, 1) if n_all_trades else 0,
    }
    if not wx:
        return res

    buys = [a for a in wx if a.get("side") == "BUY"]
    sells = [a for a in wx if a.get("side") == "SELL"]
    buy_notional = sum(float(a.get("usdcSize") or 0) for a in buys)
    sell_notional = sum(float(a.get("usdcSize") or 0) for a in sells)
    tot_notional = buy_notional + sell_notional

    res.update({
        "weather_volume_usd": round(tot_notional, 2),
        "n_buys": len(buys), "n_sells": len(sells),
        "sell_count_ratio": round(len(sells) / n_wx, 3),
        "sell_notional_ratio": round(sell_notional / tot_notional, 3) if tot_notional else 0,
        "n_redeems": len(wx_redeem),
        "avg_trade_usd": round(tot_notional / n_wx, 2),
        "median_trade_usd": round(sorted(float(a.get("usdcSize") or 0) for a in wx)[n_wx // 2], 3),
    })

    # price regime (buys only — entry price)
    pr = Counter(price_bucket(float(a.get("price") or 0)) for a in buys)
    res["entry_price_regime"] = dict(pr)

    # direction
    dirc = Counter(a.get("outcome") for a in wx)
    res["direction"] = dict(dirc)

    # highest vs lowest, cities
    kinds, cities = Counter(), Counter()
    hours_before = []
    for a in wx:
        kind, city, dt = parse_event(a.get("eventSlug"))
        if kind: kinds[kind] += 1
        if city: cities[city] += 1
        if dt:
            # resolution ~ end of target day (use 23:00 UTC as proxy)
            res_ts = datetime.datetime(dt.year, dt.month, dt.day, 23, 0,
                                       tzinfo=datetime.timezone.utc).timestamp()
            hb = (res_ts - float(a.get("timestamp") or 0)) / 3600.0
            if -48 < hb < 240:
                hours_before.append(hb)
    res["kind_split"] = dict(kinds)
    res["n_distinct_cities"] = len(cities)
    res["top_cities"] = cities.most_common(8)
    if hours_before:
        hours_before.sort()
        res["entry_hours_before_resolution"] = {
            "p10": round(hours_before[int(0.1 * len(hours_before))], 1),
            "median": round(hours_before[len(hours_before) // 2], 1),
            "p90": round(hours_before[int(0.9 * len(hours_before))], 1),
        }

    # active window
    ts = [a.get("timestamp") for a in wx if a.get("timestamp")]
    if ts:
        res["first_weather_trade"] = time.strftime("%Y-%m-%d", time.gmtime(min(ts)))
        res["last_weather_trade"] = time.strftime("%Y-%m-%d", time.gmtime(max(ts)))

    # PnL snapshot from current positions
    pos = get(f"{DATA}/positions", {"user": wallet, "limit": 500}) or []
    wpos = [p for p in pos if is_weather(p) or "temperature" in (p.get("title") or "").lower()]
    res["open_weather_positions"] = len(wpos)
    res["open_weather_realized_pnl"] = round(sum(float(p.get("realizedPnl") or 0) for p in wpos), 2)
    res["open_weather_cash_pnl"] = round(sum(float(p.get("cashPnl") or 0) for p in wpos), 2)
    res["open_weather_value"] = round(sum(float(p.get("currentValue") or 0) for p in wpos), 2)
    return res


def main():
    with open(os.path.join(OUT_DIR, "discovery.json")) as f:
        disc = json.load(f)
    targets = disc["top_wallets"][:18]

    profiles = []
    for i, t in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] profiling {t['name']} {t['wallet']} ...")
        p = profile(t["wallet"], t["name"])
        p["discovery_events"] = t["n_events"]
        p["discovery_cities"] = t["n_cities"]
        profiles.append(p)

    out = {"as_of": time.strftime("%Y-%m-%d %H:%M:%S"), "profiles": profiles}
    path = os.path.join(OUT_DIR, "profiles.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {path}\n")

    hdr = f"{'name':22} {'wxTrades':>8} {'wx%':>5} {'wxVol$':>12} {'sellR':>6} {'redeem':>6} {'avg$':>8} {'cities':>6} {'medHrs':>7}"
    print(hdr)
    for p in profiles:
        hrs = p.get("entry_hours_before_resolution", {}).get("median", "")
        print(f"{str(p['name'])[:22]:22} {p.get('n_weather_trades',0):>8} "
              f"{p.get('weather_trade_pct',0):>5} {p.get('weather_volume_usd',0):>12,.0f} "
              f"{p.get('sell_count_ratio',0):>6} {p.get('n_redeems',0):>6} "
              f"{p.get('avg_trade_usd',0):>8,.0f} {p.get('n_distinct_cities',0):>6} {str(hrs):>7}")


if __name__ == "__main__":
    main()
