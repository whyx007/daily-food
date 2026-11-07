import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app import guard, picker
from app.amap import AmapError
from app.geo import haversine_m, quantize_grid
from app.models import Envelope, Meta, Poi

router = APIRouter()
TZ = ZoneInfo("Asia/Shanghai")


def today_key() -> str:
    return datetime.now(TZ).date().isoformat()


def _now() -> int:
    return int(time.time())


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Real-IP")
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _envelope(data, meta: Meta) -> dict:
    return Envelope(data=data, meta=meta).model_dump()


def _pois(payload: list[dict]) -> list[Poi]:
    return [Poi(**item) for item in payload]


def _classic_poi(item: dict) -> dict:
    return Poi(id=item["poiid"], name=item["name"], lat=item["lat"], lng=item["lng"],
               rating=item.get("rating"), cost=item.get("cost"),
               type=item.get("type"), address=item.get("address")).model_dump()


def _rating_float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _apply_fixes(store, items: list[dict]) -> list[dict]:
    """用户手工校正过的点位优先于高德原始 POI 坐标。"""
    fixes = store.list_fixes()
    for item in items:
        fix = fixes.get(item.get("id"))
        if fix:
            item["lat"], item["lng"] = fix
            item["distance"] = None
    return items


def _with_distance(items: list[Poi], lat: float, lng: float, keep_distance: bool) -> list[Poi]:
    out = []
    for poi in items:
        if not keep_distance or poi.distance is None:
            poi.distance = haversine_m(lat, lng, poi.lat, poi.lng)
        out.append(poi)
    return out


@router.get("/api/health")
def health():
    return {"data": {"status": "ok"}, "meta": {"stale": False, "degraded": None}}


@router.get("/api/config")
def config(request: Request):
    s = request.app.state.settings
    state = guard.breaker_state(request.app.state.store, today_key(), s.daily_call_limit)
    return _envelope({
        "siteName": s.site_name,
        "defaultCenter": {"lat": s.default_lat, "lng": s.default_lng},
        "radiusOptions": s.radius_list,
        "modes": ["area", "classic", "weighted"],
        "jsKey": s.amap_js_key,
        "securityServiceHost": request.headers.get("host", ""),
    }, Meta(degraded=None if state == "warning" else state))


@router.get("/api/today")
async def today(request: Request, lat: float, lng: float, mode: str = "area",
                radius: int = 1000, nonce: int = 0, min_rating: float | None = None):
    settings = request.app.state.settings
    store = request.app.state.store
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"},
                            headers={"Retry-After": "60"})
    if mode not in {"area", "classic", "weighted"}:
        return JSONResponse(status_code=400, content={"detail": "bad_mode"})
    if mode != "classic" and radius not in settings.radius_list:
        radius = settings.radius_list[min(1, len(settings.radius_list) - 1)]

    grid = quantize_grid(lat, lng)
    day = today_key()
    degraded = guard.breaker_state(store, day, settings.daily_call_limit)
    if degraded == "warning":
        degraded = None

    stale = False
    pool: list[dict] = []
    fetched_at: int | None = None

    if mode == "classic":
        pool = [_classic_poi(item) for item in store.list_classics()]
    else:
        cached = store.get_pool(day, grid, radius)
        if cached is not None:
            pool, fetched_at = cached
        elif degraded != "daily_limit_reached":
            try:
                fetched = await request.app.state.client.around(lat, lng, radius)
                store.bump_calls(day)
                payload = [p.model_dump() for p in fetched]
                store.put_pool(day, grid, radius, "all", payload, _now())
                pool, fetched_at = payload, _now()
            except AmapError as exc:
                if exc.info in {"INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH"}:
                    degraded = "misconfigured"
        if not pool:
            latest = store.get_latest_pool(grid, radius)
            if latest is not None:
                pool, fetched_at, _ = latest
                stale = True

    if not pool:
        return JSONResponse(status_code=404, content={
            "data": None, "meta": {"stale": False, "degraded": degraded or "no_data"}})

    if mode == "weighted" and min_rating is not None:
        pool = [item for item in pool
                if (_rating_float(item.get("rating")) or 0) >= min_rating]
        if not pool:
            return JSONResponse(status_code=404, content={
                "data": None, "meta": {"stale": stale, "degraded": "no_match"}})

    pool = _apply_fixes(store, pool)

    try:
        computed = _with_distance(_pois(pool), lat, lng, keep_distance=False)
        chosen, picked_degraded = picker.pick(computed, date=day, grid=grid, mode=mode,
                                              radius=radius, nonce=nonce)
    except ValueError:
        return JSONResponse(status_code=404, content={
            "data": None, "meta": {"stale": stale, "degraded": "no_data"}})

    if chosen.distance is None:
        chosen.distance = haversine_m(lat, lng, chosen.lat, chosen.lng)

    candidates = _with_distance(_pois(pool)[:20], lat, lng, keep_distance=False)
    return _envelope({
        "pick": chosen.model_dump(),
        "candidates": [p.model_dump() for p in candidates],
        "mode": mode,
    }, Meta(cachedAt=fetched_at, stale=stale, degraded=picked_degraded or degraded,
            seed=picker.seed_text(day, grid, mode, radius, nonce)))


