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

# WiFi, managed through NetworkManager on the Raspberry Pi.
# Credentials belong in .env, never in the code or in git.
WIFI_MANAGED = _env_bool("WIFI_MANAGED", False)
WIFI_SSID = _env_str("WIFI_SSID", "")
WIFI_PASSWORD = _env_str("WIFI_PASSWORD", "")
WIFI_PRIORITY = _env_int("WIFI_PRIORITY", 20)

# Second network the Pi falls back to, keeps it reachable when the hotspot
# is not around
WIFI_FALLBACK_SSID = _env_str("WIFI_FALLBACK_SSID", "")
WIFI_FALLBACK_PASSWORD = _env_str("WIFI_FALLBACK_PASSWORD", "")
WIFI_FALLBACK_PRIORITY = _env_int("WIFI_FALLBACK_PRIORITY", 10)

WIFI_WATCHDOG_S = _env_float("WIFI_WATCHDOG_S", 15.0)

# UDP discovery beacon
DISCOVERY_ENABLED = _env_bool("DISCOVERY_ENABLED", True)
DISCOVERY_PORT = _env_int("DISCOVERY_PORT", 41234)
DISCOVERY_INTERVAL_S = _env_float("DISCOVERY_INTERVAL_S", 1.0)
WIFI_INTERFACE = _env_str("WIFI_INTERFACE", "wlan0")

# Storage
LOCAL_DATA_PATH = _env_str("LOCAL_DATA_PATH", "/tmp/projects")
BASE_USB_PATH = _env_str("BASE_USB_PATH", f"/media/{getuser()}")
