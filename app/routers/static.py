# The /static endpoints for measurement recording
from fastapi import APIRouter, responses

from app.core import static_session

router = APIRouter()


@router.get("/status")
def get_static_status_route():
    return responses.JSONResponse(
        status_code=200,
        content=static_session.get_state(),
    )


@router.post("/start")
def start_static_route(point_id: str):
    """Records one surveyed point, the point id names the files."""
    response = static_session.start(point_id)

    if response is True:
        return responses.JSONResponse(
            status_code=200,
            content={"status": "recording", **static_session.get_state()},
        )

    if response == 1:
        return responses.JSONResponse(
            status_code=409,
            content={"status": "already recording"},
        )

    if response == 2:
        return responses.JSONResponse(
            status_code=503,
            content={"status": "receiver not connected"},
        )

    if response == 4:
        return responses.JSONResponse(
            status_code=400,
            content={"status": "unusable point id"},
        )

    return responses.JSONResponse(
        status_code=500,
        content={"status": "could not open the measurement file"},
    )


@router.post("/stop")
def stop_static_route():
    response = static_session.stop()

    if not response:
        return responses.JSONResponse(
            status_code=409,
            content={"status": "not recording"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "stopped", **response},
    )
