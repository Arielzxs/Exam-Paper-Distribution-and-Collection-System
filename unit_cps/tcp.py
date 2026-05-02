"""
unit_cps.tcp – TCP segment build / send / receive via raw sockets.

TCP Segment Structure (RFC 793)
================================
Offset  Field               Size
------  ------------------  ----
0       Source port         2 bytes
2       Destination port    2 bytes
4       Sequence number     4 bytes
8       Acknowledgment num  4 bytes
12      Data offset + Res.  1 byte   (upper 4 bits = header length in 32-bit words)
13      Flags               1 byte   (CWR ECE URG ACK PSH RST SYN FIN)
14      Window size         2 bytes
16      Checksum            2 bytes
18      Urgent pointer      2 bytes
20+     Options + Data      variable

IP pseudo-header (used for TCP checksum)
  - Source IP      4 bytes
  - Destination IP 4 bytes
  - Zero           1 byte
  - Protocol (6)   1 byte
  - TCP length     2 bytes

Permissions note (macOS / Linux)
==================================
Raw socket (``IPPROTO_TCP``) requires elevated privileges.
On macOS re-run with ``sudo python -m unit_cps tcp ...``.
"""

import socket
import struct
import sys
import threading
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TCP_FLAG_FIN: int = 0x01
TCP_FLAG_SYN: int = 0x02
TCP_FLAG_RST: int = 0x04
TCP_FLAG_PSH: int = 0x08
TCP_FLAG_ACK: int = 0x10
TCP_FLAG_URG: int = 0x20
TCP_FLAG_ECE: int = 0x40
TCP_FLAG_CWR: int = 0x80


# ---------------------------------------------------------------------------
# Checksum helper
# ---------------------------------------------------------------------------

def _checksum(data: bytes) -> int:
    """Compute the Internet checksum (RFC 1071) over *data*."""
    if len(data) % 2 != 0:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _tcp_checksum(
    src_ip: str,
    dst_ip: str,
    tcp_segment: bytes,
) -> int:
    """Compute the TCP checksum using the IP pseudo-header."""
    pseudo_header = struct.pack(
        "!4s4sBBH",
        socket.inet_aton(src_ip),
        socket.inet_aton(dst_ip),
        0,           # reserved zero byte
        socket.IPPROTO_TCP,
        len(tcp_segment),
    )
    return _checksum(pseudo_header + tcp_segment)


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def build_tcp_segment(
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    seq: int = 0,
    ack: int = 0,
    flags: int = TCP_FLAG_SYN,
    window: int = 65535,
    payload: bytes = b"",
    urgent: int = 0,
) -> bytes:
    """Build a TCP segment with a correct checksum.

    Parameters
    ----------
    src_ip / dst_ip:
        Dotted-decimal IPv4 addresses (needed for checksum pseudo-header).
    src_port / dst_port:
        Source and destination ports (0-65535).
    seq:
        Sequence number.
    ack:
        Acknowledgment number.
    flags:
        Bitwise-OR of ``TCP_FLAG_*`` constants.
    window:
        Advertised receive window (bytes).
    payload:
        Application-layer data to include in the segment.
    urgent:
        Urgent pointer (usually 0).

    Returns
    -------
    bytes
        Raw TCP segment (header + payload) ready for embedding in an IP packet.
    """
    # Data offset: header length in 32-bit words (5 for no options = 20 bytes)
    data_offset = (5 << 4)  # upper nibble = 5, lower nibble = 0 (reserved)

    # First build with checksum = 0
    header = struct.pack(
        "!HHIIBBHHH",
        src_port,
        dst_port,
        seq,
        ack,
        data_offset,  # data offset + reserved
        flags,
        window,
        0,            # checksum placeholder
        urgent,
    )
    segment = header + payload

    # Compute and embed the real checksum
    csum = _tcp_checksum(src_ip, dst_ip, segment)
    # Checksum is at bytes 16-17 inside the segment
    segment = segment[:16] + struct.pack("!H", csum) + segment[18:]
    return segment


# ---------------------------------------------------------------------------
# Send (raw socket)
# ---------------------------------------------------------------------------

