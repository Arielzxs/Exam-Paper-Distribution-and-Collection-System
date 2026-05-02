"""
unit_cps.ip_parser – Capture raw IP packets and parse header fields / payload.

IPv4 Header Structure (RFC 791)
================================
Byte  Field                  Size   Description
----  ---------------------  -----  ------------------------------------------
0     Version + IHL          1      Upper nibble = 4 (IPv4); lower = header len
1     DSCP / ECN             1      Differentiated Services / Explicit Congestion
2-3   Total Length           2      Total packet length (header + data)
4-5   Identification         2      Fragment group identifier
6-7   Flags + Frag Offset    2      Bit 1: DF, Bit 2: MF; lower 13 bits = offset
8     TTL                    1      Hop limit
9     Protocol               1      1=ICMP  6=TCP  17=UDP
10-11 Header Checksum        2
12-15 Source IP              4
16-19 Destination IP         4
20+   Options (if IHL > 5)   variable
IHL*4 Payload               variable

Known protocol numbers
  1  = ICMP
  6  = TCP
 17  = UDP
 41  = IPv6-in-IPv4
 89  = OSPF

Permissions note (macOS / Linux)
==================================
Raw socket capture requires ``sudo``.  This module raises ``PermissionError``
with a clear hint when privileges are missing.  A ``--file`` option lets you
parse packets from a pre-captured pcap-like hex dump without needing root.

Usage example
=============
    from unit_cps.ip_parser import capture_and_parse, parse_ip_packet

    packets = capture_and_parse(count=10, timeout=15.0)
    for p in packets:
        print(p)
"""

import socket
import struct
import sys
import time


# ---------------------------------------------------------------------------
# Protocol name mapping
# ---------------------------------------------------------------------------

_PROTO_NAMES: dict = {
    1: "ICMP",
    2: "IGMP",
    6: "TCP",
    17: "UDP",
    41: "IPv6",
    47: "GRE",
    50: "ESP",
    51: "AH",
    58: "ICMPv6",
    89: "OSPF",
    132: "SCTP",
}