def _grid_query_key(grid: str, q: str | None, category: str | None, radius: int) -> str:
    raw = f"{grid}|{q or ''}|{category or ''}|{radius}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@router.get("/api/search")
async def search(request: Request, lat: float, lng: float, q: str | None = None,
                 category: str | None = None, radius: int = 1000, expand: bool = False,
                 city: bool = False):
    store = request.app.state.store
    if not (q or "").strip() and not category:
        return JSONResponse(status_code=400, content={"detail": "query_required"})
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"})

    grid = quantize_grid(lat, lng)
    key = _grid_query_key(grid, q, category, radius)
    if expand:
        key = "expand:" + key
    if city:
        key = "city:" + key
    cached = store.get_search(key, ttl=300)
    if cached is not None:
        payload, fetched_at = cached
        return _envelope({"items": payload, "cached": True}, Meta(cachedAt=fetched_at))

    day = today_key()
    limit = request.app.state.settings.daily_call_limit
    if guard.breaker_state(store, day, limit) == "daily_limit_reached":
        return _envelope({"items": [], "cached": False}, Meta(degraded="daily_limit_reached"))

    try:
        if city:
            # 全城市搜索：先用逆地理编码拿 adcode，再按城市关键字搜索
            info = await request.app.state.client.regeo(lat, lng)
            store.bump_calls(day)
            adcode = info.get("adcode") or ""
            items = await request.app.state.client.text_search(
                (q or category or "").strip(), city=adcode, types=(category or None) or ("050000" if not q else None))
            store.bump_calls(day)
        else:
            items = await request.app.state.client.around(lat, lng, radius,
                                                          keywords=(q or None), types=category or "050000")
            store.bump_calls(day)
            if not items and expand and (q or "").strip() and radius < 5000:
                # 只有用户显式要求时才放宽到 5km，默认严格按所选距离
                items = await request.app.state.client.around(lat, lng, 5000, keywords=q.strip(), types=None)
                store.bump_calls(day)
    except AmapError as exc:
        return _envelope({"items": [], "cached": False}, Meta(degraded=f"amap:{exc.info}"))

    payload = _apply_fixes(store, [p.model_dump() for p in items[:20]])
    payload = [p.model_dump() for p in _with_distance(_pois(payload), lat, lng, keep_distance=False)]
    store.put_search(key, payload, _now())
    return _envelope({"items": payload, "cached": False}, Meta(cachedAt=_now()))


@router.get("/api/classics")
def list_classics(request: Request):
    items = request.app.state.store.list_classics()
    return _envelope({"items": items}, Meta())


