from app.guard import RateLimiter, breaker_state
from app.store import Store


def test_rate_limiter_allows_20_per_minute():
    limiter = RateLimiter(limit=20, window=60)
    assert all(limiter.allow("ip", now=1000.0) for _ in range(20))
    assert limiter.allow("ip", now=1000.0) is False
    assert limiter.allow("ip", now=1061.0) is True


def test_rate_limiter_isolates_keys():
    limiter = RateLimiter(limit=2, window=60)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0) is False
    assert limiter.allow("b", now=1000.0) is True


def test_breaker_states(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert breaker_state(s, "2026-11-07", 500) is None
    for _ in range(400):
        s.bump_calls("2026-11-07")
    assert breaker_state(s, "2026-11-07", 500) == "warning"
    for _ in range(100):
        s.bump_calls("2026-11-07")
    assert breaker_state(s, "2026-11-07", 500) == "daily_limit_reached"
    s.close()
