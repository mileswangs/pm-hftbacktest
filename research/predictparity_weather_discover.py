#!/usr/bin/env python3
"""Discover recurring weather specialists on Polymarket (the data layer behind
predictparity.com's weather filter).

Pipeline:
  1. Pull active "highest temperature" events (tag 104596) across all cities.
  2. For the highest-volume events, pull current holders of every temperature
     bucket market.
  3. Aggregate by wallet: how many distinct weather events they currently hold,
     total share exposure, which cities.

Output: research/data/weather_traders/discovery.json  (gitignored)
"""
import json, time, os, re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.parse

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "weather_traders")
os.makedirs(OUT_DIR, exist_ok=True)


def get(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i == retries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def city_of(title):
    m = re.search(r"in (.+?) on", title or "")
    return m.group(1) if m else "?"


def pull_events():
    """Paginate active highest-temperature events."""
    events = []
    for offset in range(0, 400, 100):
        d = get(f"{GAMMA}/events", {"tag_id": 104596, "closed": "false",
                                    "limit": 100, "offset": offset})
        if not d:
            break
        events.extend(d)
        if len(d) < 100:
            break
    # de-dup by id
    seen = {}
    for e in events:
        seen[e.get("id")] = e
    return list(seen.values())


def holders_for_market(cond_id):
    d = get(f"{DATA}/holders", {"market": cond_id, "limit": 40})
    out = []
    if not d:
        return out
    for tok in d:
        for h in tok.get("holders", []):
            out.append({
                "wallet": h.get("proxyWallet"),
                "name": h.get("name") or h.get("pseudonym"),
                "amount": h.get("amount", 0),
                "outcomeIndex": h.get("outcomeIndex"),
            })
    return out


def main():
    events = pull_events()
    events.sort(key=lambda e: float(e.get("volume") or 0), reverse=True)
    print(f"active weather events: {len(events)}")

    # take the top events by volume (where real money/specialists concentrate)
    top_events = events[:60]

    # build (cond_id, city, event_title, bucket) task list
    tasks = []
    for e in top_events:
        city = city_of(e.get("title"))
        for m in e.get("markets", []):
            cond = m.get("conditionId")
            if cond:
                tasks.append((cond, city, e.get("title"), m.get("groupItemTitle"),
                              float(m.get("volume") or 0)))
    print(f"markets to scan: {len(tasks)}")

    wallet = defaultdict(lambda: {"events": set(), "cities": set(),
                                  "shares": 0.0, "name": None, "positions": 0})

    def work(t):
        cond, city, title, bucket, vol = t
        return t, holders_for_market(cond)

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(work, t) for t in tasks]
        for f in as_completed(futs):
            t, hs = f.result()
            cond, city, title, bucket, vol = t
            for h in hs:
                w = h["wallet"]
                if not w:
                    continue
                rec = wallet[w]
                rec["events"].add(title)
                rec["cities"].add(city)
                rec["shares"] += float(h["amount"] or 0)
                rec["positions"] += 1
                if h["name"]:
                    rec["name"] = h["name"]
            done += 1
            if done % 100 == 0:
                print(f"  scanned {done}/{len(tasks)} markets, wallets={len(wallet)}")

    # rank by number of distinct weather events currently held
    ranked = []
    for w, rec in wallet.items():
        ranked.append({
            "wallet": w,
            "name": rec["name"],
            "n_events": len(rec["events"]),
            "n_cities": len(rec["cities"]),
            "n_positions": rec["positions"],
            "total_shares": round(rec["shares"], 2),
            "cities": sorted(rec["cities"]),
        })
    ranked.sort(key=lambda x: (x["n_events"], x["total_shares"]), reverse=True)

    out = {"as_of": time.strftime("%Y-%m-%d %H:%M:%S"),
           "n_active_events": len(events),
           "n_scanned_events": len(top_events),
           "n_scanned_markets": len(tasks),
           "n_wallets": len(ranked),
           "top_wallets": ranked[:60]}
    path = os.path.join(OUT_DIR, "discovery.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {path}")
    print("\nTOP 25 recurring weather wallets by # distinct events held:")
    print(f"{'wallet':44} {'name':22} {'evts':>4} {'cits':>4} {'pos':>4} {'shares':>14}")
    for r in ranked[:25]:
        print(f"{r['wallet']:44} {str(r['name'])[:22]:22} {r['n_events']:>4} "
              f"{r['n_cities']:>4} {r['n_positions']:>4} {r['total_shares']:>14,.0f}")


if __name__ == "__main__":
    main()
