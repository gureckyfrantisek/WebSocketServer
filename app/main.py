from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import config, discovery, serial_link, static_session, ublox, wifi, ws_bridge
from app.routers import common, discovery as discovery_router, gnss, points, static, wifi as wifi_router, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.WIFI_MANAGED:
        # Joining the hotspot comes first, the beacon needs an address
        wifi.start_watchdog()

    # Rates go out every time the port opens, so a receiver that was reset or
    # swapped still ends up sending what this project expects
    serial_link.on_port_opened.append(ublox.apply_message_rates)

    # The supervisor opens the receiver port and reopens it after an unplug
    serial_link.start_supervisor()

    if config.DISCOVERY_ENABLED:
        # The beacon runs only while nobody is connected, keeping the link 1:1
        ws_bridge.on_connected.append(discovery.stop)
        ws_bridge.on_disconnected.append(discovery.start)
        discovery.start()

    yield   # The server runs in here

    # A measurement left running must still end up with a closed file
    static_session.stop()
    discovery.stop()
    wifi.stop_watchdog()
    serial_link.stop_supervisor()
    serial_link.close_port()


app = FastAPI(title="K155 GNSS Server", lifespan=lifespan)

app.include_router(gnss.router, prefix="/gnss", tags=["GNSS"])
app.include_router(wifi_router.router, prefix="/wifi", tags=["WiFi"])
app.include_router(discovery_router.router, prefix="/discovery", tags=["Discovery"])
app.include_router(static.router, prefix="/static", tags=["Static measurement"])
app.include_router(points.router, prefix="/points", tags=["Points"])
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(common.router, tags=["Common"])
