from datetime import datetime, timedelta, timezone

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
    assert 'data-view-section="receivers"' in page.text
    assert 'data-view-section="nodes"' in page.text
    assert 'data-view-section="messages"' in page.text
    assert 'data-view-section="coverage"' in page.text
    assert 'id="stationSettings"' in page.text
    assert "MORNS Station" in page.text
    assert '<section class="settings-page" id="setupPage"' in page.text
    assert 'id="setupModal"' not in page.text
    assert 'id="serverTimezone"' in page.text
    assert 'id="device-settings"' in page.text
    assert 'id="access-settings"' in page.text
    assert 'id="about-settings"' in page.text
    assert 'id="collectorLocation"' in page.text
    assert 'class="tool event-stream-settings"' in page.text
    assert 'id="baseTelemetryArchive"' in page.text
    assert "This MORNS server" in page.text
    assert "Local radios do not need a station API key" in page.text
    assert "MORNS is already installed on this server" in page.text
    assert "document.execCommand('copy')" in page.text
    assert "● Checking server…" in page.text
    assert "indicator.textContent=online?'● Server online':'● Server offline'" in page.text
    assert "setStationReachability(false)" in page.text
    assert 'role="status" aria-live="polite"' in page.text


def test_legacy_setup_route_opens_settings_page(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/setup", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/#settings"


def test_dashboard_has_truthful_empty_states_and_page_defaults(tmp_path):
    client, _ = make_client(tmp_path)
    page = client.get("/").text
    assert "Waiting for current station data…" in page
    assert "Waiting for current receiver observations…" in page
    assert "Waiting for current signal observations…" in page
    assert "No positioned node loaded" in page
    assert "Aug 16, 7:51 PM" not in page
    assert "!f081aff6" not in page
    assert "defaultMetrics:['messageCount','lastHeard','peakMessages']" in page
    assert "essentialTiles:['messages']" in page
    assert "Essential content cannot be hidden" in page
    assert "VIEW_METRIC_STORAGE='morns-view-metrics-v1'" in page
    assert "VIEW_TILE_STORAGE='morns-view-tiles-v1'" in page
    assert "Receiver status could not be refreshed" in page
    assert 'data-minutes="0">All time</button>' in page
    assert "retained decoded public message" in page
    assert "Encrypted or otherwise unreadable packets are not counted as messages." in page
    assert "recommendedMessageWindow" in page
    assert "/api/v1/messages/history-summary?minutes=${selected}" in page


def test_dashboard_has_windowed_and_mobile_layouts(tmp_path):
    client, _ = make_client(tmp_path)
    page = client.get("/").text
    assert "@media(max-width:1100px)" in page
    assert "@media(max-width:760px)" in page
    assert "@media(max-width:480px)" in page
    assert ".scroll table{min-width:720px}" in page
    assert ".message-history-head{flex-direction:column" in page


def test_message_api_does_not_return_non_messages(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA"})
    store.add({"receiver_id": "rx", "from_node": "!two", "message_text": "heard",
        "transport": "LORA", "ingress_transport": "USB_SERIAL",
        "raw": {"hopStart": 3, "hopLimit": 1}})
    messages = client.get("/api/v1/messages?minutes=5").json()
    assert len(messages) == 1
    assert messages[0]["message_text"] == "heard"
    assert messages[0]["hops_away"] == 2
    assert messages[0]["ingress_transport"] == "USB_SERIAL"


def test_message_observability_api_does_not_label_encrypted_packets_as_chats(tmp_path):
    client, store = make_client(tmp_path)
    store.add({
        "receiver_id": "rx", "from_node": "!public", "transport": "LORA",
        "portnum": "TEXT_MESSAGE_APP", "message_text": "readable",
    })
    store.add({
        "receiver_id": "rx", "from_node": "!private", "transport": "LORA",
        "raw": {"encrypted": "not-readable-by-this-receiver"},
    })

    body = client.get("/api/v1/messages/observability?minutes=60").json()
    assert body["decoded_public_messages"] == 1
    assert body["encrypted_undecodable_packets"] == 1
    assert body["undecodable_packets"] == 1
    assert client.get("/api/v1/messages?minutes=60").json()[0]["message_text"] == "readable"


def test_message_history_summary_counts_only_retained_decoded_public_content(tmp_path):
    client, store = make_client(tmp_path)
    older = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    redacted = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.add({
        "received_at": older, "receiver_id": "rx", "from_node": "!older",
        "transport": "LORA", "portnum": "TEXT_MESSAGE_APP", "message_text": "retained",
    })
    store.add({
        "received_at": redacted, "receiver_id": "rx", "from_node": "!redacted",
        "transport": "LORA", "portnum": "TEXT_MESSAGE_APP", "message_text": "expired",
    })
    store.add({
        "receiver_id": "rx", "from_node": "!private", "transport": "LORA",
        "raw": {"encrypted": "not-readable-by-this-receiver"},
    })
    store.enforce_retention(observation_days=30, message_days=7)

    summary = client.get("/api/v1/messages/history-summary?minutes=5").json()
    assert summary["window_minutes"] == 5
    assert summary["selected_count"] == 0
    assert summary["retained_count"] == 1
    assert summary["newest_retained_at"] == older
    assert [row["message_text"] for row in client.get(
        "/api/v1/messages?minutes=0"
    ).json()] == ["retained"]


def test_base_station_health_does_not_call_local_telemetry_rf(tmp_path):
    store = ObservationStore(tmp_path / "radio-idle.db")
    settings = Settings(
        tmp_path / "radio-idle.db", "QE Station", "/dev/ttyACM0",
        "127.0.0.1", 8787, False,
    )
    client = TestClient(create_app(settings, store))
    store.add({"receiver_id": "rx", "from_node": "!self", "transport": "LOCAL"})
    result = client.get("/api/v1/base-station/stats?minutes=60").json()
    assert result["health"] == "radio_idle"
    assert result["rf_observations"] == 0
    assert result["local_events"] == 1


def test_base_station_health_is_healthy_only_with_recent_rf(tmp_path):
    store = ObservationStore(tmp_path / "rf-health.db")
    settings = Settings(
        tmp_path / "rf-health.db", "QE Station", "/dev/ttyACM0",
        "127.0.0.1", 8787, False,
    )
    client = TestClient(create_app(settings, store))
    store.add({"receiver_id": "rx", "from_node": "!remote", "transport": "LORA"})
    result = client.get("/api/v1/base-station/stats?minutes=60").json()
    assert result["health"] == "healthy"
    assert result["health_reason"] == "Over-the-air observations are arriving"


def test_node_registry_and_detail_endpoints(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA",
        "portnum": "NODEINFO_APP", "raw": {"decoded": {"user": {
            "longName": "Test Node", "hwModel": "HELTEC_V3", "role": "CLIENT"
        }}}})
    nodes = client.get("/api/v1/nodes?minutes=60")
    assert nodes.status_code == 200
    assert nodes.json()[0]["hardware_model"] == "HELTEC_V3"
    detail = client.get("/api/v1/nodes/!one?minutes=60")
    assert detail.status_code == 200
    assert detail.json()["long_name"] == "Test Node"
    assert client.get("/api/v1/nodes/!missing?minutes=60").status_code == 404


def test_node_position_history_endpoint_returns_retained_track(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA",
        "portnum": "POSITION_APP", "latitude": 35.5, "longitude": -97.5})
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA",
        "portnum": "POSITION_APP", "latitude": 35.6, "longitude": -97.6})
    response = client.get("/api/v1/nodes/!one/positions")
    assert response.status_code == 200
    assert [row["latitude"] for row in response.json()] == [35.6, 35.5]


