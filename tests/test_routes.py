from datetime import date as date_cls, timedelta

import httpx
import pytest
import respx
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
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "t.db"),
                              admin_token="secret", amap_security_code="sc"))
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


def test_search_allows_single_cjk_char(client):
    resp = client.get("/api/search", params={"q": "面", "lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.json()["data"]["items"]


def test_search_requires_query(client):
    resp = client.get("/api/search", params={"lat": 39.91, "lng": 116.40})
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


@respx.mock
def test_amap_proxy_injects_jscode(client):
    route = respx.get("https://restapi.amap.com/v3/ip").mock(
        return_value=httpx.Response(200, json={"status": "1", "info": "OK"}))
    r = client.get("/_AMapService/v3/ip", params={"key": "k"})
    assert r.status_code == 200
    assert route.called
    assert "jscode=sc" in str(route.calls[0].request.url)


def test_rate_limit_uses_settings(client, tmp_path):
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "rl.db"), rate_limit_per_min=1))
    app.state.client = FakeAmap()
    c = TestClient(app)
    assert c.get("/api/today", params={"lat": 39.91, "lng": 116.40}).status_code == 200
    resp = c.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


def test_classics_add_by_coordinates(client):
    r = client.post("/api/classics", json={"name": "路口小馆", "lat": 39.91, "lng": 116.40},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    items = client.get("/api/classics").json()["data"]["items"]
    assert items[0]["name"] == "路口小馆"


def test_classics_add_by_coordinates_rejects_bad_latlng(client):
    r = client.post("/api/classics", json={"name": "x", "lat": 999, "lng": 116.4},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 400


def test_weighted_min_rating_filters_candidates(client):
    body = client.get("/api/today", params={"lat": 39.91, "lng": 116.40,
                                             "mode": "weighted", "min_rating": 4.5}).json()
    assert body["data"]["candidates"]
    assert all(float(c["rating"]) >= 4.5 for c in body["data"]["candidates"])


def test_weighted_min_rating_no_match(client):
    r = client.get("/api/today", params={"lat": 39.91, "lng": 116.40,
                                          "mode": "weighted", "min_rating": 6})
    assert r.status_code == 404
    assert r.json()["meta"]["degraded"] == "no_match"


def test_search_expands_when_empty(client):
    calls = []

    async def fake_around(lat, lng, radius, keywords=None, types="050000", max_items=60):
        calls.append({"radius": radius, "types": types})
        if len(calls) == 1:
            return []
        return [Poi(id="B900", name="鲍家水饺", distance=3065, lat=lat, lng=lng, rating="4.2")]

    client.app.state.client.around = fake_around
    r = client.get("/api/search", params={"q": "鲍家水饺", "lat": 34.17, "lng": 108.86, "radius": 1000})
    assert r.status_code == 200
    assert r.json()["data"]["items"][0]["name"] == "鲍家水饺"
    assert len(calls) == 2
    assert calls[1]["radius"] == 5000
    assert calls[1]["types"] is None


def test_poi_fix_overrides_coordinates(client):
    r = client.post("/api/fixes", json={"poiid": "B001", "lat": 39.95, "lng": 116.45},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    body = client.get("/api/today", params={"lat": 39.91, "lng": 116.40}).json()
    fixed = [c for c in body["data"]["candidates"] if c["id"] == "B001"]
    assert fixed and fixed[0]["lat"] == 39.95 and fixed[0]["lng"] == 116.45


def test_poi_fix_rejects_invalid(client):
    r = client.post("/api/fixes", json={"poiid": "B001", "lat": 999, "lng": 116.4})
    assert r.status_code == 400


def test_regeo_returns_label(client):
    async def fake_regeo(lat, lng, radius=300):
        return {"label": "天安门", "address": "北京市东城区东华门街道天安门"}

    client.app.state.client.regeo = fake_regeo
    r = client.get("/api/regeo", params={"lat": 39.90923, "lng": 116.397428})
    assert r.status_code == 200
    assert r.json()["data"]["label"] == "天安门"


def test_regeo_is_cached(client):
    calls = []

    async def fake_regeo(lat, lng, radius=300):
        calls.append(1)
        return {"label": "某小区", "address": "某地址"}

    client.app.state.client.regeo = fake_regeo
    params = {"lat": 39.90923, "lng": 116.397428}
    client.get("/api/regeo", params=params)
    client.get("/api/regeo", params=params)
    assert len(calls) == 1


def test_staticmap_returns_png(client):
    resp = client.get("/api/staticmap", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
