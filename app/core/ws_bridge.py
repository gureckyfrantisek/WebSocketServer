# WebSocket bridge between the GNSS receiver and the phone app.
#
# NMEA sentences go up to the app, RTCM corrections come back down to the
# receiver. Only one client at a time, the same as the original Node server.
import threading

from app.core import config, nmea, serial_link

# Sentences buffered for the client before the oldest ones get dropped
QUEUE_LIMIT = 1000

# The single connected client, None while nobody is connected
_session = None
_lock = threading.Lock()


def is_connected() -> bool:
    return _session is not None


def get_state() -> dict:
    """Diagnostics for the status endpoints."""
    session = _session

    if not session:
        return {"connected": False}

    return {
        "connected": True,
        "framing": config.WS_FRAMING,
        "peer": session["peer"],
        "connected_since_ns": session["connected_ns"],
        "sentences_sent": session["sentences_sent"],
        "sentences_dropped": session["sentences_dropped"],
        "bytes_received": session["bytes_received"],
    }


def acquire(peer: str, loop, queue) -> bool:
    """Claims the single client slot and starts feeding the queue.

    Parameters:
        peer (str): Client address, only for logging
        loop (AbstractEventLoop): Loop the queue belongs to
        queue (asyncio.Queue): Receives complete NMEA sentences

    Returns:
        bool: False if another client already holds the slot
    """
    global _session

    with _lock:
        if _session is not None:
            return False

        _session = {
            "peer": peer,
            "loop": loop,
            "queue": queue,
            "extractor": nmea.Extractor() if config.WS_FRAMING == "lines" else None,
            "connected_ns": serial_link.now_ns(),
            "sentences_sent": 0,
            "sentences_dropped": 0,
            "bytes_received": 0,
        }

    serial_link.subscribe(_on_serial_data)
    return True


def release():
    """Frees the client slot."""
    global _session

    with _lock:
        if _session is None:
            return
        _session = None

    serial_link.unsubscribe(_on_serial_data)


def send_to_receiver(data: bytes) -> bool:
    """Forwards RTCM corrections from the app down to the receiver."""
    session = _session
    if session:
        session["bytes_received"] += len(data)

    return serial_link.write(data)


def _on_serial_data(chunk: bytes):
    """Runs on the serial reader thread, never on the event loop."""
    session = _session
    if not session:
        return

    extractor = session["extractor"]

    if extractor is None:
        # Pass the chunk straight through, the way the Node server did.
        # Undecodable bytes become the replacement character rather than
        # dropping the whole chunk, so binary UBX cannot break the stream.
        sentences = [chunk.decode("utf-8", errors="replace")]
    else:
        sentences = extractor.feed(chunk)

    if not sentences:
        return

    loop = session["loop"]
    queue = session["queue"]

    for sentence in sentences:
        try:
            loop.call_soon_threadsafe(_offer, session, queue, sentence)
        except RuntimeError:
            # Loop already closed, the connection is on its way out
            return


def _offer(session, queue, sentence: str):
    """Puts a sentence on the queue, dropping the oldest one when full."""
    if queue.qsize() >= QUEUE_LIMIT:
        try:
            queue.get_nowait()
            session["sentences_dropped"] += 1
        except Exception:
            pass

    queue.put_nowait(sentence)


def note_sent(count: int = 1):
    """Counts sentences handed to the client, called by the router."""
    session = _session
    if session:
        session["sentences_sent"] += count
