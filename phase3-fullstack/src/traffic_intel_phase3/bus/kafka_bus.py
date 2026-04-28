"""Optional Kafka backend (aiokafka).

Install with ``pip install 'traffic-intel[kafka]'`` or ``pip install aiokafka``.
Select at runtime with ``TRAFFIC_INTEL_BUS=kafka``.

Connection env vars:
    TRAFFIC_INTEL_KAFKA_BOOTSTRAP  — e.g. "localhost:9092" (required)
    TRAFFIC_INTEL_KAFKA_CLIENT_ID  — default "traffic-intel"
    TRAFFIC_INTEL_KAFKA_GROUP_ID   — default "traffic-intel-consumers"
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


class KafkaBus:
    def __init__(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # noqa: F401
        except ImportError as e:  # pragma: no cover — optional extra
            raise ImportError(
                "KafkaBus requires the 'aiokafka' package. "
                "Install with `pip install aiokafka` or `pip install 'traffic-intel[kafka]'`."
            ) from e

        self._bootstrap = os.environ.get("TRAFFIC_INTEL_KAFKA_BOOTSTRAP", "localhost:9092")
        self._client_id = os.environ.get("TRAFFIC_INTEL_KAFKA_CLIENT_ID", "traffic-intel")
        self._group_id = os.environ.get("TRAFFIC_INTEL_KAFKA_GROUP_ID", "traffic-intel-consumers")
        self._producer: "AIOKafkaProducer | None" = None  # noqa: F821 — runtime import
        self._handlers: dict[Topic, list[Handler]] = defaultdict(list)
        self._consumers: list["AIOKafkaConsumer"] = []  # noqa: F821
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer
        self._loop = asyncio.get_running_loop()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            client_id=self._client_id,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self._producer.start()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for c in self._consumers:
            await c.stop()
        if self._producer is not None:
            await self._producer.stop()
        self._tasks.clear()
        self._consumers.clear()
        self._producer = None

    async def publish(self, msg: BusMessage) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaBus.start() must be called before publish()")
        await self._producer.send_and_wait(
            msg.topic.value,
            value={
                "payload": msg.payload,
                "site_id": msg.site_id,
                "producer": msg.producer,
                "ts_unix": msg.ts_unix,
            },
        )

    def publish_threadsafe(self, msg: BusMessage) -> None:
        if not self._running or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.publish(msg), self._loop)

    async def subscribe(self, topic: Topic, handler: Handler) -> None:
        from aiokafka import AIOKafkaConsumer
        self._handlers[topic].append(handler)
        consumer = AIOKafkaConsumer(
            topic.value,
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            client_id=f"{self._client_id}-{topic.value}",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=True,
        )
        await consumer.start()
        self._consumers.append(consumer)
        task = asyncio.create_task(self._drain(topic, consumer), name=f"kafka-{topic.value}")
        self._tasks.append(task)

    async def _drain(self, topic: Topic, consumer) -> None:
        try:
            async for rec in consumer:
                msg = BusMessage(
                    topic=topic,
                    payload=rec.value.get("payload", {}),
                    site_id=rec.value.get("site_id", "wadi_saqra"),
                    producer=rec.value.get("producer", "unknown"),
                    ts_unix=rec.value.get("ts_unix", 0.0),
                )
                for h in self._handlers.get(topic, []):
                    try:
                        await h(msg)
                    except Exception:  # noqa: BLE001
                        log.exception("kafka subscriber for %s raised", topic.value)
        except asyncio.CancelledError:
            return
