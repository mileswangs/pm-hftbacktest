#!/usr/bin/env python3
"""Compute lifetime realized weather PnL + event-level win rate for the candidate
weather specialists, reconstructed from the full Polymarket activity log.

Why not use /positions: hold-to-resolve traders redeem winners (which then leave
their open positions), so a positions snapshot systematically *understates* their
PnL. The activity log (BUY / SELL / REDEEM cashflows) is the correct source.

  realized_weather_pnl = sum(REDEEM payout) + sum(SELL proceeds) - sum(BUY cost)
  event = (city, date); event win = net cashflow on that event > 0

Output: research/data/weather_traders/pnl.json (gitignored)
"""
import json, time, os, re
from collections import defaultdict
import urllib.request, urllib.parse

DATA = "https://data-api.polymarket.com"
HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "data", "weather_traders")

# real candidates (skip the 0.1c reward-farm/dust wallets) + HighTempTation cross-check
CANDIDATES = {
    "1DVSBSTD":             "0xeb1d1cd1b31070fb34b1d1de20d700f59c9959b0",
    "AMAM13":               "0x52ebca459280966f4a56240a05e38df8527067ac",
    "OnlyLuckNoBrain":      "0x6a8d1709bfb718d8555d315a983c4816278350f9",
    "Poligarch":            "0xb40e89677d59665d5188541ad860450a6e2a7cc9",
    "0x0820-4":             "0xea12c83bb04d6b15a534374ea0c775d57d84993b",
    "L.X":                  "0xcc2c17375fe97e38e1f734ae30f42cab57f20a2c",
    "Mojito9":              "0xf2cf3cf7863182c763bce60580a7d20e9333464b",
    "pootytherewardfarmer": "0xa3e22cd32aa9238ef7dbcfb4761e33b9eaa1fdf8",
    "Lavincey":             "0x1cdd071bb612de6d66d0c882b676c663697de595",
    "Corlys":               "0xd23f8c8aab13cfb2a35da40b67f8471faf9894a1",
    "AMAM13b/ultralisk":    "0x74957ea27ac4fbdee46d861fdae357859ff67fcf",
    "HighTempTation":       "0x6011655c4afb76f36dd1b08a137a1ba73466b31e",
}


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


def pull_activity(wallet, cap=12000):
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


def event_key(a):
    s = a.get("eventSlug") or a.get("slug") or ""
    m = re.match(r"((?:highest|lowest)-temperature-in-.+?-on-[a-z]+-\d+-\d+)", s)
    return m.group(1) if m else s


def analyze(wallet):
    acts = pull_activity(wallet)
    wx = [a for a in acts if is_weather(a)]
    buy = sum(float(a.get("usdcSize") or 0) for a in wx if a.get("side") == "BUY")
    sell = sum(float(a.get("usdcSize") or 0) for a in wx if a.get("side") == "SELL")
    redeem = sum(float(a.get("usdcSize") or 0) for a in wx if a.get("type") == "REDEEM")
    realized = sell + redeem - buy

    # event-level cashflow win rate (only events with no residual open exposure
    # are fully realized; we approximate using all events that have a redeem or
    # are old enough — here we use net cashflow per event)
    ev = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "redeem": 0.0, "n": 0})
    for a in wx:
        k = event_key(a)
        usd = float(a.get("usdcSize") or 0)
        if a.get("type") == "REDEEM":
            ev[k]["redeem"] += usd
        elif a.get("side") == "BUY":
            ev[k]["buy"] += usd
        elif a.get("side") == "SELL":
            ev[k]["sell"] += usd
        ev[k]["n"] += 1

    wins = losses = 0
    win_sum = loss_sum = 0.0
    settled = []
    for k, v in ev.items():
        pnl = v["sell"] + v["redeem"] - v["buy"]
        # treat an event as "settled" if it produced any redeem or sell (cashed out)
        if v["redeem"] > 0 or v["sell"] > 0:
            settled.append(pnl)
            if pnl > 0:
                wins += 1; win_sum += pnl
            else:
                losses += 1; loss_sum += pnl
    n_settled = wins + losses
    return {
        "wallet": wallet,
        "n_weather_activity": len(wx),
        "buy_cost": round(buy, 2),
        "sell_proceeds": round(sell, 2),
        "redeem_payout": round(redeem, 2),
        "realized_weather_pnl": round(realized, 2),
        "roi_on_cost_pct": round(100 * realized / buy, 1) if buy else None,
        "n_events_traded": len(ev),
        "n_events_settled": n_settled,
        "event_win_rate_pct": round(100 * wins / n_settled, 1) if n_settled else None,
        "avg_win": round(win_sum / wins, 2) if wins else None,
        "avg_loss": round(loss_sum / losses, 2) if losses else None,
        "profit_factor": round(win_sum / -loss_sum, 2) if loss_sum < 0 else None,
    }


def main():
    rows = []
    for name, w in CANDIDATES.items():
        print(f"analyzing {name} ...")
        r = analyze(w)
        r["name"] = name
        rows.append(r)
    rows.sort(key=lambda x: x["realized_weather_pnl"], reverse=True)
    out = {"as_of": time.strftime("%Y-%m-%d %H:%M:%S"), "method":
           "realized = sell + redeem - buy, over weather activity log", "rows": rows}
    with open(os.path.join(OUT_DIR, "pnl.json"), "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n{'name':20}{'realPnL$':>11}{'ROI%':>7}{'buyCost$':>11}{'evTraded':>9}"
          f"{'evSettl':>8}{'winR%':>7}{'avgWin':>8}{'avgLoss':>9}{'PF':>7}")
    for r in rows:
        print(f"{r['name'][:20]:20}{r['realized_weather_pnl']:>11,.0f}"
              f"{str(r['roi_on_cost_pct']):>7}{r['buy_cost']:>11,.0f}"
              f"{r['n_events_traded']:>9}{r['n_events_settled']:>8}"
              f"{str(r['event_win_rate_pct']):>7}{str(r['avg_win']):>8}"
              f"{str(r['avg_loss']):>9}{str(r['profit_factor']):>7}")


if __name__ == "__main__":
    main()