@router.post("/api/classics")
async def add_classic(request: Request, body: dict):
    token = request.headers.get("X-Client-Token", "")
    if not token:
        return JSONResponse(status_code=400, content={"detail": "missing_token"})
    body = body or {}
    poiid = body.get("poiid", "")
    name = body.get("name", "")
    address = body.get("address", "")

    if poiid:
        poi = await request.app.state.client.detail(poiid)
        if poi is not None and body.get("lat") is not None and body.get("lng") is not None:
            # 用户点定的位置优先：字段用高德的，坐标用用户选中的点
            try:
                coords = float(body["lat"]), float(body["lng"])
            except (TypeError, ValueError):
                return JSONResponse(status_code=400, content={"detail": "invalid_coordinates"})
            if not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180):
                return JSONResponse(status_code=400, content={"detail": "invalid_coordinates"})
            poi.lat, poi.lng = coords
            if (body.get("name") or "").strip():
                poi.name = body["name"].strip()
    elif name and body.get("lat") is not None and body.get("lng") is not None:
        try:
            lat = float(body["lat"])
            lng = float(body["lng"])
        except (TypeError, ValueError):
            return JSONResponse(status_code=400, content={"detail": "invalid_coordinates"})
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return JSONResponse(status_code=400, content={"detail": "invalid_coordinates"})
        raw = hashlib.sha1(f"{name}|{lat:.6f}|{lng:.6f}".encode("utf-8")).hexdigest()[:12]
        poi = Poi(id=f"manual:{raw}", name=name, lat=lat, lng=lng)
    elif name and address:
        coords = await request.app.state.client.geocode(address)
        if coords is None:
            return JSONResponse(status_code=404, content={"detail": "address_not_found"})
        lat, lng = coords
        raw = hashlib.sha1(f"{name}|{address}".encode("utf-8")).hexdigest()[:12]
        poi = Poi(id=f"addr:{raw}", name=name, lat=lat, lng=lng, address=address)
    else:
        return JSONResponse(status_code=400, content={"detail": "poiid_or_address_required"})

    if poi is None:
        return JSONResponse(status_code=404, content={"detail": "poi_not_found"})
    request.app.state.store.upsert_classic(poi.model_dump(), token, body.get("note"))
    return _envelope({"ok": True, "poiid": poi.id}, Meta())


@router.delete("/api/classics/{poiid}")
def delete_classic(request: Request, poiid: str):
    admin = request.app.state.settings.admin_token
    password = request.headers.get("X-Admin-Password", "")
    # 密码确认优先：密码正确（或等于添加者 token）才允许删除
    if password and password == admin:
        ok = request.app.state.store.delete_classic(poiid, admin, admin)
    else:
        token = request.headers.get("X-Client-Token", "")
        ok = request.app.state.store.delete_classic(poiid, token, admin)
    if not ok:
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    return _envelope({"ok": True}, Meta())


@router.get("/_AMapService/{path:path}")
async def amap_proxy(request: Request, path: str):
    """把 JS API 的安全密钥注入后转发给高德，前端不暴露 jscode。

    生产环境可以交给 Nginx 做同一件事；这里保留是因为本地开发没有 Nginx 也能跑通 2.0。
    """
    params = dict(request.query_params)
    code = request.app.state.settings.amap_security_code
    if code:
        params["jscode"] = code
    host = "https://webapi.amap.com" if path.startswith("v4/map/styles") else "https://restapi.amap.com"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{host}/{path}", params=params)
        except httpx.HTTPError:
            return JSONResponse(status_code=502, content={"detail": "amap_proxy_unavailable"})
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type=resp.headers.get("content-type"))


