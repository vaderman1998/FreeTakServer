"""A client's channel selection has to be honoured, and cannot widen access.

Switching a channel off in a TAK client tells the server the client no longer
wants that traffic. The server has to stop delivering it, keep reporting the
choice so it survives a reconnect, and never let the choice reach a channel
the client's certificate does not allow.

Usage: python3 test_channel_selection.py [host]
"""
import json
import sqlite3
import sys
import urllib.error
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
API = f"http://{HOST}:8080/Marti/api"
FTS_DB = "/opt/fts/FTSDataBase.db"

CLIENT_UID = "SELECTION-PROBE-1"
CLIENT_CN = "chan-alpha-one"      # allowed on "alpha" only
# the address the client is recorded at has to be the one it calls from, since
# that is what the server matches it on when the client does not name itself
CLIENT_IP = "127.0.0.1"

failures = []


def check(condition, message):
    print(("PASS: " if condition else "FAIL: ") + message)
    if not condition:
        failures.append(message)


def request(path, method="GET", body=None):
    req = urllib.request.Request(f"{API}{path}", method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        return error.code, None


def stored_selection():
    connection = sqlite3.connect(FTS_DB)
    row = connection.execute(
        "select active_channels from User where uid = ?", (CLIENT_UID,)
    ).fetchone()
    connection.close()
    return row[0] if row else None


def groups_for_client():
    status, body = request("/groups/all?useCache=true")
    return status, {
        group["name"]: group["active"]
        for group in (body or {}).get("data", [])
        if group["direction"] == "OUT"
    }


# a client the server already knows, as one appears once it has connected
connection = sqlite3.connect(FTS_DB)
connection.execute(
    "insert or replace into User (uid, callsign, CN, IP) values (?,?,?,?)",
    (CLIENT_UID, "selection-probe", CLIENT_CN, CLIENT_IP),
)
connection.commit()
connection.close()

status, before = groups_for_client()
check(status == 200, "the channel list is served")
check(all(before.values()), "a client that has chosen nothing is active on every channel")

# the client switches everything off except "alpha", the anonymous channel
# included: clients know the public channel by that name
selection = [
    {"name": name, "direction": "OUT", "active": name == "alpha"} for name in before
]
status, _ = request(f"/groups/active?clientUid={CLIENT_UID}", "PUT", {"data": selection})
check(status == 200, "the server accepts a channel selection")
check(stored_selection() == "alpha", f"the selection is stored (got {stored_selection()!r})")

status, after = groups_for_client()
check(after.get("alpha") is True, "the chosen channel is reported active")
check(
    all(active is False for name, active in after.items() if name != "alpha"),
    f"the channels switched off are reported inactive (got {after})",
)

# a selection naming a channel the certificate does not allow must not grant it
from FreeTAKServer.core.configuration.ChannelConstants import active_channels  # noqa: E402

check(
    active_channels(["alpha"], ["alpha", "bravo"]) == ["alpha"],
    "a selection cannot reach a channel the client is not allowed on",
)
check(
    active_channels(["alpha", "bravo"], None) == ["alpha", "bravo"],
    "no selection means every allowed channel is active",
)
check(
    active_channels(["alpha"], ["bravo"]) == ["alpha"],
    "a selection that leaves nothing falls back to every allowed channel",
)

# clearing the selection returns the client to all of its channels
request(f"/groups/active?clientUid={CLIENT_UID}", "PUT", {"data": [
    {"name": name, "direction": "OUT", "active": True} for name in before
]})
status, restored = groups_for_client()
check(all(restored.values()), "switching everything back on restores every channel")

connection = sqlite3.connect(FTS_DB)
connection.execute("delete from User where uid = ?", (CLIENT_UID,))
connection.commit()
connection.close()

print(f"\nRESULT: {len(failures)} failed")
sys.exit(1 if failures else 0)
