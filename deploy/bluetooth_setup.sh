#!/bin/bash
# Prepares the Raspberry Pi so a phone can pair with it and open a serial
# connection to the server.
#
#   sudo bash deploy/bluetooth_setup.sh [name] [pin]
#
# Without a pin the Pi pairs with no prompt at all, which is convenient and
# means anyone within range can pair. With a pin the phone has to type it, and
# a small agent service supplies it from the Pi side, since a headless Pi has
# no keyboard to enter one on.
#
# Three things have to be true before Android can connect:
#   1. The adapter is discoverable and accepts pairing without a keyboard
#   2. A Serial Port Profile record is published, otherwise the phone cannot
#      find the channel to connect to
#   3. Something is listening on that channel, which is the server itself
set -e

NAME="${1:-K155GNSS}"
PIN="${2:-}"

echo "Setting the Pi up as \"$NAME\""

# --- Packages ----------------------------------------------------------------

if ! command -v bluetoothctl >/dev/null; then
    echo "Installing bluez"
    apt-get update
    apt-get install -y bluez
fi

# --- Compatibility mode ------------------------------------------------------

# Publishing a Serial Port Profile record with sdptool needs bluetoothd running
# in compatibility mode, which it does not do by default.
SERVICE_FILE="/lib/systemd/system/bluetooth.service"
OVERRIDE_DIR="/etc/systemd/system/bluetooth.service.d"

if ! grep -q '\-\-compat' "$SERVICE_FILE" 2>/dev/null && [ ! -f "$OVERRIDE_DIR/compat.conf" ]; then
    echo "Turning on bluetoothd compatibility mode"
    mkdir -p "$OVERRIDE_DIR"
    EXEC_LINE=$(grep '^ExecStart=' "$SERVICE_FILE" | head -1)
    cat > "$OVERRIDE_DIR/compat.conf" <<EOF
[Service]
ExecStart=
$EXEC_LINE --compat
EOF
    systemctl daemon-reload
    systemctl restart bluetooth
    sleep 2
fi

# --- Pairing agent -----------------------------------------------------------

if [ -n "$PIN" ]; then
    if ! command -v bt-agent >/dev/null; then
        echo "Installing bluez-tools for the pairing agent"
        apt-get install -y bluez-tools
    fi

    echo "Requiring pin $PIN when pairing"

    # One line per device, the star matches any of them
    echo "* $PIN" > /etc/bluetooth/pins
    chmod 600 /etc/bluetooth/pins

    cat > /etc/systemd/system/bt-agent.service <<EOF
[Unit]
Description=Bluetooth pairing agent for $NAME
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c DisplayOnly -p /etc/bluetooth/pins
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now bt-agent
    AGENT_MODE="DisplayOnly"
else
    echo "Pairing without a pin, anyone in range can pair"
    AGENT_MODE="NoInputNoOutput"
fi

# --- Adapter -----------------------------------------------------------------

echo "Naming the adapter and making it discoverable"

# The alias is what the phone shows in its list of devices
bluetoothctl <<EOF
power on
system-alias $NAME
discoverable on
pairable on
agent $AGENT_MODE
default-agent
EOF

# Discoverability normally times out after three minutes. A field unit has
# nobody around to press a button, so it stays discoverable.
btmgmt discoverable yes 2>/dev/null || true

# --- Serial Port Profile record ----------------------------------------------

echo "Publishing the Serial Port Profile record"
sdptool add --channel=1 SP || echo "sdptool failed, check that compatibility mode is on"

sdptool browse local | grep -A2 "Serial Port" || echo "No serial port record found"

echo
echo "Done. On the phone:"
if [ -n "$PIN" ]; then
    echo "  1. Bluetooth settings, pair with \"$NAME\", pin $PIN"
else
    echo "  1. Bluetooth settings, pair with \"$NAME\""
fi
echo "  2. Open the app, it connects to the serial profile and hands over"
echo "     the hotspot credentials"
echo
echo "Set BLUETOOTH_ENABLED=1 in .env and restart the service:"
echo "  sudo systemctl restart k155-gnss"
