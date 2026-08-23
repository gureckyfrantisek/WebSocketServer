# Finds out why a receiver stays silent.
#
# Tries the port with several baud rates and control-line settings and reports
# how many bytes each combination produced.
#
#   python tools/serial_probe.py COM3
import sys
import time

import serial

BAUD_RATES = [115200, 38400, 9600, 460800, 57600]
CONTROL_LINES = [(False, False), (True, True)]
LISTEN_S = 2.0


def probe(path, baudrate, dtr, rts):
    try:
        port = serial.Serial(port=path, baudrate=baudrate, timeout=0.2)
    except Exception as e:
        return None, str(e)

    try:
        port.dtr = dtr
        port.rts = rts
        # Give the device a moment to react to the control lines
        time.sleep(0.2)
        port.reset_input_buffer()

        data = b""
        deadline = time.time() + LISTEN_S
        while time.time() < deadline:
            data += port.read(port.in_waiting or 1)
    finally:
        port.close()

    return data, None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "COM3"

    print(f"Probing {path}\n")

    for dtr, rts in CONTROL_LINES:
        for baudrate in BAUD_RATES:
            data, error = probe(path, baudrate, dtr, rts)

            label = f"{baudrate:>6} baud  DTR={int(dtr)} RTS={int(rts)}"

            if error:
                print(f"{label}  open failed: {error}")
                continue

            nmea = data.count(b"$")
            ubx = data.count(b"\xb5\x62")

            print(f"{label}  {len(data):>5} bytes  NMEA starts: {nmea:>3}  UBX frames: {ubx:>3}")

            if data:
                print(f"        {data[:120]}")


if __name__ == "__main__":
    main()
