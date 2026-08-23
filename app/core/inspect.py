# Looking at what the receiver is actually sending.
#
# Answers the question "the app shows nothing useful, what is on the wire" by
# listening in on the stream for a moment and summarising it. Works while a
# client is connected, because it subscribes like every other consumer.
import threading
import time

from app.core import serial_link

# UBX message classes, for a readable summary
UBX_CLASS_NAMES = {
    0x01: "NAV",
    0x02: "RXM",
    0x04: "INF",
    0x05: "ACK",
    0x06: "CFG",
    0x0A: "MON",
    0x0D: "TIM",
    0x13: "MGA",
    0x21: "LOG",
    0xF0: "NMEA",
    0xF5: "RTCM",
}


def sample(seconds: float = 2.0) -> dict:
    """Collects the raw stream for a moment and describes it.

    Parameters:
        seconds (float): How long to listen

    Returns:
        dict: Byte count, what messages were seen, and a short preview
    """
    collected = bytearray()
    done = threading.Event()

    def collect(chunk):
        collected.extend(chunk)

    if not serial_link.verify_connection():
        return {"error": "receiver not connected"}

    serial_link.subscribe(collect)
    try:
        done.wait(seconds)
    finally:
        serial_link.unsubscribe(collect)

    data = bytes(collected)

    return {
        "seconds": seconds,
        "bytes": len(data),
        "bytes_per_second": round(len(data) / seconds, 1) if seconds else 0,
        "nmea": count_nmea(data),
        "ubx": count_ubx(data),
        "preview": preview(data),
    }


def count_nmea(data: bytes) -> dict:
    """How many of each NMEA sentence type appeared."""
    counts = {}

    for line in data.split(b"\r\n"):
        if not line.startswith(b"$") or len(line) < 6:
            continue

        talker = line[1:6].decode("ascii", errors="replace")
        counts[talker] = counts.get(talker, 0) + 1

    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def count_ubx(data: bytes) -> dict:
    """How many of each UBX message appeared, walking the frame headers."""
    counts = {}
    index = 0

    while True:
        start = data.find(b"\xb5\x62", index)

        if start < 0 or start + 6 > len(data):
            break

        message_class = data[start + 2]
        message_id = data[start + 3]
        length = int.from_bytes(data[start + 4:start + 6], "little")

        name = UBX_CLASS_NAMES.get(message_class, f"0x{message_class:02X}")
        label = f"{name}-0x{message_id:02X}"
        counts[label] = counts.get(label, 0) + 1

        index = start + 6 + length + 2

    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def preview(data: bytes, limit: int = 400) -> str:
    """First part of the stream as readable text, binary shown as dots."""
    chunk = data[:limit]

    return "".join(
        chr(byte) if 32 <= byte < 127 else ("\n" if byte == 10 else ("\r" if byte == 13 else "."))
        for byte in chunk
    )
