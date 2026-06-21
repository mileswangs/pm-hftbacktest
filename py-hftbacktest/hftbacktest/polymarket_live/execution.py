from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .config import PolymarketCredentials, PolymarketSettings
from .exceptions import PolymarketConfigurationError, PolymarketDependencyError
from .models import PolymarketOrderIntent, PolymarketTradeIntent


def _sdk():
    try:
        from polymarket import PublicClient, SecureClient
        from polymarket.models import ApiKeyCreds
    except ImportError as exc:
        raise PolymarketDependencyError(
            "Install the optional 'polymarket-live' dependencies to use live trading."
        ) from exc
    return PublicClient, SecureClient, ApiKeyCreds


@dataclass
class PolymarketExecutionClient:
    settings: PolymarketSettings

    def __post_init__(self) -> None:
        self._secure_client = None
        self._public_client = None

    def close(self) -> None:
        if self._secure_client is not None:
            self._secure_client.close()
            self._secure_client = None
        if self._public_client is not None:
            self._public_client.close()
            self._public_client = None

    def ensure_credentials(self) -> PolymarketCredentials:
        client = self._get_secure_client()
        creds = client._ctx.credentials  # Intentional wrapper access to keep setup centralized.
        return PolymarketCredentials(
            key=creds.key,
            secret=creds.secret,
            passphrase=creds.passphrase,
        )

    def get_order_book(self, token_id: str):
        return self._get_public_client().get_order_book(token_id=token_id)

    def get_last_trade_price(self, token_id: str):
        return self._get_public_client().get_last_trade_price(token_id=token_id)

    def list_open_orders(self, token_id: Optional[str] = None, market: Optional[str] = None) -> list:
        paginator = self._get_secure_client().list_open_orders(token_id=token_id, market=market)
        return list(paginator)

    def get_order(self, order_id: str):
        return self._get_secure_client().get_order(order_id=order_id)

    def place_limit_order(self, intent: PolymarketOrderIntent):
        client = self._get_secure_client()
        return client.place_limit_order(
            token_id=intent.token_id,
            side=intent.side.value,
            price=intent.price,
            size=intent.size,
            order_type=intent.time_in_force.value,
            builder_code=intent.builder_code,
        )

    def place_market_order(self, intent: PolymarketTradeIntent):
        client = self._get_secure_client()
        kwargs = {
            "token_id": intent.token_id,
            "side": intent.side.value,
            "order_type": intent.time_in_force.value,
            "builder_code": intent.builder_code,
        }
        if intent.amount is not None:
            kwargs["amount"] = intent.amount
        if intent.shares is not None:
            kwargs["shares"] = intent.shares
        if intent.max_spend is not None:
            kwargs["max_spend"] = intent.max_spend
        if intent.max_price is not None:
            kwargs["max_price"] = intent.max_price
        if intent.min_price is not None:
            kwargs["min_price"] = intent.min_price
        return client.place_market_order(**kwargs)

    def cancel_order(self, order_id: str):
        return self._get_secure_client().cancel_order(order_id=order_id)

    def cancel_orders(self, order_ids: Sequence[str]):
        return self._get_secure_client().cancel_orders(order_ids=order_ids)

    def cancel_all(self):
        return self._get_secure_client().cancel_all()

    def cancel_market_orders(
        self,
        market: Optional[str] = None,
        token_id: Optional[str] = None,
    ):
        return self._get_secure_client().cancel_market_orders(market=market, token_id=token_id)

    def _get_public_client(self):
        if self._public_client is None:
            PublicClient, _, _ = _sdk()
            self._public_client = PublicClient()
        return self._public_client

    def _get_secure_client(self):
        if self._secure_client is not None:
            return self._secure_client

        _, SecureClient, ApiKeyCreds = _sdk()
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

        self._secure_client = SecureClient.create(
            private_key=self.settings.private_key,
            wallet=self.settings.wallet,
            credentials=credentials,
        )
        return self._secure_client
