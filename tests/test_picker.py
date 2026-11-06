import pytest

from app.models import Poi
from app.picker import pick, seed_text


def mk(pid: str, rating: str | None, distance: int, lat: float = 39.91, lng: float = 116.40) -> Poi:
    return Poi(id=pid, name=pid, distance=distance, lat=lat, lng=lng, rating=rating)


POOL = [mk(f"p{i}", f"{3 + i % 3}.0", 100 * (i + 1)) for i in range(10)]


def test_same_inputs_same_result_1000_times():
    first, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    for _ in range(999):
        again, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
        assert again.id == first.id


def test_different_date_changes_result():
    a, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    b, _ = pick(POOL, date="2026-11-08", grid="39.910,116.395", mode="area", radius=1000)
    assert a.id != b.id


def test_nonce_changes_result_within_same_date():
    seen = {pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area",
                 radius=1000, nonce=n)[0].id for n in range(20)}
    assert len(seen) > 1


def test_classic_mode_ignores_radius():
    a, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="classic", radius=500)
    b, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="classic", radius=3000)
    assert a.id == b.id


def test_weighted_prefers_high_rating():
    pool = [mk("high", "5.0", 100), mk("low", "1.0", 100)] + [mk(f"mid{i}", "3.0", 100) for i in range(8)]
    counts = {"high": 0, "low": 0}
    for n in range(1000):
        chosen, _ = pick(pool, date="2026-11-07", grid="39.910,116.395", mode="weighted",
                         radius=1000, nonce=n)
        if chosen.id in counts:
            counts[chosen.id] += 1
    assert counts["high"] > counts["low"] * 3


def test_missing_rating_does_not_crash_or_zero_weight():
    pool = [mk("a", None, 100), mk("b", "4.0", 100), mk("c", None, 900)]
    for n in range(50):
        pick(pool, date="2026-11-07", grid="39.910,116.395", mode="weighted", radius=1000, nonce=n)


def test_small_pool_degrades():
    pool = [mk("a", "4.0", 100), mk("b", "4.0", 200)]
    _, degraded = pick(pool, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    assert degraded == "pool_too_small"


def test_empty_pool_raises():
    with pytest.raises(ValueError, match="empty_pool"):
        pick([], date="2026-11-07", grid="39.910,116.395")


def test_duplicate_ids_are_deduped():
    dup = [POOL[0], POOL[0]]
    _, degraded = pick(dup, date="2026-11-07", grid="39.910,116.395")
    assert degraded == "pool_too_small"


def test_seed_text_excludes_radius_for_classic():
    assert "500" not in seed_text("2026-11-07", "39.910,116.395", "classic", 500)
