from datetime import datetime, timedelta, timezone
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


def test_message_observability_separates_public_text_from_ciphertext(tmp_path):
    store = ObservationStore(tmp_path / "visibility.db")
    store.add({
        "receiver_id": "rx", "from_node": "!public", "transport": "LORA",
        "portnum": "TEXT_MESSAGE_APP", "message_text": "hello",
        "raw": {"decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hello"}},
    })
    store.add({
        "receiver_id": "rx", "from_node": "!telemetry", "transport": "LORA",
        "portnum": "TELEMETRY_APP", "raw": {"decoded": {"portnum": "TELEMETRY_APP"}},
    })
    store.add({
        "receiver_id": "rx", "from_node": "!private", "transport": "LORA",
        "raw": {"encrypted": b"ciphertext"},
    })
    store.add({
        "receiver_id": "rx", "from_node": "!unknown", "transport": "LORA",
        "raw": {"id": 4},
    })
    store.add({
        "receiver_id": "rx", "from_node": "!self", "transport": "LOCAL",
        "message_text": "local status",
    })

    result = store.message_observability(60)
    assert result == {
        "rf_packets": 4,
        "decoded_packets": 2,
        "decoded_public_messages": 1,
        "encrypted_undecodable_packets": 1,
        "other_undecodable_packets": 1,
        "window_minutes": 60,
        "undecodable_packets": 2,
    }
    assert [row["message_text"] for row in store.recent(messages_only=True)] == ["hello"]


def test_message_classification_survives_content_retention_redaction(tmp_path):
    store = ObservationStore(tmp_path / "visibility-retention.db")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.add({
        "received_at": old, "receiver_id": "rx", "from_node": "!public",
        "transport": "LORA", "portnum": "TEXT_MESSAGE_APP", "message_text": "expired",
    })
    store.enforce_retention(observation_days=30, message_days=7)

    assert store.message_observability(60 * 24 * 30)["decoded_public_messages"] == 1
    assert store.recent(minutes=60 * 24 * 30, messages_only=True) == []


def test_node_registry_combines_declared_observed_and_telemetry_fields(tmp_path):
    store = ObservationStore(tmp_path / "nodes.db")
    base = {"receiver_id": "rx", "from_node": "!abc12345", "transport": "LORA"}
    store.add({**base, "portnum": "NODEINFO_APP", "rssi": -105, "snr": 4.5, "raw": {
        "hopStart": 3, "hopLimit": 1, "decoded": {"user": {
            "id": "!abc12345", "longName": "Garden Relay", "shortName": "GRDN",
            "hwModel": "RAK4631", "role": "ROUTER_LATE", "publicKey": "public-only",
        }}}})
    store.add({**base, "portnum": "TELEMETRY_APP", "rssi": -110, "snr": 2.0, "raw": {
        "decoded": {"telemetry": {"deviceMetrics": {
            "batteryLevel": 82, "voltage": 4.03, "uptimeSeconds": 3600,
        }}}}})
    store.add({**base, "portnum": "POSITION_APP", "latitude": 35.5, "longitude": -97.5,
        "raw": {"decoded": {"position": {"altitude": 350, "locationSource": "LOC_INTERNAL"}}}})

    node = store.nodes(60)[0]
    assert node["hardware_model"] == "RAK4631"
    assert node["role"] == "ROUTER_LATE"
    assert node["public_key_available"] is True
    assert "public-only" not in str(node)
    assert node["battery_level"] == 82
    assert node["latitude"] == 35.5
    assert node["hops_away"] == 2
    assert node["observations"] == 3


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


def test_retention_redacts_message_content_before_observation_expiry(tmp_path):
    store = ObservationStore(tmp_path / "retention.db")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    expired = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    store.add({"received_at": old, "receiver_id": "rx", "from_node": "!old",
               "message_text": "forget me", "raw": {"text": "forget me"}, "transport": "LORA"})
    store.add({"received_at": expired, "receiver_id": "rx", "from_node": "!expired",
               "transport": "LORA"})
    result = store.enforce_retention(observation_days=30, message_days=7)
    assert result == {
        "base_station_telemetry_archived": 0,
        "messages_redacted": 1,
        "observations_deleted": 1,
    }
    retained = store.recent(minutes=60 * 24 * 30)
    assert retained[0]["message_text"] is None
    assert retained[0]["raw_json"] == "{}"


def test_base_station_stats_are_windowed_and_use_broadcast_positions(tmp_path):
    store = ObservationStore(tmp_path / "stats.db")
    store.add({
        "receiver_id": "base", "from_node": "!near", "transport": "LORA",
        "message_text": "hello", "latitude": 35.5, "longitude": -97.5,
        "receiver_latitude": 35.5, "receiver_longitude": -97.51,
    })
    store.add({
        "receiver_id": "base", "from_node": "!far", "transport": "LORA",
        "latitude": 35.6, "longitude": -97.5,
        "receiver_latitude": 35.5, "receiver_longitude": -97.51,
    })
    stats = store.base_station_stats(60)
    assert stats["observations"] == 2
    assert stats["nodes"] == 2
    assert stats["messages"] == 1
    assert stats["peak_observations"] == 2
    assert stats["farthest_contact"]["node_id"] == "!far"
    assert stats["farthest_contact"]["distance_km"] > 10
    assert stats["farthest_contact"]["latitude"] == 35.6
    assert stats["farthest_contact"]["longitude"] == -97.5


def test_recent_zero_minutes_means_all_retained_history(tmp_path):
    store = ObservationStore(tmp_path / "all-time.db")
    store.add({
        "received_at": "2020-01-01T00:00:00+00:00",
        "receiver_id": "base", "from_node": "!old", "transport": "LORA",
    })
    assert store.recent(0)[0]["from_node"] == "!old"


