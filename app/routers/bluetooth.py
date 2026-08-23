# The /bluetooth endpoints for the pairing handshake
from fastapi import APIRouter, responses

from app.core import bluetooth, config

router = APIRouter()


@router.get("/status")
def get_bluetooth_status_route():
    state = bluetooth.get_state()

    return responses.JSONResponse(
        status_code=200,
        content={**state, "name": config.BLUETOOTH_NAME, "spp_uuid": bluetooth.SPP_UUID},
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