def test_query_limits_are_bounded(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/v1/observations?limit=5001").status_code == 422


def test_map_scale_time_windows_are_accepted(tmp_path):
    client, _ = make_client(tmp_path)
    for minutes in (0, 5, 60, 1440, 10080, 43200, 129600, 525600):
        assert client.get(f"/api/v1/observations?minutes={minutes}").status_code == 200


def test_stats_exposes_history_and_retention_for_dynamic_map_ranges(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "rx", "from_node": "!one", "transport": "LORA"})
    stats = client.get("/api/v1/stats").json()
    assert stats["oldest_received_at"] is not None
    assert stats["observation_retention_days"] == 365
    assert stats["message_retention_days"] == 30
    assert stats["base_station_telemetry_archive_days"] == 30
    assert 525600 in stats["map_windows_minutes"]
    assert 0 in stats["map_windows_minutes"]


def test_base_station_health_explains_awaiting_data(tmp_path):
    settings = Settings(tmp_path / "station.db", "Test station", None, "127.0.0.1", 8787, False, "test-token")
    client = TestClient(create_app(settings=settings))
    stats = client.get("/api/v1/base-station/stats?minutes=60")
    assert stats.status_code == 200
    body = stats.json()
    assert body["health"] == "awaiting_data"
    assert body["operational_uptime_seconds"] >= 0
    assert body["window_minutes"] == 60


