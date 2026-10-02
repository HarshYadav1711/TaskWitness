"""In-memory progress/event stream for Phase 4 (and future operator UI).

Not durable event sourcing. Not Redis / WebSockets / queues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from taskwitness.schemas import RunState


@dataclass(frozen=True)
class ProgressEvent:
    run_state: RunState
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    candidate_id: Optional[str] = None
    action: Optional[str] = None
    event_type: str = "info"


class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...


class InMemoryProgressCollector:
    """Test-friendly collector that retains events in order."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def messages(self) -> list[str]:
        return [e.message for e in self.events]

    def states(self) -> list[RunState]:
        return [e.run_state for e in self.events]


class CallbackProgressSink:
    def __init__(self, callback: Callable[[ProgressEvent], None]) -> None:
        self._callback = callback

    def emit(self, event: ProgressEvent) -> None:
        self._callback(event)


class MultiplexProgressSink:
    """Fan-out to multiple sinks (e.g. collector + console printer)."""

    def __init__(self, *sinks: ProgressSink) -> None:
        self._sinks = sinks

    def emit(self, event: ProgressEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)


def print_progress(event: ProgressEvent) -> None:
    """Compact console progress for the Phase 4 development harness."""
    label = event.run_state.value.upper()
    if event.run_state == RunState.awaiting_approval:
        label = "APPROVAL"
    parts = [f"[{label}]"]
    if event.candidate_id:
        parts.append(event.candidate_id)
    if event.action:
        parts.append(event.action)
    parts.append(event.message)
    print(" ".join(parts))
