"""Asyncio bus: publish → subscribe roundtrip and threadsafe publish path."""

from __future__ import annotations

import asyncio
import threading

import pytest

from traffic_intel_phase3.bus import BusMessage, Topic
from traffic_intel_phase3.bus.asyncio_bus import AsyncioBus


@pytest.mark.asyncio
async def test_publish_subscribe_roundtrip() -> None:
    bus = AsyncioBus()
    await bus.start()
    received: list[BusMessage] = []
    done = asyncio.Event()

    async def handler(m: BusMessage) -> None:
        received.append(m)
        done.set()

    await bus.subscribe(Topic.DETECTOR_COUNTS, handler)
    await bus.publish(BusMessage(
        topic=Topic.DETECTOR_COUNTS,
        payload={"ts": "2026-04-23T10:00:00Z", "approach": "S", "count": 7},
        site_id="wadi_saqra", producer="test",
    ))

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await bus.stop()

    assert len(received) == 1
    assert received[0].topic == Topic.DETECTOR_COUNTS
    assert received[0].payload["count"] == 7
    assert received[0].site_id == "wadi_saqra"


@pytest.mark.asyncio
async def test_topic_isolation() -> None:
    """A subscriber to one topic does not see messages on another."""
    bus = AsyncioBus()
    await bus.start()
    counts: list[BusMessage] = []
    signals: list[BusMessage] = []
    counts_done = asyncio.Event()

    async def counts_h(m: BusMessage) -> None:
        counts.append(m); counts_done.set()

    async def signals_h(m: BusMessage) -> None:
        signals.append(m)

    await bus.subscribe(Topic.DETECTOR_COUNTS, counts_h)
    await bus.subscribe(Topic.SIGNAL_EVENTS, signals_h)

    await bus.publish(BusMessage(topic=Topic.DETECTOR_COUNTS, payload={"n": 1}))
    await asyncio.wait_for(counts_done.wait(), timeout=1.0)
    await bus.stop()

    assert len(counts) == 1
    assert signals == []


@pytest.mark.asyncio
async def test_publish_threadsafe_from_daemon_thread() -> None:
    """Models the tracker path: daemon thread publishes, async loop drains."""
    bus = AsyncioBus()
    await bus.start()
    received: list[BusMessage] = []
    done = asyncio.Event()

    async def handler(m: BusMessage) -> None:
        received.append(m); done.set()

    await bus.subscribe(Topic.DETECTOR_COUNTS, handler)

    def _producer() -> None:
        bus.publish_threadsafe(BusMessage(
            topic=Topic.DETECTOR_COUNTS, payload={"from": "thread"},
        ))

    t = threading.Thread(target=_producer, daemon=True)
    t.start()
    t.join()

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await bus.stop()

    assert len(received) == 1
    assert received[0].payload["from"] == "thread"


def test_factory_defaults_to_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env var → AsyncioBus."""
    from traffic_intel_phase3.bus.factory import get_bus, reset_bus_singleton
    monkeypatch.delenv("TRAFFIC_INTEL_BUS", raising=False)
    reset_bus_singleton()
    bus = get_bus()
    assert type(bus).__name__ == "AsyncioBus"
    reset_bus_singleton()


def test_factory_unknown_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown backend name → warning + AsyncioBus fallback."""
    from traffic_intel_phase3.bus.factory import get_bus, reset_bus_singleton
    monkeypatch.setenv("TRAFFIC_INTEL_BUS", "mqtt")
    reset_bus_singleton()
    bus = get_bus()
    assert type(bus).__name__ == "AsyncioBus"
    reset_bus_singleton()
