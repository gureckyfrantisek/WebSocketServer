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
import os
import socket
import subprocess
import threading
import time

from app.core import config, wifi

# Serial Port Profile, the well known identifier Android asks for
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

# Longest request accepted, a hotspot password cannot be anywhere near this
MAX_LINE_BYTES = 4096

_thread: threading.Thread = None
_start_thread: threading.Thread = None
_stop_event: threading.Event = None
_server = None

# Held while a phone is being served, so a second one is turned away at once
# instead of sitting in the backlog looking like a hung connection
_busy = threading.Lock()

_state = {
    "enabled": False,
    "listening": False,
    "available": False,
    "address": None,
    "name": None,
    "powered": False,
    "discoverable": False,
    "discoverable_timeout": None,
    "serial_profile": False,
    "channel": None,
    "peer": None,
    "pairable": False,
    "refused": 0,
    "requests": 0,
    "last_command": None,
    "last_error": None,
}


def get_state() -> dict:
    return dict(_state)


def _bluetoothctl(commands: list):
    """Runs bluetoothctl commands, one process per command.

    Piping several commands into one interactive session is unreliable: the
    session reaches the end of its input and exits before the last commands
    have been answered, so a setting looks applied when it never was. Passing
    a single command as arguments makes bluetoothctl run it and wait.

    Returns:
        tuple: (success, output)
    """
    # Without a controller bluetoothd is not running, and bluetoothctl then
    # waits for it forever rather than failing. Nothing below may be reached
    # in that state.
    if not has_controller():
        return False, "no Bluetooth controller"

    collected = []
    failed = []

    # Every command is attempted even after one fails, so a rejected setting
    # cannot stop the adapter being made discoverable
    for command in commands:
        try:
            result = subprocess.run(
                ["bluetoothctl", *command.split()],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return False, "bluetoothctl is not installed"
        except subprocess.TimeoutExpired:
            failed.append(f"{command}: timed out")
            continue

        collected.append(result.stdout)

        if result.returncode != 0:
            failed.append(f"{command}: {result.stderr.strip() or result.stdout.strip()}")

    if failed:
        return False, "; ".join(failed)

    return True, "".join(collected)


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
        "pairable": False,
        "discoverable_timeout": None,
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
        elif line.startswith("Pairable:"):
            state["pairable"] = line.partition(":")[2].strip() == "yes"
        elif line.startswith("DiscoverableTimeout:"):
            value = line.partition(":")[2].strip()

            # Printed as hex on some builds and as plain seconds on others
            try:
                state["discoverable_timeout"] = int(value, 0)
            except ValueError:
                state["discoverable_timeout"] = None

    return state


def list_devices() -> dict:
    """Which phones are paired, and which one is connected right now.

    The RFCOMM peer only shows a phone that has opened the serial link. This
    shows the Bluetooth level, which is what tells you whether pairing worked
    at all.
    """
    result = {"paired": [], "connected": []}

    # Older bluetoothctl takes no filter after devices and answers "Too many
    # arguments", so the paired list comes from its own command and each entry
    # is then asked whether it is connected
    success, output = _bluetoothctl(["paired-devices"])

    if not success:
        success, output = _bluetoothctl(["devices"])

    if not success:
        return result

    for line in output.splitlines():
        line = line.strip()

        # Lines look like: Device AA:BB:CC:DD:EE:FF Pixel 7
        if not line.startswith("Device "):
            continue

        parts = line.split(None, 2)

        if len(parts) < 2:
            continue

        device = {
            "address": parts[1],
            "name": parts[2] if len(parts) > 2 else None,
        }

        result["paired"].append(device)

        connected, info = _bluetoothctl([f"info {device['address']}"])

        if connected and "Connected: yes" in info:
            result["connected"].append(device)

    return result


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


def publish_serial_profile(channel: int) -> bool:
    """Publishes the Serial Port record and reports whether one is there now.

    sdptool keeps the record inside the running bluetoothd and nowhere else, so
    a reboot, or a restart of the Bluetooth service, takes it away again.
    Without the record the phone has no channel to open and Android reports the
    connection as failed, while this side still looks perfectly healthy. So the
    record is published on every start rather than once at install time.
    """
    if has_serial_profile():
        return True

    try:
        result = subprocess.run(
            ["sdptool", "add", f"--channel={channel}", "SP"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        print("sdptool is not installed, the Serial Port record cannot be published")
        return False
    except subprocess.TimeoutExpired:
        print("sdptool timed out publishing the Serial Port record")
        return False

    if result.returncode != 0:
        print(f"Could not publish the Serial Port record: {result.stderr.strip()}")
        return False

    # sdptool exits cleanly even when it registered nothing at all, which is
    # what happens when bluetoothd is not in compatibility mode or the server
    # is not root, so the record is read back rather than taken on trust
    if not has_serial_profile():
        print("The Serial Port record did not appear. Check that bluetoothd runs "
              "with --compat and that the server runs as root")
        return False

    print(f"Published the Serial Port record on channel {channel}")
    return True


def unblock_adapter() -> bool:
    """Clears a soft block, and says whether one had to be cleared.

    A blocked adapter still accepts every command, so nothing looks wrong until
    a phone cannot find the Pi.
    """
    try:
        result = subprocess.run(
            ["rfkill", "list", "bluetooth"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    if "Soft blocked: yes" not in result.stdout:
        return False

    print("Bluetooth is soft blocked, unblocking")

    try:
        subprocess.run(["rfkill", "unblock", "bluetooth"], timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    return True


def has_controller() -> bool:
    """Whether the kernel has a Bluetooth controller at all.

    Read straight from sysfs rather than by asking bluetoothctl, because when
    there is no controller bluetoothd does not run either: its unit carries
    ConditionPathIsDirectory=/sys/class/bluetooth and is skipped. bluetoothctl
    against a bluetoothd that is not there blocks forever instead of failing,
    which is the difference between a server that reports no Bluetooth and a
    server that never finishes starting.
    """
    try:
        return bool(os.listdir("/sys/class/bluetooth"))
    except OSError:
        return False


def wait_for_adapter(timeout: float = 60.0) -> dict:
    """Waits for the controller to be enumerated before anything is set on it.

    bluetooth.service counts as started before the controller is up, and at
    boot the server follows it immediately. Commands sent in that gap are
    accepted and lost, which leaves the Pi listening but invisible until
    somebody restarts the service by hand.

    On a Raspberry Pi the radio is attached over a UART by hciuart, which can
    take ten seconds and can fail outright, so the wait is on sysfs and costs
    nothing while there is nothing to talk to.
    """
    deadline = time.monotonic() + timeout

    while not has_controller() and time.monotonic() < deadline:
        time.sleep(1.0)

    if not has_controller():
        print(f"No Bluetooth controller appeared within {timeout:.0f}s. "
              f"On a Raspberry Pi check: systemctl status hciuart")
        return {
            "address": None,
            "name": None,
            "powered": False,
            "discoverable": False,
            "pairable": False,
            "discoverable_timeout": None,
        }

    return read_adapter()


def prepare_adapter(name: str, attempts: int = 3) -> dict:
    """Powers the adapter up, names it and keeps it discoverable.

    Discoverability normally expires after three minutes, which is no use to a
    unit sitting in a field, so the timeout is turned off. Neither discoverable
    nor pairable comes back reliably after a reboot, so both are set on every
    start, read back, and set again when they did not take: early after boot
    the adapter will accept a command and quietly ignore it.
    """
    pairable = "on" if config.BLUETOOTH_PAIRABLE else "off"

    commands = [
        "power on",
        f"pairable {pairable}",
        "discoverable-timeout 0",
        f"discoverable {pairable}",
    ]

    if name:
        commands.insert(1, f"system-alias {name}")

    if unblock_adapter():
        time.sleep(1.0)

    state = wait_for_adapter()

    # Nothing to configure and nothing that would answer, so the retries would
    # only be a slow way of reaching the same conclusion
    if not has_controller():
        return state

    for attempt in range(1, attempts + 1):
        success, output = _bluetoothctl(commands)

        if not success:
            print(f"Could not prepare the Bluetooth adapter: {output}")

        state = read_adapter()

        # A timeout that is still the default three minutes is the reason a Pi
        # is visible right after setup and gone by the time anybody looks
        timeout_held = state["discoverable_timeout"] in (0, None)

        if (state["powered"]
                and state["discoverable"] == config.BLUETOOTH_PAIRABLE
                and timeout_held):
            return state

        if attempt < attempts:
            print(f"The adapter did not take the settings, retrying "
                  f"({attempt}/{attempts})")
            time.sleep(2.0)

    if not state["powered"]:
        print("The Bluetooth adapter is powered down, the phone cannot see the Pi")
    elif not state["discoverable"]:
        print("The Bluetooth adapter is not discoverable, pairing will not work")
    elif state["discoverable_timeout"]:
        print(f"Discoverability expires in {state['discoverable_timeout']}s, "
              f"the Pi will disappear from the phone. Set DiscoverableTimeout = 0 "
              f"in /etc/bluetooth/main.conf")

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

def start_background():
    """Starts without holding up the rest of the server.

    Bringing the adapter up waits on hardware: on a Raspberry Pi the radio is
    attached over a UART at boot and that can take ten seconds, or never
    finish. Run inline this would hold the whole application in startup, so a
    receiver that works and a WebSocket that works would both be unreachable
    because of a radio that does not.
    """
    global _start_thread

    _start_thread = threading.Thread(target=start, daemon=True)
    _start_thread.start()


def start():
    """Starts listening for the phone on the RFCOMM channel."""
    global _thread, _stop_event, _server

    _state["enabled"] = True

    if not is_supported():
        _state["last_error"] = "this machine has no Bluetooth socket support"
        print("Bluetooth handshake skipped, no Bluetooth socket support here")
        return

    # Before the socket, because binding on a controller that has not been
    # enumerated yet fails, and at boot the server can get here first
    adapter = prepare_adapter(config.BLUETOOTH_NAME)

    try:
        _server = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server.bind((socket.BDADDR_ANY, config.BLUETOOTH_CHANNEL))
        _server.listen(2)
        _server.settimeout(1.0)
    except Exception as e:
        _state["last_error"] = str(e)
        _state["available"] = False
        print(f"Could not open the Bluetooth channel: {e}")
        _server = None
        return

    # Only once something is listening on the channel the record points at
    _state.update({
        "available": True,
        "listening": True,
        "channel": config.BLUETOOTH_CHANNEL,
        "last_error": None,
        "serial_profile": publish_serial_profile(config.BLUETOOTH_CHANNEL),
        **adapter,
    })

    if not _state["serial_profile"]:
        print("No Serial Port record is published, phones will fail to connect. "
              "Run deploy/bluetooth_setup.sh")

    print(f"Bluetooth adapter {_state['address']} is visible as {_state['name']}, "
          f"powered {_state['powered']}, discoverable {_state['discoverable']}")

    print(f"Bluetooth handshake listening on RFCOMM channel {config.BLUETOOTH_CHANNEL}")

    _stop_event = threading.Event()
    _thread = threading.Thread(target=_accept_loop, daemon=True)
    _thread.start()


def stop():
    """Stops listening."""
    global _thread, _start_thread, _stop_event, _server

    # A start that is still waiting on the adapter is given a moment to finish,
    # so it cannot open a socket after everything else has been closed
    if _start_thread:
        _start_thread.join(timeout=3.0)
        _start_thread = None

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

        # Connections are taken one at a time. A second phone is told so and
        # dropped immediately, rather than waiting in the backlog while the
        # first one is served, which on the phone looks like a dead link.
        if not _busy.acquire(blocking=False):
            _state["refused"] += 1
            print(f"Bluetooth client refused, already serving {_state['peer']}: {peer}")

            try:
                _send(connection, {"status": "error", "message": "another phone is connected"})
            except Exception:
                pass
            finally:
                _close(connection)

            continue

        # Served on its own thread so the loop is free to refuse the next one
        handler = threading.Thread(target=_handle_client, args=(connection, peer), daemon=True)
        handler.start()


def _handle_client(connection, peer: str):
    """Serves one phone, then frees the slot for the next."""
    _state["peer"] = peer
    print(f"Bluetooth client connected: {peer}")

    try:
        _serve_client(connection)
    except Exception as e:
        _state["last_error"] = str(e)
        print(f"Bluetooth connection failed: {e}")
    finally:
        _close(connection)
        _state["peer"] = None
        _busy.release()
        print(f"Bluetooth client disconnected: {peer}")


def _close(connection):
    """Closes a connection without throwing away what was just written.

    Closing outright can discard buffered bytes, so the refusal message would
    never reach the phone that needs to read it.
    """
    try:
        connection.shutdown(socket.SHUT_WR)
    except Exception:
        pass

    try:
        connection.close()
    except Exception:
        pass


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
