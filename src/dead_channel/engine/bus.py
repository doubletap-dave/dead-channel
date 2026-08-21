"""Async pub/sub bus fanning engine events out to SSE subscribers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self

from dead_channel.core.events import Event

DEFAULT_QUEUE_MAXSIZE = 1000


class Subscription(AbstractAsyncContextManager["Subscription"]):
    def __init__(self, bus: EventBus, queue_maxsize: int) -> None:
        self._bus = bus
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=queue_maxsize)
        self._active = True

    def close(self) -> None:
        if not self._active:
            return
        self._active = False
        self._bus._unsubscribe(self)
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(None)

    def offer(self, event: Event) -> None:
        # Drop-oldest: a stalled SSE consumer must never block the engine.
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(event)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        if not self._active and self._queue.empty():
            raise StopAsyncIteration
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class EventBus:
    def __init__(self, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._maxsize = queue_maxsize
        self._subscribers: list[Subscription] = []

    def publish(self, event: Event) -> None:
        for subscriber in list(self._subscribers):
            subscriber.offer(event)

    def subscribe(self) -> Subscription:
        subscription = Subscription(self, self._maxsize)
        self._subscribers.append(subscription)
        return subscription

    def subscription(self) -> Subscription:
        return self.subscribe()

    def _unsubscribe(self, subscription: Subscription) -> None:
        self._subscribers.remove(subscription)
