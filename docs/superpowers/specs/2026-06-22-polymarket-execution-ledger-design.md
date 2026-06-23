# Polymarket Live Execution Core + Account Ledger — Design

Date: 2026-06-22
Branch: `feat/polymarket-execution`
Status: Approved pending spec review
Revision: v2 — see §1 "Revision note", Rust dropped after empirical measurement.

## 1. Purpose

Build an idempotent, atomic order-submission path and a local account ledger
for trading Polymarket weather markets with real money, on the user's existing
wallet. This is the first of several sub-projects toward the larger goal of
letting the Weather Study / METAR strategies place real trades automatically;
this spec covers only the execution core and the ledger — strategy-to-order
wiring, risk controls, and a frontend trading UI are explicitly out of scope
here (see §2).

**Revision note (why this is v2):** v1 of this spec proposed a Rust hot path
for EIP-712 signing, on the premise (from secondhand research about a
*different* package, `py-clob-client-v2`) that Python signing costs ~1
second/order. Before writing the implementation plan, the actual dependency
this repo uses (`polymarket-client`, the official Python client, pinned in
`py-hftbacktest/pyproject.toml`) was installed and its real signing path
(`eth_account`'s `LocalAccount.sign_typed_data`) was timed directly:
**~3.4ms/signature, averaged over 20 calls**, not ~1 second. That number is
noise next to Polymarket's network round-trip (~20-85ms, per the same earlier
research) and irrelevant next to this strategy's actual decision cadence (one
METAR observation every ~30 minutes). There is no measured latency problem
for Rust to solve here, so this revision drops the Rust crate entirely:
**everything in this spec is Python**, using the official `polymarket-client`
SDK directly. Atomicity/idempotency are logic properties, not language
properties — fully achievable in Python.

This also means the existing partial live-trading layer at
`py-hftbacktest/hftbacktest/polymarket_live/` (`config.py`, `execution.py`,
`models.py`, `stream.py`, `runtime.py`) is **not replaced** — `execution.py`
already correctly wraps the official SDK's `PublicClient`/`SecureClient`
(verified directly against the installed package). This spec adds an
idempotency-and-ledger layer *in front of* it, untouched otherwise.

(The repo's separate, more elaborate live-trading framework — the `connector`
crate's `Connector`/`ConnectorBuilder` traits, `hftbacktest/src/live/`'s
iceoryx shared-memory IPC, `py-hftbacktest/src/live.rs`'s PyO3 bindings — is
real and already in this codebase, but it targets market-making-grade message
rates across CEX assets. It is not used here: irrelevant at Polymarket weather
markets' message rate, and Polymarket's CLOB is mechanically unlike a CEX
anyway, so reusing those traits would buy us nothing.)

## 2. Constraints & Non-Goals

- **No real order placement from a US IP.** Polymarket prohibits US persons /
  US-IP trading. The development machine this was built on is US-based, so
  switching `OrderRouter` from `DryRunExecutionClient` to the real
  `PolymarketExecutionClient` must not happen from this machine or any other
  US-IP environment — this is a compliance blocker, not a code-readiness
  question, and it is independent of whether the code itself is correct.
  Whoever eventually flips that config flag must do so from a non-US
  environment, and should re-confirm this constraint still applies (rules can
  change) before doing so. Everything built and tested in this plan runs only
  against `DryRunExecutionClient` or read-only public endpoints — nothing here
  required or used a US-restricted code path.
- **No strategy wiring.** Nothing in this spec decides *when* to trade based
  on METAR or Weather Study signals. That is a separate, later sub-project.
- **No risk controls** (position limits, circuit breakers, kill switch) beyond
  the atomicity guarantees below. Separate sub-project.
- **No frontend trading UI.** The existing METAR Study / Weather Study pages
  stay read-only this round. Separate sub-project.
- **Paper trading first.** The order router ships with a `DryRunExecutionClient`
  behind the same minimal interface as the real one; the first real run
  against this code must use it. Switching to real order submission is a
  config flag, not a code change, and is a separate decision the user makes
  explicitly later — this spec does not authorize live order placement.
- **Reuses existing credentials.** Wallet/API credentials come from the
  existing `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_WALLET` / etc. environment
  variables already defined in `py-hftbacktest/hftbacktest/polymarket_live/config.py`.
  No new credential-handling surface is introduced.
- **On-chain allowance is assumed sufficient.** The official SDK can submit an
  ERC20/ERC1155 approval transaction and wait for confirmation when allowance
  is insufficient (`post_order_with_allowance_recovery`) — that's a one-time,
  block-confirmation-speed operation (seconds), categorically different from
  per-order latency. This spec does not orchestrate that flow; it assumes the
  wallet already has sufficient allowance (a one-time manual setup step, out
  of scope) and treats an allowance-rejection error like any other order
  failure (logged, not retried automatically).
