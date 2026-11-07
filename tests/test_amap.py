import httpx
import pytest
import respx

from app.amap import AmapClient, AmapError

SAMPLE = {
    "status": "1", "info": "OK", "count": "2",
    "pois": [
        {"id": "B001", "name": "来今雨轩", "distance": "133", "type": "餐饮服务;中餐厅",
         "address": "某街", "location": "116.400123,39.909321",
         "biz_ext": {"rating": "4.7", "cost": "89.00"}, "tel": "010-1234"},
        {"id": "B002", "name": "小馆", "distance": "211", "type": "餐饮服务;快餐厅",
         "address": "某巷", "location": "116.398765,39.910111",
         "biz_ext": {"rating": [], "cost": []}, "tel": []},
    ],
}


@pytest.mark.asyncio
@respx.mock
async def test_around_normalizes_pois():
    respx.get("https://restapi.amap.com/v3/place/around").mock(
        return_value=httpx.Response(200, json=SAMPLE))
    client = AmapClient(key="k")
    pois = await client.around(39.90923, 116.397428, 1000)
    await client.aclose()
    assert [p.id for p in pois] == ["B001", "B002"]
    assert pois[0].rating == "4.7"
    assert pois[1].rating is None
    assert pois[1].cost is None
    assert pois[1].tel is None
    assert pois[0].lat == pytest.approx(39.909321)
    assert pois[0].lng == pytest.approx(116.400123)


@pytest.mark.asyncio
@respx.mock
async def test_platform_mismatch_raises_amap_error():
    respx.get("https://restapi.amap.com/v3/place/around").mock(
        return_value=httpx.Response(200, json={"status": "0", "info": "USERKEY_PLAT_NOMATCH",
                                               "infocode": "10009"}))
    client = AmapClient(key="k")
    with pytest.raises(AmapError) as exc:
        await client.around(39.9, 116.4, 1000)
    await client.aclose()
    assert exc.value.info == "USERKEY_PLAT_NOMATCH"
    assert exc.value.infocode == "10009"


@pytest.mark.asyncio
@respx.mock
async def test_around_omits_types_when_none():
    route = respx.get("https://restapi.amap.com/v3/place/around").mock(
        return_value=httpx.Response(200, json=SAMPLE))
    client = AmapClient(key="k")
    await client.around(39.9, 116.4, 5000, keywords="鲍家水饺", types=None)
    await client.aclose()
    assert route.called
    url = str(route.calls[0].request.url)
    assert "types=" not in url
    assert "keywords=" in url


@pytest.mark.asyncio
@respx.mock
async def test_regeo_prefers_aoi_name():
    payload = {
        "status": "1", "info": "OK",
        "regeocode": {
            "formatted_address": "陕西省西安市长安区郭杜街道西部大道103号",
            "addressComponent": {"township": "郭杜街道", "district": "长安区",
                                 "streetNumber": {"street": "西部大道"}},
            "aois": [{"name": "西安市高新区新型工业园", "distance": "0"}],
            "pois": [{"name": "阳光天地SOHO", "distance": "192"}],
        },
    }
    respx.get("https://restapi.amap.com/v3/geocode/regeo").mock(
        return_value=httpx.Response(200, json=payload))
    client = AmapClient(key="k")
    out = await client.regeo(34.172176, 108.862074)
    await client.aclose()
    assert out["label"] == "西安市高新区新型工业园"
    assert "西部大道" in out["address"]


@pytest.mark.asyncio
@respx.mock
async def test_regeo_falls_back_to_township_and_street():
    payload = {
        "status": "1", "info": "OK",
        "regeocode": {
            "formatted_address": "某地",
            "addressComponent": {"township": "郭杜街道", "district": "长安区",
                                 "streetNumber": {"street": "西部大道"}},
            "aois": [],
            "pois": [{"name": "某店", "distance": "800"}],
        },
    }
    respx.get("https://restapi.amap.com/v3/geocode/regeo").mock(
        return_value=httpx.Response(200, json=payload))
    client = AmapClient(key="k")
    out = await client.regeo(34.17, 108.86)
    await client.aclose()
    assert out["label"] == "郭杜街道 西部大道"


