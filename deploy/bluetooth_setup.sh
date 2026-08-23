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

# --- Adapter powers up at boot -----------------------------------------------

# Without this the radio comes up powered down after a reboot, and a socket
# still binds happily on a powered down adapter, so nothing looks wrong until a
# phone tries to find the Pi and cannot.
MAIN_CONF="/etc/bluetooth/main.conf"

if [ -f "$MAIN_CONF" ]; then
    echo "Making the adapter power up at boot"

    if grep -q '^\s*#\?\s*AutoEnable' "$MAIN_CONF"; then
        sed -i 's/^\s*#\?\s*AutoEnable.*/AutoEnable=true/' "$MAIN_CONF"
    elif grep -q '^\[Policy\]' "$MAIN_CONF"; then
        sed -i '/^\[Policy\]/a AutoEnable=true' "$MAIN_CONF"
    else
        printf '\n[Policy]\nAutoEnable=true\n' >> "$MAIN_CONF"
    fi

    # Discoverability otherwise expires after three minutes
    if grep -q '^\s*#\?\s*DiscoverableTimeout' "$MAIN_CONF"; then
        sed -i 's/^\s*#\?\s*DiscoverableTimeout.*/DiscoverableTimeout = 0/' "$MAIN_CONF"
    else
        sed -i '/^\[General\]/a DiscoverableTimeout = 0' "$MAIN_CONF"
    fi

    # An adapter reporting a class of zero says nothing about what it is, and
    # some phones refuse to bond with it. 0x1F00 is an uncategorised computer.
    if grep -q '^\s*#\?\s*Class' "$MAIN_CONF"; then
        sed -i 's/^\s*#\?\s*Class.*/Class = 0x1F00/' "$MAIN_CONF"
    else
        sed -i '/^\[General\]/a Class = 0x1F00' "$MAIN_CONF"
    fi

    systemctl restart bluetooth
    sleep 2
fi

# --- Pairing agent -----------------------------------------------------------

# An agent has to be running for the whole time the Pi is up. Registering one
# from a piped bluetoothctl session is no use, the agent disappears the moment
# that session ends, and pairing then fails on the phone with nothing on this
# side to answer it. So the agent gets its own service.

if ! command -v bt-agent >/dev/null; then
    echo "Installing bluez-tools for the pairing agent"
    apt-get install -y bluez-tools
fi

if [ -n "$PIN" ]; then
    echo "Requiring pin $PIN when pairing"

    # One line per device, the star matches any of them
    echo "* $PIN" > /etc/bluetooth/pins
    chmod 600 /etc/bluetooth/pins

    AGENT_ARGS="-c DisplayOnly -p /etc/bluetooth/pins"
    AGENT_MODE="DisplayOnly"
else
    echo "Pairing without a pin, anyone in range can pair"

    # A pin file left behind by an earlier run would make the agent answer with
    # a pin the phone was never asked for, which Android reports as a wrong pin
    rm -f /etc/bluetooth/pins

    # Accepts the pairing itself, so a headless Pi needs nobody to confirm
    AGENT_ARGS="-c NoInputNoOutput"
    AGENT_MODE="NoInputNoOutput"
fi

cat > /etc/systemd/system/bt-agent.service <<EOF
[Unit]
Description=Bluetooth pairing agent for $NAME
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent $AGENT_ARGS
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now bt-agent
systemctl is-active --quiet bt-agent && echo "Pairing agent running ($AGENT_MODE)"     || echo "Pairing agent failed to start, pairing will not work"

# --- Adapter -----------------------------------------------------------------

# A soft block leaves the adapter looking configured but powered down, and
# every command below would quietly fail to take effect
if rfkill list bluetooth 2>/dev/null | grep -q "Soft blocked: yes"; then
    echo "Bluetooth is soft blocked, unblocking"
    rfkill unblock bluetooth
    sleep 1
fi

echo "Naming the adapter and making it discoverable"

# The alias is what the phone shows in its list of devices
bluetoothctl <<EOF
power on
system-alias $NAME
pairable on
discoverable-timeout 0
discoverable on
agent $AGENT_MODE
default-agent
EOF

echo "Adapter state:"
bluetoothctl show | grep -E "Alias|Powered|Discoverable:|Pairable:"


# Discoverability normally times out after three minutes. A field unit has
# nobody around to press a button, so it stays discoverable.
btmgmt discoverable yes 2>/dev/null || true

# --- Serial Port Profile record ----------------------------------------------

echo "Publishing the Serial Port Profile record"
sdptool add --channel=1 SP || echo "sdptool failed, check that compatibility mode is on"

sdptool browse local | grep -A2 "Serial Port" || echo "No serial port record found"

echo
echo "If a phone was paired before, remove the old bond on both sides first."
echo "On the Pi:"
bluetoothctl devices Paired | sed 's/^/  /' || true
echo "  bluetoothctl remove <address>"
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
