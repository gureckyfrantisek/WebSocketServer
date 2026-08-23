# Serial connection to the GNSS receiver.
#
# One reader thread owns the port and fans raw bytes out to every subscriber
# (the WebSocket bridge, the static-measurement logger, ...). Nothing else may
# read from the port. Writes (RTCM corrections) go straight through.
import threading
import time
import serial

from app.core import config

# Port handle, None while disconnected
_port = None

# Reader thread and its stop flag
_thread: threading.Thread = None
_stop_event: threading.Event = None

# Callbacks receiving every raw chunk read from the receiver
_subscribers: list = []
_lock = threading.Lock()

# Called after the port opens, used to push the message rates to the receiver
on_port_opened = []

# Diagnostics for /status
_bytes_read = 0
_last_data_ns = 0
_last_error = None


def now_ns() -> int:
    return time.time_ns()


# --- Subscriptions -----------------------------------------------------------

def subscribe(callback):
    """Registers a callback(chunk: bytes) called from the reader thread.

    Parameters:
        callback (callable): Receives every raw chunk read from the receiver

    Returns:
        callable: The same callback, pass it to unsubscribe()
    """
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)
    return callback


def unsubscribe(callback):
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


def _fire(hooks):
    for hook in hooks:
        try:
            hook()
        except Exception as e:
            print(f"Port hook failed: {e}")


def _dispatch(chunk: bytes):
    with _lock:
        targets = list(_subscribers)

    for callback in targets:
        try:
            callback(chunk)
        except Exception as e:
            # A broken subscriber must never kill the reader thread
            print(f"Subscriber failed: {e}")


# --- Port lifecycle ----------------------------------------------------------

def verify_connection() -> bool:
    """Returns True while the receiver port is open."""
    return _port is not None and _port.is_open


def open_port() -> bool:
    """Opens the receiver port and starts the reader thread.

    Returns:
        bool: True if the port is open afterwards
    """
    global _port, _thread, _stop_event, _last_error

    if verify_connection():
        return True

    try:
        if config.GNSS_SIMULATE:
            _port = _SimulatedPort()
        else:
            _port = serial.Serial(
                port=config.SERIAL_PATH,
                baudrate=config.SERIAL_BAUDRATE,
                timeout=0.1,
                # Without this a wedged receiver blocks the correction path
                write_timeout=2.0,
            )
        _last_error = None
    except Exception as e:
        _port = None
        _last_error = str(e)
        print(f"Serial port error: {e}")
        return False

    print(f"Serial port open: {config.SERIAL_PATH} @ {config.SERIAL_BAUDRATE}")

    _stop_event = threading.Event()
    _thread = threading.Thread(target=_read_loop, daemon=True)
    _thread.start()

    _fire(on_port_opened)

    return True


def close_port():
    """Stops the reader thread and closes the port."""
    global _port, _thread, _stop_event

    if _stop_event:
        _stop_event.set()

    if _thread:
        _thread.join(timeout=2.0)
        _thread = None

    if _port:
        try:
            _port.close()
            print("Serial port closed")
        except Exception as e:
            print(f"Error closing serial port: {e}")
        _port = None


def write(data: bytes) -> bool:
    """Sends bytes to the receiver, used for RTCM corrections.

    Returns:
        bool: True if the bytes were handed to the port
    """
    global _last_error

    if not verify_connection():
        return False

    try:
        _port.write(data)
        return True
    except Exception as e:
        _last_error = str(e)
        print(f"Serial write error: {e}")
        return False


def get_state() -> dict:
    """Diagnostics for the status endpoints."""
    return {
        "connected": verify_connection(),
        "path": config.SERIAL_PATH,
        "baudrate": config.SERIAL_BAUDRATE,
        "simulated": config.GNSS_SIMULATE,
        "bytes_read": _bytes_read,
        "last_data_ns": _last_data_ns,
        "subscribers": len(_subscribers),
        "last_error": _last_error,
    }


# --- Reader thread -----------------------------------------------------------

def _read_loop():
    global _bytes_read, _last_data_ns, _port, _last_error

    while not _stop_event.is_set():
        try:
            # Blocks up to the port timeout, then returns whatever arrived
            chunk = _port.read(1)
            waiting = getattr(_port, "in_waiting", 0)
            if waiting:
                chunk += _port.read(waiting)
        except Exception as e:
            _last_error = str(e)
            print(f"Serial read error: {e}")
            # Drop the handle so the supervisor reopens it
            try:
                _port.close()
            except Exception:
                pass
            _port = None
            return

        if not chunk:
            continue

        _bytes_read += len(chunk)
        _last_data_ns = now_ns()
        _dispatch(chunk)


# --- Supervisor --------------------------------------------------------------

_supervisor_thread: threading.Thread = None
_supervisor_stop: threading.Event = None


def start_supervisor():
    """Keeps the port open, reopening it after an unplug."""
    global _supervisor_thread, _supervisor_stop

    _supervisor_stop = threading.Event()

    def _supervise():
        while not _supervisor_stop.is_set():
            if not verify_connection():
                open_port()
            _supervisor_stop.wait(config.SERIAL_RETRY_S)

    _supervisor_thread = threading.Thread(target=_supervise, daemon=True)
    _supervisor_thread.start()


def stop_supervisor():
    global _supervisor_thread, _supervisor_stop

    if _supervisor_stop:
        _supervisor_stop.set()
    if _supervisor_thread:
        _supervisor_thread.join(timeout=2.0)
        _supervisor_thread = None


# --- Simulation --------------------------------------------------------------

class _SimulatedPort:
    """Stand-in for serial.Serial emitting valid NMEA once per second.

    Lets every stage be tested on a machine with no receiver attached.
    """

    def __init__(self):
        self.is_open = True
        self.in_waiting = 0
        self._counter = 0

    def read(self, size=1) -> bytes:
        if not self.is_open:
            return b""

        time.sleep(1.0)
        self._counter += 1

        # Walk the position slightly so the app sees movement
        latitude = 4913.1234 + self._counter * 0.0001
        longitude = 1826.5678 + self._counter * 0.0001
        clock = time.strftime("%H%M%S", time.gmtime())

        sentences = [
            f"GNGGA,{clock}.00,{latitude:.4f},N,{longitude:.4f},E,1,08,1.2,320.5,M,45.0,M,,",
            f"GNRMC,{clock}.00,A,{latitude:.4f},N,{longitude:.4f},E,0.05,180.0,010126,,,A",
        ]

        return b"".join(_nmea(sentence) for sentence in sentences)

    def write(self, data: bytes):
        print(f"Simulated receiver got {len(data)} bytes")

    def close(self):
        self.is_open = False


def _nmea(body: str) -> bytes:
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}\r\n".encode("ascii")
