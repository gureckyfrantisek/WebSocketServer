# UDP discovery beacon.
#
# The Raspberry Pi joins the phone hotspot as a client, so the app has no way
# of knowing its address. The beacon shouts the server IP into the subnet once
# a second until a client connects, exactly like the original Node server.
import ipaddress
import socket
import threading

import psutil

from app.core import config

_thread: threading.Thread = None
_stop_event: threading.Event = None
_lock = threading.Lock()

# Diagnostics for the status endpoints
_state = {
    "running": False,
    "interface": None,
    "local_ip": None,
    "broadcast_ip": None,
    "sent": 0,
    "last_error": None,
}


def get_state() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


# --- Addresses ---------------------------------------------------------------

def get_interface_address(name: str):
    """Reads the IPv4 address and netmask of one interface.

    Returns:
        tuple: (ip, netmask), or (None, None) when the interface has no IPv4
    """
    interfaces = psutil.net_if_addrs()

    if name not in interfaces:
        return None, None

    for address in interfaces[name]:
        if address.family == socket.AF_INET:
            return address.address, address.netmask

    return None, None


def get_primary_address():
    """Falls back to whichever interface carries the default route.

    Only used for development, on the Raspberry Pi the configured wlan0 exists.

    Returns:
        tuple: (interface_name, ip, netmask)
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet leaves the machine, this only resolves the routing decision
        probe.connect(("8.8.8.8", 80))
        local_ip = probe.getsockname()[0]
    except Exception:
        local_ip = None
    finally:
        probe.close()

    if not local_ip:
        return None, None, None

    for name, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            if address.family == socket.AF_INET and address.address == local_ip:
                return name, address.address, address.netmask

    return None, local_ip, None


def get_broadcast_ip(ip: str, netmask: str) -> str:
    """Broadcast address of the subnet the given address sits in."""
    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
    return str(network.broadcast_address)


def resolve_addresses():
    """Picks the interface to advertise on.

    Returns:
        tuple: (interface_name, local_ip, broadcast_ip), all None on failure
    """
    name = config.WIFI_INTERFACE
    local_ip, netmask = get_interface_address(name)

    if not local_ip:
        print(f"Interface {name} has no IPv4 address, falling back to the default route")
        name, local_ip, netmask = get_primary_address()

    if not local_ip or not netmask:
        return None, None, None

    broadcast_ip = get_broadcast_ip(local_ip, netmask)

    print(f"Beacon interface {name}: {local_ip} mask {netmask} broadcast {broadcast_ip}")

    return name, local_ip, broadcast_ip


# --- Beacon ------------------------------------------------------------------

def start():
    """Starts broadcasting the server IP. Safe to call when already running."""
    global _thread, _stop_event

    with _lock:
        if _thread is not None:
            return

        name, local_ip, broadcast_ip = resolve_addresses()

        if not local_ip:
            _state["last_error"] = "no usable network interface"
            print("Beacon not started, no usable network interface")
            return

        _state.update({
            "interface": name,
            "local_ip": local_ip,
            "broadcast_ip": broadcast_ip,
            "last_error": None,
            "running": True,
        })

        _stop_event = threading.Event()
        _thread = threading.Thread(target=_broadcast_loop, args=(local_ip, broadcast_ip), daemon=True)
        _thread.start()


def stop():
    """Stops broadcasting. Safe to call when already stopped."""
    global _thread, _stop_event

    with _lock:
        if _thread is None:
            return

        _stop_event.set()
        thread = _thread
        _thread = None
        _state["running"] = False

    thread.join(timeout=2.0)
    print("Beacon stopped")


def _broadcast_loop(local_ip: str, broadcast_ip: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    try:
        # Bound to the chosen address so the packet leaves the right interface
        sock.bind((local_ip, 0))
    except Exception as e:
        _state["last_error"] = str(e)
        print(f"Beacon bind failed: {e}")
        sock.close()
        return

    # The app expects the bare IP as text, the same as the Node server sent
    message = local_ip.encode("ascii")
    target = (broadcast_ip, config.DISCOVERY_PORT)

    print(f"Broadcasting {local_ip} to {broadcast_ip}:{config.DISCOVERY_PORT}")

    while not _stop_event.is_set():
        try:
            sock.sendto(message, target)
            _state["sent"] += 1
        except Exception as e:
            _state["last_error"] = str(e)
            print(f"Error broadcasting UDP message: {e}")

        _stop_event.wait(config.DISCOVERY_INTERVAL_S)

    sock.close()
