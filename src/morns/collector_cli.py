from __future__ import annotations

import argparse
import logging
import signal
import threading

from .collector import SerialCollector
from .remote import HttpObservationSink


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="morns-collector",
        description="Forward a locally attached Meshtastic radio to a MORNs server",
    )
    parser.add_argument("--port", required=True, help="Serial device, such as /dev/cu.usbmodem1101")
    parser.add_argument("--server", default="http://127.0.0.1:8787", help="MORNs server URL")
    parser.add_argument("--token", required=True, help="Station ingest token")
    parser.add_argument("--receiver-id", required=True, help="Stable public receiver identifier")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sink = HttpObservationSink(args.server, args.token)
    collector = SerialCollector(sink, args.port, args.receiver_id)
    collector.start()
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    logging.info("Forwarding physical LoRa observations to %s", args.server)
    try:
        stopped.wait()
    finally:
        collector.close()


if __name__ == "__main__":
    main()
