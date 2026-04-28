"""Pluggable message bus for cross-module event fanout.

Default backend is in-process asyncio (zero dependencies). Kafka (aiokafka)
and RabbitMQ (aio-pika) backends are optional extras — the handbook
(§9.3) lists them as recommended messaging layers. Both are selectable
at runtime via the ``TRAFFIC_INTEL_BUS`` environment variable.

See ``bus/topics.py`` for the canonical topic catalog that all three
backends share — so swapping backends is a config change, not a code
change.
"""

from .base import BusMessage, MessageBus
from .factory import get_bus
from .topics import Topic

__all__ = ["BusMessage", "MessageBus", "Topic", "get_bus"]
