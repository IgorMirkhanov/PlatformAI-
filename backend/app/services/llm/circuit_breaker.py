"""Lightweight Circuit Breaker for LLM provider calls (no external deps)."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Callable


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    Consecutive-failure circuit breaker.

    CLOSED → failures accumulate until ``failure_threshold`` → OPEN.
    OPEN → reject until ``recovery_timeout`` elapses → HALF_OPEN.
    HALF_OPEN → one probe; success → CLOSED, failure → OPEN again.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    name: str = ""
    time_fn: Callable[[], float] = field(default=time.monotonic, repr=False)

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _half_open_probe_in_flight: bool = field(default=False, init=False)

    @property
    def state(self) -> CircuitState:
        self._maybe_transition_to_half_open()
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def allow_request(self) -> bool:
        """Return True if a call may proceed to the protected provider."""
        self._maybe_transition_to_half_open()
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.OPEN:
            return False
        # HALF_OPEN — allow a single probe at a time.
        if self._half_open_probe_in_flight:
            return False
        self._half_open_probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        self._opened_at = None
        self._half_open_probe_in_flight = False
        self._state = CircuitState.CLOSED

    def record_failure(self) -> bool:
        """
        Record a failed call.

        Returns
        -------
        bool
            ``True`` when this call transitioned the breaker into ``OPEN``.
        """
        self._half_open_probe_in_flight = False
        if self._state is CircuitState.HALF_OPEN:
            self._trip_open()
            return True
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._trip_open()
            return True
        return False

    def _trip_open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self.time_fn()

    def _maybe_transition_to_half_open(self) -> None:
        if self._state is not CircuitState.OPEN:
            return
        if self._opened_at is None:
            return
        if (self.time_fn() - self._opened_at) >= self.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._half_open_probe_in_flight = False
