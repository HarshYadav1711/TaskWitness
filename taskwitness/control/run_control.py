"""Cooperative in-memory run control (pause / resume / approval halt).

Pause means: stop before the next external side effect / safe workflow
checkpoint. It does NOT interrupt an in-flight Playwright click, kill
Chromium, or roll back the current atomic browser operation.

Precedence with approval (deterministic Phase-4 rule):

- AWAITING_APPROVAL is its own halted state.
- A pause request during approval wait remains pending (flag set);
  the visible state stays awaiting_approval.
- After approval resolution, state returns to running; the next
  checkpoint honors a pending pause via wait_if_paused().

Control state is process-local / in-memory. No crash resume.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from taskwitness.schemas import RunState


class RunControl:
    """Small in-memory run-control object for Phase 4 harnesses and tests."""

    def __init__(
        self,
        *,
        on_state_change: Optional[Callable[[RunState], None]] = None,
    ) -> None:
        self._condition = threading.Condition()
        self._pause_requested = False
        self._awaiting_approval = False
        self._state = RunState.ready
        self._on_state_change = on_state_change
        self._terminal = False

    @property
    def state(self) -> RunState:
        with self._condition:
            return self._state

    @property
    def pause_requested(self) -> bool:
        with self._condition:
            return self._pause_requested

    @property
    def is_awaiting_approval(self) -> bool:
        with self._condition:
            return self._awaiting_approval

    def set_state(self, state: RunState) -> None:
        with self._condition:
            if self._terminal:
                return
            self._set_state_locked(state)

    def mark_terminal(self, state: RunState) -> None:
        with self._condition:
            self._pause_requested = False
            self._awaiting_approval = False
            self._terminal = True
            self._set_state_locked(state)
            self._condition.notify_all()

    def request_pause(self) -> None:
        with self._condition:
            if self._terminal:
                return
            self._pause_requested = True
            # Do not overwrite awaiting_approval; pause takes effect at the
            # next checkpoint after approval resolves.

    def resume(self) -> None:
        with self._condition:
            if self._terminal:
                return
            self._pause_requested = False
            if self._state == RunState.paused:
                self._set_state_locked(RunState.running)
            self._condition.notify_all()

    def wait_if_paused(self) -> None:
        """Block at a safe checkpoint while a pause is pending.

        No-op while awaiting approval (approval wait is already halted).
        """
        with self._condition:
            if self._terminal or self._awaiting_approval:
                return
            while self._pause_requested and not self._terminal:
                self._set_state_locked(RunState.paused)
                self._condition.wait()
            if not self._terminal and self._state == RunState.paused:
                self._set_state_locked(RunState.running)

    def begin_awaiting_approval(self) -> None:
        with self._condition:
            if self._terminal:
                return
            self._awaiting_approval = True
            self._set_state_locked(RunState.awaiting_approval)

    def end_awaiting_approval(self) -> None:
        """Leave approval halt. Pending pause is honored at the next checkpoint."""
        with self._condition:
            if self._terminal:
                return
            self._awaiting_approval = False
            if self._state == RunState.awaiting_approval:
                self._set_state_locked(RunState.running)

    def _set_state_locked(self, state: RunState) -> None:
        if self._state == state:
            return
        self._state = state
        callback = self._on_state_change
        if callback is None:
            return
        # Callback runs while holding the condition lock; keep callbacks light
        # (progress emit / test barriers). Do not call wait_if_paused from them.
        callback(state)
