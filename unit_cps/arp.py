"""
unit_cps.arp – ARP (Address Resolution Protocol) frame build / send / parse.

ARP frame structure (RFC 826)
==============================
Ethernet header (14 bytes)
  - Destination MAC  : 6 bytes
  - Source MAC       : 6 bytes
  - EtherType        : 2 bytes  (0x0806 = ARP)

ARP payload (28 bytes for IPv4)
  - Hardware type    : 2 bytes  (1 = Ethernet)
  - Protocol type    : 2 bytes  (0x0800 = IPv4)
  - Hardware length  : 1 byte   (6 for MAC)
  - Protocol length  : 1 byte   (4 for IPv4)
  - Operation        : 2 bytes  (1 = request, 2 = reply)
  - Sender MAC       : 6 bytes
  - Sender IP        : 4 bytes
  - Target MAC       : 6 bytes
  - Target IP        : 4 bytes

Permissions note (macOS / Linux)
==================================
Sending raw Ethernet frames requires a raw socket bound to a network interface.
On macOS this needs ``sudo``.  If the socket cannot be opened the module raises
``PermissionError`` with a descriptive message instead of crashing silently.

Usage example
=============
    from unit_cps.arp import build_arp_request, send_arp, parse_arp_frame

    frame = build_arp_request(
        sender_mac="aa:bb:cc:dd:ee:ff",
        sender_ip="192.168.1.10",
        target_ip="192.168.1.1",
    )
    # send_arp(frame, iface="en0")          # needs sudo
    parsed = parse_arp_frame(frame)
    print(parsed)
"""

import socket
import struct
import sys


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ETHERTYPE_ARP: int = 0x0806
ETHERTYPE_IPv4: int = 0x0800
ARP_HWTYPE_ETHERNET: int = 1
ARP_OP_REQUEST: int = 1
ARP_OP_REPLY: int = 2

BROADCAST_MAC: str = "ff:ff:ff:ff:ff:ff"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mac_to_bytes(mac: str) -> bytes:
    """Convert a colon-separated MAC string to 6 raw bytes."""
    return bytes(int(x, 16) for x in mac.split(":"))


def _ip_to_bytes(ip: str) -> bytes:
    """Convert a dotted-decimal IPv4 string to 4 raw bytes."""
    return socket.inet_aton(ip)


def _bytes_to_mac(raw: bytes) -> str:
    """Convert 6 raw bytes to a colon-separated MAC string."""
    return ":".join(f"{b:02x}" for b in raw)


def _bytes_to_ip(raw: bytes) -> str:
    """Convert 4 raw bytes to a dotted-decimal IPv4 string."""
    return socket.inet_ntoa(raw)


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------

def build_arp_request(
    sender_mac: str,
    sender_ip: str,
    target_ip: str,
    target_mac: str = BROADCAST_MAC,
    dst_mac: str = BROADCAST_MAC,
) -> bytes:
    """Build a complete Ethernet-ARP request frame.

    Parameters
    ----------
    sender_mac:
        Source / sender MAC address (``"aa:bb:cc:dd:ee:ff"``).
    sender_ip:
        Source / sender IPv4 address.
    target_ip:
        IPv4 address being resolved.
    target_mac:
        Target MAC address – normally all-zeros for a request, but broadcast
        is commonly used as the Ethernet destination (``dst_mac``).
    dst_mac:
        Ethernet frame destination MAC – broadcast for ARP requests.

    Returns
    -------
    bytes
        A 42-byte raw Ethernet frame ready to be sent on the wire.
    """
    # --- Ethernet header (14 bytes) ---
    eth_header = struct.pack(
        "!6s6sH",
        _mac_to_bytes(dst_mac),     # destination MAC
        _mac_to_bytes(sender_mac),  # source MAC
        ETHERTYPE_ARP,              # EtherType
    )

    # --- ARP payload (28 bytes) ---
    # '!' = network (big-endian), H=uint16, B=uint8, 6s=6 bytes, 4s=4 bytes
    arp_payload = struct.pack(
        "!HHBBH6s4s6s4s",
        ARP_HWTYPE_ETHERNET,           # hardware type
        ETHERTYPE_IPv4,                # protocol type
        6,                             # hardware address length
        4,                             # protocol address length
        ARP_OP_REQUEST,                # operation: request
        _mac_to_bytes(sender_mac),     # sender MAC
        _ip_to_bytes(sender_ip),       # sender IP
        _mac_to_bytes(target_mac),     # target MAC (zeros for request)
        _ip_to_bytes(target_ip),       # target IP
    )

    return eth_header + arp_payload


