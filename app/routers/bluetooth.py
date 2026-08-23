# The /bluetooth endpoints for the pairing handshake
from fastapi import APIRouter, responses

from app.core import bluetooth, config

router = APIRouter()


@router.get("/status")
def get_bluetooth_status_route():
    """What the adapter is doing, and which phones it knows about."""
    state = bluetooth.get_state()

    # Read live rather than from the cached startup values, the adapter can be
    # powered down or unblocked long after the server started
    state.update(bluetooth.read_adapter())
    state["serial_profile"] = bluetooth.has_serial_profile()
    state["devices"] = bluetooth.list_devices()

    return responses.JSONResponse(
        status_code=200,
        content={**state, "spp_uuid": bluetooth.SPP_UUID},
    )


@router.post("/start")
def start_bluetooth_route():
    bluetooth.start()

    state = bluetooth.get_state()

    if not state["listening"]:
        return responses.JSONResponse(
            status_code=503,
            content={"status": "could not start", **state},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "listening", **state},
    )


@router.post("/stop")
def stop_bluetooth_route():
    bluetooth.stop()

    return responses.JSONResponse(
        status_code=200,
        content={"status": "stopped"},
    )
