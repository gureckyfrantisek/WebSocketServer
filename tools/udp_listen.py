# Listens for the discovery beacon, the way the app does before it connects.
#
#   python tools/udp_listen.py
import socket
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 41234

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("", PORT))

print(f"Listening for the beacon on UDP {PORT}")

while True:
    message, sender = sock.recvfrom(1024)
    print(f"{sender[0]} says: {message.decode('ascii', errors='replace')}  ->  ws://{message.decode()}:8080")
