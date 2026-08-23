# Asks the receiver a question and waits for the answer.
#
# If the receiver replies, the link is fine and only its message output is
# switched off. If nothing comes back, the problem is lower down - wrong port,
# wrong baud rate or the receiver is not talking at all.
#
#   python tools/ublox_poll.py COM3
#   python tools/ublox_poll.py COM3 --enable-nmea
import sys
import time

import serial

# UBX message classes and ids used here
MON_VER = (0x0A, 0x04)
CFG_PRT = (0x06, 0x00)

LISTEN_S = 2.0


def build(message_class, message_id, payload=b"") -> bytes:
    """Wraps a payload in the UBX frame with both checksum bytes."""
    body = bytes([message_class, message_id]) + len(payload).to_bytes(2, "little") + payload

    check_a = 0
    check_b = 0
    for byte in body:
        check_a = (check_a + byte) & 0xFF
        check_b = (check_b + check_a) & 0xFF

    return b"\xb5\x62" + body + bytes([check_a, check_b])


def ask(port, frame: bytes) -> bool:
    """Sends a frame, reporting a receiver that will not even take input."""
    try:
        port.write(frame)
        return True
    except serial.SerialTimeoutException:
        print("        the receiver did not accept the write, it is not responding")
        return False


def listen(port, seconds=LISTEN_S) -> bytes:
    data = b""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            data += port.read(port.in_waiting or 1)
        except Exception as e:
            print(f"        read failed: {e}")
            break
    return data


def describe(data: bytes):
    if not data:
        print("        nothing came back")
        return

    nmea = data.count(b"$")
    ubx = data.count(b"\xb5\x62")

    print(f"        {len(data)} bytes, NMEA starts: {nmea}, UBX frames: {ubx}")
    print(f"        {data[:160]}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    enable_nmea = "--enable-nmea" in sys.argv

    port = serial.Serial(port=path, baudrate=115200, timeout=0.2, write_timeout=2.0)

    # USB serial devices on Windows sometimes need the control lines raised
    port.dtr = True
    port.rts = True
    time.sleep(0.3)
    port.reset_input_buffer()

    print(f"Listening on {path} without asking anything", flush=True)
    describe(listen(port))

    print("\nPolling UBX-MON-VER (receiver version)", flush=True)
    if ask(port, build(*MON_VER)):
        describe(listen(port))

    print("\nPolling UBX-CFG-PRT (port configuration)", flush=True)
    if ask(port, build(*CFG_PRT)):
        describe(listen(port))

    if enable_nmea:
        # CFG-PRT for the USB port: portID 3, both protocols in and out
        payload = bytes([3, 0]) + (0).to_bytes(2, "little") + (0).to_bytes(4, "little")
        payload += (0).to_bytes(4, "little")
        payload += (0x0003).to_bytes(2, "little")   # inProtoMask:  UBX + NMEA
        payload += (0x0003).to_bytes(2, "little")   # outProtoMask: UBX + NMEA
        payload += (0).to_bytes(2, "little") + (0).to_bytes(2, "little")

        print("\nEnabling UBX and NMEA output on the USB port", flush=True)
        if ask(port, build(*CFG_PRT, payload)):
            describe(listen(port, 3.0))

    port.close()


if __name__ == "__main__":
    main()
