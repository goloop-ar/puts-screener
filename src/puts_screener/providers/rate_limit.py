"""Rate limiter token-bucket thread-safe para APIs con límite por minuto."""

import threading
import time
from collections import deque

_SECONDS_PER_MINUTE = 60


class RateLimiter:
    """Limita las llamadas a `max_per_minute` usando una ventana deslizante de 60s."""

    def __init__(self, max_per_minute: int):
        if max_per_minute < 1:
            raise ValueError("max_per_minute debe ser >= 1")
        self._max_per_minute = max_per_minute
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def wait_for_slot(self) -> None:
        """Bloquea hasta que haya un slot disponible dentro del límite por minuto."""
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - _SECONDS_PER_MINUTE
                while self._calls and self._calls[0] <= cutoff:
                    self._calls.popleft()
                if len(self._calls) < self._max_per_minute:
                    self._calls.append(now)
                    return
                sleep_for = self._calls[0] + _SECONDS_PER_MINUTE - now
            time.sleep(max(sleep_for, 0.0))
