from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from contextlib import asynccontextmanager
import os

from app.database import init_db
from app.routes.dashboard import router as dashboard_router
from app.routes.gatekeeper import router as gatekeeper_router
from app.routes.subscriptions import router as subscriptions_router
from app.routes.rollup import router as rollup_router
from app.routes.settings import router as settings_router
from app.routes.ai import router as ai_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
IS_VERCEL = bool(os.getenv("VERCEL"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not IS_VERCEL:
        from app.scheduler import ScanManager
        ScanManager.get_instance().start_background_loop()
    yield
    if not IS_VERCEL:
        from app.scheduler import ScanManager
        ScanManager.get_instance().stop_background_loop()

app = FastAPI(
    title="ZenInbox",
    description="Intelligent Email Gatekeeper, Daily Digest & Subscription Cleaner for Gmail",
    version="2.0.0",
    lifespan=lifespan
)

all_routers = [
    dashboard_router,
    ai_router,
    gatekeeper_router,
    subscriptions_router,
    rollup_router,
    settings_router
]

# Mount all routers with /api prefix AND without prefix
for r in all_routers:
    app.include_router(r, prefix="/api")
    app.include_router(r)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"status": "ok", "app": "ZenInbox API"}