def test_event_stream_can_hide_only_base_station_telemetry(tmp_path):
    store = ObservationStore(tmp_path / "telemetry-filter.db")
    store.add({"receiver_id": "base", "from_node": "!self", "transport": "LOCAL",
               "portnum": "TELEMETRY_APP"})
    store.add({"receiver_id": "base", "from_node": "!remote", "transport": "LORA",
               "portnum": "TELEMETRY_APP"})
    store.add({"receiver_id": "base", "from_node": "!self", "transport": "LOCAL",
               "portnum": "NODEINFO_APP"})

    rows = store.recent(include_base_station_telemetry=False)
    assert {(row["transport"], row["portnum"]) for row in rows} == {
        ("LORA", "TELEMETRY_APP"), ("LOCAL", "NODEINFO_APP")
    }


def test_base_station_telemetry_has_independent_archive(tmp_path):
    store = ObservationStore(tmp_path / "telemetry-retention.db")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    store.add({"received_at": old, "receiver_id": "base", "from_node": "!self",
               "transport": "LOCAL", "portnum": "TELEMETRY_APP"})
    store.add({"received_at": recent, "receiver_id": "base", "from_node": "!self",
               "transport": "LOCAL", "portnum": "TELEMETRY_APP"})
    store.add({"received_at": old, "receiver_id": "base", "from_node": "!remote",
               "transport": "LORA", "portnum": "TELEMETRY_APP"})

    result = store.enforce_retention(30, 30, base_station_telemetry_days=7)
    assert result["base_station_telemetry_archived"] == 1
    assert {(row["transport"], row["received_at"]) for row in store.recent(0)} == {
        ("LOCAL", recent), ("LORA", old)
    }
    with store.connect() as db:
        archived = db.execute(
            "SELECT received_at, transport, portnum FROM archived_base_station_telemetry"
        ).fetchone()
    assert dict(archived) == {
        "received_at": old, "transport": "LOCAL", "portnum": "TELEMETRY_APP"
    }
    assert store.stats()["archived_base_station_telemetry"]["observations"] == 1


def test_base_station_stats_use_saved_station_fallback_for_old_positions(tmp_path):
    store = ObservationStore(tmp_path / "fallback-stats.db")
    store.add({
        "receiver_id": "base", "from_node": "!far", "transport": "LORA",
        "latitude": 35.6, "longitude": -97.5,
    })
    stats = store.base_station_stats(60, 35.5, -97.51)
    assert stats["farthest_contact"]["node_id"] == "!far"
    assert stats["farthest_contact"]["distance_km"] > 10


def test_base_station_stats_separate_rf_from_local_events(tmp_path):
    store = ObservationStore(tmp_path / "health-stats.db")
    store.add({"receiver_id": "base", "from_node": "!self", "transport": "LOCAL"})
    stats = store.base_station_stats(60)
    assert stats["observations"] == 1
    assert stats["rf_observations"] == 0
    assert stats["local_events"] == 1
    assert stats["last_rf_received_at"] is None


def test_position_history_retains_every_declared_position_newest_first(tmp_path):
    store = ObservationStore(tmp_path / "positions.db")
    start = datetime(2026, 8, 16, tzinfo=timezone.utc)
    for index, latitude in enumerate((35.50, 35.51, 35.52)):
        store.add({
            "received_at": (start + timedelta(minutes=index)).isoformat(),
            "receiver_id": "rx", "from_node": "!moving", "transport": "LORA",
            "portnum": "POSITION_APP", "latitude": latitude, "longitude": -97.5,
        })
    history = store.position_history("!moving")
    assert [row["latitude"] for row in history] == [35.52, 35.51, 35.50]


def test_mobility_classification_rejects_implausible_jumps(tmp_path):
    store = ObservationStore(tmp_path / "implausible.db")
    start = datetime(2026, 8, 16, tzinfo=timezone.utc)
    points = ((35.50, -97.50), (40.71, -74.00), (35.5001, -97.5001))
    for index, (latitude, longitude) in enumerate(points):
        store.add({
            "received_at": (start + timedelta(minutes=index)).isoformat(),
            "receiver_id": "rx", "from_node": "!jump", "transport": "LORA",
            "latitude": latitude, "longitude": longitude,
        })
    mobility = store.refresh_mobility_states()["!jump"]
    assert mobility["state"] == "unknown"
    assert mobility["evidence"]["rejected_as_implausible"] >= 1


def test_mobility_transition_from_mobile_to_long_dwell_static_is_recorded(tmp_path):
    store = ObservationStore(tmp_path / "mobility.db")
    start = datetime(2026, 8, 16, tzinfo=timezone.utc)
    mobile = (
        (start, 35.5000, -97.5000),
        (start + timedelta(minutes=10), 35.5100, -97.5000),
        (start + timedelta(minutes=20), 35.5200, -97.5000),
    )
    for received_at, latitude, longitude in mobile:
        store.add({"received_at": received_at.isoformat(), "receiver_id": "rx",
            "from_node": "!traveler", "transport": "LORA",
            "latitude": latitude, "longitude": longitude})
    assert store.refresh_mobility_states()["!traveler"]["state"] == "potential_mobile"

    for hours, latitude in ((7, 35.5200), (10, 35.5201), (13, 35.5199)):
        store.add({"received_at": (start + timedelta(hours=hours)).isoformat(),
            "receiver_id": "rx", "from_node": "!traveler", "transport": "LORA",
            "latitude": latitude, "longitude": -97.5000})
    mobility = store.refresh_mobility_states()["!traveler"]
    assert mobility["state"] == "potential_static"
    assert any(t["from_state"] == "potential_mobile" and
               t["to_state"] == "potential_static" for t in mobility["transitions"])
