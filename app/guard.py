import time
from collections import defaultdict, deque

from app.store import Store


class RateLimiter:
    def __init__(self, limit: int = 20, window: int = 60) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def breaker_state(store: Store, date: str, limit: int) -> str | None:
    count = store.calls_today(date)
    if count >= limit:
        return "daily_limit_reached"
    if count >= int(limit * 0.8):
        return "warning"
    return None
