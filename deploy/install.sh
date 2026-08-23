#!/bin/bash
# Sets the server up as a service on the Raspberry Pi.
#
#   sudo bash deploy/install.sh
set -e

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="k155-gnss"

echo "Installing from $APP_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
    echo "No .env found, copying the example"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "Edit $APP_DIR/.env before starting the service"
fi

if [ ! -d "$APP_DIR/.venv" ]; then
    echo "Creating the virtual environment"
    python3 -m venv "$APP_DIR/.venv"
fi

echo "Installing dependencies"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "Writing the service file"
sed "s|/home/pi/GNSSApp|$APP_DIR|g" "$APP_DIR/deploy/$SERVICE_NAME.service" \
    > "/etc/systemd/system/$SERVICE_NAME.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "Done. Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  systemctl restart $SERVICE_NAME"
