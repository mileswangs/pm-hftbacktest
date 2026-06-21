from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from hftbacktest.polymarket_live import (
    PolymarketExecutionClient,
    PolymarketOrderIntent,
    PolymarketRuntime,
    PolymarketSettings,
    PolymarketSide,
    PolymarketStreamClient,
    PolymarketTimeInForce,
)


async def _stream(token_id: str) -> None:
    settings = PolymarketSettings.from_env()
    stream = PolymarketStreamClient(settings)
    count = 0
    async for event in stream.stream_market([token_id]):
        print(event.kind.value, event.payload)
        count += 1
        if count >= 5:
            break


def _book(token_id: str) -> None:
    settings = PolymarketSettings.from_env()
    client = PolymarketExecutionClient(settings)
    try:
        book = client.get_order_book(token_id)
        print(book)
        print("Derived credentials:", client.ensure_credentials())
    finally:
        client.close()


def _limit_buy(token_id: str, price: str, size: str) -> None:
    settings = PolymarketSettings.from_env()
    client = PolymarketExecutionClient(settings)
    try:
        resp = client.place_limit_order(
            PolymarketOrderIntent(
                token_id=token_id,
                side=PolymarketSide.BUY,
                price=Decimal(price),
                size=Decimal(size),
                time_in_force=PolymarketTimeInForce.GTC,
            )
        )
        print(resp)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Polymarket live-integration smoke runner")
    sub = parser.add_subparsers(dest="command", required=True)

    book = sub.add_parser("book")
    book.add_argument("--token-id", required=True)

    stream = sub.add_parser("stream")
    stream.add_argument("--token-id", required=True)

    buy = sub.add_parser("limit-buy")
    buy.add_argument("--token-id", required=True)
    buy.add_argument("--price", required=True)
    buy.add_argument("--size", required=True)

    args = parser.parse_args()
    if args.command == "book":
        _book(args.token_id)
    elif args.command == "stream":
        asyncio.run(_stream(args.token_id))
    elif args.command == "limit-buy":
        _limit_buy(args.token_id, args.price, args.size)


if __name__ == "__main__":
    main()
