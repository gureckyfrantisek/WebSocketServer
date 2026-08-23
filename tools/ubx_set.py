# Sends one configuration key to a generation 9 receiver from the command line.
#
# Stop the server first, only one process can hold the serial port.
#
#   sudo .venv/bin/python tools/ubx_set.py /dev/serial0 115200 0x10730004 1
#   sudo .venv/bin/python tools/ubx_set.py /dev/serial0 115200 --listen
#
# Useful keys on UART1:
#   0x10730001 UBX in      0x10740001 UBX out
#   0x10730002 NMEA in     0x10740002 NMEA out
#   0x10730004 RTCM3 in    0x10740004 RTCM3 out
#   0x209100bb GGA out     0x209100ac RMC out
import sys
import time

import serial

CFG_VALSET = (0x06, 0x8A)
LAYER_RAM = 0x01


def build(message_class, message_id, payload=b""):
    body = bytes([message_class, message_id]) + len(payload).to_bytes(2, "little") + payload

    check_a = 0
    check_b = 0
    for byte in body:
        check_a = (check_a + byte) & 0xFF
        check_b = (check_b + check_a) & 0xFF

    return b"\xb5\x62" + body + bytes([check_a, check_b])


def valset(key, value, layers=LAYER_RAM):
    payload = bytes([0x00, layers, 0x00, 0x00])
    payload += key.to_bytes(4, "little")
    payload += bytes([value & 0xFF])
    return build(*CFG_VALSET, payload)


def show(data):
    """Prints the stream, keeping text readable and marking binary."""
    text = "".join(
        chr(b) if 32 <= b < 127 else ("\n" if b == 10 else ("" if b == 13 else "."))
        for b in data
    )
    print(text, end="", flush=True)


def main():
    path = sys.argv[1]
    baud = int(sys.argv[2])

    port = serial.Serial(path, baud, timeout=0.2, write_timeout=2.0)

    if "--listen" in sys.argv:
        print(f"Listening on {path} at {baud}, Ctrl+C to stop\n")
        try:
            while True:
                show(port.read(port.in_waiting or 1))
        except KeyboardInterrupt:
            port.close()
            return

    key = int(sys.argv[3], 0)
    value = int(sys.argv[4], 0)

    print(f"Setting key 0x{key:08X} to {value}")
    port.write(valset(key, value))

    deadline = time.time() + 2.0
    answer = b""
    while time.time() < deadline:
        answer += port.read(port.in_waiting or 1)

    if b"\xb5\x62\x05\x01" in answer:
        print("ACK, the receiver accepted it")
    elif b"\xb5\x62\x05\x00" in answer:
        print("NAK, the receiver refused it, the key is probably wrong")
    else:
        print("No acknowledgement came back")

    show(answer)
    port.close()


if __name__ == "__main__":
    main()
