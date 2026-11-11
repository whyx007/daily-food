from contextlib import asynccontextmanager
from pathlib import Path
import json
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.amap import AmapClient
from app.config import Settings, get_settings
from app.guard import RateLimiter
from app.routes import router
from app.store import Store

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "data" / "classics.json"


def seed_classics(store: Store, path: Path = SEED_FILE) -> int:
    """数据库为空时，用仓库里的种子文件填充名人堂（便于换机器/部署时带上名单）。"""
    if store.count_classics() > 0 or not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    imported = 0
    for item in payload.get("items") or []:
        if not item.get("poiid") or not item.get("name"):
            continue
        store.upsert_classic({
            "id": item["poiid"],
            "name": item["name"],
            "lat": float(item["lat"]),
            "lng": float(item["lng"]),
            "rating": item.get("rating"),
            "cost": item.get("cost"),
            "type": item.get("type"),
            "address": item.get("address"),
        }, "seed", item.get("note"))
        imported += 1
    return imported


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.client.aclose()
        app.state.store.close()

    app = FastAPI(title="Daily Food", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = Store(settings.db_path)
    if settings.seed_file:
        seed_classics(app.state.store, ROOT / settings.seed_file)
    app.state.client = AmapClient(key=settings.amap_key, max_concurrency=settings.qps)
    app.state.limiter = RateLimiter(limit=settings.rate_limit_per_min, window=60)
    app.include_router(router)

    @app.middleware("http")
    async def access_log_middleware(request, call_next):
        """记录每次访问（访问日志见 /admin.html 或 logs/access.log）。"""
        started = time.perf_counter()
        response = await call_next(request)
        try:
            import os

            if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("ACCESS_LOG_OFF"):
                return response        # 跑测试时不要把用例请求写进真实日志
            from app import accesslog

            client = request.client.host if request.client else "unknown"
            ip = request.headers.get("X-Real-IP") or client
            accesslog.log_request(
                ip=ip,
                method=request.method,
                path=request.url.path,
                query=list(request.query_params.multi_items()),
                status=response.status_code,
                ms=(time.perf_counter() - started) * 1000,
                ua=request.headers.get("User-Agent", ""),
                referer=request.headers.get("Referer", ""),
            )
        except Exception:
            pass       # 日志失败绝不能影响正常请求
        return response

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """前端文件禁止浏览器缓存，否则改了 JS/CSS 后用户看到的还是旧版。"""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
