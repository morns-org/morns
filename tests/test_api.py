from fastapi.testclient import TestClient

from morns.api import create_app
from morns.config import Settings
from morns.store import ObservationStore


def make_client(tmp_path):
    store = ObservationStore(tmp_path / "api.db")
    settings = Settings(tmp_path / "api.db", "QE Station", None, "127.0.0.1", 8787, False)
    return TestClient(create_app(settings, store)), store


def test_health_and_dashboard(tmp_path):
    client, _ = make_client(tmp_path)
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["simulator"] is False
    assert health["radio_configured"] is False
    page = client.get("/")
    assert page.status_code == 200
    assert "Public message history" in page.text


def test_message_api_does_not_return_non_messages(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA"})
    store.add({"receiver_id": "rx", "from_node": "!two", "message_text": "heard", "transport": "LORA"})
    messages = client.get("/api/v1/messages?minutes=5").json()
    assert len(messages) == 1
    assert messages[0]["message_text"] == "heard"


def test_query_limits_are_bounded(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/v1/observations?limit=5001").status_code == 422


def test_ingest_requires_configured_token(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/api/v1/ingest", json={}).status_code == 503


def test_ingest_authenticates_and_forces_lora_provenance(tmp_path):
    path = tmp_path / "ingest.db"
    store = ObservationStore(path)
    settings = Settings(path, "QE Station", None, "127.0.0.1", 8787, False, "secret")
    client = TestClient(create_app(settings, store))
    packet = {"receiver_id": "physical-one", "from_node": "!abc", "message_text": "real"}
    assert client.post("/api/v1/ingest", json=packet).status_code == 401
    response = client.post(
        "/api/v1/ingest", json=packet, headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 202
    assert store.recent()[0]["transport"] == "LORA"


def test_ingest_rejects_simulator_provenance(tmp_path):
    path = tmp_path / "ingest.db"
    store = ObservationStore(path)
    settings = Settings(path, "QE Station", None, "127.0.0.1", 8787, False, "secret")
    client = TestClient(create_app(settings, store))
    response = client.post(
        "/api/v1/ingest",
        json={"receiver_id": "fake", "transport": "SIMULATOR"},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 422
