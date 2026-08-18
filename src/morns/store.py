from __future__ import annotations

import json
import math
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
    content_state TEXT,
    rssi REAL,
    snr REAL,
    latitude REAL,
    longitude REAL,
    receiver_latitude REAL,
    receiver_longitude REAL,
    ingress_transport TEXT,
    transport TEXT NOT NULL CHECK (transport IN ('LORA', 'LOCAL', 'MQTT', 'IMPORT', 'SIMULATOR')),
    raw_json TEXT NOT NULL
)
"""
ARCHIVE_TABLE = CREATE_TABLE.format(table="archived_base_station_telemetry").replace(
    "raw_json TEXT NOT NULL\n)",
    "raw_json TEXT NOT NULL,\n    archived_at TEXT NOT NULL\n)",
)
SCHEMA = CREATE_TABLE.format(table="observations") + ";\n" + ARCHIVE_TABLE + """;
CREATE INDEX IF NOT EXISTS observations_received_at_idx ON observations(received_at DESC);
CREATE INDEX IF NOT EXISTS observations_from_node_idx ON observations(from_node, received_at DESC);
CREATE INDEX IF NOT EXISTS archived_telemetry_received_at_idx
    ON archived_base_station_telemetry(received_at DESC);
CREATE TABLE IF NOT EXISTS receiver_setup (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    setup_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_collector_credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    token_hash TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS node_mobility_state (
    node_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    last_evaluated_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_mobility_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mobility_transitions_node_idx
    ON node_mobility_transitions(node_id, detected_at DESC);
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
            if "ingress_transport" not in columns:
                db.execute("ALTER TABLE observations ADD COLUMN ingress_transport TEXT")
            if "content_state" not in columns:
                db.execute("ALTER TABLE observations ADD COLUMN content_state TEXT")
            self._backfill_content_state(db)

    @staticmethod
    def _backfill_content_state(db: sqlite3.Connection) -> None:
        """Classify retained packets without treating encrypted payloads as chats."""
        rows = db.execute(
            """SELECT id, transport, portnum, message_text, raw_json FROM observations
            WHERE content_state IS NULL"""
        ).fetchall()
        for row in rows:
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except (TypeError, ValueError):
                raw = {}
            state = _content_state(
                row["transport"], row["portnum"], row["message_text"], raw
            )
            db.execute(
                "UPDATE observations SET content_state = ? WHERE id = ?",
                (state, row["id"]),
            )

    @staticmethod
    def _migrate_transport_constraint(db: sqlite3.Connection) -> None:
        """Add LOCAL provenance without discarding an existing event log."""
        old_columns = {row[1] for row in db.execute("PRAGMA table_info(observations)")}
        receiver_lat = "receiver_latitude" if "receiver_latitude" in old_columns else "NULL"
        receiver_lon = "receiver_longitude" if "receiver_longitude" in old_columns else "NULL"
        ingress = "ingress_transport" if "ingress_transport" in old_columns else "NULL"
        content_state = "content_state" if "content_state" in old_columns else "NULL"
        db.execute("DROP TABLE IF EXISTS observations_v2")
        db.execute(CREATE_TABLE.format(table="observations_v2"))
        db.execute(
            f"""INSERT INTO observations_v2
            (id, received_at, receiver_id, packet_id, from_node, to_node, channel,
             portnum, message_text, content_state, rssi, snr, latitude, longitude,
             receiver_latitude, receiver_longitude, ingress_transport, transport, raw_json)
            SELECT id, received_at, receiver_id, packet_id, from_node, to_node, channel,
             portnum, message_text, {content_state}, rssi, snr, latitude, longitude,
             {receiver_lat}, {receiver_lon}, {ingress}, transport, raw_json FROM observations"""
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
        raw = observation.get("raw", observation)
        transport = observation.get("transport", "LORA")
        fields = {
            "received_at": observation.get("received_at") or datetime.now(timezone.utc).isoformat(),
            "receiver_id": observation.get("receiver_id", "local"),
            "packet_id": observation.get("packet_id"),
            "from_node": observation.get("from_node"),
            "to_node": observation.get("to_node"),
            "channel": observation.get("channel"),
            "portnum": observation.get("portnum"),
            "message_text": observation.get("message_text"),
            "content_state": _content_state(
                transport, observation.get("portnum"), observation.get("message_text"), raw
            ),
            "rssi": observation.get("rssi"),
            "snr": observation.get("snr"),
            "latitude": observation.get("latitude"),
            "longitude": observation.get("longitude"),
            "receiver_latitude": observation.get("receiver_latitude"),
            "receiver_longitude": observation.get("receiver_longitude"),
            "ingress_transport": observation.get("ingress_transport"),
            "transport": transport,
            "raw_json": json.dumps(raw, separators=(",", ":"), default=str),
        }
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO observations
                (received_at, receiver_id, packet_id, from_node, to_node, channel,
                 portnum, message_text, content_state, rssi, snr, latitude, longitude,
                 receiver_latitude, receiver_longitude, ingress_transport, transport, raw_json)
                VALUES (:received_at, :receiver_id, :packet_id, :from_node, :to_node, :channel,
                 :portnum, :message_text, :content_state, :rssi, :snr, :latitude, :longitude,
                 :receiver_latitude, :receiver_longitude, :ingress_transport, :transport, :raw_json)""",
                fields,
            )
            return int(cursor.lastrowid)

    def recent(
        self,
        minutes: int = 60,
        limit: int = 500,
        messages_only: bool = False,
        include_base_station_telemetry: bool = True,
    ) -> list[dict[str, Any]]:
        since = (
            "0001-01-01T00:00:00+00:00"
            if minutes == 0
            else (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        )
        filters = (
            " AND message_text IS NOT NULL AND content_state = 'decoded_public_message'"
            if messages_only else ""
        )
        if not include_base_station_telemetry:
            filters += " AND NOT (transport = 'LOCAL' AND portnum = 'TELEMETRY_APP')"
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM observations WHERE received_at >= ?{filters} ORDER BY received_at DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            try:
                raw = json.loads(result["raw_json"])
            except (TypeError, ValueError):
                raw = {}
            hop_start = raw.get("hopStart")
            hop_limit = raw.get("hopLimit")
            result["hops_away"] = (
                max(0, int(hop_start) - int(hop_limit or 0))
                if hop_start is not None
                else None
            )
            results.append(result)
        return results

    def nodes(self, minutes: int = 60) -> list[dict[str, Any]]:
        """Build provenance-aware node records from retained physical RF observations."""
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM observations
                WHERE received_at >= ? AND transport = 'LORA' AND from_node IS NOT NULL
                ORDER BY received_at ASC""",
                (since,),
            ).fetchall()
        records: dict[str, dict[str, Any]] = {}
        for sql_row in rows:
            row = dict(sql_row)
            node_id = row["from_node"]
            record = records.setdefault(node_id, {
                "node_id": node_id, "first_heard": row["received_at"], "last_heard": row["received_at"],
                "observations": 0, "receivers": set(), "packet_types": set(), "best_rssi": None,
                "latest_rssi": None, "latest_snr": None, "hops_away": None,
                "long_name": None, "short_name": None, "hardware_model": None, "role": None,
                "public_key_available": False, "battery_level": None, "voltage": None,
                "uptime_seconds": None, "channel_utilization": None, "air_util_tx": None,
                "latitude": None, "longitude": None, "altitude": None, "position_source": None,
                "position_precision_bits": None, "position_updated_at": None,
                "declared_updated_at": None, "telemetry_updated_at": None,
            })
            record["last_heard"] = row["received_at"]
            record["observations"] += 1
            record["receivers"].add(row["receiver_id"])
            if row["portnum"]:
                record["packet_types"].add(row["portnum"])
            if row["rssi"] is not None:
                record["latest_rssi"] = row["rssi"]
                record["latest_snr"] = row["snr"]
                record["best_rssi"] = max(record["best_rssi"] or -999, row["rssi"])
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                raw = {}
            decoded = raw.get("decoded") or {}
            if user := decoded.get("user"):
                record.update({
                    "long_name": user.get("longName") or user.get("long_name"),
                    "short_name": user.get("shortName") or user.get("short_name"),
                    "hardware_model": user.get("hwModel") or user.get("hw_model"),
                    "role": user.get("role"),
                    "public_key_available": bool(user.get("publicKey") or user.get("public_key")),
                    "declared_updated_at": row["received_at"],
                })
            if telemetry := decoded.get("telemetry"):
                metrics = telemetry.get("deviceMetrics") or telemetry.get("device_metrics") or {}
                for source, target in (("batteryLevel", "battery_level"), ("voltage", "voltage"),
                    ("uptimeSeconds", "uptime_seconds"), ("channelUtilization", "channel_utilization"),
                    ("airUtilTx", "air_util_tx")):
                    value = metrics.get(source, metrics.get(target))
                    if value is not None:
                        record[target] = value
                record["telemetry_updated_at"] = row["received_at"]
            if position := decoded.get("position"):
                record.update({
                    "latitude": row["latitude"], "longitude": row["longitude"],
                    "altitude": position.get("altitude"),
                    "position_source": position.get("locationSource") or position.get("location_source"),
                    "position_precision_bits": position.get("precisionBits") or position.get("precision_bits"),
                    "position_updated_at": row["received_at"],
                })
            hop_start = raw.get("hopStart")
            hop_limit = raw.get("hopLimit")
            if hop_start is not None:
                record["hops_away"] = max(0, hop_start - (hop_limit or 0))
        mobility = self.refresh_mobility_states()
        result = []
        for record in records.values():
            record["receivers"] = sorted(record["receivers"])
            record["packet_types"] = sorted(record["packet_types"])
            record["mobility"] = mobility.get(record["node_id"], {
                "state": "unknown", "changed_at": None, "evidence": {}, "transitions": []
            })
            result.append(record)
        return sorted(result, key=lambda item: item["last_heard"], reverse=True)

    def position_history(self, node_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Return every retained node-declared position, newest first."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT received_at, receiver_id, latitude, longitude, raw_json
                FROM observations WHERE from_node = ? AND transport = 'LORA'
                AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY received_at DESC LIMIT ?""",
                (node_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                raw = {}
            position = (raw.get("decoded") or {}).get("position") or {}
            result.append({
                "received_at": row["received_at"], "receiver_id": row["receiver_id"],
                "latitude": row["latitude"], "longitude": row["longitude"],
                "altitude": position.get("altitude"),
                "source": position.get("locationSource") or position.get("location_source"),
                "precision_bits": position.get("precisionBits") or position.get("precision_bits"),
            })
        return result

    def refresh_mobility_states(self) -> dict[str, dict[str, Any]]:
        """Classify retained tracks and record meaningful state changes."""
        with self.connect() as db:
            node_rows = db.execute(
                """SELECT DISTINCT from_node FROM observations WHERE transport='LORA'
                AND latitude IS NOT NULL AND longitude IS NOT NULL AND from_node IS NOT NULL"""
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for node_row in node_rows:
            node_id = node_row["from_node"]
            track = list(reversed(self.position_history(node_id)))
            classification = _classify_mobility(track)
            now = datetime.now(timezone.utc).isoformat()
            with self.connect() as db:
                previous = db.execute(
                    "SELECT state, changed_at FROM node_mobility_state WHERE node_id=?", (node_id,)
                ).fetchone()
                old_state = previous["state"] if previous else "unknown"
                changed_at = previous["changed_at"] if previous else now
                new_state = classification["state"]
                if new_state != "unknown" and new_state != old_state:
                    changed_at = now
                    db.execute(
                        """INSERT INTO node_mobility_transitions
                        (node_id, from_state, to_state, detected_at, evidence_json)
                        VALUES (?, ?, ?, ?, ?)""",
                        (node_id, old_state, new_state, now, json.dumps(classification["evidence"])),
                    )
                    old_state = new_state
                elif previous:
                    new_state = old_state
                db.execute(
                    """INSERT INTO node_mobility_state
                    (node_id, state, changed_at, last_evaluated_at, evidence_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET state=excluded.state,
                    changed_at=excluded.changed_at, last_evaluated_at=excluded.last_evaluated_at,
                    evidence_json=excluded.evidence_json""",
                    (node_id, new_state, changed_at, now, json.dumps(classification["evidence"])),
                )
                transitions = db.execute(
                    """SELECT from_state, to_state, detected_at, evidence_json
                    FROM node_mobility_transitions WHERE node_id=? ORDER BY detected_at DESC""",
                    (node_id,),
                ).fetchall()
            result[node_id] = {
                "state": new_state, "changed_at": changed_at,
                "evidence": classification["evidence"],
                "transitions": [{**dict(item), "evidence": json.loads(item["evidence_json"])} for item in transitions],
            }
            for item in result[node_id]["transitions"]:
                item.pop("evidence_json", None)
        return result

    def stats(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """SELECT COUNT(*) observations,
                COUNT(DISTINCT CASE WHEN transport = 'LORA' THEN from_node END) nodes,
                SUM(CASE WHEN transport = 'LORA' THEN 1 ELSE 0 END) rf_observations,
                SUM(CASE WHEN transport = 'LOCAL' THEN 1 ELSE 0 END) local_events,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'decoded_public_message' THEN 1 ELSE 0 END), 0) messages,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state IN ('decoded_packet', 'decoded_public_message') THEN 1 ELSE 0 END), 0) decoded_packets,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'encrypted_undecodable' THEN 1 ELSE 0 END), 0) encrypted_undecodable_packets,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'undecodable' THEN 1 ELSE 0 END), 0) other_undecodable_packets,
                MIN(received_at) oldest_received_at,
                MAX(received_at) last_received_at FROM observations"""
            ).fetchone()
            archived = db.execute(
                """SELECT COUNT(*) observations,
                MIN(received_at) oldest_received_at,
                MAX(received_at) newest_received_at
                FROM archived_base_station_telemetry"""
            ).fetchone()
        result = dict(row)
        result["archived_base_station_telemetry"] = dict(archived)
        return result

    def message_observability(self, minutes: int = 60) -> dict[str, int]:
        """Describe what was readable without guessing that ciphertext was a chat."""
        since = "0001-01-01T00:00:00+00:00" if minutes == 0 else (
            datetime.now(timezone.utc) - timedelta(minutes=minutes)
        ).isoformat()
        with self.connect() as db:
            row = db.execute(
                """SELECT
                COUNT(*) rf_packets,
                COALESCE(SUM(CASE WHEN content_state IN ('decoded_packet', 'decoded_public_message') THEN 1 ELSE 0 END), 0) decoded_packets,
                COALESCE(SUM(CASE WHEN content_state = 'decoded_public_message' THEN 1 ELSE 0 END), 0) decoded_public_messages,
                COALESCE(SUM(CASE WHEN content_state = 'encrypted_undecodable' THEN 1 ELSE 0 END), 0) encrypted_undecodable_packets,
                COALESCE(SUM(CASE WHEN content_state = 'undecodable' THEN 1 ELSE 0 END), 0) other_undecodable_packets
                FROM observations WHERE received_at >= ? AND transport = 'LORA'""",
                (since,),
            ).fetchone()
        result = dict(row)
        result["window_minutes"] = minutes
        result["undecodable_packets"] = (
            result["encrypted_undecodable_packets"] + result["other_undecodable_packets"]
        )
        return result

    def base_station_stats(
        self,
        minutes: int = 60,
        fallback_receiver_latitude: float | None = None,
        fallback_receiver_longitude: float | None = None,
    ) -> dict[str, Any]:
        """Return measured station statistics for one explicit time window."""
        since = "0001-01-01T00:00:00+00:00" if minutes == 0 else (
            datetime.now(timezone.utc) - timedelta(minutes=minutes)
        ).isoformat()
        bucket_seconds = 86400 if minutes == 0 else 300 if minutes <= 60 else 3600 if minutes <= 1440 else 86400
        with self.connect() as db:
            totals = dict(db.execute(
                """SELECT COUNT(*) observations,
                COUNT(DISTINCT CASE WHEN transport = 'LORA' THEN from_node END) nodes,
                COALESCE(SUM(CASE WHEN transport = 'LORA' THEN 1 ELSE 0 END), 0) rf_observations,
                COALESCE(SUM(CASE WHEN transport = 'LOCAL' THEN 1 ELSE 0 END), 0) local_events,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'decoded_public_message' THEN 1 ELSE 0 END), 0) messages,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'encrypted_undecodable' THEN 1 ELSE 0 END), 0) encrypted_undecodable_packets,
                COALESCE(SUM(CASE WHEN transport = 'LORA' AND content_state = 'undecodable' THEN 1 ELSE 0 END), 0) other_undecodable_packets,
                MIN(received_at) first_received_at,
                MAX(received_at) last_received_at,
                MAX(CASE WHEN transport = 'LORA' THEN received_at END) last_rf_received_at
                FROM observations WHERE received_at >= ?""",
                (since,),
            ).fetchone())
            buckets = db.execute(
                """SELECT CAST(strftime('%s', received_at) AS INTEGER) / ? bucket,
                COUNT(*) observations,
                COUNT(DISTINCT CASE WHEN transport = 'LORA' THEN from_node END) nodes,
                SUM(CASE WHEN transport = 'LORA' AND content_state = 'decoded_public_message' THEN 1 ELSE 0 END) messages
                FROM observations WHERE received_at >= ?
                GROUP BY bucket""",
                (bucket_seconds, since),
            ).fetchall()
            positioned = db.execute(
                """SELECT from_node, latitude, longitude, receiver_latitude, receiver_longitude,
                received_at, portnum, rssi, snr, raw_json FROM observations
                WHERE received_at >= ? AND transport = 'LORA'
                AND latitude IS NOT NULL AND longitude IS NOT NULL
                """,
                (since,),
            ).fetchall()

        farthest: dict[str, Any] | None = None
        for row in positioned:
            receiver_latitude = row["receiver_latitude"]
            receiver_longitude = row["receiver_longitude"]
            if receiver_latitude is None:
                receiver_latitude = fallback_receiver_latitude
            if receiver_longitude is None:
                receiver_longitude = fallback_receiver_longitude
            if receiver_latitude is None or receiver_longitude is None:
                continue
            distance = _haversine_km(
                receiver_latitude, receiver_longitude,
                row["latitude"], row["longitude"],
            )
            if farthest is None or distance > farthest["distance_km"]:
                raw = json.loads(row["raw_json"] or "{}")
                hop_start = raw.get("hopStart")
                hop_limit = raw.get("hopLimit")
                farthest = {
                    "node_id": row["from_node"],
                    "distance_km": round(distance, 2),
                    "received_at": row["received_at"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "portnum": row["portnum"],
                    "rssi": row["rssi"],
                    "snr": row["snr"],
                    "via_mqtt": bool(raw.get("viaMqtt")),
                    "hops_away": max(0, hop_start - hop_limit)
                    if isinstance(hop_start, int) and isinstance(hop_limit, int)
                    else None,
                }
        return {
            "window_minutes": minutes,
            "bucket_minutes": bucket_seconds // 60,
            **totals,
            "peak_observations": max((row["observations"] for row in buckets), default=0),
            "peak_nodes": max((row["nodes"] for row in buckets), default=0),
            "peak_messages": max((row["messages"] or 0 for row in buckets), default=0),
            "farthest_contact": farthest,
        }

    def enforce_retention(
        self,
        observation_days: int,
        message_days: int,
        base_station_telemetry_days: int = 30,
    ) -> dict[str, int]:
        """Archive base telemetry, purge expired observations, and redact old messages."""
        now = datetime.now(timezone.utc)
        observation_cutoff = (now - timedelta(days=observation_days)).isoformat()
        message_cutoff = (now - timedelta(days=message_days)).isoformat()
        telemetry_cutoff = (now - timedelta(days=base_station_telemetry_days)).isoformat()
        with self.connect() as db:
            redacted = db.execute(
                """UPDATE observations SET message_text = NULL, raw_json = '{}'
                WHERE received_at < ? AND message_text IS NOT NULL""",
                (message_cutoff,),
            ).rowcount
            telemetry_archived = db.execute(
                """INSERT INTO archived_base_station_telemetry
                (id, received_at, receiver_id, packet_id, from_node, to_node, channel,
                 portnum, message_text, content_state, rssi, snr, latitude, longitude,
                 receiver_latitude, receiver_longitude, ingress_transport, transport,
                 raw_json, archived_at)
                SELECT id, received_at, receiver_id, packet_id, from_node, to_node, channel,
                 portnum, message_text, content_state, rssi, snr, latitude, longitude,
                 receiver_latitude, receiver_longitude, ingress_transport, transport,
                 raw_json, ? FROM observations
                WHERE received_at < ? AND transport = 'LOCAL' AND portnum = 'TELEMETRY_APP'""",
                (now.isoformat(), telemetry_cutoff),
            ).rowcount
            db.execute(
                """DELETE FROM observations
                WHERE received_at < ? AND transport = 'LOCAL' AND portnum = 'TELEMETRY_APP'""",
                (telemetry_cutoff,),
            )
            deleted = db.execute(
                "DELETE FROM observations WHERE received_at < ?",
                (observation_cutoff,),
            ).rowcount
        return {
            "base_station_telemetry_archived": telemetry_archived,
            "messages_redacted": redacted,
            "observations_deleted": deleted,
        }

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

    def save_local_collector_credential(self, token_hash: str, token_prefix: str) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """INSERT INTO local_collector_credentials
                (id, token_hash, token_prefix, created_at, last_used_at)
                VALUES (1, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash,
                token_prefix=excluded.token_prefix, created_at=excluded.created_at, last_used_at=NULL""",
                (token_hash, token_prefix, created_at),
            )
        return {"token_prefix": token_prefix, "created_at": created_at, "last_used_at": None}

    def local_collector_credential(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT token_hash, token_prefix, created_at, last_used_at FROM local_collector_credentials WHERE id=1"
            ).fetchone()
        return dict(row) if row else None

    def mark_local_collector_used(self) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE local_collector_credentials SET last_used_at=? WHERE id=1",
                (datetime.now(timezone.utc).isoformat(),),
            )


def _content_state(
    transport: str, portnum: str | None, message_text: str | None, raw: Any
) -> str:
    """Classify payload readability while making no claim about ciphertext contents."""
    if transport != "LORA":
        return "non_rf"
    if portnum == "TEXT_MESSAGE_APP" or message_text is not None:
        return "decoded_public_message"
    if portnum is not None or (isinstance(raw, dict) and raw.get("decoded")):
        return "decoded_packet"
    if isinstance(raw, dict) and raw.get("encrypted") is not None:
        return "encrypted_undecodable"
    return "undecodable"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classify_mobility(track: list[dict[str, Any]]) -> dict[str, Any]:
    """Conservatively label a track while excluding implausible location jumps."""
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for point in track:
        try:
            stamp = datetime.fromisoformat(point["received_at"])
            lat, lon = float(point["latitude"]), float(point["longitude"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        candidate = {**point, "stamp": stamp, "latitude": lat, "longitude": lon}
        if accepted:
            previous = accepted[-1]
            hours = (stamp - previous["stamp"]).total_seconds() / 3600
            distance = _haversine_km(previous["latitude"], previous["longitude"], lat, lon)
            if hours <= 0 or (distance > 2 and distance / hours > 250):
                rejected += 1
                continue
        accepted.append(candidate)

    evidence: dict[str, Any] = {
        "retained_positions": len(track), "accepted_positions": len(accepted),
        "rejected_as_implausible": rejected, "mobile_threshold_km": 1.0,
        "static_radius_km": 0.25, "static_dwell_hours": 6,
    }
    if len(accepted) < 3:
        return {"state": "unknown", "evidence": evidence}
    span_hours = (accepted[-1]["stamp"] - accepted[0]["stamp"]).total_seconds() / 3600
    max_displacement = max(
        _haversine_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
        for index, a in enumerate(accepted) for b in accepted[index + 1:]
    )
    latest = accepted[-1]["stamp"]
    recent = [point for point in accepted if (latest - point["stamp"]).total_seconds() <= 6 * 3600]
    recent_span = (recent[-1]["stamp"] - recent[0]["stamp"]).total_seconds() / 3600 if len(recent) > 1 else 0
    center_lat = sorted(point["latitude"] for point in recent)[len(recent) // 2]
    center_lon = sorted(point["longitude"] for point in recent)[len(recent) // 2]
    recent_radius = max(
        (_haversine_km(center_lat, center_lon, point["latitude"], point["longitude"]) for point in recent),
        default=0,
    )
    evidence.update({
        "track_span_hours": round(span_hours, 2),
        "max_displacement_km": round(max_displacement, 3),
        "recent_dwell_hours": round(recent_span, 2),
        "recent_radius_km": round(recent_radius, 3),
    })
    if len(recent) >= 3 and recent_span >= 6 and recent_radius <= 0.25:
        return {"state": "potential_static", "evidence": evidence}
    if span_hours >= (10 / 60) and max_displacement >= 1:
        return {"state": "potential_mobile", "evidence": evidence}
    return {"state": "unknown", "evidence": evidence}
