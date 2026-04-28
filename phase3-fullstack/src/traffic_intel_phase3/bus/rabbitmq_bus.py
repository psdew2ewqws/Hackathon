"""Optional RabbitMQ backend (aio-pika).

Install with ``pip install 'traffic-intel[rabbitmq]'`` or ``pip install aio-pika``.
Select at runtime with ``TRAFFIC_INTEL_BUS=rabbitmq``.

Topology: one topic exchange named ``traffic-intel`` with routing keys =
topic names. Each subscriber gets its own durable queue bound to the topic.

Connection env vars:
    TRAFFIC_INTEL_RABBITMQ_URL  — default "amqp://guest:guest@localhost/"
    TRAFFIC_INTEL_RABBITMQ_EXCHANGE  — default "traffic-intel"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict

from .base import BusMessage, Handler
from .topics import Topic

log = logging.getLogger(__name__)

_EXCHANGE_DEFAULT = "traffic-intel"


class RabbitMQBus:
    def __init__(self) -> None:
        try:
            import aio_pika  # noqa: F401
        except ImportError as e:  # pragma: no cover — optional extra
            raise ImportError(
                "RabbitMQBus requires the 'aio-pika' package. "
                "Install with `pip install aio-pika` or `pip install 'traffic-intel[rabbitmq]'`."
            ) from e

        self._url = os.environ.get("TRAFFIC_INTEL_RABBITMQ_URL", "amqp://guest:guest@localhost/")
        self._exchange_name = os.environ.get("TRAFFIC_INTEL_RABBITMQ_EXCHANGE", _EXCHANGE_DEFAULT)
        self._conn = None
        self._channel = None
        self._exchange = None
        self._handlers: dict[Topic, list[Handler]] = defaultdict(list)
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    async def start(self) -> None:
        import aio_pika
        self._loop = asyncio.get_running_loop()
        self._conn = await aio_pika.connect_robust(self._url)
        self._channel = await self._conn.channel()
        self._exchange = await self._channel.declare_exchange(
            self._exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
        )
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._channel is not None:
            await self._channel.close()
        if self._conn is not None:
            await self._conn.close()
        self._tasks.clear()
        self._channel = None
        self._conn = None

    async def publish(self, msg: BusMessage) -> None:
        import aio_pika
        if self._exchange is None:
            raise RuntimeError("RabbitMQBus.start() must be called before publish()")
        body = json.dumps({
            "payload": msg.payload,
            "site_id": msg.site_id,
            "producer": msg.producer,
            "ts_unix": msg.ts_unix,
        }).encode("utf-8")
        await self._exchange.publish(
            aio_pika.Message(body=body, content_type="application/json"),
            routing_key=msg.topic.value,
        )

    def publish_threadsafe(self, msg: BusMessage) -> None:
        if not self._running or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.publish(msg), self._loop)

    async def subscribe(self, topic: Topic, handler: Handler) -> None:
        if self._channel is None or self._exchange is None:
            raise RuntimeError("RabbitMQBus.start() must be called before subscribe()")
        self._handlers[topic].append(handler)
        queue = await self._channel.declare_queue(
            f"traffic-intel.{topic.value}", durable=True
        )
        await queue.bind(self._exchange, routing_key=topic.value)
        task = asyncio.create_task(self._drain(topic, queue), name=f"rabbit-{topic.value}")
        self._tasks.append(task)

    async def _drain(self, topic: Topic, queue) -> None:
        try:
            async with queue.iterator() as it:
                async for message in it:
                    async with message.process():
                        body = json.loads(message.body.decode("utf-8"))
                        msg = BusMessage(
                            topic=topic,
                            payload=body.get("payload", {}),
                            site_id=body.get("site_id", "wadi_saqra"),
                            producer=body.get("producer", "unknown"),
                            ts_unix=body.get("ts_unix", 0.0),
                        )
                        for h in self._handlers.get(topic, []):
                            try:
                                await h(msg)
                            except Exception:  # noqa: BLE001
                                log.exception("rabbitmq subscriber for %s raised", topic.value)
        except asyncio.CancelledError:
            return
