from app.store import Store


def poi(pid="B001", name="老边饺子"):
    return {"id": pid, "name": name, "lat": 39.91, "lng": 116.40,
            "rating": "4.5", "cost": "35", "type": "中餐", "address": "某街"}


def test_upsert_and_list(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", "好吃")
    items = s.list_classics()
    assert len(items) == 1
    assert items[0]["poiid"] == "B001"
    assert items[0]["addedBy"] == "token-a"
    assert items[0]["note"] == "好吃"
    s.close()


def test_upsert_same_poiid_updates(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", "v1")
    s.upsert_classic(poi(name="老边饺子(新)"), "token-b", "v2")
    items = s.list_classics()
    assert len(items) == 1
    assert items[0]["name"] == "老边饺子(新)"
    assert items[0]["note"] == "v2"
    s.close()


def test_delete_requires_owner_or_admin(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", None)
    assert s.delete_classic("B001", "token-b", "secret") is False
    assert s.delete_classic("B001", "token-a", "secret") is True
    assert s.list_classics() == []
    s.close()


def test_admin_can_delete_any(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", None)
    assert s.delete_classic("B001", "secret", "secret") is True
    s.close()


def test_delete_missing_returns_false(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.delete_classic("nope", "t", "") is False
    s.close()
