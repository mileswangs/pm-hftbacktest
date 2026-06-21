from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from .exceptions import PolymarketConfigurationError


def _read_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise PolymarketConfigurationError("Invalid boolean value: %s" % raw)


@dataclass(frozen=True)
class PolymarketCredentials:
    key: str
    secret: str
    passphrase: str

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        prefix: str = "POLYMARKET",
    ) -> Optional["PolymarketCredentials"]:
        values = env or os.environ
        key = values.get("%s_API_KEY" % prefix)
        secret = values.get("%s_API_SECRET" % prefix)
        passphrase = values.get("%s_API_PASSPHRASE" % prefix)
        if not any((key, secret, passphrase)):
            return None
        if not all((key, secret, passphrase)):
            raise PolymarketConfigurationError(
                "Incomplete Polymarket API credentials in environment."
            )
        return cls(key=key, secret=secret, passphrase=passphrase)


@dataclass(frozen=True)
class PolymarketSettings:
    private_key: str
    wallet: Optional[str] = None
    credentials: Optional[PolymarketCredentials] = None
    allow_credential_derivation: bool = True
    custom_market_features: bool = True

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        prefix: str = "POLYMARKET",
    ) -> "PolymarketSettings":
        values = env or os.environ
        private_key = values.get("%s_PRIVATE_KEY" % prefix, "").strip()
        if not private_key:
            raise PolymarketConfigurationError(
                "%s_PRIVATE_KEY is required for Polymarket trading." % prefix
            )
        wallet = values.get("%s_WALLET" % prefix)
        credentials = PolymarketCredentials.from_env(values, prefix=prefix)
        allow_derive = _read_bool(
            values.get("%s_ALLOW_CREDENTIAL_DERIVATION" % prefix),
            True,
        )
        custom_market_features = _read_bool(
            values.get("%s_CUSTOM_MARKET_FEATURES" % prefix),
            True,
        )
        return cls(
            private_key=private_key,
            wallet=wallet.strip() if wallet else None,
            credentials=credentials,
            allow_credential_derivation=allow_derive,
            custom_market_features=custom_market_features,
        )