@router.post("/api/fixes")
def add_fix(request: Request, body: dict):
    try:
        poiid = str((body or {}).get("poiid") or "")
        lat = float(body["lat"])
        lng = float(body["lng"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse(status_code=400, content={"detail": "invalid_fix"})
    if not poiid or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JSONResponse(status_code=400, content={"detail": "invalid_fix"})
    request.app.state.store.upsert_fix(poiid, lat, lng)
    return _envelope({"ok": True, "poiid": poiid}, Meta())


@router.delete("/api/fixes/{poiid}")
def remove_fix(request: Request, poiid: str):
    ok = request.app.state.store.delete_fix(poiid)
    return _envelope({"ok": ok}, Meta())


@router.get("/api/regeo")
async def regeo(request: Request, lat: float, lng: float):
    """把坐标换成人能读的地名（小区/园区/商圈），30 天内复用缓存。"""
    store = request.app.state.store
    key = "regeo:" + hashlib.sha1(f"{lat:.4f},{lng:.4f}".encode()).hexdigest()
    cached = store.get_search(key, ttl=2592000)
    if cached is not None:
        payload, fetched_at = cached
        return _envelope(payload, Meta(cachedAt=fetched_at))
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"})

    day = today_key()
    if guard.breaker_state(store, day, request.app.state.settings.daily_call_limit) == "daily_limit_reached":
        return _envelope({"label": "", "address": ""}, Meta(degraded="daily_limit_reached"))
    try:
        payload = await request.app.state.client.regeo(lat, lng)
        store.bump_calls(day)
    except AmapError as exc:
        return _envelope({"label": "", "address": ""}, Meta(degraded=f"amap:{exc.info}"))
    if not payload.get("label"):
        payload["label"] = payload.get("address") or ""
    store.put_search(key, payload, _now())
    return _envelope(payload, Meta(cachedAt=_now()))


EXCLUDED_TYPE_HINTS = ("交通", "地名", "公交", "地铁", "停车场", "道路", "路口", "出入口", "收费站", "桥梁")


def _pick_nearest(items):
    usable = [p for p in items
              if not any(hint in (p.type or "") for hint in EXCLUDED_TYPE_HINTS)]
    if not usable:
        usable = items
    return min(usable, key=lambda p: p.distance if p.distance is not None else 10**9)


async def _resolve_point(store, client, lat: float, lng: float) -> dict:
    """识别某个点位上是哪家店：直接按点周边搜索（比逆地理编码准），逐级放大半径。"""
    poi = None
    for radius in (60, 150, 300):
        items = await client.around(lat, lng, radius, types=None, max_items=25)
        if items:
            poi = _pick_nearest(items)
            break
    if poi is None:
        info = await client.regeo(lat, lng)
        name = info.get("label") or info.get("address") or "地图选点"
        raw = hashlib.sha1(f"{lat:.6f},{lng:.6f}".encode()).hexdigest()[:10]
        poi = Poi(id=f"pt:{raw}", name=name, lat=lat, lng=lng, address=info.get("address") or None)
    payload = poi.model_dump()
    fix = store.list_fixes().get(payload["id"])
    if fix:
        payload["lat"], payload["lng"] = fix
    return payload


@router.get("/api/poi-nearby")
async def poi_nearby(request: Request, lat: float, lng: float):
    store = request.app.state.store
    key = "poiinfo:" + hashlib.sha1(f"{lat:.5f},{lng:.5f}".encode()).hexdigest()
    cached = store.get_search(key, ttl=86400)
    if cached is not None:
        payload, fetched_at = cached
        return _envelope(payload, Meta(cachedAt=fetched_at))
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"})

    day = today_key()
    if guard.breaker_state(store, day, request.app.state.settings.daily_call_limit) == "daily_limit_reached":
        return _envelope({"poi": None, "click": {"lat": lat, "lng": lng}},
                         Meta(degraded="daily_limit_reached"))
    try:
        poi = await _resolve_point(store, request.app.state.client, lat, lng)
        store.bump_calls(day)
    except AmapError as exc:
        return _envelope({"poi": None, "click": {"lat": lat, "lng": lng}},
                         Meta(degraded=f"amap:{exc.info}"))
    payload = {"poi": poi, "click": {"lat": lat, "lng": lng}}
    store.put_search(key, payload, _now())
    return _envelope(payload, Meta(cachedAt=_now()))


@router.get("/api/staticmap")
async def staticmap(request: Request, lat: float, lng: float, zoom: int = 14):
    try:
        data = await request.app.state.client.staticmap(lat, lng, zoom=zoom)
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "staticmap_unavailable"})
    return Response(content=data, media_type="image/png")
