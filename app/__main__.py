# Entry point that binds the port the beacon advertises.
#
# Plain "uvicorn app.main:app" listens on 127.0.0.1 only, so the phone cannot
# reach the server even though the beacon is shouting the right address.
#
#   python -m app
import uvicorn

from app.core import config


def main():
    print(f"Listening on 0.0.0.0:{config.SERVER_PORT}")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.SERVER_PORT,
    )


if __name__ == "__main__":
    main()
