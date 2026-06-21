from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Sequence

from .execution import PolymarketExecutionClient
from .models import PolymarketEvent
from .stream import PolymarketStreamClient


EventHandler = Callable[[PolymarketEvent], Awaitable[None]]


@dataclass
class PolymarketRuntime:
    execution: PolymarketExecutionClient
    stream: PolymarketStreamClient

    async def watch_market(
        self,
        token_ids: Sequence[str],
        on_event: EventHandler,
    ) -> None:
        async for event in self.stream.stream_market(token_ids):
            await on_event(event)

    async def watch_user(
        self,
        markets: Optional[Sequence[str]],
        on_event: EventHandler,
    ) -> None:
        async for event in self.stream.stream_user(markets):
            await on_event(event)

    async def watch_market_and_user(
        self,
        token_ids: Sequence[str],
        on_event: EventHandler,
        markets: Optional[Sequence[str]] = None,
    ) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.watch_market(token_ids, on_event))
            tg.create_task(self.watch_user(markets, on_event))
