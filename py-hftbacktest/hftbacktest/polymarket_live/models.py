from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence, Union


class PolymarketSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PolymarketTimeInForce(str, Enum):
    GTC = "GTC"
    FOK = "FOK"
    FAK = "FAK"
    GTD = "GTD"


class PolymarketEventKind(str, Enum):
    BOOK = "book"
    PRICE_CHANGE = "price_change"
    LAST_TRADE = "last_trade_price"
    TICK_SIZE_CHANGE = "tick_size_change"
    BEST_BID_ASK = "best_bid_ask"
    MARKET_RESOLVED = "market_resolved"
    USER_ORDER = "user_order"
    USER_TRADE = "user_trade"


Number = Union[str, int, float, Decimal]


def _decimal(value: Optional[Number]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class PolymarketBookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class PolymarketBookSnapshot:
    market_id: str
    token_id: str
    bids: Sequence[PolymarketBookLevel]
    asks: Sequence[PolymarketBookLevel]
    timestamp_ms: Optional[int]
    tick_size: Optional[Decimal]
    min_order_size: Optional[Decimal]
    last_trade_price: Optional[Decimal]


@dataclass(frozen=True)
class PolymarketOrderIntent:
    token_id: str
    side: PolymarketSide
    price: Decimal
    size: Decimal
    time_in_force: PolymarketTimeInForce = PolymarketTimeInForce.GTC
    builder_code: Optional[str] = None


@dataclass(frozen=True)
class PolymarketTradeIntent:
    token_id: str
    side: PolymarketSide
    amount: Optional[Decimal] = None
    shares: Optional[Decimal] = None
    max_spend: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    min_price: Optional[Decimal] = None
    time_in_force: PolymarketTimeInForce = PolymarketTimeInForce.FAK
    builder_code: Optional[str] = None


@dataclass(frozen=True)
class PolymarketUserOrderUpdate:
    order_id: str
    market_id: str
    token_id: str
    side: PolymarketSide
    price: Decimal
    original_size: Decimal
    matched_size: Decimal
    event_type: str
    status: Optional[str]
    timestamp_ms: Optional[int]


@dataclass(frozen=True)
class PolymarketUserTradeUpdate:
    trade_id: str
    order_id: str
    market_id: str
    token_id: str
    side: PolymarketSide
    price: Decimal
    size: Decimal
    status: str
    timestamp_ms: Optional[int]


@dataclass(frozen=True)
class PolymarketEvent:
    kind: PolymarketEventKind
    payload: object


def normalize_market_event(event: object) -> PolymarketEvent:
    event_type = getattr(event, "type", None)
    payload = getattr(event, "payload", event)
    if event_type == "book":
        bids = tuple(
            PolymarketBookLevel(price=_decimal(level.price), size=_decimal(level.size))
            for level in payload.bids
        )
        asks = tuple(
            PolymarketBookLevel(price=_decimal(level.price), size=_decimal(level.size))
            for level in payload.asks
        )
        snapshot = PolymarketBookSnapshot(
            market_id=payload.market,
            token_id=str(payload.token_id),
            bids=bids,
            asks=asks,
            timestamp_ms=payload.timestamp,
            tick_size=_decimal(getattr(payload, "tick_size", None)),
            min_order_size=_decimal(getattr(payload, "min_order_size", None)),
            last_trade_price=_decimal(getattr(payload, "last_trade_price", None)),
        )
        return PolymarketEvent(kind=PolymarketEventKind.BOOK, payload=snapshot)
    if event_type == "price_change":
        return PolymarketEvent(kind=PolymarketEventKind.PRICE_CHANGE, payload=payload)
    if event_type == "last_trade_price":
        return PolymarketEvent(kind=PolymarketEventKind.LAST_TRADE, payload=payload)
    if event_type == "tick_size_change":
        return PolymarketEvent(kind=PolymarketEventKind.TICK_SIZE_CHANGE, payload=payload)
    if event_type == "best_bid_ask":
        return PolymarketEvent(kind=PolymarketEventKind.BEST_BID_ASK, payload=payload)
    if event_type == "market_resolved":
        return PolymarketEvent(kind=PolymarketEventKind.MARKET_RESOLVED, payload=payload)
    raise ValueError("Unsupported market event type: %r" % (event_type,))


def normalize_user_event(event: object) -> PolymarketEvent:
    event_type = getattr(event, "type", None)
    payload = getattr(event, "payload", event)
    if event_type == "order":
        order = PolymarketUserOrderUpdate(
            order_id=payload.id,
            market_id=payload.market,
            token_id=str(payload.token_id),
            side=PolymarketSide(str(payload.side).upper()),
            price=_decimal(payload.price),
            original_size=_decimal(payload.original_size),
            matched_size=_decimal(payload.size_matched),
            event_type=payload.order_event_type,
            status=getattr(payload, "status", None),
            timestamp_ms=payload.timestamp,
        )
        return PolymarketEvent(kind=PolymarketEventKind.USER_ORDER, payload=order)
    if event_type == "trade":
        trade = PolymarketUserTradeUpdate(
            trade_id=payload.id,
            order_id=payload.taker_order_id,
            market_id=payload.market,
            token_id=str(payload.token_id),
            side=PolymarketSide(str(payload.side).upper()),
            price=_decimal(payload.price),
            size=_decimal(payload.size),
            status=payload.status,
            timestamp_ms=payload.timestamp,
        )
        return PolymarketEvent(kind=PolymarketEventKind.USER_TRADE, payload=trade)
    raise ValueError("Unsupported user event type: %r" % (event_type,))
