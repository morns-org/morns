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

    def receiver_config() -> dict[str, Any]:
        setup = store.get_setup() or {}
        return {
            "station_name": setup.get("station_name", settings.station_name),
            "location_policy": setup.get("location_policy"),
            "latitude": setup.get("latitude", settings.station_latitude),
            "longitude": setup.get("longitude", settings.station_longitude),
            "radius_km": setup.get("radius_km", settings.station_radius_km),
            "setup_complete": bool(setup),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return files("morns").joinpath("templates/dashboard.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, str | bool | float | None]:
        receiver = receiver_config()
        return {
            "status": "ok",
            "version": __version__,
            "station": receiver["station_name"],
            "simulator": settings.simulator,
            "radio_configured": bool(settings.serial_port),
            "serial_port": settings.serial_port,
            "remote_ingest_enabled": bool(settings.ingest_token),
            "station_latitude": receiver["latitude"],
            "station_longitude": receiver["longitude"],
            "station_radius_km": receiver["radius_km"],
            "location_policy": receiver["location_policy"],
            "setup_complete": receiver["setup_complete"],
        }

    @app.get("/api/v1/setup")
    def get_setup() -> dict[str, Any]:
        return store.get_setup() or receiver_config()

    @app.put("/api/v1/setup")
    def put_setup(setup: dict[str, Any]) -> dict[str, Any]:
        name = str(setup.get("station_name", "")).strip()
        policy = setup.get("location_policy")
        try:
            latitude = float(setup.get("latitude"))
            longitude = float(setup.get("longitude"))
            radius_km = float(setup.get("radius_km"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Coordinates and radius must be numbers")
        if not name or len(name) > 80:
            raise HTTPException(status_code=422, detail="Receiver name is required (80 characters maximum)")
        if policy not in {"precise", "approximate", "private"}:
            raise HTTPException(status_code=422, detail="Choose a valid location policy")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise HTTPException(status_code=422, detail="Coordinates are outside valid ranges")
        if not 0.1 <= radius_km <= 500:
            raise HTTPException(status_code=422, detail="Observation radius must be between 0.1 and 500 km")
        return store.save_setup({
            "station_name": name,
            "location_policy": policy,
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_km,
        })

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
        if observation.get("transport") not in {"LORA", "LOCAL"}:
            raise HTTPException(status_code=422, detail="Collector must classify physical RF or local-device events")
        receiver = receiver_config()
        observation["receiver_latitude"] = receiver["latitude"]
        observation["receiver_longitude"] = receiver["longitude"]
        row_id = store.add(observation)
        return {"status": "accepted", "id": row_id}

    @app.get("/api/v1/stats")
    def stats() -> dict:
        return {"station": receiver_config()["station_name"], **store.stats()}

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
