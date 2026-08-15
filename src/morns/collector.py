from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .normalize import normalize_packet
log = logging.getLogger(__name__)


class SerialCollector:
    def __init__(self, store: Any, port: str, receiver_id: str):
        self.store = store
        self.port = port
        self.receiver_id = receiver_id
        self.interface: Any = None

    def start(self) -> None:
        from meshtastic.serial_interface import SerialInterface
        from pubsub import pub

        pub.subscribe(self._on_receive, "meshtastic.receive")
        self.interface = SerialInterface(devPath=self.port)
        log.info("Connected receiver %s on %s", self.receiver_id, self.port)

    def _on_receive(self, packet: dict[str, Any], interface: Any = None) -> None:
        self.store.add(normalize_packet(packet, self.receiver_id))

    def close(self) -> None:
        if self.interface is not None:
            self.interface.close()


class SimulatorCollector:
    def __init__(self, store: Any, receiver_id: str, interval: float = 3.0):
        self.store = store
        self.receiver_id = receiver_id
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        sequence = 0
        while not self.stop_event.wait(self.interval):
            sequence += 1
            self.store.add({
                "received_at": datetime.now(timezone.utc).isoformat(),
                "receiver_id": self.receiver_id,
                "packet_id": sequence,
                "from_node": f"!sim{sequence % 4:04d}",
                "to_node": "^all",
                "channel": 0,
                "portnum": "TEXT_MESSAGE_APP" if sequence % 3 == 0 else "TELEMETRY_APP",
                "message_text": f"Simulated public message {sequence}" if sequence % 3 == 0 else None,
                "rssi": random.randint(-112, -72),
                "snr": round(random.uniform(-8, 9), 1),
                "latitude": 35.55 + random.uniform(-0.05, 0.05),
                "longitude": -97.55 + random.uniform(-0.05, 0.05),
                "transport": "SIMULATOR",
            })

    def close(self) -> None:
        self.stop_event.set()
