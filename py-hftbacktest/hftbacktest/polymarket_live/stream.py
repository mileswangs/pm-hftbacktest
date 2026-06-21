from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Sequence

from .config import PolymarketSettings
from .exceptions import PolymarketConfigurationError, PolymarketDependencyError
from .models import PolymarketEvent, normalize_market_event, normalize_user_event


def _async_sdk():
    try:
        from polymarket import AsyncPublicClient, AsyncSecureClient
        from polymarket.models import ApiKeyCreds
        from polymarket.streams import MarketSpec, UserSpec
    except ImportError as exc:
        raise PolymarketDependencyError(
            "Install the optional 'polymarket-live' dependencies to use realtime streams."
        ) from exc
    return AsyncPublicClient, AsyncSecureClient, ApiKeyCreds, MarketSpec, UserSpec


@dataclass
class PolymarketStreamClient:
    settings: PolymarketSettings

    async def stream_market(
        self,
        token_ids: Sequence[str],
    ) -> AsyncIterator[PolymarketEvent]:
        AsyncPublicClient, _, _, MarketSpec, _ = _async_sdk()
        client = AsyncPublicClient()
        handle = None
        try:
            handle = await client.subscribe(
                MarketSpec(
                    token_ids=tuple(token_ids),
                    custom_feature_enabled=self.settings.custom_market_features,
                )
            )
            async for event in handle:
                yield normalize_market_event(event)
        finally:
            if handle is not None:
                await handle.close()
            await client.close()

    async def stream_user(
        self,
        markets: Optional[Sequence[str]] = None,
    ) -> AsyncIterator[PolymarketEvent]:
        _, AsyncSecureClient, ApiKeyCreds, _, UserSpec = _async_sdk()
        credentials = None
        if self.settings.credentials is not None:
            credentials = ApiKeyCreds(
                key=self.settings.credentials.key,
                secret=self.settings.credentials.secret,
                passphrase=self.settings.credentials.passphrase,
            )
        elif not self.settings.allow_credential_derivation:
            raise PolymarketConfigurationError(
                "No API credentials were provided and credential derivation is disabled."
            )
        client = await AsyncSecureClient.create(
            private_key=self.settings.private_key,
            wallet=self.settings.wallet,
            credentials=credentials,
        )
        handle = None
        try:
            handle = await client.subscribe(
                UserSpec(markets=tuple(markets) if markets is not None else None)
            )
            async for event in handle:
                yield normalize_user_event(event)
        finally:
            if handle is not None:
                await handle.close()
            await client.close()
