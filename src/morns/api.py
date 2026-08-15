from __future__ import annotations

from importlib.resources import files
import hmac
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from . import __version__
from .config import Settings
from .store import ObservationStore

ALLOWED_WINDOWS = {5, 10, 30, 60, 360, 720, 1440, 10080, 43200}


def create_app(settings: Settings | None = None, store: ObservationStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or ObservationStore(settings.database_path)
    app = FastAPI(title="MORNs Station", version=__version__)
    app.state.settings = settings
    app.state.store = store

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return files("morns").joinpath("templates/dashboard.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, str | bool | None]:
        return {
            "status": "ok",
            "version": __version__,
            "station": settings.station_name,
            "simulator": settings.simulator,
            "radio_configured": bool(settings.serial_port),
            "serial_port": settings.serial_port,
            "remote_ingest_enabled": bool(settings.ingest_token),
        }

    @app.post("/api/v1/ingest", status_code=status.HTTP_202_ACCEPTED)
    def ingest(
        observation: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, int | str]:
        if not settings.ingest_token:
            raise HTTPException(status_code=503, detail="Remote ingestion is not configured")
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, settings.ingest_token):
            raise HTTPException(status_code=401, detail="Invalid station token")
        if observation.get("transport") not in {None, "LORA"}:
            raise HTTPException(status_code=422, detail="Collector ingest accepts LoRa observations only")
        observation["transport"] = "LORA"
        row_id = store.add(observation)
        return {"status": "accepted", "id": row_id}

    @app.get("/api/v1/stats")
    def stats() -> dict:
        return {"station": settings.station_name, **store.stats()}

    @app.get("/api/v1/observations")
    def observations(
        minutes: int = Query(60), limit: int = Query(500, ge=1, le=5000)
    ) -> list[dict]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.recent(minutes=minutes, limit=limit)

    @app.get("/api/v1/messages")
    def messages(
        minutes: int = Query(60), limit: int = Query(500, ge=1, le=5000)
    ) -> list[dict]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.recent(minutes=minutes, limit=limit, messages_only=True)

    return app
