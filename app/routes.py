import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
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

# 候选池缓存版本标记：改动抓取上限（页数/max_items）后改这个值，旧池自动失效
POOL_CATEGORY = "all2"

# 「高分优先」排除的快餐/饮品/烘焙连锁：这类店铺评分虚高，不是大家要找的馆子
CHAIN_HINTS = (
    "肯德基", "麦当劳", "必胜客", "汉堡王", "德克士", "华莱士", "塔斯汀", "正新鸡排",
    "蜜雪冰城", "瑞幸", "库迪", "星巴克", "COSTA", "幸运咖", "茶百道", "古茗",
    "一点点", "喜茶", "奈雪", "益禾堂", "甜啦啦",
    "米旗", "好利来", "面包新语", "85度C",
    "沙县小吃", "兰州拉面", "魏家凉皮", "袁记肉夹馍", "老潼关", "绝味", "紫燕",
)


def _is_chain(name: str | None) -> bool:
    text = name or ""
    return any(hint in text for hint in CHAIN_HINTS)


# 高德偶尔把非餐饮 POI 标成「餐饮服务;中餐厅」（数据错误），按店名排掉
NON_FOOD_HINTS = (
    "头疗", "养生", "SPA", "按摩", "足浴", "足道", "洗浴", "美容", "美发", "理发",
    "酒店", "宾馆", "公寓", "超市", "便利店", "药店", "洗衣", "洗车", "宠物",
    "健身", "瑜伽", "摄影", "茶艺", "棋牌", "网吧", "KTV",
)


