"""Pick a backend at runtime from ``TRAFFIC_INTEL_BUS``."""

from __future__ import annotations

import logging
import os

from .asyncio_bus import AsyncioBus
from .base import MessageBus

log = logging.getLogger(__name__)

_SINGLETON: MessageBus | None = None


def get_bus() -> MessageBus:
    """Return the process-wide bus singleton.

    Reads ``TRAFFIC_INTEL_BUS`` once:
        - unset or "asyncio" → in-process (default)
        - "kafka"            → aiokafka
        - "rabbitmq"         → aio-pika
    """
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON

    choice = os.environ.get("TRAFFIC_INTEL_BUS", "asyncio").strip().lower()
    if choice in ("", "asyncio", "inproc", "memory"):
        _SINGLETON = AsyncioBus()
    elif choice == "kafka":
        from .kafka_bus import KafkaBus
        _SINGLETON = KafkaBus()
    elif choice == "rabbitmq":
        from .rabbitmq_bus import RabbitMQBus
        _SINGLETON = RabbitMQBus()
    else:
        log.warning("unknown TRAFFIC_INTEL_BUS=%r, falling back to asyncio", choice)
        _SINGLETON = AsyncioBus()
    return _SINGLETON


def reset_bus_singleton() -> None:
    """Test-only: drop the singleton so the next ``get_bus()`` builds fresh."""
    global _SINGLETON
    _SINGLETON = None
