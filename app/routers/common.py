# The / endpoints for common actions
from fastapi import APIRouter, responses

from app.core.common import *

router = APIRouter()


@router.get("/status")
def get_status_route():
    status = get_status()

    return responses.JSONResponse(
        status_code=200 if status["status"] == "ready" else 503,
        content=status,
    )
