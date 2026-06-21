# Polymarket Live Integration

This repo now includes a local Polymarket integration layer under `py-hftbacktest/hftbacktest/polymarket_live/`.

## Design

- `config.py`
  - Loads wallet and API credential settings from environment.
- `execution.py`
  - Wraps the official Polymarket Python SDK sync clients for order placement, cancelation, and public reads.
- `stream.py`
  - Wraps the official async market and user subscriptions.
- `models.py`
  - Defines repo-local order intents and normalized events so strategy code is not coupled to SDK objects.
- `runtime.py`
  - Provides a small orchestration layer for concurrent market and user event handling.
- `tools/polymarket_live/`
  - Node-based execution path using the official CLOB client with explicit deposit-wallet settings.

## Environment

Set these before live usage:

```bash
export POLYMARKET_PRIVATE_KEY=0x...
export POLYMARKET_WALLET=0x...   # optional; defaults to the SDK-derived Polymarket wallet
export POLYMARKET_API_KEY=...
export POLYMARKET_API_SECRET=...
export POLYMARKET_API_PASSPHRASE=...
```

For deposit-wallet mode, also set:

```bash
export POLYMARKET_SIGNER_ADDRESS=0x...
export POLYMARKET_DEPOSIT_WALLET_ADDRESS=0x...
export POLYMARKET_SIGNATURE_TYPE=3
```

If API credentials are omitted, the wrapper lets the official SDK derive them unless you disable that with:

```bash
export POLYMARKET_ALLOW_CREDENTIAL_DERIVATION=0
```

## Install

The live layer uses the optional dependency group in `py-hftbacktest/pyproject.toml`:

```bash
pip install -e ./py-hftbacktest[polymarket-live]
```

## Smoke Commands

```bash
python3 research/polymarket_live_smoke.py book --token-id <TOKEN_ID>
python3 research/polymarket_live_smoke.py stream --token-id <TOKEN_ID>
python3 research/polymarket_live_smoke.py limit-buy --token-id <TOKEN_ID> --price 0.10 --size 5
```

Use a dedicated wallet and start with tiny size.

## Node Path For Deposit Wallets

This machine currently has Python 3.8, while the official Python SDK requires Python 3.11+.
For immediate local execution, use the Node client under `tools/polymarket_live/`.

Install once:

```bash
cd tools/polymarket_live
npm install
```

Run:

```bash
node ./src/cli.mjs derive-creds
node ./src/cli.mjs book <TOKEN_ID>
node ./src/cli.mjs open-orders
```

The Node client is configured explicitly with:

- `funderAddress = POLYMARKET_DEPOSIT_WALLET_ADDRESS`
- `signatureType = 3`
- `builderCode = POLYMARKET_BUILDER_CODE` when present
