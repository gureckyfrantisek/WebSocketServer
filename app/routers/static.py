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
def start_static_route(
    point_id: str,
    antenna_height: str = "",
    antenna_offset: str = "",
    code: str = "",
):
    """Records one surveyed point, the point id names the files.

    The antenna figures and the code are optional, the app leaves them out when
    the surveyor left the field empty. They are taken as text because a Czech
    keyboard produces a comma decimal separator.
    """
    response = static_session.start(point_id, antenna_height, antenna_offset, code)

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

    if response == 5:
        return responses.JSONResponse(
            status_code=400,
            content={"status": "unusable antenna height"},
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