def _is_non_food(name: str | None) -> bool:
    text = (name or "").upper()
    return any(hint.upper() in text for hint in NON_FOOD_HINTS)


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
        pool_cat = POOL_CATEGORY
        cached = store.get_pool(day, grid, radius, pool_cat)
        if cached is not None:
            pool, fetched_at = cached
        elif degraded != "daily_limit_reached":
            try:
                fetched = await request.app.state.client.around(lat, lng, radius)
                store.bump_calls(day)
                payload = [p.model_dump() for p in fetched]
                store.put_pool(day, grid, radius, pool_cat, payload, _now())
                pool, fetched_at = payload, _now()
            except AmapError as exc:
                if exc.info in {"INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH"}:
                    degraded = "misconfigured"
        if not pool:
            latest = store.get_latest_pool(grid, radius, pool_cat)
            if latest is not None:
                pool, fetched_at, _ = latest
                stale = True

    if not pool:
        return JSONResponse(status_code=404, content={
            "data": None, "meta": {"stale": False, "degraded": degraded or "no_data"}})

    pool_size = len(pool)
    if mode != "classic":
        pool = [item for item in pool if not _is_non_food(item.get("name"))]
    if mode == "weighted":
        # 高分优先不看快餐/饮品/烘焙连锁（评分虚高，且不是「馆子」）
        pool = [item for item in pool if not _is_chain(item.get("name"))]
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

    candidates_all = _with_distance(_pois(pool), lat, lng, keep_distance=False)
    if mode == "weighted":
        # 高分优先：与 picker 的权重同口径排序（评分 0.65 + 距离 0.35），近且好的排前面
        def score(p):
            rating = _rating_float(p.rating) or 0
            decay = 1.0 - min((p.distance or 0) / max(radius, 1), 1.0)
            return -(0.65 * (rating / 5.0) + 0.35 * decay)
        candidates_all.sort(key=score)
    else:
        candidates_all.sort(key=lambda p: p.distance or 0)

    # 同一家店在高德可能有重复条目（同名、位置几乎重合），按「店名 + 50m 网格」去重
    seen_keys: set[tuple[str, int]] = set()
    deduped: list[Poi] = []
    for poi in candidates_all:
        key = (poi.name.strip(), int((poi.distance or 0) // 50))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(poi)
    candidates = deduped[:40]

    return _envelope({
        "pick": chosen.model_dump(),
        "candidates": [p.model_dump() for p in candidates],
        "mode": mode,
        "matched": len(deduped),
        "poolSize": pool_size,
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


# ---------- 网络推荐（来自「美食雷达」radar/out/food_table.json） ----------

RADAR_JSON = Path(__file__).resolve().parent.parent / "radar" / "out" / "food_table.json"
_radar_cache: dict = {"mtime": None, "payload": None}


def _load_radar() -> dict:
    """读取雷达导出的 JSON；文件变了才重新读（避免每次请求都解析 100KB+）。"""
    try:
        mtime = RADAR_JSON.stat().st_mtime
    except OSError:
        return {"items": [], "generatedAt": None}
    cache = _radar_cache
    if cache["mtime"] != mtime or cache["payload"] is None:
        try:
            data = json.loads(RADAR_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"items": [], "generatedAt": None}
        cache["payload"] = data
        cache["mtime"] = mtime
    return cache["payload"]


@router.get("/api/admin/logs")
def admin_logs(request: Request, limit: int = 200, path: str = "", status: str = "",
               ip: str = "", files: int = 1):
    """访问日志（需要密码：X-Admin-Password 头或 ?token=）。"""
    admin = request.app.state.settings.admin_token
    given = request.headers.get("X-Admin-Password", "") or request.query_params.get("token", "")
    if not admin or given != admin:
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    from app import accesslog

    limit = max(1, min(2000, int(limit)))
    items = accesslog.tail(limit, path_prefix=path, status=status, ip=ip, files=max(1, min(5, files)))
    stats = {"total": len(items)}
    if items:
        stats["errors"] = sum(1 for i in items if int(i.get("status", 0)) >= 400)
        stats["avgMs"] = round(sum(float(i.get("ms", 0)) for i in items) / len(items), 1)
    return _envelope({"items": items, "stats": stats,
                      "file": str(accesslog.LOG_FILE)}, Meta())


@router.get("/api/admin/logs/stats")
def admin_logs_stats(request: Request):
    """按路径/状态汇总最近的请求（方便看哪个接口被刷）。"""
    admin = request.app.state.settings.admin_token
    given = request.headers.get("X-Admin-Password", "") or request.query_params.get("token", "")
    if not admin or given != admin:
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    from collections import Counter

    from app import accesslog

    items = accesslog.tail(2000, files=5)
    by_path = Counter(i.get("path", "") for i in items).most_common(20)
    by_ip = Counter(i.get("ip", "") for i in items).most_common(20)
    by_status = Counter(str(i.get("status", "")) for i in items).most_common(20)
    return _envelope({
        "count": len(items),
        "byPath": [{"path": p, "n": n} for p, n in by_path],
        "byIp": [{"ip": p, "n": n} for p, n in by_ip],
        "byStatus": [{"status": p, "n": n} for p, n in by_status],
    }, Meta())


@router.get("/api/radar")
def radar(request: Request, lat: float | None = None, lng: float | None = None,
          category: str | None = None, min_trust: float = 0):
    data = _load_radar()
    items = list(data.get("items") or [])
    if category and category != "all":
        items = [i for i in items if (i.get("category") or "") == category]
    if min_trust:
        items = [i for i in items if (i.get("trust") or 0) >= min_trust]
    # 带了出发点就补距离并排序：先按可信度，再按距离
    if lat is not None and lng is not None:
        for i in items:
            if i.get("lat") is not None and i.get("lng") is not None:
                i = i  # noqa: B007 - 保持原对象
        items = [
            {**i, "distance": round(haversine_m(lat, lng, i["lat"], i["lng"]))}
            if i.get("lat") is not None and i.get("lng") is not None else {**i, "distance": None}
            for i in items
        ]
    items.sort(key=lambda i: (-(i.get("trust") or 0), i.get("distance") or 10 ** 9))
    cats = sorted({(i.get("category") or "其他") for i in (data.get("items") or [])})
    return _envelope({
        "items": items,
        "total": len(data.get("items") or []),
        "categories": cats,
        "generatedAt": data.get("generatedAt"),
    }, Meta())


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
