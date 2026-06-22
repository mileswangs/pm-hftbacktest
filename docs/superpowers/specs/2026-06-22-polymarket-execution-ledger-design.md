# Polymarket Live Execution Core + Account Ledger — Design

Date: 2026-06-22
Branch: `feat/polymarket-execution`
Status: Approved pending spec review

## 1. Purpose

Build the foundational low-latency execution core and a local, idempotent
account ledger for trading Polymarket weather markets with real money, on the
user's existing wallet. This is the first of several sub-projects toward the
larger goal of letting the Weather Study / METAR strategies place real trades
automatically; this spec covers only the execution core and the ledger —
strategy-to-order wiring, risk controls, and a frontend trading UI are
explicitly out of scope here (see §2).

The repo (`pm-hftbacktest`, a fork of `nkaz001/hftbacktest`) already ships a
mature live-trading framework for centralized exchanges: the `connector` crate
defines `Connector`/`ConnectorBuilder` traits (implemented for Binance Futures,
Bybit), `hftbacktest/src/live/` runs the live bot loop over a shared-memory
(`iceoryx`) IPC channel, and `py-hftbacktest/src/live.rs` exposes
`submit_buy_order`/`submit_sell_order`/`cancel`/`position` to Python via PyO3.
That machinery targets market-making-grade message rates across many assets.
Polymarket weather markets trade at a tiny fraction of that rate (at most a
handful of orders per day), and Polymarket's CLOB is mechanically different
from a CEX (EIP-712-signed orders, Polygon settlement, conditional-token
markets) — so this design borrows the *naming/interface spirit* of the
`Connector` trait for consistency, but does **not** reuse the iceoryx
shared-memory IPC layer, which would be unjustified complexity at this
message rate.

There is also an existing, partial live-trading layer at
`py-hftbacktest/hftbacktest/polymarket_live/` (`config.py`, `execution.py`,
`models.py`, `stream.py`, `runtime.py`) that wraps the **official Python CLOB
SDK**. Per separate research this round, that official Python client's
EIP-712 order signing costs roughly 1 second per order — a real, specific,
avoidable bottleneck, not a generic "Python is slow" problem. This design
replaces only that signing/submission path with a new Rust core, keeping the
rest of the existing module (credentials, models, streaming) as-is.

## 2. Constraints & Non-Goals

- **No strategy wiring.** Nothing in this spec decides *when* to trade based
  on METAR or Weather Study signals. That is a separate, later sub-project.
- **No risk controls** (position limits, circuit breakers, kill switch) beyond
  the atomicity guarantees below. Separate sub-project.
- **No frontend trading UI.** The existing METAR Study / Weather Study pages
  stay read-only this round. Separate sub-project.
- **Paper trading first.** The execution client ships with a `DryRunClient`
  behind the exact same interface as the real client; the first real run
  against this code must use it. Switching to real order submission is a
  config flag, not a code change, and is a separate decision the user makes
  explicitly later — this spec does not authorize live order placement.
- **Reuses existing credentials.** Wallet/API credentials come from the
  existing `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_WALLET` / etc. environment
  variables already defined in `py-hftbacktest/hftbacktest/polymarket_live/config.py`.
  No new credential-handling surface is introduced.
