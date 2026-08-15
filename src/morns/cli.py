from __future__ import annotations

import argparse
import logging
import threading

import uvicorn

from .api import create_app
from .collector import SerialCollector, SimulatorCollector
from .config import Settings
from .store import ObservationStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="morns", description="Run a MORNs observation station")
    parser.add_argument("--port", help="Meshtastic serial device, for example /dev/ttyACM0")
    parser.add_argument("--host", help="Web listen address")
    parser.add_argument("--web-port", type=int, help="Web listen port")
    parser.add_argument("--simulator", action="store_true", help="Generate deterministic-style demo traffic")
    args = parser.parse_args()

    base = Settings.from_env()
    settings = Settings(
        database_path=base.database_path,
        station_name=base.station_name,
        serial_port=args.port or base.serial_port,
        host=args.host or base.host,
        port=args.web_port or base.port,
        simulator=args.simulator or base.simulator,
        ingest_token=base.ingest_token,
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = ObservationStore(settings.database_path)

    collector = None
    if settings.simulator:
        collector = SimulatorCollector(store, settings.station_name)
        threading.Thread(target=collector.run, daemon=True).start()
    elif settings.serial_port:
        collector = SerialCollector(store, settings.serial_port, settings.station_name)
        collector.start()
    else:
        logging.warning("No radio selected; web interface is running in read-only mode")

    try:
        uvicorn.run(create_app(settings, store), host=settings.host, port=settings.port)
    finally:
        if collector:
            collector.close()


if __name__ == "__main__":
    main()
