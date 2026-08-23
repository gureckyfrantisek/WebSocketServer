# The /storage endpoints, showing where recordings go
from fastapi import APIRouter, responses

from app.core import storage

router = APIRouter()


@router.get("/status")
def get_storage_status_route():
    """Which storage the next recording lands on and how much room is left."""
    return responses.JSONResponse(
        status_code=200,
        content=storage.get_state(),
    )


@router.post("/download-all")
def download_all_route(cleanup: bool = False):
    """Moves every locally stored recording onto the flash drive."""
    if not storage.get_usb_path():
        return responses.JSONResponse(
            status_code=503,
            content={"status": "no flash drive mounted"},
        )

    result = storage.download_all(cleanup)

    if result["failed"]:
        return responses.JSONResponse(
            status_code=500,
            content={"status": "some recordings could not be copied", **result},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "downloaded", **result},
    )
