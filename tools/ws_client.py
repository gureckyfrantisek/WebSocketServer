# Minimal stand-in for the phone app, for testing without Android.
#
# Prints every NMEA sentence the server sends and forwards anything typed on
# stdin down to the receiver, the same way the app sends RTCM corrections.
#
#   python tools/ws_client.py                    # ws://127.0.0.1:8080
#   python tools/ws_client.py 192.168.1.42       # a Raspberry Pi on the network
import asyncio
import sys

import websockets


async def uplink(connection):
    async for message in connection:
        print(message if isinstance(message, str) else f"<{len(message)} binary bytes>")


async def downlink(connection):
    loop = asyncio.get_running_loop()

    while True:
        # Reading stdin in a thread keeps the event loop free
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        await connection.send(line.strip())
        print(f"sent {len(line.strip())} bytes to the receiver")


async def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "8080"
    url = f"ws://{host}:{port}/"

    print(f"Connecting to {url}")

    async with websockets.connect(url) as connection:
        print("Connected, type a line and press enter to send it to the receiver")

        tasks = [
            asyncio.create_task(uplink(connection)),
            asyncio.create_task(downlink(connection)),
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Closed")
