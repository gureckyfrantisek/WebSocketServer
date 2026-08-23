# The WebSocket endpoint the phone app connects to.
#
# The app opens ws://<ip>:8080 with no path, so the socket lives on the root.
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import ws_bridge

router = APIRouter()

# Sent to a second client that tries to connect while the slot is taken
CLOSE_BUSY = 1013


@router.websocket("/")
async def websocket_root_route(websocket: WebSocket):
    await _serve(websocket)


@router.websocket("/ws")
async def websocket_alias_route(websocket: WebSocket):
    """Same bridge under a named path, handy for testing."""
    await _serve(websocket)


async def _serve(websocket: WebSocket):
    peer = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    # Claimed before the handshake, so a second client is refused outright with
    # HTTP 403 instead of being accepted and closed a moment later
    if not ws_bridge.acquire(peer, loop, queue):
        print(f"Rejected {peer}, a client is already connected")
        await websocket.close(code=CLOSE_BUSY, reason="server busy")
        return

    try:
        await websocket.accept()
    except Exception:
        ws_bridge.release()
        raise

    print(f"Client connected: {peer}")

    uplink = asyncio.create_task(_uplink(websocket, queue))
    downlink = asyncio.create_task(_downlink(websocket))

    try:
        # Whichever side ends first takes the connection down with it
        await asyncio.wait({uplink, downlink}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (uplink, downlink):
            task.cancel()
        await asyncio.gather(uplink, downlink, return_exceptions=True)

        ws_bridge.release()
        print(f"Client disconnected: {peer}")


async def _uplink(websocket: WebSocket, queue: asyncio.Queue):
    """Receiver to app: NMEA sentences as text frames."""
    while True:
        sentence = await queue.get()
        await websocket.send_text(sentence)
        ws_bridge.note_sent()


async def _downlink(websocket: WebSocket):
    """App to receiver: RTCM corrections written straight to the port."""
    while True:
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            return

        kind = message.get("type")

        if kind == "websocket.disconnect":
            return

        if message.get("bytes") is not None:
            payload = message["bytes"]
        elif message.get("text") is not None:
            payload = message["text"].encode("utf-8")
        else:
            continue

        if not ws_bridge.send_to_receiver(payload):
            print("Correction dropped, receiver port is closed")