@pytest.mark.asyncio
@respx.mock
async def test_regeo_uses_nearby_poi_within_200m():
    payload = {
        "status": "1", "info": "OK",
        "regeocode": {
            "formatted_address": "某地",
            "addressComponent": {"township": "某街道", "district": "某区", "streetNumber": {}},
            "aois": [],
            "pois": [{"name": "阳光天地SOHO", "distance": "192"}],
        },
    }
    respx.get("https://restapi.amap.com/v3/geocode/regeo").mock(
        return_value=httpx.Response(200, json=payload))
    client = AmapClient(key="k")
    out = await client.regeo(34.17, 108.86)
    await client.aclose()
    assert out["label"] == "阳光天地SOHO附近"


@pytest.mark.asyncio
@respx.mock
async def test_regeo_prefers_restaurant_poi():
    payload = {
        "status": "1", "info": "OK",
        "regeocode": {
            "formatted_address": "某地",
            "addressComponent": {"township": "某街道", "district": "某区", "streetNumber": {}},
            "aois": [],
            "pois": [{"name": "某打卡点", "id": "B0XX", "distance": "20", "type": "风景名胜;景点"},
                     {"name": "老王水饺", "id": "B0ABC", "distance": "80", "type": "餐饮服务;中餐厅"}],
        },
    }
    respx.get("https://restapi.amap.com/v3/geocode/regeo").mock(
        return_value=httpx.Response(200, json=payload))
    client = AmapClient(key="k")
    out = await client.regeo(34.17, 108.86)
    await client.aclose()
    assert out["poiName"] == "老王水饺"
    assert out["poiId"] == "B0ABC"


@pytest.mark.asyncio
@respx.mock
async def test_regeo_exposes_nearest_poi():
    payload = {
        "status": "1", "info": "OK",
        "regeocode": {
            "formatted_address": "某地",
            "addressComponent": {"township": "某街道", "district": "某区", "streetNumber": {}},
            "aois": [{"name": "某某广场", "distance": "0"}],
            "pois": [{"name": "老王水饺", "id": "B0ABC", "distance": "35"},
                     {"name": "别家", "id": "B0DEF", "distance": "180"}],
        },
    }
    respx.get("https://restapi.amap.com/v3/geocode/regeo").mock(
        return_value=httpx.Response(200, json=payload))
    client = AmapClient(key="k")
    out = await client.regeo(34.17, 108.86)
    await client.aclose()
    assert out["label"] == "某某广场"
    assert out["poiName"] == "老王水饺"
    assert out["poiId"] == "B0ABC"
    assert out["poiDistance"] == 35


@pytest.mark.asyncio
@respx.mock
async def test_qps_limit_is_retried_once():
    route = respx.get("https://restapi.amap.com/v3/place/around")
    route.side_effect = [
        httpx.Response(200, json={"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"}),
        httpx.Response(200, json=SAMPLE),
    ]
    client = AmapClient(key="k")
    pois = await client.around(39.9, 116.4, 1000)
    await client.aclose()
    assert len(pois) == 2
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_detail_returns_poi():
    respx.get("https://restapi.amap.com/v3/place/detail").mock(
        return_value=httpx.Response(200, json=SAMPLE))
    client = AmapClient(key="k")
    poi = await client.detail("B001")
    await client.aclose()
    assert poi is not None and poi.name == "来今雨轩"


@pytest.mark.asyncio
@respx.mock
async def test_geocode_parses_location():
    respx.get("https://restapi.amap.com/v3/geocode/geo").mock(
        return_value=httpx.Response(200, json={"status": "1", "info": "OK",
                                               "geocodes": [{"location": "116.397428,39.90923"}]}))
    client = AmapClient(key="k")
    coords = await client.geocode("天安门")
    await client.aclose()
    assert coords == pytest.approx((39.90923, 116.397428))


@pytest.mark.asyncio
@respx.mock
async def test_staticmap_returns_bytes():
    respx.get("https://restapi.amap.com/v3/staticmap").mock(
        return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    client = AmapClient(key="k")
    data = await client.staticmap(39.9, 116.4)
    await client.aclose()
    assert data == b"\x89PNG"
