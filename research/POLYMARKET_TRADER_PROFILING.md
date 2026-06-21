# Polymarket Trader Profiling

This is the fixed lightweight workflow for profiling a Polymarket wallet.

## Goal

Given a wallet address or username, classify the trader into a small set of trading styles and explain why with minimal token usage.

## Data sources

Use the lowest-cost sources first:

1. Wallet dashboards
   - Polydata
   - Predicts.guru
   - Struct explorer
2. Public market pages
   - sample trades
   - category concentration
   - typical entry price
3. Public social/web references
   - X
   - Reddit
   - blog posts

## Minimal output schema

Return only these fields unless deeper work is requested:

- `wallet`
- `alias`
- `as_of_date`
- `primary_style`
- `secondary_style`
- `confidence`
- `core_evidence`
- `risk_notes`
- `what_they_are_actually_doing`

## Core features to inspect

### 1. Market concentration

- weather / politics / crypto / sports / other
- top city / top topic / top event family

### 2. Price regime

- mostly buys near `0.01-0.10`
- mostly buys near `0.40-0.60`
- mostly buys near `0.90-0.999`

### 3. Direction bias

- mostly `Yes`
- mostly `No`
- balanced

### 4. Execution pattern

- opens and holds to resolution
- opens then actively exits
- many partial fills
- repetitive same-market slicing

### 5. Outcome profile

- high win rate / low payoff
- lower win rate / convex payoff
- mixed

### 6. Specialization signal

- one-category specialist
- one-city specialist
- multi-city same-model trader
- broad discretionary trader

## Style taxonomy

Use one primary style and at most one secondary style.

### A. High-probability resolution scalper

Definition:
- buys near-certain contracts late
- usually `0.90+`
- often farms `0.99 -> 1.00` or `0.01 -> 0.00`

Signs:
- extremely high win rate
- modest average PnL per trade
- many repetitive trades

### B. Weather forecast arb

Definition:
- concentrated in daily temperature / weather markets
- edge comes from forecast/model disagreement versus market

Signs:
- weather concentration is dominant
- city repetition
- trades cluster around forecast update cycles

### C. Long-tail mispricing hunter

Definition:
- buys cheap outcomes with asymmetric payoff

Signs:
- many entries below `0.10`
- lower hit rate
- a few large winners drive PnL

### D. Momentum/news trader

Definition:
- trades fast-moving narrative markets after information shocks

Signs:
- politics / crypto / breaking news concentration
- high turnover around headlines

### E. Passive carry / event carry

Definition:
- takes positions when event is nearly settled and clips residual spread

Signs:
- price near certainty
- short holding period
- low volatility categories

### F. Market maker / spread recycler

Definition:
- repeatedly buys and sells both sides or slices inventory

Signs:
- high sell ratio
- many small fills
- similar buy/sell notional

## Fixed classification rules

### Classify as `High-probability resolution scalper` when:

- dominant entry regime is above `0.90` or below `0.10`, and
- win rate is very high, and
- average PnL per trade is small relative to volume

### Add `Weather forecast arb` as secondary when:

- weather share is dominant, and
- city/date temperature markets are the main venue

### Classify as `Long-tail mispricing hunter` when:

- most entries are cheap tails, and
- PnL depends on a few outsized wins

### Classify as `Market maker / spread recycler` when:

- the wallet shows repeated in/out inventory management, not just directional holds

## Standard answer template

Use this exact structure:

1. `Profile`
2. `Why the win rate is high`
3. `Actual playbook`
4. `Style classification`
5. `What to copy and what not to copy`

## Important cautions

- Do not trust a single dashboard's win rate blindly.
- Record the exact observation date because different dashboards use different windows.
- Distinguish `trade win rate` from `event win rate`.
- Distinguish forecast edge from mere late-resolution carry.
