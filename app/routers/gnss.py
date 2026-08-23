# The /gnss endpoints
from fastapi import APIRouter, Body, responses

from app.core import config, inspect as gnss_inspect, serial_link, ublox

router = APIRouter()


@router.get("/status")
def get_gnss_status_route():
    state = serial_link.get_state()

    return responses.JSONResponse(
        status_code=200 if state["connected"] else 503,
        content=state,
    )


@router.post("/reconnect")
def reconnect_route():
    """Closes and reopens the receiver port."""
    serial_link.close_port()

    if not serial_link.open_port():
        return responses.JSONResponse(
            status_code=503,
            content={"status": "receiver not available"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "reconnected"},
    )


@router.post("/write")
def write_route(payload: str = Body(..., embed=True)):
    """Writes text straight to the receiver. Debug aid for the RTCM path."""
    if not serial_link.write(payload.encode("ascii")):
        return responses.JSONResponse(
            status_code=503,
            content={"status": "receiver not available"},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "written", "bytes": len(payload)},
    )


@router.get("/messages")
def get_messages_route():
    """Shows the configured message rates and the names that can be used."""
    entries = ublox.parse_message_rates(config.UBX_MESSAGE_RATES)

    return responses.JSONResponse(
        status_code=200,
        content={
            "configured": [f"{name}:{rate}" for name, rate in entries],
            "raw_setting": config.UBX_MESSAGE_RATES,
            "generation": config.UBX_GENERATION,
            "port": config.UBX_PORT,
            "known_names": sorted(ublox.MESSAGES_GEN8),
        },
    )


@router.post("/messages/apply")
def apply_messages_route():
    """Resends the configured rates to the receiver."""
    result = ublox.apply_message_rates()

    if result["failed"] or result["rejected"]:
        return responses.JSONResponse(
            status_code=503,
            content={"status": "the receiver did not accept every setting", **result},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "applied", **result},
    )


@router.get("/sample")
def sample_route(seconds: float = 2.0):
    """Listens to the receiver for a moment and reports what it is sending."""
    seconds = max(0.1, min(seconds, 10.0))

    result = gnss_inspect.sample(seconds)

    if "error" in result:
        return responses.JSONResponse(status_code=503, content=result)

    return responses.JSONResponse(status_code=200, content=result)


@router.post("/protocols/enable")
def enable_protocols_route():
    """Switches UBX, NMEA and RTCM3 on for both directions of the port."""
    result = ublox.enable_protocols()

    if result["rejected"] or result["failed"]:
        return responses.JSONResponse(
            status_code=503,
            content={"status": "the receiver did not accept every protocol", **result},
        )

    return responses.JSONResponse(
        status_code=200,
        content={"status": "enabled", **result},
    )
