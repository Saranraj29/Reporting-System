"""Circuit breaker for the provider: after 5 consecutive transient failures, or more than 5 % errors over the last 60 s (20+ calls), calls are
skipped (built-in wording is used at once) and one probe is let through every 30 s; a success closes it again. Per process."""

import threading
import time
from collections import deque

CONSECUTIVE = 5
WINDOW_S = 60
RATE = 0.05
MIN_CALLS = 20
PROBE_S = 30


class Breaker:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.events: deque[tuple[float, bool]] = deque()
        self.consecutive = 0
        self.opened_at: float | None = None
        self.last_probe = 0.0

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def allow(self) -> bool:
        """True = go ahead and call the provider. While open, one probe per PROBE_S is allowed."""
        with self.lock:
            if self.opened_at is None:
                return True
            now = self.clock()
            if now - self.last_probe >= PROBE_S:
                self.last_probe = now
                return True
            return False

    def record(self, ok: bool) -> None:
        with self.lock:
            now = self.clock()
            self.events.append((now, ok))
            while self.events and now - self.events[0][0] > WINDOW_S:
                self.events.popleft()
            if ok:
                self.consecutive = 0
                self.opened_at = None  # a successful probe closes it
                return
            self.consecutive += 1
            errors = sum(1 for _, good in self.events if not good)
            if self.consecutive >= CONSECUTIVE or (len(self.events) >= MIN_CALLS and errors / len(self.events) > RATE):
                if self.opened_at is None:
                    self.last_probe = now
                self.opened_at = now


breaker = Breaker()
