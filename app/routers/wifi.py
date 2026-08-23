# The /wifi endpoints
from fastapi import APIRouter, responses

from app.core import config, wifi

router = APIRouter()


@router.get("/status")
def get_wifi_status_route():
    state = wifi.refresh_state()

    return responses.JSONResponse(
        status_code=200 if state["connected"] else 503,
        content={**state, "interface": config.WIFI_INTERFACE},
    )


@router.post("/connect")
def connect_route(ssid: str):
    """Brings up a network NetworkManager already knows.

    New networks arrive through the Bluetooth handshake, this is for bringing
    back one the Pi has joined before.
    """
    target = ssid

    if not wifi.connect(target):
        return responses.JSONResponse(
            status_code=503,
            content={"status": "could not connect", "ssid": target,
                     "last_error": wifi.get_state()["last_error"]},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "connected", **wifi.get_state()},
    )