def send_tcp(
    src_ip: str,
    dst_ip: str,
    segment: bytes,
) -> None:
    """Send a raw TCP segment.

    The OS will wrap *segment* in an IP header automatically when using
    ``IPPROTO_RAW`` + ``IP_HDRINCL=0``.

    Parameters
    ----------
    src_ip / dst_ip:
        Source and destination IP addresses.
    segment:
        Raw TCP segment returned by :func:`build_tcp_segment`.

    Raises
    ------
    PermissionError
        When the process lacks raw-socket privileges.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 0)
        sock.sendto(segment, (dst_ip, 0))
        sock.close()
        print(f"[TCP] Segment sent {src_ip} -> {dst_ip}.")
    except PermissionError:
        raise PermissionError(
            "Sending raw TCP segments requires elevated privileges.\n"
            "Re-run with: sudo python -m unit_cps tcp --send ..."
        )


# ---------------------------------------------------------------------------
# Receive (raw socket)
# ---------------------------------------------------------------------------

def receive_tcp(
    bind_ip: str = "0.0.0.0",
    timeout: float = 5.0,
    count: int = 5,
) -> list:
    """Capture and parse raw TCP segments from the network.

    Parameters
    ----------
    bind_ip:
        Local IP address to bind the raw socket to.
    timeout:
        Seconds to wait for packets.
    count:
        Maximum number of TCP packets to capture.

    Returns
    -------
    list of dict
        Each dict is the result of :func:`parse_tcp_segment`.

    Raises
    ------
    PermissionError
        When the process lacks raw-socket privileges.
    """
    results: list = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        sock.bind((bind_ip, 0))
        sock.settimeout(timeout)
        while len(results) < count:
            try:
                data, addr = sock.recvfrom(65535)
                parsed = parse_ip_and_tcp(data)
                if parsed:
                    results.append(parsed)
            except socket.timeout:
                break
        sock.close()
    except PermissionError:
        raise PermissionError(
            "Receiving raw TCP packets requires elevated privileges.\n"
            "Re-run with: sudo python -m unit_cps tcp --receive ..."
        )
    return results


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_tcp_segment(data: bytes, src_ip: str = "", dst_ip: str = "") -> dict:
    """Parse a raw TCP segment (no IP header).

    Parameters
    ----------
    data:
        Raw bytes of the TCP segment (header + optional payload).
    src_ip / dst_ip:
        Optional IP addresses for display purposes.

    Returns
    -------
    dict with keys:
        src_port, dst_port, seq, ack, data_offset, flags (dict of flag names),
        window, checksum, urgent, payload_len, payload_hex
    """
    if len(data) < 20:
        raise ValueError(f"TCP segment too short: {len(data)} bytes.")

    (
        src_port, dst_port, seq, ack, data_offset_byte, flags_byte,
        window, checksum, urgent,
    ) = struct.unpack("!HHIIBBHHH", data[:20])

    header_len = (data_offset_byte >> 4) * 4  # in bytes
    payload = data[header_len:]

    flags = {
        "CWR": bool(flags_byte & TCP_FLAG_CWR),
        "ECE": bool(flags_byte & TCP_FLAG_ECE),
        "URG": bool(flags_byte & TCP_FLAG_URG),
        "ACK": bool(flags_byte & TCP_FLAG_ACK),
        "PSH": bool(flags_byte & TCP_FLAG_PSH),
        "RST": bool(flags_byte & TCP_FLAG_RST),
        "SYN": bool(flags_byte & TCP_FLAG_SYN),
        "FIN": bool(flags_byte & TCP_FLAG_FIN),
    }

    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "seq": seq,
        "ack": ack,
        "header_len": header_len,
        "flags": flags,
        "window": window,
        "checksum": f"0x{checksum:04X}",
        "urgent": urgent,
        "payload_len": len(payload),
        "payload_hex": payload[:32].hex() + ("..." if len(payload) > 32 else ""),
    }


def parse_ip_and_tcp(data: bytes) -> dict | None:
    """Parse a raw IP+TCP packet received from a raw socket.

    Parameters
    ----------
    data:
        Raw bytes including the IP header.

    Returns
    -------
    dict or None
        Parsed TCP info dict if the IP payload is TCP (protocol 6), else None.
    """
    if len(data) < 20:
        return None
    ihl = (data[0] & 0x0F) * 4  # IP header length in bytes
    protocol = data[9]
    src_ip = socket.inet_ntoa(data[12:16])
    dst_ip = socket.inet_ntoa(data[16:20])

    if protocol != 6:  # 6 = TCP
        return None

    tcp_data = data[ihl:]
    try:
        parsed = parse_tcp_segment(tcp_data, src_ip=src_ip, dst_ip=dst_ip)
        return parsed
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Simple high-level TCP client / server (using normal sockets for portability)
# ---------------------------------------------------------------------------

def tcp_send_message(host: str, port: int, message: str, timeout: float = 5.0) -> str:
    """Send *message* to a TCP server and return the response.

    Uses a standard (non-raw) TCP socket, so no special permissions are needed.
    This is the portable fallback for the send/receive demonstration.

    Parameters
    ----------
    host:
        Server hostname or IP.
    port:
        Server port.
    message:
        UTF-8 string to send.
    timeout:
        Socket timeout in seconds.

    Returns
    -------
    str
        Decoded response from the server.
    """
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.sendall(message.encode())
        response = b""
        conn.settimeout(timeout)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass
    return response.decode(errors="replace")


def tcp_echo_server(host: str = "127.0.0.1", port: int = 9000) -> None:
    """Start a simple TCP echo server (blocks until interrupted).

    Useful for testing :func:`tcp_send_message`.

    Parameters
    ----------
    host:
        Bind address.
    port:
        Listen port.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[TCP] Echo server listening on {host}:{port}  (Ctrl-C to stop)")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"[TCP] Connection from {addr}")
            threading.Thread(
                target=_handle_echo,
                args=(conn,),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("\n[TCP] Server stopped.")
    finally:
        srv.close()


def _handle_echo(conn: socket.socket) -> None:
    """Handle a single echo-server connection."""
    with conn:
        data = conn.recv(65535)
        if data:
            conn.sendall(data)


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for TCP sub-feature.

    Usage:
        python -m unit_cps tcp --build  --src-ip 1.2.3.4 --dst-ip 5.6.7.8 \\
                                        --src-port 12345 --dst-port 80
        python -m unit_cps tcp --send   --src-ip ... --dst-ip ...
        python -m unit_cps tcp --receive [--timeout 5] [--count 5]
        python -m unit_cps tcp --server [--host 127.0.0.1] [--port 9000]
        python -m unit_cps tcp --client --host 127.0.0.1 --port 9000 \\
                                        --message "hello"
    """
    import argparse
    import pprint
    p = argparse.ArgumentParser(prog="unit_cps tcp", description=__doc__.split("\n")[0])
    p.add_argument("--build", action="store_true")
    p.add_argument("--send", action="store_true", help="Send raw TCP SYN (needs sudo)")
    p.add_argument("--receive", action="store_true", help="Capture TCP packets (needs sudo)")
    p.add_argument("--server", action="store_true", help="Start TCP echo server")
    p.add_argument("--client", action="store_true", help="Send message via normal TCP")
    p.add_argument("--src-ip", default="127.0.0.1")
    p.add_argument("--dst-ip", default="127.0.0.1")
    p.add_argument("--src-port", type=int, default=12345)
    p.add_argument("--dst-port", type=int, default=80)
    p.add_argument("--seq", type=int, default=0)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--message", default="Hello, TCP!")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--count", type=int, default=5)
    ns = p.parse_args(args)

    if ns.build or ns.send:
        seg = build_tcp_segment(
            ns.src_ip, ns.dst_ip, ns.src_port, ns.dst_port,
            seq=ns.seq, flags=TCP_FLAG_SYN,
        )
        parsed = parse_tcp_segment(seg, src_ip=ns.src_ip, dst_ip=ns.dst_ip)
        print("=== TCP Segment ===")
        pprint.pprint(parsed)
        print(f"Raw bytes ({len(seg)}): {seg.hex()}")
        if ns.send:
            send_tcp(ns.src_ip, ns.dst_ip, seg)
    elif ns.receive:
        print(f"[TCP] Capturing {ns.count} TCP packets (timeout={ns.timeout}s)…")
        pkts = receive_tcp(timeout=ns.timeout, count=ns.count)
        for i, pk in enumerate(pkts, 1):
            print(f"\n--- Packet {i} ---")
            pprint.pprint(pk)
    elif ns.server:
        tcp_echo_server(host=ns.host, port=ns.port)
    elif ns.client:
        resp = tcp_send_message(ns.host, ns.port, ns.message, timeout=ns.timeout)
        print(f"[TCP] Response: {resp!r}")
    else:
        p.print_help()
