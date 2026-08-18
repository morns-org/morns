#!/bin/sh
set -eu

REPO_URL="${MORNS_REPO_URL:-https://github.com/morns-org/morns.git}"
REF="${MORNS_REF:-main}"
INSTALL_DIR="${MORNS_INSTALL_DIR:-/opt/morns}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root (for example: sudo ./scripts/install.sh)." >&2
  exit 1
fi

command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 1; }
command -v git >/dev/null || { echo "git is required." >&2; exit 1; }

if ! id morns >/dev/null 2>&1; then
  useradd --system --home /var/lib/morns --create-home --shell /usr/sbin/nologin morns
fi
if getent group dialout >/dev/null 2>&1; then
  usermod -a -G dialout morns
fi
install -d -o morns -g morns /var/lib/morns
install -d -m 0755 /etc/morns

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --tags origin "$REF"
  git -C "$INSTALL_DIR" checkout --detach FETCH_HEAD
else
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
fi

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install "$INSTALL_DIR"
sed "s|@MORNS_INSTALL_DIR@|$INSTALL_DIR|g" "$INSTALL_DIR/systemd/morns.service" \
  > /etc/systemd/system/morns.service
chmod 0644 /etc/systemd/system/morns.service

if [ ! -f /etc/morns/station.env ]; then
  cat > /etc/morns/station.env <<'EOF'
MORNS_DATABASE=/var/lib/morns/morns.db
MORNS_HOST=0.0.0.0
MORNS_PORT=8787
MORNS_STATION_NAME=MORNS Station
# Set after identifying the radio, for example: MORNS_SERIAL_PORT=/dev/ttyACM0
EOF
  chmod 0640 /etc/morns/station.env
fi

systemctl daemon-reload
systemctl enable --now morns.service
echo "MORNS is installed. Open http://$(hostname -I | awk '{print $1}'):8787"
