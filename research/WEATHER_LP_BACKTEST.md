# Weather LP Prototype Backtest

Date checked: `2026-06-19`

This is an **approximate** LP backtest. It is **not** a full historical order-book replay.

Inputs:

- public Polymarket price history (`prices-history`) as midpoint proxy
- current reward configs from `GET /rewards/markets/current`
- current market reward params such as `rewardsMinSize` and `rewardsMaxSpread`

Representative command:

```bash
python3 research/weather_lp_backtest.py \
  --days-lookback 30 \
  --quote-width-cents 1.5 \
  --size-multiplier 1.0
```

## What the model estimates

- mark-to-market trading PnL of a symmetric passive quoting policy
- raw reward pool over the sample window
- score-adjusted reward pool using the official quadratic reward score
- breakeven reward share needed to offset trading losses

## Current result

Top reward-bearing weather/climate opportunity found by the scanner:

- event: `min-arctic-sea-ice-extent-this-summer`
- notable buckets:
  - `<4m sq km`
  - `4.0-4.2m sq km`
  - `4.6-4.8m sq km`

At `1.5c` quote width:

| bucket | viability | trading pnl | raw reward pool | score-adjusted pool | breakeven share of adjusted pool |
| --- | --- | ---: | ---: | ---: | ---: |
| `4.6-4.8m sq km` | inventory_sensitive | `+0.15` | `89.99` | `24.40` | `0.00` |
| `<4m sq km` | good_candidate | `-67.75` | `89.99` | `23.02` | `2.94x` |
| `4.0-4.2m sq km` | needs_improvement | `-125.17` | `89.99` | `22.47` | `5.57x` |

Interpretation:

- `4.6-4.8m sq km` looks viable mainly because it trades infrequently and inventory did not get run over in the sample
- `<4m sq km` is much more liquid, but the trading losses dominate reward unless you assume an unrealistically large share of the reward pool
- `4.0-4.2m sq km` is worse because the visible spread is already wider than the reward cutoff, so you must improve the book while still absorbing adverse selection

## Width sensitivity

For the same event, changing quote width materially changes feasibility.

### `4.6-4.8m sq km`

- `0.5c`: trading pnl `+3.67`, score pool `36.19`
- `1.0c`: trading pnl `+0.45`, score pool `46.87`
- `1.5c`: trading pnl `+0.15`, score pool `24.40`
- `2.0c+`: still near-flat trading pnl, but reward score decays

### `<4m sq km`

- all widths from `0.5c` to `3.0c` stayed meaningfully negative on trading PnL
- the reward share required to break even remained well above a realistic competitive share

### `4.0-4.2m sq km`

- narrow quoting increased adverse-selection losses
- very wide quoting reduced score enough that the reward capacity collapsed

## Main conclusion

LP on rewarded weather/climate markets is feasible **only selectively**.

Good use case:

- reward-active bucket
- moderate visible spread
- low or moderate trade-through frequency
- not too much inventory drift

Bad use case:

- high-frequency bucket near the main consensus point
- visible spread already wider than reward cutoff
- bucket is reward-active, but competition is high and reward pool is too small versus trading losses

## Risk points

1. **Adverse selection**
   - The core risk. Tight quotes in liquid buckets got run over faster than rewards could compensate.

2. **Extreme midpoint regime**
   - When midpoint is outside `[0.10, 0.90]`, the official rules effectively require double-sided liquidity to score.
   - This makes skewed inventory much more dangerous.

3. **Competition for reward share**
   - The prototype can estimate raw pool and a score-adjusted pool, but not the true normalized share against other makers.
   - A market can look attractive on gross rewards and still be unattractive after competition.

4. **Historical reward-rate uncertainty**
   - The prototype assumes the current reward config applied throughout the backtest window.
   - This is conservative for structure, but not exact for historical PnL attribution.

5. **Public-price-history approximation**
   - This is not historical L2.
   - Passive fill logic is approximated from last-price transitions, so fill realism is limited.

## Practical implication

The LP path is viable enough to keep building, but it should move in this order:

1. reward scanner
2. market shortlist
3. reward-share monitoring
4. fuller L2-based maker backtest for only the shortlisted markets
