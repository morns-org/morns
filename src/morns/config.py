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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("MORNS_DATABASE", "morns.db")),
            station_name=os.getenv("MORNS_STATION_NAME", "MORNs Station"),
            serial_port=os.getenv("MORNS_SERIAL_PORT") or None,
            host=os.getenv("MORNS_HOST", "127.0.0.1"),
            port=int(os.getenv("MORNS_PORT", "8787")),
            simulator=os.getenv("MORNS_SIMULATOR", "false").lower() in {"1", "true", "yes"},
        )