- **Historical backfill is in scope** for the ledger (one-time import of this
  wallet's pre-existing Polymarket activity), reusing the existing
  `research/predictparity_weather_*.py` data-api fetchers rather than writing
  new ones.

## 3. Tech Stack

- **Rust** for the signing + order submission/cancellation hot path, exposed
  to Python via **PyO3** as a direct in-process extension module — no IPC, no
  separate process, no network hop beyond the actual HTTPS call to Polymarket.
  This mirrors the existing `py-hftbacktest` pattern of exposing a Rust core
  to Python (already used for the backtest engine itself), just applied to a
  new crate.
- **Python** for the ledger, reconciliation, and historical backfill — none of
  this is latency-sensitive, and it sits naturally alongside the existing
  `polymarket_live` package and `research/` scripts it depends on.
- **SQLite** for the ledger, same convention as `research/weather_data_warehouse.py`.

## 4. Architecture

```
polymarket-execution/                  # new Rust crate, repo-root workspace member
  Cargo.toml
  src/
    lib.rs            # #[pymodule]; exposes PolymarketExecutionClient + DryRunClient
    signing.rs         # EIP-712 order struct + secp256k1 signing
    client.rs           # CLOB REST: submit_order / cancel_order / get_order_status
    idempotency.rs       # idempotency-key derivation + local "already-sent" check

py-hftbacktest/hftbacktest/polymarket_live/
  execution.py        # MODIFIED: delegates signing/submission to the new Rust
                       #           client instead of the official SDK's slow path
  ledger.py           # NEW: SQLite ledger (order_intents, fills, reconciliation_log)
  config.py            # unchanged — existing env-var credential loading
  models.py / stream.py / runtime.py   # unchanged

research/
  backfill_polymarket_ledger.py   # NEW: one-time historical import for this
                                   # wallet, reusing predictparity_weather_pnl.py's
                                   # data-api fetch logic, writing into ledger.py's schema

research/data/polymarket_ledger/
  ledger.sqlite3       # gitignored, same convention as research/data/ elsewhere
```

### `PolymarketExecutionClient` (Rust, via PyO3)

```
submit_order(intent: OrderIntent) -> OrderResult
cancel_order(order_id: str) -> CancelResult
get_order_status(order_id: str) -> OrderStatus
```

`OrderIntent` carries: market/token id, side, price, size, order type
(default **FOK** — fill-or-kill, see §6), and an `idempotency_key`. The
`DryRunClient` implements the identical three methods but only logs and
returns a synthetic `OrderResult`, never calling Polymarket.

### `ledger.py` schema (SQLite)

- `order_intents(idempotency_key PK, market, token_id, side, price, size, order_type, created_at, status)`
- `fills(fill_id PK, idempotency_key FK, price, size, fee, filled_at)`
- `reconciliation_log(id PK, checked_at, market, local_position, remote_position, mismatch)`

## 5. Data Flow

```
(future) strategy signal
        -> OrderIntent (idempotency_key derived from strategy_id + market + bucket + signal_ts)
        -> ledger.record_intent()                  [Python, before submission]
        -> PolymarketExecutionClient.submit_order() [Rust, signs + POSTs, or DryRun logs]
        -> ledger.record_result()                   [Python, after response]
        -> (periodic) reconciliation job             diffs local position vs
                                                       Polymarket /positions and /activity,
                                                       writes mismatches to reconciliation_log
```

The intent is recorded **before** submission so that a crash between "intent
recorded" and "response received" is recoverable: on restart, anything in
`order_intents` without a matching terminal status is checked against
Polymarket's real order status before any retry — never blindly resubmitted.

## 6. Atomicity & Idempotency

- **No duplicate submission on retry/restart:** `submit_order` first checks
  `ledger.order_intents` for the given `idempotency_key`. If a non-failed
  entry already exists, it returns that recorded result instead of
  submitting again.
- **No partial fills:** orders default to **FOK** (fill-or-kill) — either the
  full size fills immediately or the order is rejected outright. No
  half-filled position is left dangling.
- **Crash recovery:** if the process dies after sending the HTTP request but
  before recording the response, the next startup reconciles any
  `order_intents` row stuck in a non-terminal state by querying Polymarket's
  order-status endpoint directly — the local ledger never assumes an outcome
  it hasn't confirmed.
- **Ledger vs. exchange drift:** the reconciliation job is the only place
  mismatches are surfaced, and it only *logs* them — it does not silently
  auto-correct the ledger. Mismatches are for the user to review.

## 7. Testing & Validation

- Rust unit tests for `signing.rs`: sign-then-recover round trip checks
  (self-consistency, since we don't have official EIP-712 test vectors yet).
- Idempotency test: submit the same `OrderIntent` twice (simulating a
  retry-after-crash), assert only one real submission occurs.
- `DryRunClient` end-to-end test: full intent -> ledger -> "submission" ->
  ledger-update path, with no network call, to validate the ledger schema and
  flow before any real money is at risk.
- Historical backfill: run `backfill_polymarket_ledger.py` against the user's
  real wallet (read-only Polymarket API calls) and confirm the ledger's
  reconciliation view matches Polymarket's own `/positions` output for that
  wallet today, before any new order is ever placed through this system.

## 8. Explicitly Deferred (future sub-projects)

1. Wiring METAR / Weather Study strategy signals into `OrderIntent` creation.
2. Risk controls: position size limits, daily loss limits, a kill switch.
3. Frontend trading UI (monitoring the ledger, manual approve/reject, eventually
   one-click or auto trading) on the existing pages.
