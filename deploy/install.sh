#!/bin/bash
# Sets the server up as a service on the Raspberry Pi.
#
#   sudo bash deploy/install.sh
set -e

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="k155-gnss"

echo "Installing from $APP_DIR"

# --- Configuration -----------------------------------------------------------

if [ ! -f "$APP_DIR/.env" ]; then
    echo "No .env found, copying the example"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "Check $APP_DIR/.env, SERIAL_PATH and SERIAL_BAUDRATE above all"
fi

# --- Python ------------------------------------------------------------------

if [ ! -d "$APP_DIR/.venv" ]; then
    echo "Creating the virtual environment"
    python3 -m venv "$APP_DIR/.venv"
fi

echo "Installing dependencies"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# --- Bluetooth ---------------------------------------------------------------

# The phone has no other way to find the Pi, so a server without this is a
# server nobody can reach.
BLUETOOTH_ENABLED=$(grep -E '^BLUETOOTH_ENABLED=' "$APP_DIR/.env" | cut -d= -f2 | tr -d ' ')
BLUETOOTH_NAME=$(grep -E '^BLUETOOTH_NAME=' "$APP_DIR/.env" | cut -d= -f2 | tr -d ' ')
BLUETOOTH_CHANNEL=$(grep -E '^BLUETOOTH_CHANNEL=' "$APP_DIR/.env" | cut -d= -f2 | tr -d ' ')

if [ "$BLUETOOTH_ENABLED" = "1" ]; then
    echo
    echo "Setting up Bluetooth"
    BT_NAME="${BLUETOOTH_NAME:-K155GNSS}"
    BT_CHANNEL="${BLUETOOTH_CHANNEL:-1}"
    bash "$APP_DIR/deploy/bluetooth_setup.sh" "$BT_NAME" "" "$BT_CHANNEL"
else
    echo "BLUETOOTH_ENABLED is not 1, skipping the Bluetooth setup"
fi

# --- Service -----------------------------------------------------------------

echo
echo "Writing the service file"
sed "s|/home/pi/GNSSApp|$APP_DIR|g" "$APP_DIR/deploy/$SERVICE_NAME.service" \
    > "/etc/systemd/system/$SERVICE_NAME.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# --- Warnings ----------------------------------------------------------------

SERIAL_PATH=$(grep -E '^SERIAL_PATH=' "$APP_DIR/.env" | cut -d= -f2 | tr -d ' ')

if [ -n "$SERIAL_PATH" ] && [ ! -e "$SERIAL_PATH" ]; then
    echo
    echo "WARNING: $SERIAL_PATH does not exist. On a Raspberry Pi the serial"
    echo "port has to be freed first: raspi-config, Interface Options, Serial"
    echo "Port, login shell no, hardware serial yes, then reboot."
fi

if systemctl is-active --quiet serial-getty@ttyAMA0.service; then
    echo
    echo "WARNING: a login console is running on the serial port. It will fight"
    echo "the receiver for it. Turn it off in raspi-config."
fi

echo
echo "Done. Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  systemctl restart $SERVICE_NAME"
echo "  curl -s localhost:8080/status | python3 -m json.tool"
echo "  curl -s localhost:8080/bluetooth/status | python3 -m json.tool"
