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
