from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

MAX_TEXT_BYTES = 233
OUTBOX_STATES = (
    "draft", "queued", "transmitting", "submitted_to_interface", "destination_radio_acknowledged",
    "failed", "expired", "canceled", "unknown",
)
DIRECT_NODE_ID = re.compile(r"^![0-9a-fA-F]{8}$")

STATUS_LABELS = {
    "draft": "Draft — saved locally and not queued for radio transmission.",
    "queued": "Queued — accepted by MORNS; not yet submitted to the attached radio.",
    "transmitting": "Transmitting — MORNS is submitting the request to the attached radio.",
    "submitted_to_interface": "Submitted to interface — the SDK accepted the request; local-radio queueing and delivery are not confirmed.",
    "destination_radio_acknowledged": "Destination radio acknowledged — a routing ACK was observed; this is not a human read receipt.",
    "failed": "Failed — MORNS or the radio reported a definite transmission failure.",
    "expired": "Expired — the message left the queue before radio transmission because its local deadline passed.",
    "canceled": "Canceled — removed before radio transmission; no over-the-air cancellation is implied.",
    "unknown": "Unknown — MORNS cannot establish the final mesh outcome.",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS message_outbox (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    content_fingerprint TEXT NOT NULL,
    radio_id TEXT NOT NULL,
    destination_kind TEXT NOT NULL CHECK(destination_kind IN ('broadcast', 'direct')),
    destination_id TEXT NOT NULL,
    channel_index INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    payload_bytes INTEGER NOT NULL,
    want_ack INTEGER NOT NULL CHECK(want_ack IN (0, 1)),
    state TEXT NOT NULL CHECK(state IN ('draft','queued','transmitting','submitted_to_interface',
      'destination_radio_acknowledged','failed','expired','canceled','unknown')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    packet_id INTEGER,
    hold_reason TEXT,
    failure_code TEXT,
    status_detail TEXT,
    radio_config_revision TEXT,
    target_public_key BLOB
);
CREATE INDEX IF NOT EXISTS message_outbox_radio_state_idx
    ON message_outbox(radio_id, state, created_at);
CREATE TABLE IF NOT EXISTS message_outbox_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    reason TEXT,
    FOREIGN KEY(outbox_id) REFERENCES message_outbox(id)
);
CREATE INDEX IF NOT EXISTS message_outbox_transitions_message_idx
    ON message_outbox_transitions(outbox_id, occurred_at);
"""


class MessagingError(ValueError):
    pass


class QueueFullError(MessagingError):
    pass


class IdempotencyConflict(MessagingError):
    pass


@dataclass(frozen=True)
class MessagingPolicy:
    max_queue_depth: int = 100
    max_queued_per_radio: int = 25
    cooldown_seconds: float = 5.0
    max_channel_utilization_percent: float = 25.0
    direct_ack_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_queue_depth < 1 or self.max_queued_per_radio < 1:
            raise MessagingError("Queue limits must be positive")
        if self.cooldown_seconds < 0 or self.direct_ack_timeout_seconds <= 0:
            raise MessagingError("Messaging time limits are invalid")
        if not 0 <= self.max_channel_utilization_percent <= 100:
            raise MessagingError("Channel-utilization limit must be between 0 and 100")


@dataclass(frozen=True)
class RadioCapability:
    radio_id: str
    protocol: str
    connected: bool
    receive_supported: bool = True
    transmit_supported: bool = False
    transmit_integration_enabled: bool = False
    manufacturer: str | None = None
    model: str | None = None
    max_text_bytes: int = MAX_TEXT_BYTES
    direct_ack_semantics: str = "destination_radio_routing_ack_not_human_read"
    broadcast_ack_semantics: str = "no_delivery_ack"
    channel_index_semantics: str = "local_radio_channel_slot_not_global_identity"
    authenticated_private_supported: bool = False

    def status(self) -> dict[str, Any]:
        result = asdict(self)
        result["ready_to_transmit"] = bool(
            self.connected and self.transmit_supported and self.transmit_integration_enabled
        )
        result["status_labels"] = dict(STATUS_LABELS)
        return result


@dataclass(frozen=True)
class SendRequest:
    text: str
    destination_id: str | int = "^all"
    channel_index: int = 0
    expires_at: datetime | None = None
    radio_config_revision: str | None = None
    target_public_key: bytes | None = None


class RadioTransport(Protocol):
    radio_id: str
    firmware_version: str | None

    def send_text(
        self,
        item: dict[str, Any],
        ack_handler: Callable[[int, bool, str | None], None],
    ) -> int: ...


class MeshtasticInterfaceTransport:
    """Wrap an existing SDK interface; this class never opens a radio connection."""

    def __init__(self, radio_id: str, interface: Any, firmware_version: str | None):
        self.radio_id = radio_id
        self.interface = interface
        self.firmware_version = firmware_version

    def send_text(
        self,
        item: dict[str, Any],
        ack_handler: Callable[[int, bool, str | None], None],
    ) -> int:
        if not item["want_ack"]:
            packet = self.interface.sendText(
                item["message_text"],
                destinationId="^all",
                wantAck=False,
                channelIndex=item["channel_index"],
            )
            return int(packet.id)

        if not _firmware_at_least(self.firmware_version, "2.7.15"):
            raise MessagingError("Authenticated private messaging requires radio firmware 2.7.15 or newer")
        public_key = item.get("target_public_key")
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise MessagingError("Authenticated private messaging requires the target's 32-byte public key")

        def onAckNak(packet: dict[str, Any]) -> None:
            decoded = packet.get("decoded") or {}
            request_id = decoded.get("requestId")
            routing = decoded.get("routing") or {}
            reason = routing.get("errorReason")
            acknowledged = reason in {None, "NONE"}
            if request_id is not None:
                ack_handler(int(request_id), acknowledged, reason)

        destination: str | int = item["destination_id"]
        if isinstance(destination, str) and destination.isdecimal():
            destination = int(destination)
        from meshtastic.protobuf import portnums_pb2

        packet = self.interface.sendData(
            item["message_text"].encode("utf-8"),
            destinationId=destination,
            portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP,
            wantAck=True,
            onResponse=onAckNak,
            onResponseAckPermitted=True,
            channelIndex=item["channel_index"],
            pkiEncrypted=True,
            publicKey=public_key,
        )
        return int(packet.id)


class OutboxStore:
    def __init__(self, database_path: Path | str):
        self.database_path = str(database_path)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def get(self, outbox_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM message_outbox WHERE id=?", (outbox_id,)).fetchone()
        return dict(row) if row else None

    def transitions(self, outbox_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM message_outbox_transitions WHERE outbox_id=? ORDER BY id",
                (outbox_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class MessagingCenter:
    """Durable outbox state machine. It has no HTTP exposure or radio ownership."""

    def __init__(
        self,
        database_path: Path | str,
        policy: MessagingPolicy | None = None,
        *,
        transmit_integration_enabled: bool = False,
    ):
        self.store = OutboxStore(database_path)
        self.policy = policy or MessagingPolicy()
        self.transmit_integration_enabled = transmit_integration_enabled
        self.recover_interrupted_transmissions()

    def capability(self, radio_id: str, protocol: str = "meshtastic", **details: Any) -> dict[str, Any]:
        supported = protocol == "meshtastic"
        firmware_version = details.pop("firmware_version", None)
        return RadioCapability(
            radio_id=radio_id,
            protocol=protocol,
            connected=bool(details.pop("connected", False)),
            transmit_supported=supported,
            transmit_integration_enabled=self.transmit_integration_enabled and supported,
            authenticated_private_supported=(
                supported and _firmware_at_least(firmware_version, "2.7.15")
            ),
            **details,
        ).status() | {"firmware_version": firmware_version}

    def save_draft(
        self, request: SendRequest, *, radio_id: str, idempotency_key: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._insert(request, radio_id, idempotency_key, "draft", now)

    def enqueue(
        self, request: SendRequest, *, radio_id: str, idempotency_key: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._insert(request, radio_id, idempotency_key, "queued", now)

    def _insert(
        self, request: SendRequest, radio_id: str, idempotency_key: str,
        state: str, now: datetime | None,
    ) -> dict[str, Any]:
        current = _utc(now)
        normalized = _validate_request(request)
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise MessagingError("Idempotency key must contain 1 to 128 characters")
        if not radio_id.strip() or len(radio_id) > 128:
            raise MessagingError("Radio ID is invalid")
        fingerprint = _fingerprint(normalized, radio_id)
        item_id = str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM message_outbox WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["content_fingerprint"] != fingerprint:
                    raise IdempotencyConflict("Idempotency key was already used for different content")
                db.commit()
                return dict(existing)
            active = db.execute(
                """SELECT COUNT(*) FROM message_outbox WHERE state IN ('draft','queued','transmitting')
                OR (state='submitted_to_interface' AND want_ack=1)"""
            ).fetchone()[0]
            per_radio = db.execute(
                """SELECT COUNT(*) FROM message_outbox WHERE radio_id=? AND
                (state IN ('draft','queued','transmitting') OR (state='submitted_to_interface' AND want_ack=1))""",
                (radio_id,),
            ).fetchone()[0]
            if active >= self.policy.max_queue_depth or per_radio >= self.policy.max_queued_per_radio:
                raise QueueFullError("Durable message queue is full")
            created = current.isoformat()
            db.execute(
                """INSERT INTO message_outbox
                (id,idempotency_key,content_fingerprint,radio_id,destination_kind,destination_id,
                 channel_index,message_text,payload_bytes,want_ack,state,created_at,updated_at,
                 expires_at,radio_config_revision,target_public_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item_id, key, fingerprint, radio_id, normalized["destination_kind"],
                    str(normalized["destination_id"]), normalized["channel_index"],
                    normalized["text"], normalized["payload_bytes"], normalized["want_ack"],
                    state, created, created,
                    request.expires_at.astimezone(timezone.utc).isoformat() if request.expires_at else None,
                    request.radio_config_revision,
                    normalized["target_public_key"],
                ),
            )
            db.execute(
                "INSERT INTO message_outbox_transitions(outbox_id,from_state,to_state,occurred_at,reason) VALUES (?,NULL,?,?,?)",
                (item_id, state, created, "created"),
            )
            db.commit()
        return self.store.get(item_id) or {}

    def queue_draft(self, outbox_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        return self._transition(outbox_id, {"draft"}, "queued", "queued_by_operator", now)

    def cancel(self, outbox_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        return self._transition(
            outbox_id, {"draft", "queued"}, "canceled", "canceled_before_transmission", now
        )

    def retry_manually(self, outbox_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        return self._transition(
            outbox_id, {"failed", "unknown"}, "queued", "manual_retry_requested", now,
            updates={"packet_id": None, "failure_code": None, "status_detail": None},
        )

    def approve_config_revision(
        self, outbox_id: str, revision: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        item = self.store.get(outbox_id)
        if not item or item["state"] != "queued":
            raise MessagingError("Only queued messages can approve a configuration revision")
        return self._update(
            outbox_id, now, radio_config_revision=revision, hold_reason=None,
            status_detail="Configuration revision explicitly approved",
        )

    def process_next(
        self,
        transport: RadioTransport,
        *,
        channel_utilization_percent: float | None,
        radio_config_revision: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        current = _utc(now)
        self.resolve_timeouts(now=current)
        self.expire_queued(now=current)
        if not self.transmit_integration_enabled:
            return {"status": "held", "reason": "transmit_integration_disabled"}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            in_flight = db.execute(
                """SELECT 1 FROM message_outbox WHERE radio_id=? AND
                (state='transmitting' OR (state='submitted_to_interface' AND want_ack=1)) LIMIT 1""",
                (transport.radio_id,),
            ).fetchone()
            if in_flight:
                db.commit()
                return {"status": "held", "reason": "radio_has_in_flight_message"}
            row = db.execute(
                "SELECT * FROM message_outbox WHERE radio_id=? AND state='queued' ORDER BY created_at,rowid LIMIT 1",
                (transport.radio_id,),
            ).fetchone()
            if not row:
                db.commit()
                return None
            item = dict(row)
            if item["destination_kind"] == "direct" and not _firmware_at_least(
                transport.firmware_version, "2.7.15"
            ):
                self._transition_in_db(
                    db, item, "failed", current, "authenticated_private_unsupported",
                    {
                        "failure_code": "FIRMWARE_TOO_OLD_OR_UNKNOWN",
                        "status_detail": "Authenticated private messaging requires radio firmware 2.7.15 or newer; no fallback was attempted",
                    },
                )
                db.commit()
                return self.store.get(item["id"])
            reason = self._gate_reason(db, item, current, channel_utilization_percent, radio_config_revision)
            if reason:
                db.execute(
                    "UPDATE message_outbox SET hold_reason=?,updated_at=? WHERE id=?",
                    (reason, current.isoformat(), item["id"]),
                )
                db.commit()
                return {"status": "held", "reason": reason, "message": self.store.get(item["id"])}
            self._transition_in_db(
                db, item, "transmitting", current, "radio_submission_started",
                {"hold_reason": None, "attempt_count": item["attempt_count"] + 1},
            )
            db.commit()
        item = self.store.get(item["id"]) or item
        early_outcomes: list[tuple[int, bool, str | None]] = []

        def acknowledge(packet_id: int, acknowledged: bool, reason: str | None) -> None:
            outcome = self.record_destination_radio_ack(
                packet_id, acknowledged, reason, radio_id=transport.radio_id
            )
            if outcome is None:
                early_outcomes.append((packet_id, acknowledged, reason))

        try:
            packet_id = transport.send_text(item, acknowledge)
        except Exception as exc:
            return self._transition(
                item["id"], {"transmitting"}, "failed", "radio_submission_failed", current,
                updates={"failure_code": type(exc).__name__, "status_detail": str(exc)[:500]},
            )
        # An SDK callback can race the return and already advance the item to ACK/failed.
        refreshed = self.store.get(item["id"]) or {}
        if refreshed.get("state") != "transmitting":
            return refreshed
        result = self._transition(
            item["id"], {"transmitting"}, "submitted_to_interface", "sdk_accepted_request", current,
            updates={"packet_id": packet_id, "status_detail": STATUS_LABELS["submitted_to_interface"]},
        )
        for acknowledged_packet, acknowledged, reason in early_outcomes:
            if acknowledged_packet == packet_id:
                result = self.record_destination_radio_ack(
                    packet_id, acknowledged, reason, radio_id=transport.radio_id, now=current
                ) or result
        return result

    def record_destination_radio_ack(
        self, packet_id: int, acknowledged: bool, error_reason: str | None = None,
        *, radio_id: str, now: datetime | None = None,
    ) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute(
                """SELECT * FROM message_outbox WHERE packet_id=? AND radio_id=? AND want_ack=1
                ORDER BY updated_at DESC LIMIT 1""",
                (packet_id, radio_id),
            ).fetchone()
        if not row:
            return None
        if acknowledged:
            return self._transition(
                row["id"], {"transmitting", "submitted_to_interface"}, "destination_radio_acknowledged",
                "destination_radio_routing_ack", now,
                updates={"status_detail": STATUS_LABELS["destination_radio_acknowledged"]},
            )
        return self._transition(
            row["id"], {"transmitting", "submitted_to_interface"}, "failed",
            "mesh_routing_nak", now,
            updates={"failure_code": error_reason or "ROUTING_NAK", "status_detail": "Destination radio returned a routing NAK"},
        )

    def recover_interrupted_transmissions(self, *, now: datetime | None = None) -> int:
        current = _utc(now)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT id FROM message_outbox WHERE state='transmitting'"
            ).fetchall()
        for row in rows:
            self._transition(
                row["id"], {"transmitting"}, "unknown", "process_restarted_during_submission",
                current,
                updates={"status_detail": "The process restarted during SDK submission; the radio outcome cannot be established"},
            )
        return len(rows)

    def resolve_timeouts(self, *, now: datetime | None = None) -> int:
        current = _utc(now)
        cutoff = (current - timedelta(seconds=self.policy.direct_ack_timeout_seconds)).isoformat()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT id FROM message_outbox WHERE state='submitted_to_interface' AND want_ack=1 AND updated_at<=?",
                (cutoff,),
            ).fetchall()
        for row in rows:
            self._transition(
                row["id"], {"submitted_to_interface"}, "unknown", "native_ack_timeout", current,
                updates={"status_detail": "No routing ACK or definite failure was observed before timeout; no automatic retry was scheduled"},
            )
        return len(rows)

    def expire_queued(self, *, now: datetime | None = None) -> int:
        current = _utc(now)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT id,state FROM message_outbox WHERE state IN ('draft','queued') AND expires_at IS NOT NULL AND expires_at<=?",
                (current.isoformat(),),
            ).fetchall()
        for row in rows:
            self._transition(
                row["id"], {row["state"]}, "expired", "local_queue_deadline_passed", current
            )
        return len(rows)

    def _gate_reason(
        self, db: sqlite3.Connection, item: dict[str, Any], current: datetime,
        utilization: float | None, revision: str | None,
    ) -> str | None:
        if utilization is None:
            return "channel_utilization_unknown"
        if utilization < 0 or utilization > 100:
            return "channel_utilization_invalid"
        if utilization > self.policy.max_channel_utilization_percent:
            return "channel_utilization_high"
        expected = item.get("radio_config_revision")
        if expected != revision:
            return "radio_configuration_changed"
        last = db.execute(
            """SELECT updated_at FROM message_outbox WHERE radio_id=? AND
            state IN ('submitted_to_interface','destination_radio_acknowledged') ORDER BY updated_at DESC LIMIT 1""",
            (item["radio_id"],),
        ).fetchone()
        if last and datetime.fromisoformat(last[0]) > current - timedelta(seconds=self.policy.cooldown_seconds):
            return "radio_cooldown_active"
        return None

    def _transition(
        self, outbox_id: str, allowed: set[str], target: str, reason: str,
        now: datetime | None, updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = _utc(now)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM message_outbox WHERE id=?", (outbox_id,)).fetchone()
            if not row:
                raise MessagingError("Outbox message does not exist")
            item = dict(row)
            if item["state"] not in allowed:
                raise MessagingError(f"Cannot move {item['state']} to {target}")
            self._transition_in_db(db, item, target, current, reason, updates or {})
            db.commit()
        return self.store.get(outbox_id) or {}

    @staticmethod
    def _transition_in_db(
        db: sqlite3.Connection, item: dict[str, Any], target: str, current: datetime,
        reason: str, updates: dict[str, Any],
    ) -> None:
        assignments = {"state": target, "updated_at": current.isoformat(), **updates}
        columns = ",".join(f"{key}=?" for key in assignments)
        db.execute(
            f"UPDATE message_outbox SET {columns} WHERE id=?",
            (*assignments.values(), item["id"]),
        )
        db.execute(
            "INSERT INTO message_outbox_transitions(outbox_id,from_state,to_state,occurred_at,reason) VALUES (?,?,?,?,?)",
            (item["id"], item["state"], target, current.isoformat(), reason),
        )

    def _update(self, outbox_id: str, now: datetime | None, **updates: Any) -> dict[str, Any]:
        current = _utc(now)
        updates["updated_at"] = current.isoformat()
        with self.store.connect() as db:
            columns = ",".join(f"{key}=?" for key in updates)
            cursor = db.execute(
                f"UPDATE message_outbox SET {columns} WHERE id=?", (*updates.values(), outbox_id)
            )
            if not cursor.rowcount:
                raise MessagingError("Outbox message does not exist")
        return self.store.get(outbox_id) or {}


def _validate_request(request: SendRequest) -> dict[str, Any]:
    if not isinstance(request.text, str) or not request.text:
        raise MessagingError("Message text is required")
    payload_bytes = len(request.text.encode("utf-8"))
    if payload_bytes > MAX_TEXT_BYTES:
        raise MessagingError(f"Message exceeds the {MAX_TEXT_BYTES}-byte UTF-8 limit")
    if isinstance(request.channel_index, bool) or not isinstance(request.channel_index, int):
        raise MessagingError("Channel index must be an integer")
    if not 0 <= request.channel_index <= 7:
        raise MessagingError("Channel index must be between 0 and 7")
    destination = request.destination_id
    if destination == "^all":
        kind, want_ack, public_key = "broadcast", False, None
    elif (
        isinstance(destination, int) and not isinstance(destination, bool) and 0 < destination <= 0xFFFFFFFF
    ) or (isinstance(destination, str) and (DIRECT_NODE_ID.fullmatch(destination) or destination.isdecimal())):
        numeric = int(destination[1:], 16) if isinstance(destination, str) and destination.startswith("!") else int(destination)
        if not 0 < numeric <= 0xFFFFFFFF:
            raise MessagingError("Direct destination is outside the 32-bit node range")
        if not isinstance(request.target_public_key, bytes) or len(request.target_public_key) != 32:
            raise MessagingError("Direct messaging requires the target's 32-byte public key")
        kind, want_ack, public_key = "direct", True, request.target_public_key
    else:
        raise MessagingError("Destination must be ^all, !xxxxxxxx, or a 32-bit numeric node ID")
    if request.expires_at is not None:
        if request.expires_at.tzinfo is None:
            raise MessagingError("Expiry must include a time zone")
    if request.radio_config_revision is not None and len(request.radio_config_revision) > 128:
        raise MessagingError("Radio configuration revision is too long")
    return {
        "text": request.text,
        "payload_bytes": payload_bytes,
        "destination_kind": kind,
        "destination_id": destination,
        "want_ack": int(want_ack),
        "channel_index": request.channel_index,
        "target_public_key": public_key,
    }


def _fingerprint(normalized: dict[str, Any], radio_id: str) -> str:
    serializable = dict(normalized)
    public_key = serializable.get("target_public_key")
    if isinstance(public_key, bytes):
        serializable["target_public_key"] = public_key.hex()
    content = json.dumps({**serializable, "radio_id": radio_id}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise MessagingError("Time must include a time zone")
    return current.astimezone(timezone.utc)


def _firmware_at_least(actual: str | None, minimum: str) -> bool:
    if not actual:
        return False
    try:
        actual_parts = tuple(int(part) for part in actual.split("-")[0].split(".")[:3])
        minimum_parts = tuple(int(part) for part in minimum.split(".")[:3])
    except ValueError:
        return False
    return actual_parts >= minimum_parts
