# The /points endpoints for recorded measurements
from fastapi import APIRouter, responses

from app.core import storage

router = APIRouter()


@router.get("")
def get_points_route():
    points = storage.get_points()

    if points is False:
        return responses.JSONResponse(
            status_code=500,
            content={"status": "local storage unreadable"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"points": points},
    )


@router.get("/{point_name}")
def get_point_files_route(point_name: str):
    response = storage.get_point_files(point_name)

    if response == 2:
        return responses.JSONResponse(
            status_code=404,
            content={"status": "invalid point"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"point_files": response},
    )


@router.delete("/{point_name}")
def delete_point_route(point_name: str):
    response = storage.delete_point(point_name)

    match response:
        case True:
            return responses.JSONResponse(
                status_code=200,
                content={"status": "deleted"},
            )

        case 2:
            return responses.JSONResponse(
                status_code=404,
                content={"status": "invalid point"},
            )

        case 3:
            return responses.JSONResponse(
                status_code=500,
                content={"status": "delete failed"},
            )


@router.post("/{point_name}/download")
def download_point_route(point_name: str, cleanup: bool = False):
    """Copies the recording onto the USB flash drive."""
    response = storage.download_point(point_name, cleanup)

    match response:
        case True:
            return responses.JSONResponse(
                status_code=200,
                content={"status": "downloaded"},
            )

        case 2:
            return responses.JSONResponse(
                status_code=404,
                content={"status": "invalid point or USB unavailable"},
            )

        case 3:
            return responses.JSONResponse(
                status_code=500,
                content={"status": "copy failed"},
            )

        case 4:
            return responses.JSONResponse(
                status_code=500,
                content={"status": "cleanup failed"},
            )
