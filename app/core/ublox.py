# Telling the receiver which messages to send.
#
# The receiver keeps its own message settings, so a factory reset or a swapped
# unit silently changes what arrives. Sending the rates from here on every
# startup makes the configuration part of the project instead.
#
# Two protocol generations are supported:
#   gen8  u-blox 8 and older, uses CFG-MSG
#   gen9  ZED-F9P and newer, uses CFG-VALSET with configuration keys
import threading
import time

from app.core import config, serial_link

CFG_MSG = (0x06, 0x01)
CFG_VALSET = (0x06, 0x8A)
ACK_ACK = (0x05, 0x01)
ACK_NAK = (0x05, 0x00)

# How long to wait for the receiver to acknowledge one command
ACK_TIMEOUT_S = 2.0

# Generation 8 message names, class and id
MESSAGES_GEN8 = {
    "NMEA-GGA": (0xF0, 0x00),
    "NMEA-GLL": (0xF0, 0x01),
    "NMEA-GSA": (0xF0, 0x02),
    "NMEA-GSV": (0xF0, 0x03),
    "NMEA-RMC": (0xF0, 0x04),
    "NMEA-VTG": (0xF0, 0x05),
    "NMEA-ZDA": (0xF0, 0x08),
    "RXM-RAWX": (0x02, 0x15),
    "RXM-SFRBX": (0x02, 0x13),
    "NAV-PVT": (0x01, 0x07),
    "NAV-SAT": (0x01, 0x35),
    "NAV-STATUS": (0x01, 0x03),
}

# Generation 9 configuration keys for the I2C port, from the u-blox interface
# description. The keys for the other ports follow right after, which is what
# PORT_OFFSETS is for.
#
# A wrong key is not silently ignored: the receiver answers with ACK-NAK and
# apply_message_rates reports it as rejected.
MSGOUT_I2C_KEYS = {
    "NMEA-GGA": 0x209100BA,
    "NMEA-GLL": 0x209100C9,
    "NMEA-GSA": 0x209100BF,
    "NMEA-GSV": 0x209100C4,
    "NMEA-RMC": 0x209100AB,
    "NMEA-VTG": 0x209100B0,
    "NMEA-ZDA": 0x209100D8,
    "RXM-RAWX": 0x209102A4,
    "RXM-SFRBX": 0x20910231,
    "NAV-PVT": 0x20910006,
    "NAV-SAT": 0x20910015,
    "NAV-STATUS": 0x2091001A,
}

# Offset added to the I2C key to reach each port
PORT_OFFSETS = {
    "I2C": 0,
    "UART1": 1,
    "UART2": 2,
    "USB": 3,
    "SPI": 4,
}

# Generation 9 keys switching whole protocols on and off, per port.
# Without RTCM3X on the input the receiver answers corrections with
# "unknown msg", and without NMEA on the output no position sentences appear.
PROTOCOL_KEYS = {
    "UART1": {"in": 0x10730000, "out": 0x10740000},
    "UART2": {"in": 0x10750000, "out": 0x10760000},
    "USB": {"in": 0x10770000, "out": 0x10780000},
    "I2C": {"in": 0x10710000, "out": 0x10720000},
    "SPI": {"in": 0x10790000, "out": 0x107A0000},
}

# Offset of each protocol inside those groups
PROTOCOL_OFFSETS = {
    "UBX": 0x01,
    "NMEA": 0x02,
    "RTCM3X": 0x04,
}

# Where the setting is stored on a generation 9 receiver
LAYER_RAM = 0x01
LAYER_BBR = 0x02
LAYER_FLASH = 0x04


def build(message_class: int, message_id: int, payload: bytes = b"") -> bytes:
    """Wraps a payload in the UBX frame with both checksum bytes."""
    body = bytes([message_class, message_id]) + len(payload).to_bytes(2, "little") + payload

    check_a = 0
    check_b = 0
    for byte in body:
        check_a = (check_a + byte) & 0xFF
        check_b = (check_b + check_a) & 0xFF

    return b"\xb5\x62" + body + bytes([check_a, check_b])


def build_rate_command_gen8(message_class: int, message_id: int, rate: int) -> bytes:
    """CFG-MSG setting the rate of one message on the port it arrives on."""
    return build(*CFG_MSG, bytes([message_class, message_id, rate]))


def build_rate_command_gen9(key: int, rate: int, layers: int) -> bytes:
    """CFG-VALSET setting one configuration key to a one byte value."""
    payload = bytes([0x00, layers, 0x00, 0x00])          # version, layers, reserved
    payload += key.to_bytes(4, "little")
    payload += bytes([rate & 0xFF])

    return build(*CFG_VALSET, payload)


def get_key(name: str) -> int:
    """Configuration key for one message on the configured port.

    Returns:
        int: The key, or 0 when the message or the port is unknown
    """
    if name not in MSGOUT_I2C_KEYS:
        return 0

    port = config.UBX_PORT.upper()

    if port not in PORT_OFFSETS:
        return 0

    return MSGOUT_I2C_KEYS[name] + PORT_OFFSETS[port]


