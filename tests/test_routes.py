from datetime import date as date_cls, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geo import quantize_grid
from app.main import create_app
from app.models import Poi
from app.routes import today_key


class FakeAmap:
    def __init__(self):
        self.calls = 0

    async def around(self, lat, lng, radius, keywords=None, types="050000", max_items=60):
        self.calls += 1
        return [Poi(id=f"B{i:03d}", name=f"店{i}", distance=100 * (i + 1), lat=lat, lng=lng,
                    rating=f"{3 + i % 3}.0", cost="40", type="中餐") for i in range(6)]

    async def detail(self, poiid):
        return Poi(id=poiid, name="详情店", lat=39.91, lng=116.40, rating="4.2")

    async def geocode(self, address):
        return (39.91, 116.40)

    async def staticmap(self, lat, lng, zoom=14, size="600*400"):
        return b"\x89PNG"

    async def aclose(self):
        pass


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "t.db"), admin_token="secret"))
    app.state.client = FakeAmap()
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json()["data"]["status"] == "ok"


def test_config_returns_radius_options(client):
    body = client.get("/api/config").json()["data"]
    assert body["radiusOptions"] == [500, 1000, 2000, 3000]
    assert body["modes"] == ["area", "classic", "weighted"]


def test_today_returns_pick_and_candidates(client):
    body = client.get("/api/today", params={"lat": 39.91, "lng": 116.40, "mode": "area"}).json()
    assert body["data"]["pick"]["id"].startswith("B")
    assert len(body["data"]["candidates"]) <= 20
    assert body["meta"]["degraded"] is None


def test_today_second_request_hits_cache(client):
    client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    assert client.app.state.client.calls == 1


def test_today_rejects_bad_params(client):
    assert client.get("/api/today", params={"lat": "abc", "lng": "116.4"}).status_code == 422


def test_today_breaker_returns_stale_pool(client):
    store = client.app.state.store
    day = today_key()
    yesterday = (date_cls.fromisoformat(day) - timedelta(days=1)).isoformat()
    store.put_pool(yesterday, quantize_grid(39.91, 116.40), 1000, "all",
                   [Poi(id="B900", name="昨日店", distance=300, lat=39.91, lng=116.40,
                        rating="4.0").model_dump()], 1)
    for _ in range(501):
        store.bump_calls(day)
    resp = client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.json()["meta"]["stale"] is True


def test_search_uses_cache(client):
    params = {"q": "饺子", "lat": 39.91, "lng": 116.40, "radius": 1000}
    client.get("/api/search", params=params)
    first = client.app.state.client.calls
    client.get("/api/search", params=params)
    assert client.app.state.client.calls == first


def test_search_requires_two_chars(client):
    resp = client.get("/api/search", params={"q": "饺", "lat": 39.91, "lng": 116.40})
    assert resp.status_code == 400


def test_classics_add_list_delete(client):
    r = client.post("/api/classics", json={"poiid": "B001", "note": "经典"},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    assert client.get("/api/classics").json()["data"]["items"][0]["note"] == "经典"
    r = client.delete("/api/classics/B001", headers={"X-Client-Token": "tok-b"})
    assert r.status_code == 403
    r = client.delete("/api/classics/B001", headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    assert client.get("/api/classics").json()["data"]["items"] == []


def test_classics_add_by_address(client):
    r = client.post("/api/classics", json={"name": "手填店", "address": "某街 1 号"},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    items = client.get("/api/classics").json()["data"]["items"]
    assert items[0]["name"] == "手填店"


def test_classic_pick_has_computed_distance(client):
    client.post("/api/classics", json={"poiid": "B001"},
                headers={"X-Client-Token": "tok-a"})
    body = client.get("/api/today", params={"lat": 39.91, "lng": 116.40, "mode": "classic"}).json()
    assert body["data"]["pick"]["distance"] is not None


def test_staticmap_returns_png(client):
    resp = client.get("/api/staticmap", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
