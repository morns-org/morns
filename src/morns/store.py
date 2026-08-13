from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
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
    transport TEXT NOT NULL CHECK (transport IN ('LORA', 'MQTT', 'IMPORT', 'SIMULATOR')),
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_received_at_idx ON observations(received_at DESC);
CREATE INDEX IF NOT EXISTS observations_from_node_idx ON observations(from_node, received_at DESC);
"""


class ObservationStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self.connect() as db:
            db.executescript(SCHEMA)

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
            "transport": observation.get("transport", "LORA"),
            "raw_json": json.dumps(observation.get("raw", observation), separators=(",", ":"), default=str),
        }
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO observations
                (received_at, receiver_id, packet_id, from_node, to_node, channel,
                 portnum, message_text, rssi, snr, latitude, longitude, transport, raw_json)
                VALUES (:received_at, :receiver_id, :packet_id, :from_node, :to_node, :channel,
                 :portnum, :message_text, :rssi, :snr, :latitude, :longitude, :transport, :raw_json)""",
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
                COUNT(DISTINCT from_node) nodes,
                SUM(CASE WHEN message_text IS NOT NULL THEN 1 ELSE 0 END) messages,
                MAX(received_at) last_received_at FROM observations"""
            ).fetchone()
        return dict(row)
