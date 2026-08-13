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
    assert client.get("/health").json()["status"] == "ok"
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
