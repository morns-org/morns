from datetime import datetime, timezone

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
