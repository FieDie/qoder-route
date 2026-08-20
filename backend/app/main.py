import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.api import accounts, chat, models, logs, settings as settings_api, status as status_api, anthropic
from app.services.account_pool import pool
from app.services import settings_service, signer_service, model_probe

# Worker endpoints are optional — the public build ships without them.
try:
    from app.api import worker
except ImportError:
    worker = None

logger = logging.getLogger("qoderroute")

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

QUOTA_REFRESH_INTERVAL = 300  # seconds


async def _quota_refresher():
    """Background loop: refresh plan/quota for all accounts periodically."""
    while True:
        try:
            await asyncio.sleep(QUOTA_REFRESH_INTERVAL)
            await pool._refresh()  # un-park accounts whose cooldown expired
            count = await pool.refresh_all_quotas()
            if count:
                logger.info(f"Quota refresh: {count} accounts updated")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Quota refresher error: {e}")


async def _model_prober():
    """Background loop: ping every model per the configured probe interval."""
    await asyncio.sleep(5)  # let the pool settle after startup
    while True:
        interval = settings_service.get_probe_interval_minutes()
        try:
            if interval > 0:
                await model_probe.probe_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Model prober error: {e}")
        # Re-read the interval each cycle; poll minutely while disabled.
        await asyncio.sleep((interval if interval > 0 else 1) * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name}")
    await init_db()
    logger.info("Database initialized")
    await settings_service.load()

    if not await signer_service.ensure_signer():
        raise RuntimeError(
            f"Signer sidecar failed to start; see {signer_service.SIGNER_LOG}"
        )
    signer_task = asyncio.create_task(
        signer_service.signer_supervisor(),
        name="signer-supervisor",
    )

    async def _initial_quota():
        await asyncio.sleep(2)
        await pool.refresh_all_quotas()

    initial_task = asyncio.create_task(_initial_quota())
    refresher = asyncio.create_task(_quota_refresher())
    prober = asyncio.create_task(_model_prober())
    try:
        yield
    finally:
        refresher.cancel()
        initial_task.cancel()
        signer_task.cancel()
        prober.cancel()
        await asyncio.gather(
            refresher,
            initial_task,
            signer_task,
            prober,
            return_exceptions=True,
        )
        # The signer is a host-level singleton.  It deliberately survives this
        # Uvicorn generation so an older draining process can never kill the
        # sidecar used by its replacement.
        logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(chat.router)
app.include_router(anthropic.router)
app.include_router(models.router)
if worker is not None:
    app.include_router(worker.router)
app.include_router(logs.router)
app.include_router(settings_api.router)
app.include_router(status_api.router)


@app.get("/api/health")
async def health():
    signer_ok = await signer_service.signer_is_healthy()
    return JSONResponse(
        status_code=200 if signer_ok else 503,
        content={
            "status": "ok" if signer_ok else "degraded",
            "app": settings.app_name,
            "version": "1.0.0",
            "signer": "ok" if signer_ok else "unavailable",
        },
    )


@app.get("/api/health/live")
async def liveness():
    return {"status": "ok", "app": settings.app_name, "version": "1.0.0"}


# ── Static frontend (production build) ──

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/qoder.svg")
    async def favicon():
        return FileResponse(FRONTEND_DIST / "qoder.svg")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA catch-all: serve index.html for any non-API route."""
        if full_path.startswith(("api/", "v1/")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(FRONTEND_DIST / "index.html")
