"""A client is only shown the channels its user is assigned to.

Listing a channel a client is not on invites the operator to switch on
traffic they will never be given. The channels shown therefore follow the
assignment on the system user holding the client's certificate, whether that
certificate was issued to the user by the server or made for them by hand.

Usage: python3 test_channel_visibility.py [host]
"""
import json
import sqlite3
import sys
import urllib.error
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
GROUPS = f"http://{HOST}:8080/Marti/api/groups/all?useCache=true"
FTS_DB = "/opt/fts/FTSDataBase.db"

PROBE_UID = "VISIBILITY-PROBE"
PROBE_IP = "127.0.0.1"

# a user whose certificate the server issued: its common name is the user's
# name with their id appended, which is what the API does when it bakes one
ISSUED_USER = "visibility-probe-user"
ISSUED_USER_ID = "8f1d4e2a-0000-4000-8000-visibilityprobe"
ISSUED_CN = ISSUED_USER + ISSUED_USER_ID

failures = []


def check(condition, message):
    print(("PASS: " if condition else "FAIL: ") + message)
    if not condition:
        failures.append(message)


def connect():
    return sqlite3.connect(FTS_DB)


def visible_channels():
    try:
        with urllib.request.urlopen(GROUPS, timeout=120) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, []
    return 200, sorted({
        group["name"] for group in data.get("data", []) if group["direction"] == "OUT"
    })


def present_as(common_name):
    """Make the next request look like it comes from this certificate holder.

    A client is matched on the address it calls from, so any other client
    recorded at this address would answer for it. The other clients here are
    the ones the CoT tests leave behind on the loopback address; a real
    deployment has each device on its own address.
    """
    database = connect()
    database.execute("delete from User where IP = ?", (PROBE_IP,))
    if common_name is not None:
        database.execute(
            "insert into User (uid, callsign, CN, IP) values (?,?,?,?)",
            (PROBE_UID, "visibility-probe", common_name, PROBE_IP),
        )
    database.commit()
    database.close()


database = connect()
database.execute(
    'insert or replace into SystemUser (uid, name, token, password, device_type, channels)'
    " values (?,?,?,?,?,?)",
    (ISSUED_USER_ID, ISSUED_USER, "visprobe-token", "visprobe-pass", "mobile", "alpha,command"),
)
database.commit()
database.close()

# a certificate the server issued, whose common name carries the user's id
present_as(ISSUED_CN)
status, channels = visible_channels()
check(status == 200, "the channel list is served")
check(
    channels == ["alpha", "command"],
    f"an issued certificate shows only its user's channels (got {channels})",
)
check(
    "__ANON__" not in channels,
    "a client on named channels is not offered the shared one",
)

# a certificate made by hand, whose common name is exactly the user's name
HANDMADE_USER = "visibility-probe-handmade"
database = connect()
database.execute(
    'insert or replace into SystemUser (uid, name, token, password, device_type, channels)'
    " values (?,?,?,?,?,?)",
    (HANDMADE_USER + "-id", HANDMADE_USER, "vis-token2", "vis-pass2", "mobile", "bravo"),
)
database.commit()
database.close()
present_as(HANDMADE_USER)
status, channels = visible_channels()
check(channels == ["bravo"], f"a hand-made certificate shows its user's channels (got {channels})")

# a user with nothing assigned belongs to the shared channel alone
present_as("admin")
status, channels = visible_channels()
check(
    channels == ["__ANON__"],
    f"a user assigned nothing is offered only the shared channel (got {channels})",
)

# a caller that cannot be placed keeps seeing everything, so that a client the
# server has not recorded yet is never left with an empty channel list
present_as(None)
status, channels = visible_channels()
check(len(channels) > 1, f"an unrecognised caller still gets a channel list (got {channels})")

database = connect()
database.execute("delete from User where uid = ?", (PROBE_UID,))
database.execute("delete from SystemUser where uid = ?", (ISSUED_USER_ID,))
database.execute("delete from SystemUser where name = ?", (HANDMADE_USER,))
database.commit()
database.close()

print(f"\nRESULT: {len(failures)} failed")
sys.exit(1 if failures else 0)
