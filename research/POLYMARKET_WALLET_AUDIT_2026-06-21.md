# Polymarket Wallet Audit

Date: 2026-06-21

Inputs provided:

- api key: `019eeb7a-5c9d-7bdf-8063-c307f1d17886`
- wallet address: `0x0883520109fa4b7d4a38a6a67e029b2bd0f8cb3e`
- builder code: `0x7fb6530b9a4bf7dc89d298579209a1d24cc581e6823870ecbe505feb87486f3c`
- private key: provided locally by user

Derived signer address from the provided private key:

- `0xA301aA66aa87AC64f07D3508CbB3619fC59689bd`

Derived official wallet candidates from that signer under the current Polymarket production derivation config:

- EOA: `0xA301aA66aa87AC64f07D3508CbB3619fC59689bd`
- POLY_PROXY: `0x1bed1BDd1B884526Fa605e6a54565d55019D4CfA`
- GNOSIS_SAFE: `0xeB5f0Bfd022F92542d188801Bc9e8ac4608643fb`
- DEPOSIT_WALLET (UUPS): `0x1E11F76cDe1eC33E8c4114697Ff308481a95A859`
- DEPOSIT_WALLET (Beacon): `0x3dFf5C5953A8AD35046664C279F443F692C63e39`

Result:

- The provided wallet address does not match the signer address.
- It also does not match the currently derived proxy, safe, or deposit-wallet candidates.
- The API key derived from the provided private key also differs from the API key the user supplied.
- The API credentials successfully derived from the provided private key therefore appear to be tied to the signer address, not provably to the provided wallet address.

Operational implication:

- Read-only market data configuration is fine.
- Real trading may fail until the user confirms that the private key and wallet address belong to the same Polymarket account flow.
