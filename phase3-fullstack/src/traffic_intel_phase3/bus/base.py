"""MessageBus protocol + message envelope."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, runtime_checkable

from .topics import Topic

Handler = Callable[["BusMessage"], Awaitable[None]]


@dataclass(slots=True)
class BusMessage:
    """Envelope every backend puts on the wire.

    ``ts_unix`` is stamped at publish time if the caller omits it. ``payload``
    must be JSON-serialisable — backends serialise with ``json.dumps``.
    """

    topic: Topic
    payload: dict
    site_id: str = "wadi_saqra"
    producer: str = "traffic_intel"
    ts_unix: float = field(default_factory=time.time)


@runtime_checkable
class MessageBus(Protocol):
    """Minimal pub/sub surface shared by every backend."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def publish(self, msg: BusMessage) -> None: ...
    def publish_threadsafe(self, msg: BusMessage) -> None:
        """Enqueue from a non-async context (e.g. tracker daemon thread)."""
        ...
    async def subscribe(self, topic: Topic, handler: Handler) -> None: ...
