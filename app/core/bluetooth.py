# How the phone finds the Pi.
#
# A network beacon cannot solve this on its own: to announce itself the Pi has
# to already be on the phone hotspot, and it cannot join that without being
# told the credentials. Bluetooth carries them out of band. The phone is paired
# once through Android settings, then hands over the hotspot name and password
# and gets back the address to open the WebSocket on.
#
# The link is a classic RFCOMM serial port, the same profile every Bluetooth
# serial adapter uses, because that is what pairing through system settings
# gives you. Messages are single line JSON, one request and one response per
# line.
import hmac
import json
import socket
import subprocess
import threading

from app.core import config, wifi

# Serial Port Profile, the well known identifier Android asks for
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

# Longest request accepted, a hotspot password cannot be anywhere near this
MAX_LINE_BYTES = 4096

_thread: threading.Thread = None
_stop_event: threading.Event = None
_server = None

_state = {
    "enabled": False,
    "listening": False,
    "available": False,
    "address": None,
    "name": None,
    "powered": False,
    "discoverable": False,
    "serial_profile": False,
    "channel": None,
    "peer": None,
    "requests": 0,
    "last_command": None,
    "last_error": None,
}


def get_state() -> dict:
    return dict(_state)


def _bluetoothctl(commands: list):
    """Runs a short bluetoothctl session.

    Returns:
        tuple: (success, output)
    """
    try:
        result = subprocess.run(
            ["bluetoothctl"],
            input="\n".join(commands) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False, "bluetoothctl is not installed"
    except subprocess.TimeoutExpired:
        return False, "bluetoothctl timed out"

    return result.returncode == 0, result.stdout


def read_adapter() -> dict:
    """Reads what state the adapter is actually in.

    A socket binds happily on a powered down adapter, so listening on a channel
    proves nothing by itself. These are the values that decide whether a phone
    can see the Pi at all.
    """
    empty = {
        "address": None,
        "name": None,
        "powered": False,
        "discoverable": False,
    }

    success, output = _bluetoothctl(["show"])

    if not success:
        return empty

    state = dict(empty)

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Controller "):
            state["address"] = line.split()[1]
        elif line.startswith("Alias:"):
            state["name"] = line.partition(":")[2].strip()
        elif line.startswith("Name:") and not state["name"]:
            state["name"] = line.partition(":")[2].strip()
        elif line.startswith("Powered:"):
            state["powered"] = line.partition(":")[2].strip() == "yes"
        elif line.startswith("Discoverable:"):
            state["discoverable"] = line.partition(":")[2].strip() == "yes"

    return state


def has_serial_profile() -> bool:
    """Whether a Serial Port record is published.

    Without it the phone has no way to learn which channel to open, however
    healthy the socket on this side looks.
    """
    try:
        result = subprocess.run(
            ["sdptool", "browse", "local"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    return "Serial Port" in result.stdout


def prepare_adapter(name: str) -> dict:
    """Powers the adapter up, names it and keeps it discoverable.

    Discoverability normally expires after three minutes, which is no use to a
    unit sitting in a field, so the timeout is turned off.
    """
    commands = ["power on", "pairable on", "discoverable-timeout 0", "discoverable on"]

    if name:
        commands.insert(1, f"system-alias {name}")

    success, output = _bluetoothctl(commands)

    if not success:
        print(f"Could not prepare the Bluetooth adapter: {output}")

    state = read_adapter()

    if not state["powered"]:
        print("The Bluetooth adapter is powered down, the phone cannot see the Pi")
    elif not state["discoverable"]:
        print("The Bluetooth adapter is not discoverable, pairing will not work")

    return state


def is_supported() -> bool:
    """True when this machine can open Bluetooth sockets at all."""
    return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_RFCOMM")


# --- Protocol ----------------------------------------------------------------

def handle_request(line: str) -> dict:
    """Turns one request line into the response to send back.

    Kept free of sockets so the protocol can be exercised without Bluetooth
    hardware.

    Parameters:
        line (string): One line of JSON as received from the phone

    Returns:
        dict: The response to serialise back
    """
    line = line.strip()

    if not line:
        return {"status": "error", "message": "empty request"}

    try:
        request = json.loads(line)
    except ValueError:
        return {"status": "error", "message": "request is not valid JSON"}

    if not isinstance(request, dict):
        return {"status": "error", "message": "request must be an object"}

    command = request.get("command")
    _state["last_command"] = command

    if command == "hello":
        # Answered without a token so the phone can tell what it is talking to
        # and whether a token will be needed
        return {
            "status": "ok",
            "device": config.BLUETOOTH_NAME,
            "server_port": config.SERVER_PORT,
            "token_required": bool(config.BLUETOOTH_TOKEN),
        }

    if not _token_accepted(request):
        _state["last_error"] = "rejected a request with a wrong token"
        print("Bluetooth request rejected, wrong token")
        return {"status": "error", "message": "invalid token"}

    if command == "status":
        return _address_response(wifi.refresh_state())

    if command == "connect_wifi":
        ssid = request.get("ssid")
        password = request.get("password", "")

        if not ssid:
            return {"status": "error", "message": "ssid is required"}

        print(f"Bluetooth asked to join {ssid}")
        result = wifi.join(ssid, password)

        if "error" in result:
            return {"status": "error", "message": result["error"]}

        return _address_response(result)

    return {"status": "error", "message": f"unknown command: {command}"}


def _token_accepted(request: dict) -> bool:
    """Checks the shared secret, when one is configured.

    Compared in constant time so a wrong token cannot be found one character at
    a time by watching how long the answer takes.
    """
    expected = config.BLUETOOTH_TOKEN

    if not expected:
        return True

    return hmac.compare_digest(str(request.get("token", "")), expected)


def _address_response(state: dict) -> dict:
    """Answer carrying the address the phone should connect back to."""
    ip = state.get("ip")

    if not ip:
        return {
            "status": "error",
            "message": "the Pi is not on a network yet",
            "wifi": state,
        }

    return {
        "status": "ok",
        "ip": ip,
        "ssid": state.get("ssid"),
        "server_port": config.SERVER_PORT,
        "ws_url": f"ws://{ip}:{config.SERVER_PORT}/",
        "api_url": f"http://{ip}:{config.SERVER_PORT}",
    }


# --- Server ------------------------------------------------------------------

def start():
    """Starts listening for the phone on the RFCOMM channel."""
    global _thread, _stop_event, _server

    _state["enabled"] = True

    if not is_supported():
        _state["last_error"] = "this machine has no Bluetooth socket support"
        print("Bluetooth handshake skipped, no Bluetooth socket support here")
        return

    try:
        _server = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server.bind((socket.BDADDR_ANY, config.BLUETOOTH_CHANNEL))
        _server.listen(1)
        _server.settimeout(1.0)
    except Exception as e:
        _state["last_error"] = str(e)
        _state["available"] = False
        print(f"Could not open the Bluetooth channel: {e}")
        _server = None
        return

    adapter = prepare_adapter(config.BLUETOOTH_NAME)

    _state.update({
        "available": True,
        "listening": True,
        "channel": config.BLUETOOTH_CHANNEL,
        "last_error": None,
        "serial_profile": has_serial_profile(),
        **adapter,
    })

    if not _state["serial_profile"]:
        print("No Serial Port record is published, run deploy/bluetooth_setup.sh")

    print(f"Bluetooth adapter {_state['address']} is visible as {_state['name']}, "
          f"powered {_state['powered']}, discoverable {_state['discoverable']}")

    print(f"Bluetooth handshake listening on RFCOMM channel {config.BLUETOOTH_CHANNEL}")

    _stop_event = threading.Event()
    _thread = threading.Thread(target=_accept_loop, daemon=True)
    _thread.start()


def stop():
    """Stops listening."""
    global _thread, _stop_event, _server

    if _stop_event:
        _stop_event.set()

    if _server:
        try:
            _server.close()
        except Exception:
            pass
        _server = None

    if _thread:
        _thread.join(timeout=3.0)
        _thread = None

    _state.update({"enabled": False, "listening": False, "peer": None})


def _accept_loop():
    while not _stop_event.is_set():
        try:
            connection, address = _server.accept()
        except socket.timeout:
            continue
        except OSError:
            # The socket was closed while shutting down
            return

        peer = address[0] if isinstance(address, tuple) else str(address)
        _state["peer"] = peer
        print(f"Bluetooth client connected: {peer}")

        try:
            _serve_client(connection)
        except Exception as e:
            _state["last_error"] = str(e)
            print(f"Bluetooth connection failed: {e}")
        finally:
            try:
                connection.close()
            except Exception:
                pass
            _state["peer"] = None
            print(f"Bluetooth client disconnected: {peer}")


def _serve_client(connection):
    """Reads request lines from one phone and answers each of them."""
    connection.settimeout(None)
    buffer = bytearray()

    while not _stop_event.is_set():
        chunk = connection.recv(1024)

        if not chunk:
            return

        buffer.extend(chunk)

        # A request that never ends is a broken client, not a huge password
        if len(buffer) > MAX_LINE_BYTES:
            buffer.clear()
            _send(connection, {"status": "error", "message": "request too long"})
            continue

        while b"\n" in buffer:
            line, _, rest = bytes(buffer).partition(b"\n")
            buffer = bytearray(rest)

            # Blank lines are keep-alives or the tail of a discarded request,
            # answering them would put the client one response out of step
            if not line.strip():
                continue

            _state["requests"] += 1
            response = handle_request(line.decode("utf-8", errors="replace"))
            _send(connection, response)


def _send(connection, response: dict):
    connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
