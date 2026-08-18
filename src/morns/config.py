from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    station_name: str
    serial_port: str | None
    host: str
    port: int
    simulator: bool
    ingest_token: str | None = None
    station_latitude: float | None = None
    station_longitude: float | None = None
    station_radius_km: float = 8.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("MORNS_DATABASE", "morns.db")),
            station_name=os.getenv("MORNS_STATION_NAME", "MORNS Station"),
            serial_port=os.getenv("MORNS_SERIAL_PORT") or None,
            host=os.getenv("MORNS_HOST", "127.0.0.1"),
            port=int(os.getenv("MORNS_PORT", "8787")),
            simulator=os.getenv("MORNS_SIMULATOR", "false").lower() in {"1", "true", "yes"},
            ingest_token=os.getenv("MORNS_INGEST_TOKEN") or None,
            station_latitude=_optional_float(os.getenv("MORNS_STATION_LATITUDE")),
            station_longitude=_optional_float(os.getenv("MORNS_STATION_LONGITUDE")),
            station_radius_km=float(os.getenv("MORNS_STATION_RADIUS_KM", "8")),
        )


def _optional_float(value: str | None) -> float | None:
    return float(value) if value not in {None, ""} else None
