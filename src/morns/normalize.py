from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_packet(
    packet: dict[str, Any], receiver_id: str = "local", local_node_num: int | None = None
) -> dict[str, Any]:
    decoded = packet.get("decoded") or {}
    position = decoded.get("position") or {}
    telemetry = decoded.get("telemetry") or {}
    text = decoded.get("text")
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "receiver_id": receiver_id,
        "packet_id": packet.get("id"),
        "from_node": packet.get("fromId") or _node_id(packet.get("from")),
        "to_node": packet.get("toId") or _node_id(packet.get("to")),
        "channel": packet.get("channel"),
        "portnum": decoded.get("portnum"),
        "message_text": text,
        "rssi": packet.get("rxRssi"),
        "snr": packet.get("rxSnr"),
        "latitude": position.get("latitude") or position.get("latitudeI") and position["latitudeI"] / 1e7,
        "longitude": position.get("longitude") or position.get("longitudeI") and position["longitudeI"] / 1e7,
        "transport": "LOCAL" if local_node_num is not None and packet.get("from") == local_node_num else "LORA",
        "telemetry": telemetry,
        "raw": packet,
    }


def _node_id(value: Any) -> str | None:
    return f"!{value:08x}" if isinstance(value, int) else None