- **Historical backfill is in scope** for the ledger (one-time import of this
  wallet's pre-existing Polymarket activity), reusing the existing
  `research/predictparity_weather_pnl.py` data-api fetch logic rather than
  writing new fetchers.

## 3. Tech Stack

- **Python**, throughout. Order submission goes through the existing
  `py-hftbacktest/hftbacktest/polymarket_live/execution.py`
  (`PolymarketExecutionClient.place_limit_order`, already a thin, correct
  wrapper over the official SDK).
- **SQLite** for the ledger, same convention as `research/weather_data_warehouse.py`.

## 4. Architecture

```
py-hftbacktest/hftbacktest/polymarket_live/
  execution.py        # UNCHANGED — existing PolymarketExecutionClient wrapper
  models.py            # MODIFIED — PolymarketOrderIntent gets one new optional
                        #            field: idempotency_key: Optional[str] = None
  config.py / stream.py / runtime.py   # unchanged
  ledger.py            # NEW: SQLite ledger (order_intents, fills, reconciliation_log)
  order_router.py      # NEW: OrderRouter — the idempotent/atomic layer that sits
                        #      in front of PolymarketExecutionClient (or DryRun)
  dry_run.py           # NEW: DryRunExecutionClient — same minimal interface as
                        #      PolymarketExecutionClient.place_limit_order/cancel_order,
                        #      logs instead of calling Polymarket

research/
  backfill_polymarket_ledger.py   # NEW: one-time historical import for this
                                   # wallet, reusing predictparity_weather_pnl.py's
                                   # data-api fetch logic, writing into ledger.py's schema

research/data/polymarket_ledger/
  ledger.sqlite3       # gitignored, same convention as research/data/ elsewhere
```

### `OrderRouter` (Python)

```python
class OrderRouter:
    def __init__(self, execution_client, ledger): ...
    def submit(self, intent: PolymarketOrderIntent) -> OrderResult: ...
    def cancel(self, order_id: str) -> CancelResult: ...
```

`execution_client` is either the real `PolymarketExecutionClient` or
`DryRunExecutionClient` — `OrderRouter` doesn't care which; both expose
`place_limit_order(intent)` / `cancel_order(order_id)`. `intent.time_in_force`
defaults to `PolymarketTimeInForce.FOK` for anything going through
`OrderRouter` (see §6). `intent.idempotency_key`, if not supplied by the
caller, is derived deterministically from `(token_id, side, price, size)` plus
a coarse time bucket, so retries of the *same logical intent* collide on
purpose.

### `ledger.py` schema (SQLite)

- `order_intents(idempotency_key PK, token_id, side, price, size, order_type, created_at, status)`
- `fills(fill_id PK, idempotency_key FK, price, size, fee, filled_at)`
- `reconciliation_log(id PK, checked_at, token_id, local_position, remote_position, mismatch)`

## 5. Data Flow

```
(future) strategy signal
        -> PolymarketOrderIntent (idempotency_key set by caller, or auto-derived)
        -> OrderRouter.submit():
             1. ledger.find_intent(idempotency_key) -- if found, return its
                recorded result, do not submit again
             2. ledger.record_intent(intent, status="submitting")  [before call]
             3. execution_client.place_limit_order(intent)         [real or DryRun]
             4. ledger.record_result(idempotency_key, result)       [after call]
        -> (periodic, manually run) reconciliation job: diff local position
           per token_id against Polymarket's /positions and /activity,
           write any mismatch to reconciliation_log
```

Recording the intent **before** calling the SDK (step 2) is what makes crash
recovery possible: if the process dies between step 2 and step 4, the next
startup finds an `order_intents` row stuck in `"submitting"` and must resolve
it by calling `execution_client.get_order(...)` (already exposed by the
existing `PolymarketExecutionClient`) to learn the real outcome — it is never
treated as "did or didn't happen" by assumption.

## 6. Atomicity & Idempotency

- **No duplicate submission on retry/restart:** `OrderRouter.submit` always
  checks `ledger.find_intent(idempotency_key)` first. A matching non-failed
  row short-circuits to returning that recorded result.
- **No partial fills:** `OrderRouter` forces `time_in_force=FOK` regardless of
  what the caller passed, unless explicitly overridden — fill-or-kill means
  the full size fills immediately or the order is rejected outright, so the
  ledger never has to represent a half-filled position.
- **Crash recovery:** any `order_intents` row left in `"submitting"` status at
  startup is resolved by querying Polymarket's real order status before the
  router will accept a new submission for that same `idempotency_key`.
- **Ledger vs. exchange drift:** the reconciliation job only *logs* mismatches
  to `reconciliation_log` — it never silently rewrites the ledger to match
  Polymarket, or vice versa. Mismatches are for the user to review by hand.

## 7. Testing & Validation

- `OrderRouter` idempotency test: call `.submit()` twice with the same intent
  (same `idempotency_key`) against `DryRunExecutionClient`; assert the
  underlying client's `place_limit_order` was invoked exactly once.
- `OrderRouter` crash-recovery test: manually insert an `order_intents` row in
  `"submitting"` status, then construct a new `OrderRouter` and assert it
  calls `get_order` (not `place_limit_order`) for that row before accepting
  any new submission for the same key.
- `DryRunExecutionClient` end-to-end test: full intent -> `OrderRouter.submit`
  -> ledger row written with the synthetic dry-run result, with no network
  call, validating the ledger schema and flow before any real money is at
  risk.
- Historical backfill: run `backfill_polymarket_ledger.py` against the user's
  real wallet (read-only Polymarket API calls) and confirm the ledger's
  derived position per token matches Polymarket's own `/positions` output for
  that wallet today, before any new order is ever placed through this system.

## 8. Explicitly Deferred (future sub-projects)

1. Wiring METAR / Weather Study strategy signals into `PolymarketOrderIntent` creation.
2. Risk controls: position size limits, daily loss limits, a kill switch.
3. On-chain allowance/approval orchestration (currently assumed pre-existing).
4. Frontend trading UI (monitoring the ledger, manual approve/reject, eventually
   one-click or auto trading) on the existing pages.
