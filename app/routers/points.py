# The /points endpoints for recorded measurements
from fastapi import APIRouter, responses

from app.core import storage

router = APIRouter()


@router.get("")
def get_points_route():
    return responses.JSONResponse(
        status_code=200,
        content={"points": storage.get_points()},
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
        content=response,
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
    """Moves a locally stored recording onto the flash drive."""
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
                content={"status": "invalid point"},
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

        case 5:
            return responses.JSONResponse(
                status_code=200,
                content={"status": "already on the flash drive"},
            )

        case 6:
            return responses.JSONResponse(
                status_code=503,
                content={"status": "no flash drive mounted"},
            )
