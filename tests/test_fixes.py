from app.store import Store


def test_fix_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.list_fixes() == {}
    s.upsert_fix("B001", 39.95, 116.45)
    assert s.list_fixes()["B001"] == (39.95, 116.45)
    s.upsert_fix("B001", 39.96, 116.46)
    assert s.list_fixes()["B001"] == (39.96, 116.46)
    assert s.delete_fix("B001") is True
    assert s.list_fixes() == {}
    assert s.delete_fix("nope") is False
    s.close()
