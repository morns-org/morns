from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from morns.messaging import (
    MAX_TEXT_BYTES,
    STATUS_LABELS,
    IdempotencyConflict,
    MeshtasticInterfaceTransport,
    MessagingCenter,
    MessagingError,
    MessagingPolicy,
    QueueFullError,
    SendRequest,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
PUBLIC_KEY = bytes(range(32))


@dataclass
class Packet:
    id: int


class FakeTransport:
    def __init__(self, radio_id: str = "radio-1", packet_id: int = 101):
        self.radio_id = radio_id
        self.packet_id = packet_id
        self.calls: list[dict] = []
        self.ack_handler = None
        self.error: Exception | None = None
        self.firmware_version = "2.7.15"

    def send_text(self, item, ack_handler):
        self.calls.append(dict(item))
        self.ack_handler = ack_handler
        if self.error:
            raise self.error
        packet_id = self.packet_id
        self.packet_id += 1
        return packet_id


def center(tmp_path: Path, **policy) -> MessagingCenter:
    return MessagingCenter(
        tmp_path / "morns.db",
        MessagingPolicy(**policy),
        transmit_integration_enabled=True,
    )


def direct(text: str = "hello", **values) -> SendRequest:
    return SendRequest(
        text=text, destination_id="!1234abcd", target_public_key=PUBLIC_KEY, **values
    )


def test_utf8_byte_limit_and_destination_validation(tmp_path: Path):
    messages = center(tmp_path)
    exact = messages.enqueue(
        SendRequest(text="é" * 116 + "a", destination_id="^all"),
        radio_id="r", idempotency_key="exact", now=NOW,
    )
    assert exact["payload_bytes"] == MAX_TEXT_BYTES
    assert exact["destination_kind"] == "broadcast"
    assert exact["want_ack"] == 0
    with pytest.raises(MessagingError, match="233-byte"):
        messages.enqueue(
            SendRequest(text="é" * 117, destination_id="^all"),
            radio_id="r", idempotency_key="large", now=NOW,
        )
    for destination in ("friendly-name", "!123", 0, 0x1_0000_0000):
        with pytest.raises(MessagingError, match="Destination|32-bit"):
            messages.enqueue(
                SendRequest(text="x", destination_id=destination),
                radio_id="r", idempotency_key=f"bad-{destination}", now=NOW,
            )
    dm = messages.enqueue(
        SendRequest(text="dm", destination_id=123456, target_public_key=PUBLIC_KEY),
        radio_id="r", idempotency_key="numeric", now=NOW,
    )
    assert dm["destination_kind"] == "direct"
    assert dm["want_ack"] == 1


def test_idempotency_is_durable_and_conflicts_are_rejected(tmp_path: Path):
    database = tmp_path / "morns.db"
    first = MessagingCenter(database).enqueue(
        direct(), radio_id="r", idempotency_key="stable", now=NOW
    )
    restarted = MessagingCenter(database)
    duplicate = restarted.enqueue(
        direct(), radio_id="r", idempotency_key="stable", now=NOW + timedelta(seconds=1)
    )
    assert duplicate["id"] == first["id"]
    with pytest.raises(IdempotencyConflict):
        restarted.enqueue(
            direct("different"), radio_id="r", idempotency_key="stable", now=NOW
        )


def test_draft_is_durable_then_explicitly_queued(tmp_path: Path):
    messages = MessagingCenter(tmp_path / "morns.db")
    item = messages.save_draft(
        direct(), radio_id="r", idempotency_key="draft", now=NOW
    )
    assert item["state"] == "draft"
    queued = messages.queue_draft(item["id"], now=NOW + timedelta(seconds=1))
    assert queued["state"] == "queued"
    assert [row["to_state"] for row in messages.store.transitions(item["id"])] == [
        "draft", "queued"
    ]


def test_truthful_status_labels_and_capabilities(tmp_path: Path):
    messages = MessagingCenter(tmp_path / "morns.db")
    capability = messages.capability(
        "r", connected=True, manufacturer="RAKwireless", model="RAK4631",
        firmware_version="2.7.15",
    )
    assert capability["transmit_supported"] is True
    assert capability["transmit_integration_enabled"] is False
    assert capability["ready_to_transmit"] is False
    assert capability["authenticated_private_supported"] is True
    assert capability["direct_ack_semantics"] == "destination_radio_routing_ack_not_human_read"
    assert capability["broadcast_ack_semantics"] == "no_delivery_ack"
    assert "not a human read receipt" in STATUS_LABELS["destination_radio_acknowledged"]
    assert "delivery are not confirmed" in STATUS_LABELS["submitted_to_interface"]
    assert "not yet submitted" in STATUS_LABELS["queued"]
    other = messages.capability("other", protocol="generic", connected=True)
    assert other["transmit_supported"] is False
    assert other["ready_to_transmit"] is False


def test_private_message_fails_closed_without_pubkey_or_supported_firmware(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0)
    with pytest.raises(MessagingError, match="public key"):
        messages.enqueue(
            SendRequest(text="private", destination_id="!1234abcd"),
            radio_id="r", idempotency_key="no-key", now=NOW,
        )
    item = messages.enqueue(direct(), radio_id="r", idempotency_key="old-radio", now=NOW)
    transport = FakeTransport("r")
    transport.firmware_version = "2.7.14"
    failed = messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None, now=NOW
    )
    assert failed["id"] == item["id"]
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "FIRMWARE_TOO_OLD_OR_UNKNOWN"
    assert "no fallback" in failed["status_detail"]
    assert transport.calls == []


