# The /discovery endpoints for the UDP beacon
from fastapi import APIRouter, responses

from app.core import discovery

router = APIRouter()


@router.get("/status")
def get_discovery_status_route():
    return responses.JSONResponse(
        status_code=200,
        content=discovery.get_state(),
    )


@router.post("/start")
def start_discovery_route():
    """Forces the beacon on, normally it starts by itself."""
    discovery.start()

    if not discovery.is_running():
        return responses.JSONResponse(
            status_code=503,
            content={"status": "no usable network interface"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "broadcasting", "local_ip": discovery.get_state()["local_ip"]},
    )


@router.post("/stop")
def stop_discovery_route():
    discovery.stop()

    return responses.JSONResponse(
        status_code=200,
        content={"status": "stopped"},
    )
