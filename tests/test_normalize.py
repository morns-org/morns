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
