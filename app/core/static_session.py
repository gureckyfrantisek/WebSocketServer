# Static measurement recording.
#
# Subscribes to the raw receiver stream and writes every byte to disk, UBX
# frames included, so the recording can be post-processed later. Runs whether
# or not a phone is connected, the WebSocket keeps streaming meanwhile.
import json
import os
import threading

from app.core import serial_link, storage

# Seconds between flushes, a power cut loses at most this much
FLUSH_INTERVAL_S = 5.0


_session = None
_lock = threading.Lock()


def is_recording() -> bool:
    return _session is not None


def get_state() -> dict:
    """Diagnostics for the status endpoints."""
    session = _session

    if not session:
        return {"recording": False}

    return {
        "recording": True,
        "point_id": session["point_id"],
        "location": session["location"],
        "start_ns": session["start_ns"],
        "bytes_written": session["bytes_written"],
        "raw_file": session["raw_name"],
        "last_error": session["last_error"],
    }


def start(point_id: str):
    """Begins writing the raw receiver stream to disk.

    Parameters:
        point_id (string): Names the files, one pair per surveyed point

    Returns:
        True on success, 1 already recording, 2 receiver not connected,
        3 file could not be opened, 4 unusable point id
    """
    global _session

    safe_point = storage.safe_name(point_id)

    if not safe_point:
        return 4

    with _lock:
        if _session is not None:
            return 1

        if not serial_link.verify_connection():
            return 2

        # A flash drive wins when one is plugged in, so the data leaves with it
        folder, location = storage.get_write_path()

        # Measuring the same point again keeps both recordings
        file_name = storage.unique_name(safe_point, folder)
        raw_path = os.path.join(folder, file_name + storage.RAW_SUFFIX)
        meta_path = os.path.join(folder, file_name + storage.META_SUFFIX)

        try:
            handle = open(raw_path, "wb")
        except Exception as e:
            print(f"Could not open the measurement file: {e}")
            return 3

        _session = {
            "point_id": point_id,
            "file_name": file_name,
            "location": location,
            "folder": folder,
            "raw_path": raw_path,
            "raw_name": file_name + storage.RAW_SUFFIX,
            "meta_path": meta_path,
            "handle": handle,
            "start_ns": serial_link.now_ns(),
            "bytes_written": 0,
            "last_flush_ns": serial_link.now_ns(),
            "last_error": None,
        }

    _write_metadata(_session, finished=False)
    serial_link.subscribe(_on_serial_data)

    print(f"Static measurement started: {_session['raw_name']} on {location} storage")
    return True


def stop():
    """Ends the measurement and finishes the metadata file.

    Returns:
        dict: Summary of the recording

        False: nothing was recording
    """
    global _session

    with _lock:
        if _session is None:
            return False
        session = _session
        _session = None

    serial_link.unsubscribe(_on_serial_data)

    try:
        session["handle"].flush()
        session["handle"].close()
    except Exception as e:
        print(f"Could not close the measurement file: {e}")
        session["last_error"] = str(e)

    session["end_ns"] = serial_link.now_ns()
    _write_metadata(session, finished=True)

    print(f"Static measurement stopped: {session['raw_name']}, {session['bytes_written']} bytes")

    return {
        "point_id": session["point_id"],
        "file_name": session["file_name"],
        "location": session["location"],
        "start_ns": session["start_ns"],
        "end_ns": session["end_ns"],
        "duration_s": (session["end_ns"] - session["start_ns"]) / 1e9,
        "bytes_written": session["bytes_written"],
        "raw_file": session["raw_name"],
    }


def _on_serial_data(chunk: bytes):
    """Runs on the serial reader thread for every chunk read."""
    session = _session
    if not session:
        return

    try:
        session["handle"].write(chunk)
        session["bytes_written"] += len(chunk)
    except Exception as e:
        session["last_error"] = str(e)
        print(f"Measurement write failed: {e}")
        return

    now = serial_link.now_ns()
    if now - session["last_flush_ns"] >= FLUSH_INTERVAL_S * 1e9:
        session["last_flush_ns"] = now
        try:
            session["handle"].flush()
            os.fsync(session["handle"].fileno())
        except Exception as e:
            session["last_error"] = str(e)


def _write_metadata(session, finished: bool):
    """Writes meta.json so an interrupted measurement is still identifiable."""
    serial_state = serial_link.get_state()

    metadata = {
        "point_id": session["point_id"],
        "file_name": session["file_name"],
        "location": session["location"],
        "start_ns": session["start_ns"],
        "end_ns": session.get("end_ns"),
        "finished": finished,
        "bytes_written": session["bytes_written"],
        "raw_file": session["raw_name"],
        "serial_path": serial_state["path"],
        "serial_baudrate": serial_state["baudrate"],
        "simulated": serial_state["simulated"],
    }

    if finished and session.get("end_ns"):
        metadata["duration_s"] = (session["end_ns"] - session["start_ns"]) / 1e9

    meta_path = session["meta_path"]

    try:
        with open(meta_path, "w") as file:
            json.dump(metadata, file, indent=2)
    except Exception as e:
        print(f"Could not write the metadata file: {e}")
