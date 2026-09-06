"""Small process-local sliding-window limiter for public API cost control.

The backend intentionally runs as one worker because review sessions are
process-local. This limiter is therefore a useful last line of defence for a
single instance; production deployments should still add an edge/API gateway
limiter for multi-instance and distributed abuse protection.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import RLock
import time


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class Limit:
    per_client: int
    global_limit: int


WINDOW_SECONDS = _positive_int("RATE_LIMIT_WINDOW_SECONDS", 600)
LIMITS = {
    "analyze": Limit(
        _positive_int("ANALYZE_RATE_LIMIT", 5),
        _positive_int("ANALYZE_GLOBAL_RATE_LIMIT", 60),
    ),
    "confirm": Limit(
        _positive_int("CONFIRM_RATE_LIMIT", 10),
        _positive_int("CONFIRM_GLOBAL_RATE_LIMIT", 120),
    ),
    "verify": Limit(
        _positive_int("VERIFY_RATE_LIMIT", 60),
        _positive_int("VERIFY_GLOBAL_RATE_LIMIT", 600),
    ),
}


class SlidingWindowLimiter:
    def __init__(self, window_seconds: int = WINDOW_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._events: dict[tuple[str, str], list[float]] = {}
        self._lock = RLock()

    def check(self, scope: str, client: str, now: float | None = None) -> int | None:
        """Record a request, or return whole seconds until it may be retried."""

        limit = LIMITS[scope]
        current = time.monotonic() if now is None else now
        client_key = (scope, client)
        global_key = (scope, "*")
        with self._lock:
            cutoff = current - self.window_seconds
            for key in (client_key, global_key):
                events = [stamp for stamp in self._events.get(key, []) if stamp > cutoff]
                if events:
                    self._events[key] = events
                else:
                    self._events.pop(key, None)
            client_events = self._events.get(client_key, [])
            global_events = self._events.get(global_key, [])
            if len(client_events) >= limit.per_client or len(global_events) >= limit.global_limit:
                oldest = min(
                    (client_events[0] if client_events else current),
                    (global_events[0] if global_events else current),
                )
                return max(1, int(self.window_seconds - (current - oldest)) + 1)
            self._events[client_key] = [*client_events, current]
            self._events[global_key] = [*global_events, current]
        return None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()