def test_base_station_nodes_are_distinct_lora_nodes_in_requested_window(tmp_path):
    client, store = make_client(tmp_path)
    recent = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.add({"receiver_id": "rx", "from_node": "!recent", "transport": "LORA", "received_at": recent})
    store.add({"receiver_id": "rx", "from_node": "!recent", "transport": "LORA", "received_at": recent})
    store.add({"receiver_id": "rx", "from_node": "!local", "transport": "LOCAL", "received_at": recent})
    store.add({"receiver_id": "rx", "from_node": "!old", "transport": "LORA", "received_at": old})

    body = client.get("/api/v1/base-station/stats?minutes=60").json()

    assert body["nodes"] == 1

    all_time = client.get("/api/v1/base-station/stats?minutes=0").json()
    assert all_time["window_minutes"] == 0
    assert all_time["nodes"] == 2


def test_ingest_requires_configured_token(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/api/v1/ingest", json={}).status_code == 503


def test_ingest_authenticates_and_preserves_physical_provenance(tmp_path):
    path = tmp_path / "ingest.db"
    store = ObservationStore(path)
    settings = Settings(path, "QE Station", None, "127.0.0.1", 8787, False, "secret")
    client = TestClient(create_app(settings, store))
    packet = {
        "receiver_id": "physical-one",
        "from_node": "!abc",
        "message_text": "real",
        "transport": "LORA",
    }
    assert client.post("/api/v1/ingest", json=packet).status_code == 401
    response = client.post(
        "/api/v1/ingest", json=packet, headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 202
    assert store.recent()[0]["transport"] == "LORA"

    local = {"receiver_id": "physical-one", "from_node": "!self", "transport": "LOCAL"}
    response = client.post(
        "/api/v1/ingest", json=local, headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 202
    assert store.recent()[0]["transport"] == "LOCAL"


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


def test_receiver_setup_has_actionable_persistent_flow(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/health").json()["setup_complete"] is False
    setup = {
        "station_name": "Community receiver",
        "server_timezone": "America/Chicago",
        "country_code": "US",
        "location_policy": "approximate",
        "location_method": "postal_code",
        "postal_code": "73100",
        "latitude": 35.5,
        "longitude": -97.5,
        "radius_km": 8,
    }
    response = client.put("/api/v1/setup", json=setup)
    assert response.status_code == 200
    assert response.json()["location_policy"] == "approximate"
    health = client.get("/health").json()
    assert health["setup_complete"] is True
    assert health["station"] == "Community receiver"
    assert health["station_latitude"] == 35.5
    assert health["server_timezone"] == "America/Chicago"
    assert client.get("/api/v1/setup").json()["radius_km"] == 8


def test_receiver_setup_rejects_unknown_timezone(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.put("/api/v1/setup", json={
        "station_name": "Receiver", "server_timezone": "Centralish/Somewhere",
        "country_code": "US", "location_policy": "precise", "location_method": "manual",
        "latitude": 35.5, "longitude": -97.5, "radius_km": 8,
    })
    assert response.status_code == 422


def test_receiver_setup_rejects_invalid_location(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.put("/api/v1/setup", json={
        "station_name": "Receiver", "location_policy": "precise",
        "location_method": "manual",
        "latitude": 95, "longitude": -97.5, "radius_km": 8,
    })
    assert response.status_code == 422


def test_receiver_setup_rejects_telemetry_archive_beyond_observations(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.put("/api/v1/setup", json={
        "station_name": "Receiver", "location_policy": "precise",
        "location_method": "manual", "latitude": 35.5, "longitude": -97.5,
        "radius_km": 8, "observation_retention_days": 30,
        "base_station_telemetry_archive_days": 90,
    })
    assert response.status_code == 422


def test_observation_api_can_hide_base_station_telemetry(tmp_path):
    client, store = make_client(tmp_path)
    store.add({"receiver_id": "base", "from_node": "!self", "transport": "LOCAL",
               "portnum": "TELEMETRY_APP"})
    store.add({"receiver_id": "base", "from_node": "!remote", "transport": "LORA",
               "portnum": "TELEMETRY_APP"})
    rows = client.get(
        "/api/v1/observations?include_base_station_telemetry=false"
    ).json()
    assert len(rows) == 1
    assert rows[0]["transport"] == "LORA"


def test_zip_lookup_uses_local_census_index(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/v1/location/postal-code?postal_code=73120")
    assert response.status_code == 200
    result = response.json()
    assert 35 < result["latitude"] < 36
    assert -98 < result["longitude"] < -97
    assert "Census" in result["source"]


def test_zip_lookup_rejects_invalid_or_unmapped_codes(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/api/v1/location/postal-code?postal_code=ABCDE").status_code == 422
    assert client.get("/api/v1/location/postal-code?postal_code=00000").status_code == 404


def test_location_dataset_discloses_vintage_and_update_policy(tmp_path):
    client, _ = make_client(tmp_path)
    result = client.get("/api/v1/location/datasets").json()
    assert result["datasets"][0]["vintage"] == "2025"
    assert "never move automatically" in result["update_policy"]


def test_canadian_setup_supports_device_or_manual_location(tmp_path):
    client, _ = make_client(tmp_path)
    setup = {
        "station_name": "Canadian receiver",
        "country_code": "CA",
        "location_policy": "approximate",
        "location_method": "manual",
        "latitude": 45.4215,
        "longitude": -75.6972,
        "radius_km": 8,
    }
    assert client.put("/api/v1/setup", json=setup).status_code == 200
    setup["location_method"] = "postal_code"
    setup["postal_code"] = "K1A0B1"
    assert client.put("/api/v1/setup", json=setup).status_code == 422


def test_context_layer_requires_setup_location(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/v1/map-layers/weather-stations")
    assert response.status_code == 409


def test_context_layer_preserves_provider_provenance(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    client.put("/api/v1/setup", json={
        "station_name": "Weather test", "country_code": "US",
        "location_policy": "approximate", "location_method": "manual",
        "latitude": 35.5, "longitude": -97.5, "radius_km": 8,
    })
    def fake_layer(kind, latitude, longitude):
        return {"type": "FeatureCollection", "features": [], "layer": kind,
            "provider": {"name": "NOAA/National Weather Service"},
            "retrieved_at": "2026-08-16T00:00:00+00:00", "freshness": "current"}
    monkeypatch.setattr("morns.api.nws_layer", fake_layer)
    response = client.get("/api/v1/map-layers/weather-stations")
    assert response.status_code == 200
    assert response.json()["provider"]["name"] == "NOAA/National Weather Service"
    assert client.get("/api/v1/map-layers/not-real").status_code == 404
