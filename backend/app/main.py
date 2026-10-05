from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import analyses, batches, videos
from app.config import get_settings
from app.db import init_db
from app.pipeline.speed import SPEEDS
from app.pipeline.tracker import TRACKER_TYPES
from app.vehicles import ALL_VEHICLE_TYPES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    stop = None
    if settings.embedded_worker:
        from app.workers.worker import recover_stale_jobs, start_embedded_worker

        recover_stale_jobs()
        stop = start_embedded_worker()
    yield
    if stop:
        stop.set()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Traffic Vision API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(videos.router)
    app.include_router(analyses.router)
    app.include_router(batches.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta() -> dict:
        return {"vehicle_types": ALL_VEHICLE_TYPES, "trackers": list(TRACKER_TYPES), "default_model": settings.model_path,
                "speeds": list(SPEEDS), "import_folder": bool(settings.import_dir)}

    # Serve the built frontend (frontend/dist) when present, for single-container deploys.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
