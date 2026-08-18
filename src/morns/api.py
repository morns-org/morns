from __future__ import annotations

from importlib.resources import files
from datetime import datetime, timezone
import hmac
import hashlib
import platform
import re
import secrets
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from . import __version__
from .config import Settings
from .context_layers import nws_layer
from .geo import location_dataset_info, zcta_center
from .store import ObservationStore

ALLOWED_WINDOWS = {
    0, 5, 10, 30, 60, 360, 720, 1440,
    2880, 10080, 20160, 43200, 129600, 259200, 525600,
}
MAP_WINDOWS = {0, 5, 30, 60, 360, 1440, 2880, 10080, 20160, 43200, 129600, 259200, 525600}


def create_app(settings: Settings | None = None, store: ObservationStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or ObservationStore(settings.database_path)
    app = FastAPI(title="MORNS Station", version=__version__)
    app.state.settings = settings
    app.state.store = store
    app.state.started_at = datetime.now(timezone.utc)

    def receiver_config() -> dict[str, Any]:
        setup = store.get_setup() or {}
        return {
            "station_name": setup.get("station_name", settings.station_name),
            "location_policy": setup.get("location_policy"),
            "latitude": setup.get("latitude", settings.station_latitude),
            "longitude": setup.get("longitude", settings.station_longitude),
            "radius_km": setup.get("radius_km", settings.station_radius_km),
            "server_timezone": setup.get("server_timezone", "UTC"),
            "observation_retention_days": setup.get("observation_retention_days", 365),
            "message_retention_days": setup.get("message_retention_days", 30),
            "base_station_telemetry_archive_days": setup.get(
                "base_station_telemetry_archive_days", 30
            ),
            "map_windows_minutes": sorted(
                set(setup.get("map_windows_minutes", sorted(MAP_WINDOWS))) | {0}
            ),
            "setup_complete": bool(setup),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return files("morns").joinpath("templates/dashboard.html").read_text(encoding="utf-8")

    @app.get("/setup", include_in_schema=False)
    def setup_screen() -> RedirectResponse:
        return RedirectResponse(url="/#settings")

    @app.get("/health")
    def health() -> dict[str, Any]:
        receiver = receiver_config()
        return {
            "status": "ok",
            "version": __version__,
            "host_system": platform.system(),
            "host_architecture": platform.machine(),
            "station": receiver["station_name"],
            "simulator": settings.simulator,
            "radio_configured": bool(settings.serial_port),
            "serial_port": settings.serial_port,
            "remote_ingest_enabled": bool(settings.ingest_token),
            "station_latitude": receiver["latitude"],
            "station_longitude": receiver["longitude"],
            "station_radius_km": receiver["radius_km"],
            "server_timezone": receiver["server_timezone"],
            "location_policy": receiver["location_policy"],
            "observation_retention_days": receiver["observation_retention_days"],
            "message_retention_days": receiver["message_retention_days"],
            "base_station_telemetry_archive_days": receiver[
                "base_station_telemetry_archive_days"
            ],
            "map_windows_minutes": receiver["map_windows_minutes"],
            "setup_complete": receiver["setup_complete"],
        }

    @app.get("/api/v1/setup")
    def get_setup() -> dict[str, Any]:
        return store.get_setup() or receiver_config()

    @app.put("/api/v1/setup")
    def put_setup(setup: dict[str, Any]) -> dict[str, Any]:
        name = str(setup.get("station_name", "")).strip()
        policy = setup.get("location_policy")
        location_method = setup.get("location_method")
        country_code = str(setup.get("country_code", "US")).upper()
        postal_code = str(setup.get("postal_code", "")).strip() or None
        server_timezone = str(setup.get("server_timezone", "UTC")).strip()
        try:
            latitude = float(setup.get("latitude"))
            longitude = float(setup.get("longitude"))
            radius_km = float(setup.get("radius_km"))
            observation_retention_days = int(setup.get("observation_retention_days", 365))
            message_retention_days = int(setup.get("message_retention_days", 30))
            base_station_telemetry_archive_days = int(
                setup.get("base_station_telemetry_archive_days", 30)
            )
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Coordinates, radius, and retention must be numbers")
        map_windows = setup.get("map_windows_minutes", sorted(MAP_WINDOWS))
        if not name or len(name) > 80:
            raise HTTPException(status_code=422, detail="Receiver name is required (80 characters maximum)")
        if policy not in {"precise", "approximate", "private"}:
            raise HTTPException(status_code=422, detail="Choose a valid location policy")
        if location_method not in {"postal_code", "browser", "manual"}:
            raise HTTPException(status_code=422, detail="Choose a valid location method")
        if country_code not in {"US", "CA"}:
            raise HTTPException(status_code=422, detail="This release supports United States and Canada receiver setup")
        try:
            ZoneInfo(server_timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(status_code=422, detail="Choose a valid IANA server time zone")
        if location_method == "postal_code" and country_code != "US":
            raise HTTPException(status_code=422, detail="Canadian postal-area lookup is not bundled yet; use device location or manual coordinates")
        if location_method == "postal_code" and not re.fullmatch(r"\d{5}", postal_code or ""):
            raise HTTPException(status_code=422, detail="Enter a five-digit US ZIP code")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise HTTPException(status_code=422, detail="Coordinates are outside valid ranges")
        if not 0.1 <= radius_km <= 500:
            raise HTTPException(status_code=422, detail="Observation radius must be between 0.1 and 500 km")
        if observation_retention_days not in {7, 30, 90, 365}:
            raise HTTPException(status_code=422, detail="Choose a valid observation retention period")
        if message_retention_days not in {1, 7, 30}:
            raise HTTPException(status_code=422, detail="Message retention cannot exceed 30 days")
        if message_retention_days > observation_retention_days:
            raise HTTPException(status_code=422, detail="Message retention cannot exceed observation retention")
        if base_station_telemetry_archive_days not in {1, 7, 30, 90}:
            raise HTTPException(
                status_code=422,
                detail="Choose a valid base-station telemetry archive period",
            )
        if base_station_telemetry_archive_days > observation_retention_days:
            raise HTTPException(
                status_code=422,
                detail="Base-station telemetry archive after cannot exceed observation retention",
            )
        if not isinstance(map_windows, list) or not map_windows or any(
            not isinstance(window, int) or window not in MAP_WINDOWS
            or window > observation_retention_days * 1440 for window in map_windows
        ):
            raise HTTPException(status_code=422, detail="Choose map ranges within the observation retention period")
        return store.save_setup({
            "station_name": name,
            "location_policy": policy,
            "location_method": location_method,
            "country_code": country_code,
            "postal_code": postal_code,
            "location_accuracy_m": setup.get("location_accuracy_m"),
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_km,
            "server_timezone": server_timezone,
            "observation_retention_days": observation_retention_days,
            "message_retention_days": message_retention_days,
            "base_station_telemetry_archive_days": base_station_telemetry_archive_days,
            "map_windows_minutes": sorted(set(map_windows)),
        })

    @app.get("/api/v1/location/postal-code")
    def postal_code_center(postal_code: str = Query(min_length=5, max_length=5)) -> dict[str, Any]:
        if not re.fullmatch(r"\d{5}", postal_code):
            raise HTTPException(status_code=422, detail="Enter a five-digit US ZIP code")
        center = zcta_center(postal_code)
        if center is None:
            raise HTTPException(status_code=404, detail="No Census ZCTA center exists for this ZIP code")
        return {
            "postal_code": postal_code,
            "latitude": center[0],
            "longitude": center[1],
            **location_dataset_info(),
        }

    @app.get("/api/v1/location/datasets")
    def location_datasets() -> dict[str, Any]:
        return {
            "datasets": [location_dataset_info()],
            "update_policy": "Dataset updates ship with signed MORNS software releases; saved receiver locations never move automatically.",
        }

    @app.get("/api/v1/map-layers/{layer_name}")
    def contextual_map_layer(layer_name: str) -> dict[str, Any]:
        if layer_name not in {"weather-stations", "weather-alerts"}:
            raise HTTPException(status_code=404, detail="Unknown contextual map layer")
        receiver = receiver_config()
        latitude, longitude = receiver["latitude"], receiver["longitude"]
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            raise HTTPException(status_code=409, detail="Configure the base-station location before loading local context layers")
        try:
            return nws_layer(layer_name, latitude, longitude)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=f"Context provider unavailable: {exc}") from exc

    @app.post("/api/v1/ingest", status_code=status.HTTP_202_ACCEPTED)
    def ingest(
        observation: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, int | str]:
        local_credential = store.local_collector_credential()
        if not settings.ingest_token and not local_credential:
            raise HTTPException(status_code=503, detail="Remote ingestion is not configured")
        scheme, _, supplied = (authorization or "").partition(" ")
        local_match = bool(local_credential) and hmac.compare_digest(
            hashlib.sha256(supplied.encode()).hexdigest(), local_credential["token_hash"]
        )
        environment_match = bool(settings.ingest_token) and hmac.compare_digest(supplied, settings.ingest_token)
        if scheme.lower() != "bearer" or not (local_match or environment_match):
            raise HTTPException(status_code=401, detail="Invalid station token")
        if observation.get("transport") not in {"LORA", "LOCAL"}:
            raise HTTPException(status_code=422, detail="Collector must classify physical RF or local-device events")
        receiver = receiver_config()
        observation["receiver_latitude"] = receiver["latitude"]
        observation["receiver_longitude"] = receiver["longitude"]
        row_id = store.add(observation)
        if local_match:
            store.mark_local_collector_used()
        return {"status": "accepted", "id": row_id}

    @app.get("/api/v1/local-collector")
    def local_collector_status() -> dict[str, Any]:
        credential = store.local_collector_credential()
        if not credential:
            return {"configured": False}
        return {"configured": True, **{k: credential[k] for k in ("token_prefix", "created_at", "last_used_at")}}

    @app.post("/api/v1/local-collector/credential")
    def create_local_collector_credential(request: Request) -> dict[str, Any]:
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="Local collector credentials can only be created from this computer")
        token = "morns_local_" + secrets.token_urlsafe(32)
        metadata = store.save_local_collector_credential(
            hashlib.sha256(token.encode()).hexdigest(), token[:18]
        )
        return {"token": token, **metadata, "warning": "Copy this credential now; MORNS will not show it again."}

    @app.get("/api/v1/stats")
    def stats() -> dict:
        receiver = receiver_config()
        store.enforce_retention(
            receiver["observation_retention_days"],
            receiver["message_retention_days"],
            receiver["base_station_telemetry_archive_days"],
        )
        return {
            "station": receiver["station_name"],
            "observation_retention_days": receiver["observation_retention_days"],
            "message_retention_days": receiver["message_retention_days"],
            "base_station_telemetry_archive_days": receiver[
                "base_station_telemetry_archive_days"
            ],
            "map_windows_minutes": receiver["map_windows_minutes"],
            **store.stats(),
        }

    @app.get("/api/v1/base-station/stats")
    def base_station_stats(minutes: int = Query(60)) -> dict[str, Any]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        receiver = receiver_config()
        measured = store.base_station_stats(
            minutes, receiver["latitude"], receiver["longitude"]
        )
        health_window = store.base_station_stats(10)
        lifetime = store.base_station_stats(0)
        last = lifetime.get("last_received_at")
        age_seconds = None
        if last:
            age_seconds = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds())
        if settings.simulator:
            health_state, health_reason = "simulator", "Generated test data is enabled"
        elif not settings.serial_port and not settings.ingest_token:
            health_state, health_reason = "not_connected", "No collector or serial receiver is configured"
        elif lifetime["observations"] == 0:
            health_state, health_reason = "awaiting_data", "Receiver is configured but no observations have arrived"
        elif health_window["rf_observations"] > 0:
            health_state, health_reason = "healthy", "Over-the-air observations are arriving"
        elif health_window["local_events"] > 0:
            health_state, health_reason = "radio_idle", "Receiver is connected; no over-the-air observation arrived in the last 10 minutes"
        else:
            health_state, health_reason = "stale", "No observation has arrived in the last 10 minutes"
        return {
            "station": receiver["station_name"],
            "operational_uptime_seconds": int((datetime.now(timezone.utc) - app.state.started_at).total_seconds()),
            "health": health_state,
            "health_reason": health_reason,
            "last_observation_age_seconds": age_seconds,
            **measured,
        }

    @app.get("/api/v1/observations")
    def observations(
        minutes: int = Query(60),
        limit: int = Query(500, ge=1, le=5000),
        include_base_station_telemetry: bool = Query(True),
    ) -> list[dict]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.recent(
            minutes=minutes,
            limit=limit,
            include_base_station_telemetry=include_base_station_telemetry,
        )

    @app.get("/api/v1/messages")
    def messages(
        minutes: int = Query(60), limit: int = Query(500, ge=1, le=5000)
    ) -> list[dict]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.recent(minutes=minutes, limit=limit, messages_only=True)

    @app.get("/api/v1/messages/observability")
    def message_observability(minutes: int = Query(60)) -> dict[str, int]:
        """Report readable messages separately from packets whose contents are unknown."""
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.message_observability(minutes)

    @app.get("/api/v1/nodes")
    def nodes(minutes: int = Query(60)) -> list[dict[str, Any]]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        return store.nodes(minutes=minutes)

    @app.get("/api/v1/nodes/{node_id}")
    def node_detail(node_id: str, minutes: int = Query(60)) -> dict[str, Any]:
        if minutes not in ALLOWED_WINDOWS:
            minutes = 60
        node = next((item for item in store.nodes(minutes=minutes) if item["node_id"] == node_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail="Node was not observed in this time window")
        return node

    @app.get("/api/v1/nodes/{node_id}/positions")
    def node_positions(node_id: str, limit: int = Query(1000, ge=1, le=5000)) -> list[dict[str, Any]]:
        return store.position_history(node_id, limit=limit)

    return app
