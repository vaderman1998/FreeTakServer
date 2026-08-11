#!/usr/bin/env python3
"""Rewrite the server addresses inside a TAK client data package.

A data package pins the address a client dials, but a server is often
reachable at more than one (a LAN address, a VPN address such as ZeroTier,
a public hostname). This rewrites the cot_streams entries in place so one
package can carry several, letting the operator enable whichever applies.

Certificates are not touched: TAK clients validate the server certificate
against the CA in the package, not against the address, so repointing a
package does not invalidate it.

    repoint_data_package.py user.zip 10.147.20.5
    repoint_data_package.py user.zip 192.168.50.169 10.147.20.5 -o both.zip
    repoint_data_package.py user.zip 10.147.20.5 --port 8089 --enable-first
"""
import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

STREAM_BLOCK = re.compile(
    r'<preference version="1" name="cot_streams">.*?</preference>', re.S
)


def build_streams(addresses, port, enable_first):
    lines = [
        '<preference version="1" name="cot_streams">',
        f'            <entry key="count" class="class java.lang.Integer">{len(addresses)}</entry>',
    ]
    for index, address in enumerate(addresses):
        enabled = "true" if (enable_first and index == 0) else "false"
        lines += [
            f'            <entry key="description{index}" class="class java.lang.String">FreeTAKServer_{address}</entry>',
            f'            <entry key="enabled{index}" class="class java.lang.Boolean">{enabled}</entry>',
            f'            <entry key="connectString{index}" class="class java.lang.String">{address}:{port}:ssl</entry>',
        ]
    lines.append("        </preference>")
    return "\n".join(lines)


def rewrite(package: Path, addresses, port, enable_first, output: Path):
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        pref_names = [n for n in names if n.endswith(".pref")]
        if not pref_names:
            sys.exit(f"{package}: no .pref file found; is this a TAK data package?")
        payload = {name: archive.read(name) for name in names}

    replacement = build_streams(addresses, port, enable_first)
    for name in pref_names:
        text = payload[name].decode()
        if not STREAM_BLOCK.search(text):
            sys.exit(f"{name}: no cot_streams preference block found")
        payload[name] = STREAM_BLOCK.sub(replacement, text, count=1).encode()

    # write to a temporary file so the original survives a failure part way
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
    shutil.move(tmp.name, output)

    print(f"wrote {output}")
    for index, address in enumerate(addresses):
        state = "enabled" if (enable_first and index == 0) else "disabled"
        print(f"  {index}: {address}:{port}:ssl ({state})")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="data package .zip to rewrite")
    parser.add_argument("addresses", nargs="+",
                        help="server addresses in the order clients should see them")
    parser.add_argument("--port", default="8089", help="SSL CoT port (default 8089)")
    parser.add_argument("-o", "--output", type=Path,
                        help="write to this file instead of replacing the input")
    parser.add_argument("--enable-first", action="store_true",
                        help="mark the first entry enabled (FTS ships them disabled)")
    args = parser.parse_args()

    if not args.package.is_file():
        sys.exit(f"{args.package}: not found")
    rewrite(args.package, args.addresses, args.port, args.enable_first,
            args.output or args.package)


if __name__ == "__main__":
    main()
