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


@router.post("/apply")
def apply_profiles_route():
    """Writes the configured networks into NetworkManager."""
    if not wifi.is_available():
        return responses.JSONResponse(
            status_code=503,
            content={"status": "nmcli is not installed"},
        )

    result = wifi.apply_profiles()

    if result["failed"]:
        return responses.JSONResponse(
            status_code=500,
            content={"status": "some profiles could not be written", **result},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "applied", **result},
    )


@router.post("/connect")
def connect_route(ssid: str = ""):
    """Connects now instead of waiting for the watchdog."""
    target = ssid or config.WIFI_SSID

    if not target:
        return responses.JSONResponse(
            status_code=400,
            content={"status": "no network configured"},
        )

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
