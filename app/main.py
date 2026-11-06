from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.amap import AmapClient
from app.config import Settings, get_settings
from app.guard import RateLimiter
from app.routes import router
from app.store import Store


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
    app.state.client = AmapClient(key=settings.amap_key, max_concurrency=settings.qps)
    app.state.limiter = RateLimiter(limit=20, window=60)
    app.include_router(router)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
