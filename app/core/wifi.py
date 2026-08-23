# Joining the phone hotspot on the Raspberry Pi.
#
# The credentials arrive over Bluetooth, they are never stored in this project.
# NetworkManager does the actual work and keeps the profile afterwards, so the
# Pi reconnects to a hotspot it has already seen on its own, with no help from
# this server and even while it is not running.
import subprocess
import threading
import time

from app.core import config

# How long a single nmcli call may take before it is given up on
COMMAND_TIMEOUT_S = 30

# Autoconnect priority given to a hotspot handed over by the phone, above the
# default so it wins over any network the Pi happens to also know
HOTSPOT_PRIORITY = 20

_state = {
    "available": False,
    "connected": False,
    "ssid": None,
    "ip": None,
    "last_error": None,
    "attempts": 0,
}


def get_state() -> dict:
    return dict(_state)


def _run(arguments: list):
    """Runs one nmcli call.

    Returns:
        tuple: (success, output), success is False when nmcli is missing too
    """
    try:
        result = subprocess.run(
            ["nmcli"] + arguments,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
        )
    except FileNotFoundError:
        _state["available"] = False
        return False, "nmcli is not installed"
    except subprocess.TimeoutExpired:
        return False, "nmcli timed out"

    _state["available"] = True

    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()

    return True, result.stdout.strip()


def is_available() -> bool:
    """True when NetworkManager can be reached on this machine."""
    success, _ = _run(["--version"])
    return success


def refresh_state():
    """Reads the current state of the wireless interface."""
    success, output = _run([
        "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
        "device", "show", config.WIFI_INTERFACE,
    ])

    if not success:
        _state["connected"] = False
        _state["last_error"] = output
        return _state

    ssid = None
    ip = None
    connected = False

    for line in output.splitlines():
        field, _, value = line.partition(":")

        if field == "GENERAL.STATE":
            connected = "connected" in value and "disconnected" not in value
        elif field == "GENERAL.CONNECTION":
            ssid = value if value and value != "--" else None
        elif field.startswith("IP4.ADDRESS"):
            ip = value.split("/")[0] if value else None

    _state.update({"connected": connected, "ssid": ssid, "ip": ip})

    return _state


def ensure_profile(ssid: str, password: str, priority: int) -> bool:
    """Creates or updates the NetworkManager profile for one network.

    The profile is what makes the Pi reconnect by itself after a reboot or
    after the hotspot comes back, with no help from this server.

    Parameters:
        ssid (string): Network name
        password (string): Network password, empty for an open network
        priority (int): Higher wins when several known networks are in range

    Returns:
        bool: True when the profile is in place
    """
    if not ssid:
        return False

    success, output = _run(["-t", "-f", "NAME", "connection", "show"])

    if not success:
        _state["last_error"] = output
        return False

    exists = ssid in output.splitlines()

    if exists:
        arguments = [
            "connection", "modify", ssid,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority),
        ]
    else:
        arguments = [
            "connection", "add",
            "type", "wifi",
            "con-name", ssid,
            "ifname", config.WIFI_INTERFACE,
            "ssid", ssid,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority),
        ]

    if password:
        arguments += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]

    success, output = _run(arguments)

    if not success:
        # The password must never reach the log
        _state["last_error"] = output.replace(password, "***") if password else output
        print(f"Could not set up the profile for {ssid}: {_state['last_error']}")
        return False

    print(f"Profile for {ssid} is in place, priority {priority}")
    return True


def connect(ssid: str) -> bool:
    """Brings up one profile now instead of waiting for autoconnect."""
    _state["attempts"] += 1

    success, output = _run(["connection", "up", ssid, "ifname", config.WIFI_INTERFACE])

    if not success:
        _state["last_error"] = output
        print(f"Could not connect to {ssid}: {output}")
        return False

    _state["last_error"] = None
    print(f"Connected to {ssid}")
    refresh_state()
    return True


def join(ssid: str, password: str, priority=HOTSPOT_PRIORITY, timeout_s=30.0) -> dict:
    """Joins a network given fresh credentials and waits for an address.

    Used by the Bluetooth handshake, where the phone hands over its hotspot
    details and expects the address to connect back to.

    Parameters:
        ssid (string): Network name
        password (string): Network password, empty keeps a stored one
        priority (int): Autoconnect priority, defaults to the hotspot priority
        timeout_s (float): How long to wait for an address

    Returns:
        dict: State with an "ip" once the link is up, plus "error" on failure
    """
    if not is_available():
        return {"error": "nmcli is not installed"}

    if not ensure_profile(ssid, password, priority):
        return {"error": _state["last_error"] or "could not write the profile"}

    if not connect(ssid):
        return {"error": _state["last_error"] or "could not connect"}

    # An address does not appear the instant the link comes up
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        state = refresh_state()

        if state["connected"] and state["ip"]:
            return dict(state)

        time.sleep(1.0)

    return {"error": "connected but no address was assigned", **dict(_state)}
