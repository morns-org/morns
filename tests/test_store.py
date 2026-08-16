from datetime import datetime, timezone
import sqlite3

from morns.store import ObservationStore


def test_store_keeps_immutable_observations(tmp_path):
    store = ObservationStore(tmp_path / "test.db")
    first = store.add({
        "received_at": datetime.now(timezone.utc).isoformat(),
        "receiver_id": "rx-1", "from_node": "!abc", "message_text": "first",
        "transport": "LORA",
    })
    second = store.add({
        "received_at": datetime.now(timezone.utc).isoformat(),
        "receiver_id": "rx-1", "from_node": "!abc", "message_text": "second",
        "transport": "LORA",
    })
    assert second > first
    rows = store.recent(messages_only=True)
    assert [row["message_text"] for row in rows] == ["second", "first"]
    assert store.stats()["nodes"] == 1


def test_transport_provenance_is_enforced(tmp_path):
    store = ObservationStore(tmp_path / "test.db")
    try:
        store.add({"receiver_id": "rx", "transport": "MAGIC"})
    except Exception as exc:
        assert "CHECK constraint" in str(exc)
    else:
        raise AssertionError("invalid transport accepted")


def test_local_events_do_not_inflate_rf_node_or_message_counts(tmp_path):
    store = ObservationStore(tmp_path / "test.db")
    store.add({"receiver_id": "rx", "from_node": "!self", "message_text": "status", "transport": "LOCAL"})
    store.add({"receiver_id": "rx", "from_node": "!remote", "message_text": "heard", "transport": "LORA"})
    stats = store.stats()
    assert stats["observations"] == 2
    assert stats["rf_observations"] == 1
    assert stats["local_events"] == 1
    assert stats["nodes"] == 1
    assert stats["messages"] == 1


def test_existing_database_migrates_to_local_provenance_without_data_loss(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL,
            receiver_id TEXT NOT NULL, packet_id INTEGER, from_node TEXT,
            to_node TEXT, channel INTEGER, portnum TEXT, message_text TEXT,
            rssi REAL, snr REAL, latitude REAL, longitude REAL,
            transport TEXT NOT NULL CHECK (transport IN ('LORA', 'MQTT', 'IMPORT', 'SIMULATOR')),
            raw_json TEXT NOT NULL
        );
        INSERT INTO observations
            (received_at, receiver_id, from_node, transport, raw_json)
        VALUES ('2026-08-16T00:00:00+00:00', 'old-rx', '!old', 'LORA', '{}');
        """)
    store = ObservationStore(path)
    assert store.recent(minutes=999999)[0]["from_node"] == "!old"
    store.add({"receiver_id": "old-rx", "from_node": "!self", "transport": "LOCAL"})
    assert store.stats()["local_events"] == 1
