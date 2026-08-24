from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import bluetooth, serial_link, static_session, ublox
from app.routers import bluetooth as bluetooth_router, common, gnss, points, static, storage as storage_router, wifi as wifi_router, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Rates go out every time the port opens, so a receiver that was reset or
    # swapped still ends up sending what this project expects
    serial_link.on_port_opened.append(ublox.apply_message_rates)

    # The supervisor opens the receiver port and reopens it after an unplug
    serial_link.start_supervisor()

    # The only way the phone finds the Pi: it hands over the hotspot
    # credentials and gets the address back. Always on, there is no other
    # way in.
    bluetooth.start()

    yield   # The server runs in here

    # A measurement left running must still end up with a closed file
    static_session.stop()
    bluetooth.stop()
    serial_link.stop_supervisor()
    serial_link.close_port()


app = FastAPI(title="K155 GNSS Server", lifespan=lifespan)

app.include_router(gnss.router, prefix="/gnss", tags=["GNSS"])
app.include_router(wifi_router.router, prefix="/wifi", tags=["WiFi"])
app.include_router(bluetooth_router.router, prefix="/bluetooth", tags=["Bluetooth"])
app.include_router(static.router, prefix="/static", tags=["Static measurement"])
app.include_router(points.router, prefix="/points", tags=["Points"])
app.include_router(storage_router.router, prefix="/storage", tags=["Storage"])
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(common.router, tags=["Common"])
