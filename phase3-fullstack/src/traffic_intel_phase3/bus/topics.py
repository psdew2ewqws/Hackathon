"""Canonical topic catalog.

Every message in the system carries one of these topic names. Kafka and
RabbitMQ backends translate these verbatim into topic/exchange names, so a
consumer written against the asyncio backend reads the same topic string
as a Kafka consumer.

Keep this list authoritative — don't publish to ad-hoc string topics.
"""

from __future__ import annotations

from enum import StrEnum


class Topic(StrEnum):
    """Canonical topic names. Values are the literal strings on the wire."""

    DETECTOR_COUNTS = "detector.counts"
    SIGNAL_EVENTS = "signal.events"
    INCIDENTS_DETECTED = "incidents.detected"
    FORECASTS_GENERATED = "forecasts.generated"
    RECOMMENDATIONS_CREATED = "recommendations.created"
    INGEST_ERRORS = "ingest.errors"
    AUDIT_EVENTS = "audit.events"
