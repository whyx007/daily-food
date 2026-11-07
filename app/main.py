from contextlib import asynccontextmanager
from pathlib import Path
import json

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
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