def enable_protocols(protocols=("UBX", "NMEA", "RTCM3X")) -> dict:
    """Switches input and output protocols on for the configured port.

    A receiver with RTCM3X disabled on the input answers every correction with
    an "unknown msg" notice instead of using it, and one with NMEA disabled on
    the output sends no position sentences at all.

    Returns:
        dict: What the receiver acknowledged and what it rejected
    """
    port = config.UBX_PORT.upper()

    result = {"port": port, "applied": [], "rejected": [], "failed": []}

    if port not in PROTOCOL_KEYS:
        result["failed"] = list(protocols)
        return result

    if not serial_link.verify_connection():
        result["failed"] = list(protocols)
        print("Cannot set protocols, the receiver is not connected")
        return result

    layers = LAYER_RAM | (LAYER_FLASH if config.UBX_SAVE_TO_FLASH else 0)

    for direction in ("in", "out"):
        group = PROTOCOL_KEYS[port][direction]

        for name in protocols:
            if name not in PROTOCOL_OFFSETS:
                result["failed"].append(name)
                continue

            key = group + PROTOCOL_OFFSETS[name]
            label = f"{direction} {name}"

            if send_and_wait(build_rate_command_gen9(key, 1, layers)):
                result["applied"].append(label)
            else:
                result["rejected"].append(label)

            time.sleep(0.05)

    print(f"Protocols acknowledged: {result['applied']}")

    if result["rejected"]:
        print(f"Protocols rejected: {result['rejected']}")

    return result


def parse_message_rates(text: str) -> list:
    """Reads the configured rates.

    Parameters:
        text (string): Comma separated NAME:RATE pairs, for example
            "NMEA-GGA:1,RXM-RAWX:1,NMEA-GSV:0"

    Returns:
        list: Tuples of (name, rate)
    """
    entries = []

    for part in text.split(","):
        part = part.strip()
        if not part:
            continue

        if ":" not in part:
            print(f"Ignoring message setting without a rate: {part}")
            continue

        name, _, rate = part.partition(":")
        name = name.strip().upper()

        if name not in MESSAGES_GEN8:
            print(f"Ignoring unknown message name: {name}")
            continue

        try:
            rate = int(rate)
        except ValueError:
            print(f"Ignoring non numeric rate for {name}: {rate}")
            continue

        entries.append((name, rate))

    return entries


# --- Acknowledgements --------------------------------------------------------

class AckWatcher:
    """Collects ACK-ACK and ACK-NAK frames while a command is in flight.

    The receiver mixes its answer into the normal NMEA and UBX stream, so this
    walks the stream looking for frame starts instead of assuming the answer
    arrives on its own.
    """

    def __init__(self):
        self._buffer = bytearray()
        self.result = None
        self.event = threading.Event()

    def feed(self, chunk: bytes):
        self._buffer.extend(chunk)

        while True:
            start = self._buffer.find(b"\xb5\x62")

            if start < 0:
                # Keep the last byte, it could be the start of a frame header
                del self._buffer[:-1]
                return

            if start > 0:
                del self._buffer[:start]

            if len(self._buffer) < 6:
                return

            length = int.from_bytes(self._buffer[4:6], "little")
            total = 6 + length + 2

            if len(self._buffer) < total:
                return

            frame = bytes(self._buffer[:total])
            del self._buffer[:total]

            pair = (frame[2], frame[3])

            if pair == ACK_ACK:
                self.result = True
                self.event.set()
            elif pair == ACK_NAK:
                self.result = False
                self.event.set()


def send_and_wait(command: bytes) -> bool:
    """Sends one command and waits for the receiver to acknowledge it.

    Returns:
        bool: True on ACK-ACK, False on ACK-NAK or on no answer at all
    """
    watcher = AckWatcher()
    serial_link.subscribe(watcher.feed)

    try:
        if not serial_link.write(command):
            return False

        watcher.event.wait(ACK_TIMEOUT_S)
        return bool(watcher.result)
    finally:
        serial_link.unsubscribe(watcher.feed)


# --- Applying ----------------------------------------------------------------

def apply_message_rates() -> dict:
    """Sends the configured rates to the receiver.

    Returns:
        dict: What the receiver acknowledged and what it rejected
    """
    entries = parse_message_rates(config.UBX_MESSAGE_RATES)

    result = {
        "generation": config.UBX_GENERATION,
        "port": config.UBX_PORT,
        "requested": len(entries),
        "applied": [],
        "rejected": [],
        "failed": [],
    }

    if not entries:
        return result

    if not serial_link.verify_connection():
        result["failed"] = [name for name, _ in entries]
        print("Cannot set message rates, the receiver is not connected")
        return result

    generation = config.UBX_GENERATION.lower()

    for name, rate in entries:
        if generation == "gen9":
            key = get_key(name)

            if not key:
                result["failed"].append(name)
                print(f"No configuration key for {name} on port {config.UBX_PORT}")
                continue

            layers = LAYER_RAM | (LAYER_FLASH if config.UBX_SAVE_TO_FLASH else 0)
            command = build_rate_command_gen9(key, rate, layers)
        else:
            message_class, message_id = MESSAGES_GEN8[name]
            command = build_rate_command_gen8(message_class, message_id, rate)

        if send_and_wait(command):
            result["applied"].append(f"{name}:{rate}")
        else:
            result["rejected"].append(f"{name}:{rate}")

        # The receiver needs a breath between configuration commands
        time.sleep(0.05)

    if result["applied"]:
        print(f"Receiver acknowledged: {result['applied']}")

    if result["rejected"]:
        print(f"Receiver rejected or did not answer: {result['rejected']}")

    return result
