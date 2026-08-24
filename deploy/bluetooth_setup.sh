#!/bin/bash
# Prepares the Raspberry Pi so a phone can pair with it and open a serial
# connection to the server.
#
#   sudo bash deploy/bluetooth_setup.sh [name] [pin] [rfcomm channel]
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
CHANNEL="${3:-1}"

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

    # Restarting Bluetooth takes the controller away for a few seconds, so it
    # only happens when the file really changed rather than on every run
    CONF_BEFORE=$(md5sum "$MAIN_CONF" | cut -d' ' -f1)

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

    CONF_AFTER=$(md5sum "$MAIN_CONF" | cut -d' ' -f1)

    if [ "$CONF_BEFORE" != "$CONF_AFTER" ]; then
        systemctl restart bluetooth
        sleep 2
    else
        echo "$MAIN_CONF was already right, leaving Bluetooth running"
    fi
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

# --- Attaching the radio -----------------------------------------------------

# On a Raspberry Pi the built in radio hangs off a UART and hciuart flashes its
# firmware at boot. With the receiver on the good PL011 the radio is left on the
# mini UART, whose baud rate follows the VPU core clock, so the handshake can
# time out for no reason anybody can see: "btuart: Initialization timed out".
# It then never runs again, /sys/class/bluetooth stays empty, bluetooth.service
# is skipped for a failed ConditionPathIsDirectory, and there is no Bluetooth
# at all until somebody logs in. Retrying turns a lost race into a slow start.
if [ -f /lib/systemd/system/hciuart.service ]; then
    echo "Making hciuart retry a failed attach"

    mkdir -p /etc/systemd/system/hciuart.service.d
    cat > /etc/systemd/system/hciuart.service.d/retry.conf <<'EOF'
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Restart=on-failure
RestartSec=5

# bluetooth.service is skipped at boot when /sys/class/bluetooth does not exist
# yet, and systemd never revisits a skipped condition, so a late attach would
# leave the controller there with no bluetoothd to drive it. Starting it from
# here is what closes that gap. --no-block because a unit may not wait on
# another unit from inside its own start.
ExecStartPost=-/bin/systemctl --no-block start bluetooth
EOF

    systemctl daemon-reload

    if ! systemctl is-active --quiet hciuart; then
        echo "hciuart is not running, starting it"
        systemctl restart hciuart || true
    fi
fi

# bluetoothd accepts connections before the controller is registered with it,
# and until it is, every command answers "No default controller available".
# A restart of the Bluetooth service is enough to open that window.
echo "Waiting for the controller"

CONTROLLER=""

for _ in $(seq 1 30); do
    if bluetoothctl list 2>/dev/null | grep -q "^Controller "; then
        CONTROLLER="yes"
        break
    fi
    sleep 1
done

if [ -z "$CONTROLLER" ]; then
    echo "No Bluetooth controller appeared within 30s."
    echo "Check that the radio is there and not blocked:"
    echo "  rfkill list bluetooth"
    echo "  dmesg | grep -i -E 'bluetooth|hci'"
    echo "  systemctl status hciuart"
    echo "  systemctl status bluetooth"
    echo
    # The receiver needs the good UART, so Bluetooth is pushed onto the mini
    # UART by the miniuart-bt overlay. The mini UART takes its baud rate from
    # the VPU core clock, and when that clock scales the radio cannot be
    # talked to, which btuart reports as a timed out initialisation. Pinning
    # the minimum core clock is what keeps it reachable.
    echo "On a Raspberry Pi, \"btuart: Initialization timed out\" with"
    echo "dtoverlay=miniuart-bt in config.txt means the mini UART baud rate is"
    echo "drifting. Add core_freq_min=500 (Pi 4 and CM4) or core_freq=250"
    echo "(Pi 3) to config.txt and reboot."
    exit 1
fi

echo "Naming the adapter and making it discoverable"

# One command per bluetoothctl run, never piped into one session. A piped
# session reaches the end of its input and exits before the last commands have
# been answered, which is how the adapter ends up visible for three minutes and
# then gone: discoverable-timeout never took.
#
# The alias is what the phone shows in its list of devices. No agent commands
# here, bt-agent above owns the agent for as long as the Pi is up.
#
# Each one is retried, since the controller can be registered and still refuse
# the first command or two, and none of them is allowed to end the script: a
# rejected setting must not stop the rest being applied.
adapter_command() {
    for _ in 1 2 3; do
        if bluetoothctl "$@"; then
            return 0
        fi
        sleep 2
    done

    echo "  giving up on: bluetoothctl $*"
    return 0
}

adapter_command power on
adapter_command system-alias "$NAME"
adapter_command pairable on
adapter_command discoverable-timeout 0
adapter_command discoverable on

echo "Adapter state:"
bluetoothctl show | grep -E "Alias|Powered|Discoverable|Pairable"

# Anything other than 0 here means the Pi vanishes from the phone on its own
if ! bluetoothctl show | grep -qE "DiscoverableTimeout: (0x00000000|0)$"; then
    echo "Discoverability still expires, check DiscoverableTimeout in $MAIN_CONF"
fi

# --- Serial Port Profile record ----------------------------------------------

# The record lives in the running bluetoothd and nowhere else, so publishing it
# here would only last until the next reboot or Bluetooth restart. A service
# tied to bluetooth.service publishes it again every time, which is what keeps
# the Pi connectable after a reboot without anybody logging in.
echo "Installing the Serial Port Profile record service"

UNIT_SOURCE="$(dirname "$0")/sdp-spp.service"
UNIT_TARGET="/etc/systemd/system/sdp-spp.service"

sed "s|__CHANNEL__|$CHANNEL|g" "$UNIT_SOURCE" > "$UNIT_TARGET"

systemctl daemon-reload

# Enabling it is what makes it run again on every Bluetooth start, and --now
# publishes the record straight away without waiting for a reboot
if ! systemctl enable --now sdp-spp; then
    echo "The Serial Port record service failed, check compatibility mode"
fi

if ! sdptool browse local | grep -A2 "Serial Port"; then
    echo "No serial port record found, check that compatibility mode is on"
fi

echo
echo "If a phone was paired before, remove the old bond on both sides first."
echo "On the Pi:"
# Older bluetoothctl takes no filter after devices and answers "Too many
# arguments", paired-devices works on every version
bluetoothctl paired-devices | sed 's/^/  /' || true
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
echo "Restart the service to pick this up:"
echo "  sudo systemctl restart k155-gnss"