def build_arp_reply(
    sender_mac: str,
    sender_ip: str,
    target_mac: str,
    target_ip: str,
) -> bytes:
    """Build a complete Ethernet-ARP reply frame.

    Parameters
    ----------
    sender_mac:
        MAC of the host *sending* the reply (the one being resolved).
    sender_ip:
        IP of the host sending the reply.
    target_mac:
        MAC of the original requester.
    target_ip:
        IP of the original requester.

    Returns
    -------
    bytes
        A 42-byte raw Ethernet ARP-reply frame.
    """
    eth_header = struct.pack(
        "!6s6sH",
        _mac_to_bytes(target_mac),
        _mac_to_bytes(sender_mac),
        ETHERTYPE_ARP,
    )
    arp_payload = struct.pack(
        "!HHBBH6s4s6s4s",
        ARP_HWTYPE_ETHERNET,
        ETHERTYPE_IPv4,
        6,
        4,
        ARP_OP_REPLY,
        _mac_to_bytes(sender_mac),
        _ip_to_bytes(sender_ip),
        _mac_to_bytes(target_mac),
        _ip_to_bytes(target_ip),
    )
    return eth_header + arp_payload


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_arp(frame: bytes, iface: str = "en0") -> None:
    """Send a raw Ethernet ARP frame on the specified interface.

    Parameters
    ----------
    frame:
        Raw bytes returned by :func:`build_arp_request` or
        :func:`build_arp_reply`.
    iface:
        Network interface name (e.g. ``"en0"`` on macOS, ``"eth0"`` on Linux).

    Raises
    ------
    PermissionError
        When the process does not have the required privileges.  Re-run with
        ``sudo python -m unit_cps arp ...``.
    OSError
        For other socket / interface errors.

    Notes
    -----
    * macOS / Linux: ``AF_PACKET`` is Linux-only.  On macOS the standard
      approach is ``AF_PACKET``-style BPF sockets or ``pcap``.  We use
      ``socket.AF_PACKET`` (Linux) and fall back to a descriptive error on
      macOS where you would need ``scapy`` or ``libpcap``.
    """
    if sys.platform == "darwin":
        # macOS does not expose AF_PACKET; raw sending requires libpcap/scapy.
        # Provide a clear message rather than a cryptic AttributeError.
        try:
            from scapy.all import sendp, Ether  # type: ignore
            from scapy.all import ARP as ScapyARP  # type: ignore
            # Re-parse our frame with scapy and send it
            pkt = Ether(frame)
            sendp(pkt, iface=iface, verbose=False)
            print(f"[ARP] Frame sent on {iface} via scapy.")
        except ImportError:
            raise OSError(
                "macOS does not support AF_PACKET raw sockets natively.\n"
                "Install scapy (`pip install scapy`) and re-run with sudo, or\n"
                "use Linux for direct AF_PACKET access."
            )
    else:
        # Linux: AF_PACKET raw socket
        try:
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
            sock.bind((iface, 0))
            sock.send(frame)
            sock.close()
            print(f"[ARP] Frame sent on {iface}.")
        except PermissionError:
            raise PermissionError(
                "Sending raw packets requires elevated privileges.\n"
                "Re-run with: sudo python -m unit_cps arp --send ..."
            )


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_arp_frame(data: bytes) -> dict:
    """Parse a raw Ethernet-ARP frame and return a structured dictionary.

    Parameters
    ----------
    data:
        Raw bytes of the complete Ethernet frame (at least 42 bytes).

    Returns
    -------
    dict with keys:
        - ``dst_mac``     – Ethernet destination MAC
        - ``src_mac``     – Ethernet source MAC
        - ``ethertype``   – EtherType value (should be ``0x0806``)
        - ``hw_type``     – Hardware type
        - ``proto_type``  – Protocol type
        - ``hw_len``      – Hardware address length
        - ``proto_len``   – Protocol address length
        - ``operation``   – 1 = request, 2 = reply
        - ``sender_mac``  – ARP sender MAC
        - ``sender_ip``   – ARP sender IP
        - ``target_mac``  – ARP target MAC
        - ``target_ip``   – ARP target IP

    Raises
    ------
    ValueError
        If the data is too short or the EtherType is not ARP.
    """
    if len(data) < 42:
        raise ValueError(f"Frame too short: {len(data)} bytes (expected >= 42).")

    # Ethernet header
    dst_mac_raw, src_mac_raw, ethertype = struct.unpack("!6s6sH", data[:14])

    if ethertype != ETHERTYPE_ARP:
        raise ValueError(
            f"EtherType 0x{ethertype:04X} is not ARP (0x{ETHERTYPE_ARP:04X})."
        )

    # ARP payload
    (
        hw_type, proto_type, hw_len, proto_len, operation,
        sender_mac_raw, sender_ip_raw,
        target_mac_raw, target_ip_raw,
    ) = struct.unpack("!HHBBH6s4s6s4s", data[14:42])

    return {
        "dst_mac": _bytes_to_mac(dst_mac_raw),
        "src_mac": _bytes_to_mac(src_mac_raw),
        "ethertype": f"0x{ethertype:04X}",
        "hw_type": hw_type,
        "proto_type": f"0x{proto_type:04X}",
        "hw_len": hw_len,
        "proto_len": proto_len,
        "operation": "request" if operation == ARP_OP_REQUEST else "reply",
        "sender_mac": _bytes_to_mac(sender_mac_raw),
        "sender_ip": _bytes_to_ip(sender_ip_raw),
        "target_mac": _bytes_to_mac(target_mac_raw),
        "target_ip": _bytes_to_ip(target_ip_raw),
    }


