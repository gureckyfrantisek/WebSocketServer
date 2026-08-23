# Port settings, baud rates, network and storage paths
import os
from dotenv import load_dotenv
from getpass import getuser


load_dotenv()


def _env_str(name, default):
    value = os.getenv(name)
    return default if not value else value


def _env_int(name, default):
    value = os.getenv(name)
    return default if not value else int(value)


def _env_float(name, default):
    value = os.getenv(name)
    return default if not value else float(value)


def _env_bool(name, default):
    value = os.getenv(name)
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# Serial / GNSS receiver
SERIAL_PATH = _env_str("SERIAL_PATH", "/dev/serial0")
SERIAL_BAUDRATE = _env_int("SERIAL_BAUDRATE", 115200)
SERIAL_RETRY_S = _env_float("SERIAL_RETRY_S", 5.0)
GNSS_SIMULATE = _env_bool("GNSS_SIMULATE", False)

# Comma separated NAME:RATE pairs sent to the receiver once it opens.
# Empty means leave the receiver on whatever it has saved itself.
UBX_MESSAGE_RATES = _env_str("UBX_MESSAGE_RATES", "")

# Protocol generation of the receiver.
#   gen8  u-blox 8, configured with CFG-MSG
#   gen9  ZED-F9P and newer, configured with CFG-VALSET
UBX_GENERATION = _env_str("UBX_GENERATION", "gen9")

# Which receiver port the messages should come out of: UART1, UART2, USB,
# I2C or SPI. The GPIO pins on the Raspberry Pi are UART1.
UBX_PORT = _env_str("UBX_PORT", "UART1")

# Generation 9 only: also write the settings to flash so they survive a reset
UBX_SAVE_TO_FLASH = _env_bool("UBX_SAVE_TO_FLASH", False)

# Server
SERVER_PORT = _env_int("SERVER_PORT", 8080)

# What the WebSocket carries.
#   raw    every chunk exactly as it came off the port, like the Node server
#   lines  only complete NMEA sentences, binary UBX filtered out
WS_FRAMING = _env_str("WS_FRAMING", "raw")

# Bluetooth handshake. The phone is paired once through Android settings, then
# hands over the hotspot credentials and receives the address to connect to.
# This is the only way the phone finds the Pi.
BLUETOOTH_ENABLED = _env_bool("BLUETOOTH_ENABLED", True)
BLUETOOTH_NAME = _env_str("BLUETOOTH_NAME", "K155GNSS")
BLUETOOTH_CHANNEL = _env_int("BLUETOOTH_CHANNEL", 1)

# Shared secret the phone must send with anything that changes the Pi.
# Pairing alone only proves a phone was once paired, it does not stop a paired
# device from redirecting the Pi onto another network. Empty disables the check.
BLUETOOTH_TOKEN = _env_str("BLUETOOTH_TOKEN", "")

# Wireless interface NetworkManager is told to use
WIFI_INTERFACE = _env_str("WIFI_INTERFACE", "wlan0")

# Storage.
# Recordings go onto a flash drive when one is plugged in, otherwise into
# LOCAL_DATA_PATH. That folder is relative to where the server was started,
# which the service file pins to the application directory. It deliberately
# avoids /tmp, which systemd empties.
PREFER_USB = _env_bool("PREFER_USB", True)
LOCAL_DATA_PATH = _env_str("LOCAL_DATA_PATH", "data")
BASE_USB_PATH = _env_str("BASE_USB_PATH", f"/media/{getuser()}")

# Subfolder made on the flash drive, empty writes into the root of the drive
USB_SUBDIR = _env_str("USB_SUBDIR", "gnss")
