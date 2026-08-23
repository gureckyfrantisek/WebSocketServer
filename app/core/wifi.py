# Joining the phone hotspot on the Raspberry Pi.
#
# NetworkManager does the actual work. The server only makes sure a connection
# profile exists and nudges it when the link drops, so the Pi still reconnects
# on its own even while this server is not running.
import shlex
import subprocess
import threading

from app.core import config

# How long a single nmcli call may take before it is given up on
COMMAND_TIMEOUT_S = 30

_thread: threading.Thread = None
_stop_event: threading.Event = None

_state = {
    "managed": False,
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


def apply_profiles() -> dict:
    """Writes the configured networks into NetworkManager.

    The hotspot gets the higher priority, the fallback network keeps the Pi
    reachable over SSH when the hotspot is not around.
    """
    result = {"configured": [], "failed": []}

    networks = [
        (config.WIFI_SSID, config.WIFI_PASSWORD, config.WIFI_PRIORITY),
        (config.WIFI_FALLBACK_SSID, config.WIFI_FALLBACK_PASSWORD, config.WIFI_FALLBACK_PRIORITY),
    ]

    for ssid, password, priority in networks:
        if not ssid:
            continue

        if ensure_profile(ssid, password, priority):
            result["configured"].append(f"{ssid} (priority {priority})")
        else:
            result["failed"].append(ssid)

    return result


# --- Watchdog ----------------------------------------------------------------

def start_watchdog():
    """Watches the link and nudges NetworkManager when it stays down."""
    global _thread, _stop_event

    _state["managed"] = True

    if not is_available():
        _state["last_error"] = "nmcli is not installed"
        print("WiFi management skipped, nmcli is not installed")
        return

    apply_profiles()

    _stop_event = threading.Event()

    def _watch():
        while not _stop_event.is_set():
            refresh_state()

            if not _state["connected"] and config.WIFI_SSID:
                print("WiFi is down, trying the configured networks")
                if not connect(config.WIFI_SSID) and config.WIFI_FALLBACK_SSID:
                    connect(config.WIFI_FALLBACK_SSID)

            _stop_event.wait(config.WIFI_WATCHDOG_S)

    _thread = threading.Thread(target=_watch, daemon=True)
    _thread.start()


def stop_watchdog():
    global _thread, _stop_event

    if _stop_event:
        _stop_event.set()
    if _thread:
        _thread.join(timeout=2.0)
        _thread = None

    _state["managed"] = False
