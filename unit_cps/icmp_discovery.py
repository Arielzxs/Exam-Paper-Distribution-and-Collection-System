"""
unit_cps.icmp_discovery – ICMP-based active host discovery (ping sweep).

ICMP Echo Request / Reply Structure (RFC 792)
===============================================
Field             Size   Notes
--------------    -----  ----------------------------------------
Type              1 byte  8 = Echo Request, 0 = Echo Reply
Code              1 byte  0
Checksum          2 bytes Internet checksum of ICMP header + data
Identifier        2 bytes Used to match request/reply (PID-based)
Sequence Number   2 bytes Incremented per probe
Data              variable Optional payload (timestamp / padding)

IP header (20 bytes, not built here – OS adds it)
  Protocol = 1 (ICMP)

Permissions note (macOS / Linux)
==================================
Raw ICMP sockets require elevated privileges (``sudo``).
On macOS the ``ping`` binary (SUID) is used as a privileged fallback when
raw sockets fail, so host discovery still works without ``sudo`` if ``ping``
is available on PATH.

Usage example
=============
    from unit_cps.icmp_discovery import ping_host, ping_sweep

    alive = ping_host("192.168.1.1")
    hosts = ping_sweep("192.168.1.0/24", timeout=1.0, max_workers=64)
    print("Active hosts:", hosts)
"""

import concurrent.futures
import ipaddress
import os
import socket
import struct
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICMP_ECHO_REQUEST: int = 8
ICMP_ECHO_REPLY: int = 0
ICMP_CODE: int = 0
ICMP_DEFAULT_ID: int = os.getpid() & 0xFFFF  # use PID as identifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _checksum(data: bytes) -> int:
    """Internet checksum (RFC 1071)."""
    if len(data) % 2 != 0:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------

def build_icmp_echo_request(
    identifier: int = ICMP_DEFAULT_ID,
    sequence: int = 1,
    payload: bytes = b"unit_cps_ping",
) -> bytes:
    """Build a raw ICMP Echo Request packet.

    Parameters
    ----------
    identifier:
        16-bit identifier (use PID to match replies).
    sequence:
        16-bit sequence number.
    payload:
        Optional data bytes appended after the ICMP header.

    Returns
    -------
    bytes
        ICMP Echo Request packet (8-byte header + payload).
    """
    # Build header with checksum = 0
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, ICMP_CODE, 0, identifier, sequence)
    raw = header + payload
    csum = _checksum(raw)
    # Embed real checksum
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, ICMP_CODE, csum, identifier, sequence)
    return header + payload


def parse_icmp_reply(data: bytes) -> dict:
    """Parse a raw IP+ICMP packet received from a raw socket.

    Parameters
    ----------
    data:
        Raw bytes including the IP header (as returned by recvfrom on a raw
        ICMP socket).

    Returns
    -------
    dict with keys:
        src_ip, icmp_type, icmp_code, checksum, identifier, sequence, payload_hex

    Raises
    ------
    ValueError
        If the packet is too short or not an ICMP echo reply.
    """
    if len(data) < 28:
        raise ValueError("Packet too short for IP+ICMP.")

    # IP header length (IHL field is the lower 4 bits of byte 0, in 32-bit words)
    ihl = (data[0] & 0x0F) * 4
    src_ip = socket.inet_ntoa(data[12:16])

    icmp_data = data[ihl:]
    if len(icmp_data) < 8:
        raise ValueError("ICMP data too short.")

    icmp_type, code, checksum, ident, seq = struct.unpack("!BBHHH", icmp_data[:8])
    payload = icmp_data[8:]

    return {
        "src_ip": src_ip,
        "icmp_type": icmp_type,
        "icmp_code": code,
        "checksum": f"0x{checksum:04X}",
        "identifier": ident,
        "sequence": seq,
        "payload_hex": payload.hex(),
    }


# ---------------------------------------------------------------------------
# Raw-socket ping
# ---------------------------------------------------------------------------

