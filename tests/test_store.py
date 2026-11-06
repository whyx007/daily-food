from app.store import Store


def test_pool_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_pool("2026-11-07", "39.910,116.395", 1000, "all", [{"id": "a"}], 100)
    assert s.get_pool("2026-11-07", "39.910,116.395", 1000) == ([{"id": "a"}], 100)
    s.close()


def test_pool_miss_returns_none(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.get_pool("2026-11-07", "39.910,116.395", 2000) is None
    s.close()


def test_latest_pool_falls_back_to_previous_day(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_pool("2026-11-06", "39.910,116.395", 1000, "all", [{"id": "old"}], 50)
    assert s.get_latest_pool("39.910,116.395", 1000) == ([{"id": "old"}], 50, "2026-11-06")
    s.close()


def test_search_cache_ttl(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_search("k1", [{"id": "a"}], 1000)
    assert s.get_search("k1", ttl=300, now=1100) == ([{"id": "a"}], 1000)
    assert s.get_search("k1", ttl=300, now=1400) is None
    s.close()


def test_calls_count_increments(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.calls_today("2026-11-07") == 0
    assert s.bump_calls("2026-11-07") == 1
    assert s.bump_calls("2026-11-07") == 2
    assert s.calls_today("2026-11-07") == 2
    s.close()
