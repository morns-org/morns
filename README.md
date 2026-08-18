# MORNS

MORNS is a local-first, protocol-agnostic observation platform. It records what physically attached receivers and approved data adapters observe, preserves source provenance, and exposes a web interface for nodes, signals, messages, locations, and optional public-interest map layers. Meshtastic is the first supported radio adapter; MORNS is independent and is not affiliated with or endorsed by the Meshtastic project.

This repository is an early MVP. It currently provides a single-station SQLite event log and local dashboard. 

## Future
Public federation, accounts, nationwide maps, encrypted MORNS Rooms, and automated device configuration are planned.

## What works now

- Direct Meshtastic serial ingestion
- Append-only observation history in SQLite
- Explicit `LORA`, `LOCAL`, `MQTT`, `IMPORT`, or `SIMULATOR` provenance
- Local health, statistics, observations, and message APIs
- Browser dashboard with the requested time windows
- Safe simulator mode for evaluation without a radio
- Docker Compose QE environment
- Raspberry Pi OS systemd installer
- Native host collector for macOS/Linux radios feeding a Docker server

MORNS logs decoded messages supplied by the connected device. It does not break Meshtastic encryption, obtain private keys, or decode channels the receiver does not belong to.

MORNS is manufacturer-agnostic. RAK, Heltec, Seeed Studio, LilyGO, and other compatible devices use the same Meshtastic protocol contract; manufacturer and model are setup metadata, not an allowlist. Public accounts and federation are planned only alongside enforceable privacy, retention, and erasure controls.

## Try it safely

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
morns --simulator --host 127.0.0.1
```

Open <http://127.0.0.1:8787>. Simulator events are visibly marked `SIMULATOR` and cannot be mistaken for RF coverage evidence.

Binding MORNS to `0.0.0.0` makes decoded message history visible to devices that can reach the station. Keep it on a trusted network until authentication and public-station privacy controls are implemented.

## Connect a radio

Identify the serial device, then run:

```bash
morns --port /dev/ttyACM0 --host 0.0.0.0
```

On macOS the device commonly resembles `/dev/cu.usbmodem*`. On Raspberry Pi OS it commonly resembles `/dev/ttyACM0`. MORNS does not change radio settings.

## macOS radio with a Docker server

Docker Desktop runs Linux inside a virtual machine and does not expose macOS serial devices as ordinary Linux device paths. MORNS therefore separates the native radio collector from the containerized server.

Create a local environment file with a unique token:

```bash
cp .env.example .env
sed -i '' "s/replace-with-a-long-random-token/$(openssl rand -hex 32)/" .env
docker compose up --build -d --wait
```

Install the collector in a Python environment on the Mac and point it at the serial device:

```bash
python3 -m venv .collector-venv
. .collector-venv/bin/activate
pip install .
set -a; . ./.env; set +a
morns-collector \
  --port /dev/cu.usbmodem1101 \
  --server http://127.0.0.1:8787 \
  --token "$MORNS_INGEST_TOKEN" \
  --receiver-id home-station
```

Use the actual device returned by `ls /dev/cu.usbmodem*`. The collector reads packets through Meshtastic's client API and never changes radio settings. The Docker port binds to localhost by default; exposing it to a LAN or the internet requires an explicit deployment configuration and authentication review.

## Raspberry Pi installation

On a fresh 64-bit Raspberry Pi OS installation:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone https://github.com/morns-org/morns.git
cd morns
sudo ./scripts/install.sh
```

Then edit `/etc/morns/station.env`, set `MORNS_SERIAL_PORT`, and restart the service:

```bash
sudo systemctl restart morns
sudo systemctl status morns
```

The service runs as an unprivileged `morns` user. Add that user to the serial device's group if required (commonly `dialout`), then restart the Pi.

## Quality engineering

Run unit and API tests:

```bash
pip install -e '.[test]'
pytest --cov=morns
```

Run MORNS normally (no generated observations):

```bash
docker compose up --build -d --wait
curl http://127.0.0.1:8787/health
docker compose down -v
```

Run the isolated simulator only when explicitly evaluating the interface:

```bash
docker compose -f compose.yaml -f compose.qe.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.qe.yaml down -v
```

Simulator mode is visibly disclosed by the health API and dashboard. Never use simulator observations for RF coverage analysis.

The container runs without Linux capabilities, with a read-only root filesystem and a dedicated data volume. QE automation should interact through a constrained controller rather than receiving unrestricted access to the Docker socket.

## API

- `GET /health`
- `GET /api/v1/stats`
- `GET /api/v1/observations?minutes=60&limit=500`
- `GET /api/v1/messages?minutes=60&limit=500`
- `POST /api/v1/ingest` (authenticated physical collector)

Accepted history windows are 5, 10, and 30 minutes; 1, 6, 12, and 24 hours; 7 days; and 1 month.

## License

MORNS is open-source software under the [Apache License 2.0](LICENSE), including its permission for commercial use.

The software license does not grant rights to scrape, resell, enrich, or otherwise reuse data from the official hosted MORNS service. The hosted service, API, federation, trademarks, and community observation dataset have separate terms; their default purpose is non-commercial community, educational, research, public-safety, environmental, and amateur-radio use.