def _raw_ping(
    host: str,
    timeout: float = 1.0,
    identifier: int = ICMP_DEFAULT_ID,
    sequence: int = 1,
) -> bool:
    """Send one ICMP echo request and wait for a reply.

    Returns True if a reply is received within *timeout* seconds.
    Raises ``PermissionError`` if raw socket cannot be opened.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.getprotobyname("icmp"))
    except PermissionError:
        raise

    sock.settimeout(timeout)
    packet = build_icmp_echo_request(identifier=identifier, sequence=sequence)
    try:
        sock.sendto(packet, (host, 0))
        start = time.monotonic()
        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                return False
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(1024)
                parsed = parse_icmp_reply(data)
                if parsed["icmp_type"] == ICMP_ECHO_REPLY and parsed["identifier"] == identifier:
                    return True
            except socket.timeout:
                return False
    finally:
        sock.close()


def _subprocess_ping(host: str, timeout: float = 1.0) -> bool:
    """Fall back to the system ``ping`` binary.

    Used on macOS when the process does not have raw-socket privileges.
    """
    cmd = [
        "ping",
        "-c", "1",
        "-W", str(max(1, int(timeout * 1000))),  # macOS: timeout in ms
        "-t", "1",                                  # macOS: TTL
        host,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ping_host(host: str, timeout: float = 1.0) -> bool:
    """Return True if *host* responds to an ICMP echo request.

    Tries a raw-socket ping first; if that fails with ``PermissionError``
    (common for non-root macOS processes) falls back to the ``ping`` binary.

    Parameters
    ----------
    host:
        Hostname or dotted-decimal IPv4 address.
    timeout:
        Time to wait for a reply, in seconds.
    """
    # Resolve hostname to IP
    try:
        host = socket.gethostbyname(host)
    except socket.gaierror:
        return False

    try:
        return _raw_ping(host, timeout=timeout)
    except PermissionError:
        # Privileged raw socket not available – use system ping
        return _subprocess_ping(host, timeout=timeout)


def ping_sweep(
    network: str,
    timeout: float = 1.0,
    max_workers: int = 64,
) -> list:
    """Discover active hosts in *network* using ICMP echo requests.

    Parameters
    ----------
    network:
        CIDR notation, e.g. ``"192.168.1.0/24"``, or a range string like
        ``"192.168.1.1-192.168.1.50"``.
    timeout:
        Per-host ping timeout in seconds.
    max_workers:
        Number of concurrent threads.

    Returns
    -------
    list of str
        IP addresses of hosts that responded (sorted).
    """
    # Build list of target IPs
    targets: list = []
    if "-" in network and "/" not in network:
        # Range format: "192.168.1.1-192.168.1.50"
        parts = network.split("-")
        if len(parts) == 2:
            start = int(ipaddress.IPv4Address(parts[0].strip()))
            end = int(ipaddress.IPv4Address(parts[1].strip()))
            targets = [str(ipaddress.IPv4Address(i)) for i in range(start, end + 1)]
    else:
        net = ipaddress.IPv4Network(network, strict=False)
        targets = [str(ip) for ip in net.hosts()]

    alive: list = []

    def probe(ip: str) -> None:
        if ping_host(ip, timeout=timeout):
            alive.append(ip)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        pool.map(probe, targets)

    return sorted(alive, key=lambda ip: ipaddress.IPv4Address(ip))


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for ICMP discovery sub-feature.

    Usage:
        python -m unit_cps icmp --ping 192.168.1.1
        python -m unit_cps icmp --sweep 192.168.1.0/24 [--timeout 1.0] [--workers 64]
        python -m unit_cps icmp --build [--seq 1]
    """
    import argparse
    import pprint
    p = argparse.ArgumentParser(
        prog="unit_cps icmp",
        description="ICMP echo request/reply host discovery",
    )
    p.add_argument("--ping", metavar="HOST", help="Ping a single host")
    p.add_argument("--sweep", metavar="NETWORK", help="Ping-sweep a subnet (CIDR or range)")
    p.add_argument("--build", action="store_true", help="Build and display an ICMP echo request")
    p.add_argument("--timeout", type=float, default=1.0)
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--seq", type=int, default=1)
    ns = p.parse_args(args)

    if ns.build:
        pkt = build_icmp_echo_request(sequence=ns.seq)
        print(f"=== ICMP Echo Request ({len(pkt)} bytes) ===")
        print(f"Type=8 Code=0 Seq={ns.seq}")
        print(f"Raw: {pkt.hex()}")
    elif ns.ping:
        alive = ping_host(ns.ping, timeout=ns.timeout)
        status = "ALIVE" if alive else "no response"
        print(f"[ICMP] {ns.ping} → {status}")
    elif ns.sweep:
        print(f"[ICMP] Sweeping {ns.sweep}  (timeout={ns.timeout}s, workers={ns.workers})…")
        hosts = ping_sweep(ns.sweep, timeout=ns.timeout, max_workers=ns.workers)
        if hosts:
            print(f"Active hosts ({len(hosts)}):")
            for h in hosts:
                print(f"  {h}")
        else:
            print("No active hosts found.")
    else:
        p.print_help()
