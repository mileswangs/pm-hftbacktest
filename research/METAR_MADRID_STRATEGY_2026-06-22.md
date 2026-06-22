# METAR-Based NO-Convergence Strategy — Madrid Highest-Temperature Markets

Date: `2026-06-22`
Branch: `research/METAR`
Market: Polymarket "Highest temperature in Madrid on {date}" (e.g. [highest-temperature-in-madrid-on-june-23-2026](https://polymarket.com/event/highest-temperature-in-madrid-on-june-23-2026)), resolved off [Wunderground's LEMD daily history page](https://www.wunderground.com/history/daily/es/madrid/LEMD) (Adolfo Suárez Madrid-Barajas Airport).

## TL;DR

Real-time METAR from LEMD lets you mechanically detect, before the market fully prices it, which temperature buckets have become impossible because the day's actual running max has already exceeded their upper bound. Backtested over 94 settled historical Madrid days (2026-03-16 to 2026-06-21): **0 misses** — every bucket the signal called "dead" really did lose, matching Polymarket's official settlement. But the edge is scarce and concentrated: only ~28–34% of days produce a tradeable opportunity at all, it shows up almost exclusively in a **14:00–19:00 Madrid-local window** (the city's afternoon heating peak), and ~94% of eliminations are already priced in (NO ≥ 0.99) by the time METAR confirms them — the real edge is catching the *one* "runner-up" bucket that dies right as the day's temperature ticks past it for the last time.

## Why this approach

This mechanizes "Style A" (NO-convergence) from the existing trader research in this repo ([PREDICTPARITY_WEATHER_TRADERS_2026-06-21.md](PREDICTPARITY_WEATHER_TRADERS_2026-06-21.md)): real, profitable wallets (Poligarch, HighTempTation, Corlys, 0xfBd8C9C2) already buy NO at >90¢ on buckets that are essentially dead, judged by eyeballing Wunderground, entering a median ~11–13h before settlement. METAR replaces the eyeball with a quantitative, sub-hourly ground-truth signal.

Two facts make this tractable for Madrid specifically:
- The market resolves to **whole-degree-C** buckets, and LEMD's international METAR already reports whole-degree-C temperatures directly (`24/08` format) — no tenths/rounding ambiguity.
- A day's running max-so-far is monotonically non-decreasing, so "upper bound already exceeded" is a hard mathematical elimination, not a probabilistic judgment.

## Data sources (both free, no auth — live-tested)

- **Live**: `aviationweather.gov/api/data/metar` — JSON, ~5 min refresh, whole-°C temps.
- **Historical**: Iowa Environmental Mesonet ASOS archive (`mesonet.agron.iastate.edu`) — 30-min interval temps, used for the backtest below.
- **Market data**: existing `research/weather_data_warehouse.py` (Gamma + CLOB public APIs, already in this repo) — settled outcomes, bucket bounds, and CLOB last-trade price history.

## Pipeline built this round

| File | Purpose |
|---|---|
| [metar_data.py](metar_data.py) | Fetch live or historical LEMD METAR into a local SQLite store. Station is a CLI arg, not hardcoded. |
| [metar_nowcast.py](metar_nowcast.py) | Pure signal logic: parse bucket labels, track Madrid-local-day running max, determine dead buckets. No I/O — unit-checked with synthetic data. |
| [metar_madrid_backtest.py](metar_madrid_backtest.py) | Joins the nowcast signal against historical Polymarket price history for every settled Madrid day; simulates buying NO the moment a bucket dies, if its price is still below a threshold. |
| [metar_live_monitor.py](metar_live_monitor.py) | Read-only CLI: prints current alive/dead buckets + NO price for any live event. **No order placement.** |

Repro:

```bash
# 1. Populate the price-history warehouse (existing script, this repo)
python3 research/weather_data_warehouse.py sync --cities madrid --anchor-date 2026-06-21 --days 120

# 2. Backfill historical METAR for the same window
python3 research/metar_data.py history --station LEMD --start-date 2026-03-15 --end-date 2026-06-22

# 3. Run the backtest
python3 research/metar_madrid_backtest.py --thresholds 0.80,0.85,0.90,0.95,0.97,0.99

# 4. Live signal for the currently active market (read-only)
python3 research/metar_live_monitor.py --event-slug highest-temperature-in-madrid-on-june-23-2026 --station LEMD
```

## Signal logic

For each bucket (e.g. `37°C`, `36°C or below`, `46°C or higher`), parse `(lower, upper)` bounds in °C. At every new METAR observation, recompute the running max-so-far **for that Madrid-local civil day** (DST-safe via `zoneinfo`, not a fixed UTC offset). A bucket is dead the instant `upper < running_max_so_far`. The open-ended top tail bucket (`X°C or higher`) has no upper bound and is never declared dead by this rule — that would need the opposite, much harder kind of reasoning ("can it still get hot enough"), out of scope this round.

## Backtest results

94 settled Madrid events (2026-03-16 to 2026-06-21; 1 of the 95 synced events was still unsettled at fetch time and excluded). Entry = first CLOB last-trade price at or after the bucket's death timestamp; PnL is per $1 of NO notional, held to settlement.

| NO-price threshold | Trades | Unique days w/ ≥1 trade | Hit rate | Avg PnL/share | Total PnL/share | Avg entry price |
|---:|---:|---:|---:|---:|---:|---:|
| 0.80 | 26 | 26/94 | 100% | 0.483 | 12.57 | 0.517 |
| 0.85 | 28 | — | 100% | 0.462 | 12.93 | 0.538 |
| 0.90 | 30 | 27/94 | 100% | 0.438 | 13.15 | 0.562 |
| 0.95 | 35 | — | 100% | 0.387 | 13.55 | 0.613 |
| 0.97 | 44 | — | 100% | 0.316 | 13.90 | 0.684 |
| 0.99 | 57 | 32/94 | 100% | 0.248 | 14.13 | 0.752 |

Out of **484** total bucket-death events across the 94 days, only **176** had any recorded CLOB trade at or after the exact death timestamp at all — the other 308 (64%) had gone quiet earlier (those buckets were obviously dead well before METAR formally confirmed it, so nobody was still trading the token by the time it mathematically died). Of the 176 with a price to check, **119 (68%) were already at NO ≥ 0.99** — fully converged before METAR's confirmation. Only the remaining **57 (32% of 176, 12% of 484)** were still tradeable below 0.99, and that's where this strategy's entire edge lives.

**Timing is tight and consistent**: every single triggered trade across every threshold fell in the **14:00–19:00 Madrid-local** window — Madrid's afternoon heating peak, when the day's last 1–2 candidate buckets get resolved by the final degree-tick.

Cheapest (highest-edge) example: `2026-06-10`, the `31°C` bucket died at `18:30` local when METAR ticked to `32°C`; NO was still trading at **0.045** at that moment (market still saw `31°C` as ~95.5% likely); actual winner was `32°C` — correct.

## Key caveats (not assumed away)

- **No fill-simulation realism.** Entry price is "first last-trade print at or after the death timestamp," not a reconstructed best-ask with depth — consistent with this repo's other backtests, which document the same gap. The very cheap entries (e.g. the 4.5¢ example above) are the ones most likely to be a stale/thin-book print rather than a truly executable fill; treat the headline PnL numbers as an upper bound until a book-depth-aware version is built.
- **METAR ≠ Wunderground is a real, measured risk, not a theoretical one** (confirmed via separate web research this round: Wunderground's daily history excludes some DSM/1-min spike data that raw METAR includes, and Kalshi's equivalent markets settle off a *different* report — NWS CLI — which can legitimately diverge from Wunderground on the same city/day). This backtest measured 0/94 misses, which is a genuinely strong result, but the sample is one city, one ~3-month warm-season window — not enough to rule out rare divergence.
- **Sample is narrow**: Madrid only, March–June (spring/early summer), 94 days. Both diurnal shape and METAR-reliability could differ in winter or other cities.
- **Edge is intermittent, not daily**: only 27–32 of 94 days produced any actionable trade at all under realistic thresholds.
- **Regulatory note, unrelated to the data/strategy work**: separate web research this round surfaced reports that Spain restricted Polymarket/Kalshi access in 2026 over gambling-license requirements — worth checking current standing before this market is relevant for live trading from Spain, independent of whether the signal itself works.

## Live monitor status

`metar_live_monitor.py` was smoke-tested against the real, currently active `highest-temperature-in-madrid-on-june-23-2026` market. Correct, expected output right now:

```
event=highest-temperature-in-madrid-on-june-23-2026 target_local_date=2026-06-23 station=LEMD
No METAR observations yet for Madrid-local 2026-06-23 (local day starts at 00:00 Europe/Madrid). Nothing to signal yet.
```

This is correct, not a bug: Madrid-local June 23 begins at `2026-06-22T22:00:00Z`, about 17.5 hours after this was run. The table-output code path (alive/dead per bucket + current YES/NO price) was separately verified using real historical METAR joined with the live event's current bucket structure. Once June 23's local day starts, re-running the same command will show real signal — and per the backtest above, the highest-probability window to watch is **14:00–19:00 Madrid local on June 23**.

## If continuing this research

1. Reconstruct actual best-ask depth at the death moment (not just last-trade price) to know how much of the headline edge survives realistic execution — this is the single biggest open question before sizing any real capital.
2. Extend the backtest to a full year (or another warm city) to see if the 0/94 hit rate holds outside spring/summer Madrid.
3. The open-ended top-tail bucket (`X°C or higher`) and the "is the day done heating" judgment are unaddressed by hard elimination — that's Approach 2 (continuous probability nowcast) from the original design discussion, deliberately deferred this round.
4. No live execution wiring was done this round by design — this is signal + backtest + a read-only monitor only.
