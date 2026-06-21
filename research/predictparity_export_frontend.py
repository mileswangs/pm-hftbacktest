#!/usr/bin/env python3
"""Export the weather-trader research into static JSON the frontend can consume
with zero backend (same pattern as frontend/public/data/weather/*.json).

Outputs:
  frontend/public/data/traders/manifest.json     -> TradersManifest
  frontend/public/data/traders/{wallet}.fills.json -> TraderFill[]

Schema mirrors frontend/src/traders/types.ts (see
research/PREDICTPARITY_FRONTEND_AND_STRATEGY_OPT_2026-06-21.md §C).

Run after the discover/profile scripts. Reuses their helpers.
"""
import json, os, re, time, importlib.util
import urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_IN = os.path.join(HERE, "data", "weather_traders")
OUT = os.path.join(REPO, "frontend", "public", "data", "traders")
os.makedirs(OUT, exist_ok=True)

# reuse helpers from the profile script
spec = importlib.util.spec_from_file_location(
    "prof", os.path.join(HERE, "predictparity_weather_profile.py"))
prof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prof)

USERPNL = "https://user-pnl-api.polymarket.com/user-pnl"

# winners + two cautionary high-volume losers (frontend can show "avoid" tag)
TARGETS = {
    "Poligarch":            "0xb40e89677d59665d5188541ad860450a6e2a7cc9",
    "0xfBd8C9C22":          "0xfbd8c9c22ca76b3662d0e53a4f79719fdc684027",
    "ultralisk":            "0x74957ea27ac4fbdee46d861fdae357859ff67fcf",
    "Lavincey":             "0x1cdd071bb612de6d66d0c882b676c663697de595",
    "Corlys":               "0xd23f8c8aab13cfb2a35da40b67f8471faf9894a1",
    "OnlyLuckNoBrain":      "0x6a8d1709bfb718d8555d315a983c4816278350f9",
    "badatmath.":           "0x8fbd7cf5f806f563080864694415829f7229a959",
    "HighTempTation":       "0x6011655c4afb76f36dd1b08a137a1ba73466b31e",
    "pootytherewardfarmer": "0xa3e22cd32aa9238ef7dbcfb4761e33b9eaa1fdf8",  # loser
    "TENETENET":            "0x3329cfc2b8d8ceb8d198f081bdf4262f421f43a6",  # farmer
}


def get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def lifetime(wallet):
    pr = get(f"https://lb-api.polymarket.com/profit?window=all&limit=1&address={wallet}")
    vol = get(f"https://lb-api.polymarket.com/volume?window=all&limit=1&address={wallet}")
    val = get(f"https://data-api.polymarket.com/value?user={wallet}")
    return ((pr[0]["amount"] if pr else None),
            (vol[0]["amount"] if vol else None),
            (val[0]["value"] if val else None))


def classify(p, pnl, vol):
    no = p.get("direction", {}).get("No", 0)
    yes = p.get("direction", {}).get("Yes", 0)
    tot = no + yes or 1
    pr = p.get("entry_price_regime", {})
    near = pr.get(">90c (near-certain)", 0)
    tail = pr.get("<10c (tail)", 0)
    mid_lo = pr.get("10-40c", 0)
    nb = sum(pr.values()) or 1
    med_hrs = p.get("entry_hours_before_resolution", {}).get("median", 0)
    # warnings first: net losers and high-volume thin-margin churn
    if pnl is not None and pnl < 0:
        return "farmer"  # cautionary: high churn / net loser
    if vol and pnl is not None and vol > 5_000_000 and abs(pnl) < vol * 0.005:
        return "farmer"
    # behavioural style by direction / price / timing (meaningful even if the
    # wallet also trades non-weather)
    if no / tot > 0.9 and near / nb > 0.4:
        return "no-convergence"
    if tail / nb > 0.4 and (p.get("avg_trade_usd") or 0) < 5:
        return "long-tail"
    if yes >= no and mid_lo / nb > 0.25 and (med_hrs or 0) >= 20:
        return "yes-forecast"
    # only here fall back: light weather footprint -> generalist
    if (p.get("weather_trade_pct") or 0) < 60:
        return "generalist"
    return "generalist"


def fills_for(wallet):
    acts = prof.pull_activity(wallet)
    out = []
    for a in acts:
        if a.get("type") != "TRADE" or not prof.is_weather(a):
            continue
        kind, city, dt = prof.parse_event(a.get("eventSlug"))
        hb = None
        if dt:
            import datetime
            res_ts = datetime.datetime(dt.year, dt.month, dt.day, 23, 0,
                                       tzinfo=datetime.timezone.utc).timestamp()
            hb = round((res_ts - float(a.get("timestamp") or 0)) / 3600.0, 1)
        out.append({
            "t": int(a.get("timestamp") or 0),
            "side": (a.get("side") or "").lower(),
            "outcome": a.get("outcome"),
            "price": round(float(a.get("price") or 0), 4),
            "size": round(float(a.get("usdcSize") or 0), 2),
            "citySlug": (city or "").lower().replace(" ", "-"),
            "bucketLabel": (a.get("title") or "").split("be ")[-1].rstrip("?"),
            "eventDate": dt.isoformat() if dt else None,
            "hoursBeforeResolution": hb,
        })
    return out


def main():
    with open(os.path.join(DATA_IN, "winner_profiles.json")) as f:
        wp = {p["wallet"].lower(): p for p in json.load(f)["profiles"]}

    traders = []
    for alias, w in TARGETS.items():
        print(f"exporting {alias} ...")
        p = wp.get(w.lower()) or prof.profile(w, alias)
        pnl, vol, val = lifetime(w)
        pnl_series = get(USERPNL, {"user_address": w, "interval": "all", "fidelity": "1d"}) or []
        fills = fills_for(w)
        with open(os.path.join(OUT, f"{w}.fills.json"), "w") as f:
            json.dump(fills, f)
        traders.append({
            "wallet": w, "alias": alias, "asOf": time.strftime("%Y-%m-%d"),
            "lifetimePnl": round(pnl, 2) if pnl is not None else None,
            "lifetimeVolume": round(vol, 2) if vol is not None else None,
            "currentValue": round(val, 2) if val is not None else None,
            "weatherPct": p.get("weather_trade_pct"),
            "avgTradeUsd": p.get("avg_trade_usd"),
            "sellRatio": p.get("sell_count_ratio"),
            "redeems": p.get("n_redeems"),
            "nCities": p.get("n_distinct_cities"),
            "direction": {"yes": p.get("direction", {}).get("Yes", 0),
                          "no": p.get("direction", {}).get("No", 0)},
            "priceRegime": p.get("entry_price_regime", {}),
            "entryHours": p.get("entry_hours_before_resolution", {}),
            "topCities": p.get("top_cities", []),
            "style": classify(p, pnl, vol),
            "nFills": len(fills),
            "pnlSeriesLast": (pnl_series[-1]["p"] if pnl_series else None),
        })

    traders.sort(key=lambda t: (t["lifetimePnl"] or -9e9), reverse=True)
    manifest = {"generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "traders": traders}
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nwrote {OUT}/manifest.json  ({len(traders)} traders)")
    for t in traders:
        print(f"  {t['alias'][:20]:20} {str(t['style']):16} "
              f"PnL={t['lifetimePnl']:>10,.0f}  fills={t['nFills']}")


if __name__ == "__main__":
    main()