def test_direct_send_ack_and_broadcast_have_truthful_transitions(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0)
    transport = FakeTransport()
    dm = messages.enqueue(direct(), radio_id="radio-1", idempotency_key="dm", now=NOW)
    sent = messages.process_next(
        transport, channel_utilization_percent=1, radio_config_revision=None, now=NOW
    )
    assert sent["state"] == "submitted_to_interface"
    assert sent["packet_id"] == 101
    assert transport.calls[0]["want_ack"] == 1
    acknowledged = messages.record_destination_radio_ack(
        101, True, radio_id="radio-1", now=NOW + timedelta(seconds=1)
    )
    assert acknowledged["state"] == "destination_radio_acknowledged"
    assert [row["to_state"] for row in messages.store.transitions(dm["id"])] == [
        "queued", "transmitting", "submitted_to_interface", "destination_radio_acknowledged"
    ]

    broadcast = messages.enqueue(
        SendRequest(text="everyone"), radio_id="radio-1", idempotency_key="broadcast", now=NOW
    )
    sent_broadcast = messages.process_next(
        transport, channel_utilization_percent=1, radio_config_revision=None,
        now=NOW + timedelta(seconds=2),
    )
    assert sent_broadcast["state"] == "submitted_to_interface"
    assert sent_broadcast["want_ack"] == 0
    assert messages.record_destination_radio_ack(
        transport.packet_id + 1, True, radio_id="radio-1"
    ) is None
    assert messages.store.get(broadcast["id"])["attempt_count"] == 1


def test_native_timeout_becomes_unknown_without_automatic_retry(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0, direct_ack_timeout_seconds=30)
    transport = FakeTransport()
    item = messages.enqueue(direct(), radio_id="radio-1", idempotency_key="timeout", now=NOW)
    messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None, now=NOW
    )
    assert messages.resolve_timeouts(now=NOW + timedelta(seconds=31)) == 1
    timed_out = messages.store.get(item["id"])
    assert timed_out["state"] == "unknown"
    assert timed_out["attempt_count"] == 1
    assert messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None,
        now=NOW + timedelta(seconds=32),
    ) is None
    retried = messages.retry_manually(item["id"], now=NOW + timedelta(seconds=33))
    assert retried["state"] == "queued"


def test_ack_callback_can_arrive_before_sdk_call_returns(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0)

    class ImmediateAck(FakeTransport):
        def send_text(self, item, ack_handler):
            self.calls.append(dict(item))
            ack_handler(self.packet_id, True, "NONE")
            return self.packet_id

    item = messages.enqueue(direct(), radio_id="r", idempotency_key="early", now=NOW)
    result = messages.process_next(
        ImmediateAck("r"), channel_utilization_percent=0,
        radio_config_revision=None, now=NOW,
    )
    assert result["id"] == item["id"]
    assert result["state"] == "destination_radio_acknowledged"


def test_broadcast_cooldown_holds_next_submission_without_retrying(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=10)
    transport = FakeTransport("r")
    messages.enqueue(
        SendRequest(text="one"), radio_id="r", idempotency_key="one", now=NOW
    )
    messages.enqueue(
        SendRequest(text="two"), radio_id="r", idempotency_key="two", now=NOW
    )
    assert messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None, now=NOW
    )["state"] == "submitted_to_interface"
    held = messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None,
        now=NOW + timedelta(seconds=1),
    )
    assert held["reason"] == "radio_cooldown_active"
    assert len(transport.calls) == 1


def test_cancel_and_expiry_only_apply_before_transmission(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0)
    canceled = messages.enqueue(direct(), radio_id="r", idempotency_key="cancel", now=NOW)
    assert messages.cancel(canceled["id"], now=NOW)["state"] == "canceled"
    expiring = messages.enqueue(
        direct(expires_at=NOW + timedelta(seconds=5)),
        radio_id="r", idempotency_key="expire", now=NOW,
    )
    assert messages.expire_queued(now=NOW + timedelta(seconds=6)) == 1
    assert messages.store.get(expiring["id"])["state"] == "expired"
    active = messages.enqueue(direct(), radio_id="r", idempotency_key="active", now=NOW)
    messages.process_next(
        FakeTransport("r"), channel_utilization_percent=0,
        radio_config_revision=None, now=NOW,
    )
    with pytest.raises(MessagingError, match="Cannot move"):
        messages.cancel(active["id"])


