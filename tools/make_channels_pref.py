#!/usr/bin/env python3
"""Build an ATAK preference file that turns the channel picker on.

ATAK hides its channel list behind two preferences it never sets itself:

    prefs_enable_channels               the channels UI as a whole
    prefs_enable_channels_host-<host>   the channel list for one server

Without the per-host one, ATAK still fetches /Marti/api/groups/all and still
announces that a server's channels changed, but the channel overlay lists no
servers and so appears empty. The preferences are normally delivered by a TAK
Server enrollment package; this writes the same file so a client that was set
up from a data package or by hand can be switched on too.

Import the result in ATAK with Import Manager, or hand it to
repoint_data_package.py's output to ship it alongside a client certificate.

    python3 make_channels_pref.py 192.168.50.169
    python3 make_channels_pref.py 192.168.50.169 10.0.0.5 -o channels.pref
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom

APP_PREFERENCES = "com.atakmap.app_preferences"
ENABLE_CHANNELS = "prefs_enable_channels"
ENABLE_CHANNELS_HOST = "prefs_enable_channels_host"


def build(hosts):
    """Build the preference document ATAK's importer expects."""
    preferences = ET.Element("preferences")
    preference = ET.SubElement(
        preferences, "preference", {"version": "1", "name": APP_PREFERENCES}
    )

    # the channels UI itself, read as a boolean
    entry = ET.SubElement(
        preference, "entry", {"key": ENABLE_CHANNELS, "class": "class java.lang.Boolean"}
    )
    entry.text = "true"

    # and the list for each server, read as the string "true"
    for host in hosts:
        entry = ET.SubElement(
            preference,
            "entry",
            {"key": f"{ENABLE_CHANNELS_HOST}-{host}", "class": "class java.lang.String"},
        )
        entry.text = "true"

    return preferences


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("host", nargs="+", help="server address as entered in ATAK, without port")
    parser.add_argument("-o", "--output", default="channels.pref", help="file to write (default: channels.pref)")
    args = parser.parse_args()

    for host in args.host:
        if ":" in host or "/" in host:
            parser.error(f"give the host on its own, without a port or scheme: {host}")

    xml = minidom.parseString(ET.tostring(build(args.host))).toprettyxml(indent="  ")
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(xml)

    print(f"wrote {args.output} for {', '.join(args.host)}")
    print("import it in ATAK with Import Manager, then reconnect and open Channels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
