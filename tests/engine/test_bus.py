import asyncio

import pytest

from dead_channel.core.events import make_event
from dead_channel.engine.bus import EventBus


async def test_fan_out_delivers_every_event_in_order_to_each_subscriber() -> None:
    bus = EventBus()
    sent = [make_event("world.ticked", seq=i, turn=i) for i in range(1, 4)]
    async with bus.subscription() as alpha, bus.subscription() as beta:
        for event in sent:
            bus.publish(event)
        assert [await anext(alpha) for _ in sent] == sent
        assert [await anext(beta) for _ in sent] == sent


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    first = make_event("run.started", seq=1, turn=0)
    async with bus.subscription() as sub:
        bus.publish(first)
        assert await anext(sub) == first
    bus.publish(make_event("run.ended", seq=2, turn=1))
    with pytest.raises(StopAsyncIteration):
        await anext(sub)


async def test_close_drains_pending_events_before_stopping() -> None:
    bus = EventBus()
    sent = [make_event("world.ticked", seq=i, turn=i) for i in (1, 2)]
    async with bus.subscription() as sub:
        for event in sent:
            bus.publish(event)
    assert [await anext(sub) for _ in sent] == sent
    with pytest.raises(StopAsyncIteration):
        await anext(sub)


async def test_close_wakes_pending_anext_with_stop() -> None:
    bus = EventBus()
    sub = bus.subscription()
    pending = asyncio.create_task(anext(sub))
    await asyncio.sleep(0)
    assert not pending.done()
    sub.close()
    with pytest.raises(StopAsyncIteration):
        await pending


async def test_full_queue_drops_oldest_to_keep_publish_nonblocking() -> None:
    bus = EventBus(queue_maxsize=2)
    async with bus.subscription() as sub:
        for i in range(1, 4):
            bus.publish(make_event("world.ticked", seq=i, turn=i))
        assert [(await anext(sub)).seq for _ in range(2)] == [2, 3]
    with pytest.raises(StopAsyncIteration):
        await anext(sub)
