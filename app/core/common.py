# Shared state and status reporting across the modules
import time

from app.core import config, discovery, serial_link, static_session, storage, wifi, ws_bridge


def now_ns() -> int:
    return time.time_ns()


def get_status() -> dict:
    """Collects the state of every subsystem.

    Returns:
        dict: Per-subsystem state plus an overall ready flag
    """
    gnss = serial_link.get_state()

    subsystems = {
        "gnss": gnss,
        "client": ws_bridge.get_state(),
        "discovery": discovery.get_state(),
        "static": static_session.get_state(),
        "storage": storage.get_state(),
        "wifi": wifi.get_state(),
    }

    ready = gnss["connected"]

    return {
        "status": "ready" if ready else "not ready",
        "server_port": config.SERVER_PORT,
        "subsystems": subsystems,
    }