def test_single_in_flight_per_radio_and_definite_failure(tmp_path: Path):
    messages = center(tmp_path, cooldown_seconds=0)
    first = messages.enqueue(direct("one"), radio_id="r", idempotency_key="one", now=NOW)
    second = messages.enqueue(direct("two"), radio_id="r", idempotency_key="two", now=NOW)
    transport = FakeTransport("r")
    messages.process_next(transport, channel_utilization_percent=0, radio_config_revision=None, now=NOW)
    held = messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None,
        now=NOW + timedelta(seconds=1),
    )
    assert held["reason"] == "radio_has_in_flight_message"
    messages.record_destination_radio_ack(
        101, False, "NO_ROUTE", radio_id="r", now=NOW + timedelta(seconds=2)
    )
    transport.error = OSError("radio disconnected")
    failed = messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None,
        now=NOW + timedelta(seconds=3),
    )
    assert messages.store.get(first["id"])["state"] == "failed"
    assert failed["id"] == second["id"]
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "OSError"


def test_anti_jam_queue_utilization_cooldown_and_config_gates(tmp_path: Path):
    messages = center(
        tmp_path, max_queue_depth=2, max_queued_per_radio=1,
        cooldown_seconds=10, max_channel_utilization_percent=20,
    )
    item = messages.enqueue(
        direct(radio_config_revision="rev-1"),
        radio_id="r1", idempotency_key="one", now=NOW,
    )
    with pytest.raises(QueueFullError):
        messages.enqueue(direct("two"), radio_id="r1", idempotency_key="two", now=NOW)
    messages.enqueue(direct("other"), radio_id="r2", idempotency_key="other", now=NOW)
    with pytest.raises(QueueFullError):
        messages.enqueue(direct("full"), radio_id="r3", idempotency_key="full", now=NOW)

    transport = FakeTransport("r1")
    assert messages.process_next(
        transport, channel_utilization_percent=None, radio_config_revision="rev-1", now=NOW
    )["reason"] == "channel_utilization_unknown"
    assert messages.process_next(
        transport, channel_utilization_percent=21, radio_config_revision="rev-1", now=NOW
    )["reason"] == "channel_utilization_high"
    assert messages.process_next(
        transport, channel_utilization_percent=1, radio_config_revision="rev-2", now=NOW
    )["reason"] == "radio_configuration_changed"
    messages.approve_config_revision(item["id"], "rev-2", now=NOW)
    assert messages.process_next(
        transport, channel_utilization_percent=1, radio_config_revision="rev-2", now=NOW
    )["state"] == "submitted_to_interface"


def test_disabled_integration_never_calls_transport(tmp_path: Path):
    messages = MessagingCenter(tmp_path / "morns.db", transmit_integration_enabled=False)
    messages.enqueue(direct(), radio_id="r", idempotency_key="held", now=NOW)
    transport = FakeTransport("r")
    held = messages.process_next(
        transport, channel_utilization_percent=0, radio_config_revision=None, now=NOW
    )
    assert held == {"status": "held", "reason": "transmit_integration_disabled"}
    assert transport.calls == []


def test_restart_marks_interrupted_sdk_submission_unknown(tmp_path: Path):
    database = tmp_path / "morns.db"
    messages = MessagingCenter(database)
    item = messages.enqueue(direct(), radio_id="r", idempotency_key="restart", now=NOW)
    with messages.store.connect() as db:
        db.execute(
            "UPDATE message_outbox SET state='transmitting',updated_at=? WHERE id=?",
            (NOW.isoformat(), item["id"]),
        )
    restarted = MessagingCenter(database)
    recovered = restarted.store.get(item["id"])
    assert recovered["state"] == "unknown"
    assert "cannot be established" in recovered["status_detail"]
    assert restarted.retry_manually(item["id"], now=NOW)["state"] == "queued"


def test_meshtastic_adapter_reuses_existing_interface_and_exact_sdk_semantics():
    class Interface:
        def __init__(self):
            self.calls = []

        def sendText(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return Packet(77)

        def sendData(self, data, **kwargs):
            self.calls.append((data, kwargs))
            return Packet(77)

    interface = Interface()
    transport = MeshtasticInterfaceTransport("r", interface, "2.7.15")
    outcomes = []
    broadcast = {
        "message_text": "public", "want_ack": 0,
        "destination_id": "^all", "channel_index": 2,
    }
    assert transport.send_text(broadcast, lambda *args: outcomes.append(args)) == 77
    assert interface.calls[-1] == (
        "public", {"destinationId": "^all", "wantAck": False, "channelIndex": 2}
    )
    dm = {
        "message_text": "private", "want_ack": 1,
        "destination_id": "!1234abcd", "channel_index": 3,
        "target_public_key": PUBLIC_KEY,
    }
    assert transport.send_text(dm, lambda *args: outcomes.append(args)) == 77
    _, kwargs = interface.calls[-1]
    assert interface.calls[-1][0] == b"private"
    assert kwargs["destinationId"] == "!1234abcd"
    assert kwargs["wantAck"] is True
    assert kwargs["channelIndex"] == 3
    assert kwargs["pkiEncrypted"] is True
    assert kwargs["publicKey"] == PUBLIC_KEY
    assert kwargs["portNum"] == 1
    assert kwargs["onResponse"].__name__ == "onAckNak"
    kwargs["onResponse"]({
        "decoded": {"requestId": 77, "routing": {"errorReason": "NONE"}}
    })
    assert outcomes == [(77, True, "NONE")]