def _proto_name(num: int) -> str:
    return _PROTO_NAMES.get(num, f"Unknown({num})")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_ip_packet(data: bytes) -> dict:
    """Parse a complete IPv4 packet and return a structured dictionary.

    Parameters
    ----------
    data:
        Raw bytes starting with the IPv4 header.

    Returns
    -------
    dict with keys:
        version, ihl_bytes, dscp, ecn, total_length, identification,
        flags_df (bool), flags_mf (bool), fragment_offset, ttl,
        protocol, protocol_name, checksum, src_ip, dst_ip,
        options_hex, payload_length, payload_hex (first 64 bytes)

    Raises
    ------
    ValueError
        If the data is too short or not an IPv4 packet.
    """
    if len(data) < 20:
        raise ValueError(f"Packet too short: {len(data)} bytes.")

    ver_ihl = data[0]
    version = (ver_ihl >> 4) & 0x0F
    if version != 4:
        raise ValueError(f"Not an IPv4 packet (version={version}).")

    ihl_bytes = (ver_ihl & 0x0F) * 4
    dscp_ecn = data[1]
    dscp = (dscp_ecn >> 2) & 0x3F
    ecn = dscp_ecn & 0x03

    (
        total_length, identification,
        flags_frag, ttl, protocol, checksum,
        src_raw, dst_raw,
    ) = struct.unpack("!HHHBBH4s4s", data[2:20])

    flags = (flags_frag >> 13) & 0x07
    fragment_offset = (flags_frag & 0x1FFF) * 8  # in bytes

    flags_df = bool(flags & 0x02)  # Don't Fragment
    flags_mf = bool(flags & 0x01)  # More Fragments

    options = data[20:ihl_bytes] if ihl_bytes > 20 else b""
    payload = data[ihl_bytes:total_length] if total_length <= len(data) else data[ihl_bytes:]
    payload_preview = payload[:64]

    return {
        "version": version,
        "ihl_bytes": ihl_bytes,
        "dscp": dscp,
        "ecn": ecn,
        "total_length": total_length,
        "identification": f"0x{identification:04X}",
        "flags_df": flags_df,
        "flags_mf": flags_mf,
        "fragment_offset": fragment_offset,
        "ttl": ttl,
        "protocol": protocol,
        "protocol_name": _proto_name(protocol),
        "checksum": f"0x{checksum:04X}",
        "src_ip": socket.inet_ntoa(src_raw),
        "dst_ip": socket.inet_ntoa(dst_raw),
        "options_hex": options.hex() if options else "",
        "payload_length": len(payload),
        "payload_hex": payload_preview.hex() + ("..." if len(payload) > 64 else ""),
    }


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture_and_parse(
    bind_ip: str = "0.0.0.0",
    count: int = 10,
    timeout: float = 30.0,
    proto_filter: int | None = None,
) -> list:
    """Capture raw IP packets and return parsed dicts.

    Parameters
    ----------
    bind_ip:
        Local IP to bind the raw socket to.
    count:
        Maximum number of packets to capture.
    timeout:
        Seconds to wait for packets.
    proto_filter:
        Optional protocol number to filter (e.g. ``6`` for TCP only).
        Pass ``None`` to capture all IP packets.

    Returns
    -------
    list of dict
        Each element is the result of :func:`parse_ip_packet`.

    Raises
    ------
    PermissionError
        If the process lacks raw-socket privileges.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        sock.bind((bind_ip, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    except PermissionError:
        raise PermissionError(
            "IP packet capture requires elevated privileges.\n"
            "Re-run with: sudo python -m unit_cps ip-parser ...\n"
            "Alternatively, use --file to parse packets from a hex-dump file."
        )

    sock.settimeout(1.0)
    results: list = []
    deadline = time.monotonic() + timeout

    try:
        while len(results) < count and time.monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
                parsed = parse_ip_packet(data)
                if proto_filter is None or parsed["protocol"] == proto_filter:
                    results.append(parsed)
            except socket.timeout:
                pass
            except ValueError:
                pass
    finally:
        sock.close()

    return results


def parse_hex_file(path: str) -> list:
    """Parse IP packets from a plain-text file of hex strings (one packet per line).

    This provides a no-privileges-needed way to test the parser.

    Parameters
    ----------
    path:
        File path.  Each non-empty line should be a hex string of raw IP packet
        bytes (spaces and ``0x`` prefix are stripped automatically).

    Returns
    -------
    list of dict
    """
    results: list = []
    with open(path, "r") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip().replace(" ", "").replace("0x", "")
            if not line or line.startswith("#"):
                continue
            try:
                raw = bytes.fromhex(line)
                results.append(parse_ip_packet(raw))
            except Exception as exc:
                print(f"[ip_parser] Line {lineno}: {exc}")
    return results


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for IP packet parsing.

    Usage:
        python -m unit_cps ip-parser --capture [--count 10] [--timeout 30] [--proto 6]
        python -m unit_cps ip-parser --file packets.hex
        python -m unit_cps ip-parser --hex <hex-string>
    """
    import argparse
    import pprint
    p = argparse.ArgumentParser(
        prog="unit_cps ip-parser",
        description="Capture and parse IPv4 packets",
    )
    p.add_argument("--capture", action="store_true", help="Capture from live network")
    p.add_argument("--file", metavar="PATH", help="Parse from hex-dump file")
    p.add_argument("--hex", metavar="HEX", help="Parse a single packet from hex string")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--proto", type=int, default=None,
                   help="Protocol filter (1=ICMP 6=TCP 17=UDP)")
    p.add_argument("--bind", default="0.0.0.0")
    ns = p.parse_args(args)

    if ns.hex:
        raw = bytes.fromhex(ns.hex.replace(" ", ""))
        pprint.pprint(parse_ip_packet(raw))
    elif ns.file:
        packets = parse_hex_file(ns.file)
        for i, pk in enumerate(packets, 1):
            print(f"\n--- Packet {i} ---")
            pprint.pprint(pk)
    elif ns.capture:
        print(f"[IP-Parser] Capturing {ns.count} packets (timeout={ns.timeout}s)…")
        packets = capture_and_parse(
            bind_ip=ns.bind,
            count=ns.count,
            timeout=ns.timeout,
            proto_filter=ns.proto,
        )
        for i, pk in enumerate(packets, 1):
            print(f"\n--- Packet {i} ---")
            pprint.pprint(pk)
        print(f"\nTotal captured: {len(packets)}")
    else:
        p.print_help()
