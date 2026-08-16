from morns.normalize import normalize_packet


def test_normalizes_text_packet():
    result = normalize_packet({
        "id": 42,
        "from": 0xAABBCCDD,
        "toId": "^all",
        "channel": 0,
        "rxRssi": -91,
        "rxSnr": 7.25,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": b"hello"},
    }, "test-station")
    assert result["packet_id"] == 42
    assert result["from_node"] == "!aabbccdd"
    assert result["message_text"] == "hello"
    assert result["transport"] == "LORA"


def test_normalizes_integer_position():
    result = normalize_packet({"decoded": {"position": {
        "latitudeI": 355000000, "longitudeI": -975000000
    }}})
    assert result["latitude"] == 35.5
    assert result["longitude"] == -97.5


def test_classifies_connected_devices_own_packet_as_local():
    result = normalize_packet(
        {"from": 0x18D19F7D, "decoded": {"portnum": "TELEMETRY_APP"}},
        receiver_id="receiver-one",
        local_node_num=0x18D19F7D,
    )
    assert result["from_node"] == "!18d19f7d"
    assert result["transport"] == "LOCAL"


def test_hardware_identity_does_not_affect_packet_normalization():
    packet = {"from": 0xAABBCCDD, "rxRssi": -90, "decoded": {"portnum": "NODEINFO_APP"}}
    rak = normalize_packet(packet, receiver_id="rak-fixture", local_node_num=1)
    heltec = normalize_packet(packet, receiver_id="heltec-fixture", local_node_num=2)
    seeed = normalize_packet(packet, receiver_id="seeed-fixture", local_node_num=3)
    assert {row["transport"] for row in (rak, heltec, seeed)} == {"LORA"}
    assert {row["from_node"] for row in (rak, heltec, seeed)} == {"!aabbccdd"}
