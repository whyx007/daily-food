import asyncio

import httpx

from app.models import Poi


class AmapError(Exception):
    def __init__(self, info: str, infocode: str = "") -> None:
        super().__init__(info)
        self.info = info
        self.infocode = infocode


CONFIG_ERRORS = {"INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH", "INVALID_USER_IP", "INVALID_USER_DOMAIN"}
QUOTA_ERRORS = {"DAILY_QUERY_OVER_LIMIT", "USER_DAILY_QUERY_OVER_LIMIT", "ACCESS_TOO_FREQUENT"}


def _text(value) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def _parse_poi(raw: dict) -> Poi | None:
    location = _text(raw.get("location"))
    if not location or "," not in location:
        return None
    lng_s, lat_s = location.split(",", 1)
    try:
        lat, lng = float(lat_s), float(lng_s)
    except ValueError:
        return None
    name = _text(raw.get("name"))
    poi_id = _text(raw.get("id"))
    if not name or not poi_id:
        return None
    biz = raw.get("biz_ext") or {}
    distance = _text(raw.get("distance"))
    return Poi(
        id=poi_id,
        name=name,
        distance=int(float(distance)) if distance else None,
        type=_text(raw.get("type")),
        address=_text(raw.get("address")),
        lat=lat,
        lng=lng,
        rating=_text(biz.get("rating")),
        cost=_text(biz.get("cost")),
        tel=_text(raw.get("tel")),
    )


def _nearest_poi(rc: dict) -> tuple[str, str, float] | None:
    """最近的一个 POI（名称、id、距离）；餐饮类优先，用于猜"这个位置是哪家店"。"""
    candidates = []
    for poi in rc.get("pois") or []:
        name = _text(poi.get("name"))
        if not name:
            continue
        try:
            distance = float(_text(poi.get("distance")) or 999)
        except ValueError:
            continue
        is_food = "餐饮" in (_text(poi.get("type")) or "")
        candidates.append((name, _text(poi.get("id")) or "", distance, is_food))
    if not candidates:
        return None
    food = [c for c in candidates if c[3]]
    best = min(food or candidates, key=lambda c: c[2])
    return best[0], best[1], best[2]


def _regeo_label(rc: dict) -> str:
    """把逆地理编码结果压成一个人类可读的地名：优先小区/园区/商圈，其次附近 POI，最后街道。"""
    for aoi in rc.get("aois") or []:
        name = _text(aoi.get("name"))
        if name:
            return name
    for poi in rc.get("pois") or []:
        name = _text(poi.get("name"))
        distance = _text(poi.get("distance"))
        if not name:
            continue
        try:
            if distance and float(distance) <= 200:
                return f"{name}附近"
        except ValueError:
            continue
    ac = rc.get("addressComponent") or {}
    township = _text(ac.get("township")) or _text(ac.get("district"))
    street = _text((ac.get("streetNumber") or {}).get("street"))
    parts = [p for p in (township, street) if p]
    if parts:
        return " ".join(parts)
    return _text(rc.get("formatted_address")) or ""


class AmapClient:
    def __init__(self, key: str, base: str = "https://restapi.amap.com",
                 timeout: float = 5.0, max_concurrency: int = 3) -> None:
        self._key = key
        self._base = base.rstrip("/")
        self._sem = asyncio.Semaphore(max_concurrency)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "key": self._key}
        async with self._sem:
            data = None
            for attempt in (1, 2):
                try:
                    resp = await self._http.get(f"{self._base}{path}", params=params)
                    if resp.status_code >= 500 and attempt == 1:
                        await asyncio.sleep(1.0)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0)
        if data is None:
            raise AmapError("NO_RESPONSE")
        if str(data.get("status")) != "1":
            raise AmapError(str(data.get("info") or "UNKNOWN"), str(data.get("infocode") or ""))
        return data

    async def around(self, lat: float, lng: float, radius: int,
                     keywords: str | None = None, types: str | None = "050000",
                     max_items: int = 60) -> list[Poi]:
        out: list[Poi] = []
        for page in range(1, 4):
            params = {
                "location": f"{lng:.6f},{lat:.6f}",
                "radius": radius,
                "offset": 25,
                "page": page,
                "extensions": "all",
                "sortrule": "distance",
            }
            if types:
                params["types"] = types
            if keywords:
                params["keywords"] = keywords
            data = await self._get("/v3/place/around", params)
            for raw in data.get("pois") or []:
                poi = _parse_poi(raw)
                if poi is not None:
                    out.append(poi)
            if len(data.get("pois") or []) < 25 or len(out) >= max_items:
                break
        return out[:max_items]

    async def detail(self, poiid: str) -> Poi | None:
        # 已用真实 key 验证：v3/place/detail?id= 可用；place/around?id= 会返回 MISSING_REQUIRED_PARAMS
        data = await self._get("/v3/place/detail", {"id": poiid, "extensions": "all"})
        for raw in data.get("pois") or []:
            poi = _parse_poi(raw)
            if poi is not None:
                return poi
        return None

    async def regeo(self, lat: float, lng: float, radius: int = 300) -> dict:
        data = await self._get("/v3/geocode/regeo", {
            "location": f"{lng:.6f},{lat:.6f}",
            "extensions": "all",
            "radius": radius,
        })
        rc = data.get("regeocode") or {}
        nearest = _nearest_poi(rc)
        return {
            "label": _regeo_label(rc),
            "address": _text(rc.get("formatted_address")) or "",
            "poiName": nearest[0] if nearest else "",
            "poiId": nearest[1] if nearest else "",
            "poiDistance": int(nearest[2]) if nearest and nearest[2] < 999 else None,
        }

    async def geocode(self, address: str) -> tuple[float, float] | None:
        data = await self._get("/v3/geocode/geo", {"address": address})
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return None
        location = _text(geocodes[0].get("location"))
        if not location or "," not in location:
            return None
        lng_s, lat_s = location.split(",", 1)
        return float(lat_s), float(lng_s)

    async def staticmap(self, lat: float, lng: float, zoom: int = 14, size: str = "600*400") -> bytes:
        params = {
            "location": f"{lng:.6f},{lat:.6f}",
            "zoom": zoom,
            "size": size,
            "key": self._key,
        }
        async with self._sem:
            resp = await self._http.get(f"{self._base}/v3/staticmap", params=params)
            resp.raise_for_status()
        return resp.content
