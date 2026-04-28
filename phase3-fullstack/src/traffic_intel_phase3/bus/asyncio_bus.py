"""Default in-process bus — zero dependencies.

Publishers drop messages into an ``asyncio.Queue``; subscribers run as
tasks that pull off the queue. Suitable for single-process deployments
(which is our default). For multi-process or multi-host, swap to the
Kafka or RabbitMQ backend via ``TRAFFIC_INTEL_BUS``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from .base import BusMessage, Handler, MessageBus  # noqa: F401 — Protocol for type hints
from .topics import Topic

log = logging.getLogger(__name__)


class AsyncioBus:
    """In-process pub/sub. One ``asyncio.Queue`` per topic."""

    def __init__(self) -> None:
        self._queues: dict[Topic, asyncio.Queue[BusMessage]] = defaultdict(asyncio.Queue)
        self._handlers: dict[Topic, list[Handler]] = defaultdict(list)
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self._handlers.clear()
        self._queues.clear()

    async def publish(self, msg: BusMessage) -> None:
        await self._queues[msg.topic].put(msg)

    def publish_threadsafe(self, msg: BusMessage) -> None:
        if not self._running or self._loop is None:
            return
        # Put-nowait is safe because asyncio.Queue is unbounded by default.
        self._loop.call_soon_threadsafe(self._queues[msg.topic].put_nowait, msg)

    async def subscribe(self, topic: Topic, handler: Handler) -> None:
        self._handlers[topic].append(handler)
        task = asyncio.create_task(self._drain(topic), name=f"bus-{topic.value}")
        self._tasks.append(task)

    async def _drain(self, topic: Topic) -> None:
        q = self._queues[topic]
        while self._running:
            try:
                msg = await q.get()
            except asyncio.CancelledError:
                return
            for h in self._handlers.get(topic, []):
                try:
                    await h(msg)
                except Exception:  # noqa: BLE001 — subscriber errors must not kill the drain
                    log.exception("subscriber for %s raised", topic.value)