def listen_arp(iface: str = "en0", count: int = 5) -> list:
    """Capture *count* ARP frames on *iface* and return parsed dicts.

    Requires ``sudo`` on macOS (via scapy) / Linux (via AF_PACKET).

    Parameters
    ----------
    iface:
        Network interface to sniff on.
    count:
        Number of ARP frames to capture before returning.

    Returns
    -------
    list of dict
        Each entry is the result of :func:`parse_arp_frame`.
    """
    results: list = []

    if sys.platform == "darwin":
        try:
            from scapy.all import sniff, ARP as ScapyARP  # type: ignore
            pkts = sniff(filter="arp", iface=iface, count=count, timeout=30)
            for p in pkts:
                try:
                    results.append(parse_arp_frame(bytes(p)))
                except Exception:
                    pass
            return results
        except ImportError:
            raise OSError(
                "Packet capture on macOS requires scapy.\n"
                "Install with: pip install scapy"
            )

    # Linux path
    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETHERTYPE_ARP))
        sock.bind((iface, 0))
        while len(results) < count:
            data, _ = sock.recvfrom(65535)
            try:
                results.append(parse_arp_frame(data))
            except ValueError:
                pass
        sock.close()
    except PermissionError:
        raise PermissionError(
            "Listening for raw packets requires elevated privileges.\n"
            "Re-run with: sudo python -m unit_cps arp --listen ..."
        )
    return results


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for ARP sub-feature.

    Usage:
        python -m unit_cps arp --build  <sender_mac> <sender_ip> <target_ip>
        python -m unit_cps arp --send   <sender_mac> <sender_ip> <target_ip> [--iface en0]
        python -m unit_cps arp --listen [--iface en0] [--count 5]
    """
    import argparse
    import pprint
    p = argparse.ArgumentParser(prog="unit_cps arp", description=__doc__.split("\n")[0])
    p.add_argument("--build", action="store_true", help="Build and print an ARP request frame")
    p.add_argument("--send", action="store_true", help="Build and send an ARP request frame")
    p.add_argument("--listen", action="store_true", help="Capture and parse ARP frames")
    p.add_argument("--sender-mac", default="aa:bb:cc:dd:ee:ff")
    p.add_argument("--sender-ip", default="192.168.1.10")
    p.add_argument("--target-ip", default="192.168.1.1")
    p.add_argument("--iface", default="en0")
    p.add_argument("--count", type=int, default=5)
    ns = p.parse_args(args)

    if ns.build or ns.send:
        frame = build_arp_request(ns.sender_mac, ns.sender_ip, ns.target_ip)
        parsed = parse_arp_frame(frame)
        print("=== ARP Request Frame ===")
        pprint.pprint(parsed)
        print(f"Raw bytes ({len(frame)}): {frame.hex()}")
        if ns.send:
            send_arp(frame, iface=ns.iface)
    elif ns.listen:
        print(f"[ARP] Listening on {ns.iface} for {ns.count} ARP packets…")
        frames = listen_arp(iface=ns.iface, count=ns.count)
        for i, f in enumerate(frames, 1):
            print(f"\n--- Frame {i} ---")
            pprint.pprint(f)
    else:
        p.print_help()
