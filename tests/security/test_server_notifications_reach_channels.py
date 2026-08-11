"""A client in a channel must still receive the server's own messages.

Mission notifications are produced by the server, not by another client, so
they carry no channel membership of their own. They still have to reach every
subscriber, including clients restricted to a non-public channel.

Usage: python3 test_server_notifications_reach_channels.py [certs_dir] [host]
"""
import json
import socket
import ssl
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

CERTS = sys.argv[1] if len(sys.argv) > 1 else "/opt/fts/certs"
HOST = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
SSL_PORT = 8089
API = f"http://{HOST}:8080/Marti/api/missions"
MISSION = "chanotify"
ITEM = "chanotify-item"
MISSION_DB = "/opt/fts/MissionRecords.db"

CLIENT_CERT = "chan-alpha-one"   # member of channel "alpha" only
CLIENT_UID = "CHANNOTIFY-ALPHA"


def api(url, method="GET"):
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def connect():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(f"{CERTS}/{CLIENT_CERT}.pem", f"{CERTS}/{CLIENT_CERT}.key")
    sock = context.wrap_socket(socket.create_connection((HOST, SSL_PORT), timeout=20))
    presence = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid="{CLIENT_UID}" type="a-f-G-U-C" how="m-g" '
        'time="2026-08-11T20:00:00.00Z" start="2026-08-11T20:00:00.00Z" '
        'stale="2027-08-11T20:00:00.00Z">'
        '<point lat="1.0" lon="1.0" hae="0" ce="9999999" le="9999999"/>'
        f'<detail><contact callsign="{CLIENT_UID}" endpoint="*:-1:stcp"/>'
        f'<uid Droid="{CLIENT_UID}"/><__group name="Cyan" role="Team Member"/>'
        '</detail></event>'
    )
    sock.sendall(presence.encode())
    return sock


received = []


def listen(sock):
    sock.settimeout(1.0)
    while True:
        try:
            data = sock.recv(65535)
            if not data:
                return
            received.append(data.decode(errors="replace"))
        except socket.timeout:
            continue
        except OSError:
            return


sock = connect()
threading.Thread(target=listen, args=(sock,), daemon=True).start()
time.sleep(5)

api(f"{API}/{MISSION}?creatorUid={CLIENT_UID}&description=channel+notify", "PUT")
time.sleep(4)

connection = sqlite3.connect(MISSION_DB)
connection.execute("insert or replace into MissionCoT (uid, mission_uid) values (?,?)", (ITEM, MISSION))
connection.commit()
connection.close()
time.sleep(1)

api(f"{API}/{MISSION}/contents?uid={ITEM}&creatorUid={CLIENT_UID}", "DELETE")
time.sleep(6)

blob = "".join(received)
api(f"{API}/{MISSION}", "DELETE")
sock.close()

failures = []
if "t-x-m-c" not in blob or "REMOVE_CONTENT" not in blob:
    failures.append("channel client did not receive the mission removal notification")
if ITEM not in blob:
    failures.append("removal notification did not name the removed item")

for failure in failures:
    print(f"FAIL: {failure}")
if not failures:
    print("PASS: client in channel 'alpha' received the server's mission removal notification")
sys.exit(1 if failures else 0)
