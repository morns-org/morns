from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    receiver_id TEXT NOT NULL,
    packet_id INTEGER,
    from_node TEXT,
    to_node TEXT,
    channel INTEGER,
    portnum TEXT,
    message_text TEXT,
    rssi REAL,
    snr REAL,
    latitude REAL,
    longitude REAL,
    receiver_latitude REAL,
    receiver_longitude REAL,
    transport TEXT NOT NULL CHECK (transport IN ('LORA', 'LOCAL', 'MQTT', 'IMPORT', 'SIMULATOR')),
    raw_json TEXT NOT NULL
)
"""
SCHEMA = CREATE_TABLE.format(table="observations") + """;
CREATE INDEX IF NOT EXISTS observations_received_at_idx ON observations(received_at DESC);
CREATE INDEX IF NOT EXISTS observations_from_node_idx ON observations(from_node, received_at DESC);
CREATE TABLE IF NOT EXISTS receiver_setup (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    setup_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class ObservationStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self.connect() as db:
            existing = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='observations'"
            ).fetchone()
            if existing and "'LOCAL'" not in existing[0]:
                self._migrate_transport_constraint(db)
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(observations)")}
            for name in ("receiver_latitude", "receiver_longitude"):
                if name not in columns:
                    db.execute(f"ALTER TABLE observations ADD COLUMN {name} REAL")

    @staticmethod
    def _migrate_transport_constraint(db: sqlite3.Connection) -> None:
        """Add LOCAL provenance without discarding an existing event log."""
        old_columns = {row[1] for row in db.execute("PRAGMA table_info(observations)")}
        receiver_lat = "receiver_latitude" if "receiver_latitude" in old_columns else "NULL"
        receiver_lon = "receiver_longitude" if "receiver_longitude" in old_columns else "NULL"
        db.execute("DROP TABLE IF EXISTS observations_v2")
        db.execute(CREATE_TABLE.format(table="observations_v2"))
        db.execute(
            f"""INSERT INTO observations_v2
            (id, received_at, receiver_id, packet_id, from_node, to_node, channel,
             portnum, message_text, rssi, snr, latitude, longitude,
             receiver_latitude, receiver_longitude, transport, raw_json)
            SELECT id, received_at, receiver_id, packet_id, from_node, to_node, channel,
             portnum, message_text, rssi, snr, latitude, longitude,
             {receiver_lat}, {receiver_lon}, transport, raw_json FROM observations"""
        )
        db.execute("DROP TABLE observations")
        db.execute("ALTER TABLE observations_v2 RENAME TO observations")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def add(self, observation: dict[str, Any]) -> int:
        fields = {
            "received_at": observation.get("received_at") or datetime.now(timezone.utc).isoformat(),
            "receiver_id": observation.get("receiver_id", "local"),
            "packet_id": observation.get("packet_id"),
            "from_node": observation.get("from_node"),
            "to_node": observation.get("to_node"),
            "channel": observation.get("channel"),
            "portnum": observation.get("portnum"),
            "message_text": observation.get("message_text"),
            "rssi": observation.get("rssi"),
            "snr": observation.get("snr"),
            "latitude": observation.get("latitude"),
            "longitude": observation.get("longitude"),
            "receiver_latitude": observation.get("receiver_latitude"),
            "receiver_longitude": observation.get("receiver_longitude"),
            "transport": observation.get("transport", "LORA"),
            "raw_json": json.dumps(observation.get("raw", observation), separators=(",", ":"), default=str),
        }
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO observations
                (received_at, receiver_id, packet_id, from_node, to_node, channel,
                 portnum, message_text, rssi, snr, latitude, longitude,
                 receiver_latitude, receiver_longitude, transport, raw_json)
                VALUES (:received_at, :receiver_id, :packet_id, :from_node, :to_node, :channel,
                 :portnum, :message_text, :rssi, :snr, :latitude, :longitude,
                 :receiver_latitude, :receiver_longitude, :transport, :raw_json)""",
                fields,
            )
            return int(cursor.lastrowid)

    def recent(self, minutes: int = 60, limit: int = 500, messages_only: bool = False) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        extra = " AND message_text IS NOT NULL" if messages_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM observations WHERE received_at >= ?{extra} ORDER BY received_at DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """SELECT COUNT(*) observations,
                COUNT(DISTINCT CASE WHEN transport = 'LORA' THEN from_node END) nodes,
                SUM(CASE WHEN transport = 'LORA' THEN 1 ELSE 0 END) rf_observations,
                SUM(CASE WHEN transport = 'LOCAL' THEN 1 ELSE 0 END) local_events,
                SUM(CASE WHEN transport = 'LORA' AND message_text IS NOT NULL THEN 1 ELSE 0 END) messages,
                MAX(received_at) last_received_at FROM observations"""
            ).fetchone()
        return dict(row)

    def get_setup(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT setup_json, updated_at FROM receiver_setup WHERE id = 1"
            ).fetchone()
        if not row:
            return None
        setup = json.loads(row["setup_json"])
        setup["updated_at"] = row["updated_at"]
        return setup

    def save_setup(self, setup: dict[str, Any]) -> dict[str, Any]:
        saved = dict(setup)
        saved.pop("updated_at", None)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """INSERT INTO receiver_setup (id, setup_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    setup_json = excluded.setup_json,
                    updated_at = excluded.updated_at""",
                (json.dumps(saved, separators=(",", ":")), updated_at),
            )
        return {**saved, "updated_at": updated_at}
