"""
unit_cps.reliable_udp – Reliable, ordered data-transfer protocol over UDP.

================================================================================
Protocol Design Document
================================================================================

Background
----------
Industrial / CPS (Cyber-Physical System) environments often connect sensors and
controllers over unreliable links (Wi-Fi, LoRa, serial-over-IP).  Plain UDP
is used because of its low overhead, but it provides no reliability guarantees.
This module implements a lightweight stop-and-wait / sliding-window ARQ
(Automatic Repeat reQuest) layer on top of UDP.

Protocol Name: RUDP-CPS (Reliable UDP for CPS)
Version: 1.0

Design Goals
------------
1. **Ordered delivery** – segments are numbered; the receiver reorders before
   delivering to the application.
2. **Reliability** – the sender retransmits any unacknowledged segment after a
   configurable timeout.
3. **Flow control** – a sliding window prevents overwhelming a slow receiver.
4. **Simplicity** – the header is intentionally small (12 bytes) to minimise
   overhead on constrained links.
5. **Configurability** – timeout and window size are constructor parameters.

Packet Header (12 bytes)
------------------------
Offset  Field        Size  Description
------  ----------   ----  ---------------------------------------------------
0       Magic        2     0xCAAF – marks this as a RUDP-CPS packet
2       Type         1     0x01 = DATA, 0x02 = ACK, 0x03 = FIN, 0x04 = FIN-ACK
3       Flags        1     0x01 = retransmit flag (for diagnostics)
4       Sequence     4     32-bit sequence number (zero-based, byte-index)
8       Length       2     Payload length in bytes (0 for ACK/FIN)
10      Checksum     2     Internet checksum of header + payload

Reliability Mechanism
---------------------
* **Stop-and-wait (window=1)**: sender transmits one segment, waits for ACK,
  retransmits on timeout.  Simple and suitable for very low-bandwidth links.
* **Sliding window (window>1)**: sender keeps up to *window* unacknowledged
  segments in flight simultaneously; receiver sends cumulative ACKs.
* **Retransmit**: after *timeout* seconds without an ACK the segment is
  re-sent up to *max_retries* times; after that the transfer is aborted.
* **Ordering**: receiver buffers out-of-order segments and delivers in order.

Performance Tuning
------------------
* Increase *window_size* for high-bandwidth / high-RTT links.
* Decrease *timeout* for low-latency LAN environments.
* Use *max_retries=0* to disable retransmit (best-effort over RUDP).

Usage example
=============
    # --- Server (receiver) ---
    from unit_cps.reliable_udp import RUDPServer
    srv = RUDPServer(host="0.0.0.0", port=9100)
    data = srv.receive()
    print("Received:", data.decode())

    # --- Client (sender) ---
    from unit_cps.reliable_udp import RUDPClient
    cli = RUDPClient(host="127.0.0.1", port=9100)
    cli.send(b"Hello from RUDP-CPS!")
================================================================================
"""

import socket
import struct
import threading
import time
from typing import Optional


# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

RUDP_MAGIC: int = 0xCAAF
RUDP_TYPE_DATA: int = 0x01
RUDP_TYPE_ACK: int = 0x02
RUDP_TYPE_FIN: int = 0x03
RUDP_TYPE_FIN_ACK: int = 0x04

RUDP_FLAG_RETRANSMIT: int = 0x01

RUDP_HEADER_SIZE: int = 12  # bytes
RUDP_MAX_PAYLOAD: int = 1400  # bytes – stays under typical MTU


# ---------------------------------------------------------------------------
# Checksum
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
# Packet build / parse
# ---------------------------------------------------------------------------

def _build_packet(
    pkt_type: int,
    seq: int,
    payload: bytes = b"",
    flags: int = 0,
) -> bytes:
    """Build a RUDP-CPS packet.

    Parameters
    ----------
    pkt_type:
        One of ``RUDP_TYPE_*`` constants.
    seq:
        Sequence number.
    payload:
        Application data (empty for ACK/FIN packets).
    flags:
        Bitfield (``RUDP_FLAG_*``).

    Returns
    -------
    bytes
        Complete RUDP-CPS packet.
    """
    length = len(payload)
    # Build header with checksum = 0
    header = struct.pack("!HBBIHH",
        RUDP_MAGIC,   # magic
        pkt_type,     # type
        flags,        # flags
        seq,          # sequence number
        length,       # payload length
        0,            # checksum placeholder
    )
    csum = _checksum(header + payload)
    # Re-pack with real checksum
    header = struct.pack("!HBBIHH",
        RUDP_MAGIC,
        pkt_type,
        flags,
        seq,
        length,
        csum,
    )
    return header + payload


def _parse_packet(data: bytes) -> Optional[dict]:
    """Parse a RUDP-CPS packet.

    Returns None if magic is wrong or checksum fails.
    """
    if len(data) < RUDP_HEADER_SIZE:
        return None

    magic, pkt_type, flags, seq, length, csum = struct.unpack(
        "!HBBIHH", data[:RUDP_HEADER_SIZE]
    )

    if magic != RUDP_MAGIC:
        return None

    payload = data[RUDP_HEADER_SIZE: RUDP_HEADER_SIZE + length]

    # Verify checksum (set checksum field to 0 before recomputing)
    header_for_check = struct.pack("!HBBIHH", magic, pkt_type, flags, seq, length, 0)
    expected = _checksum(header_for_check + payload)
    if expected != csum:
        return None  # Corrupted packet

    return {
        "type": pkt_type,
        "flags": flags,
        "seq": seq,
        "length": length,
        "payload": payload,
        "checksum": csum,
    }


# ---------------------------------------------------------------------------
# Client (sender)
# ---------------------------------------------------------------------------

class RUDPClient:
    """Reliable UDP sender.

    Parameters
    ----------
    host:
        Remote server hostname / IP.
    port:
        Remote server UDP port.
    timeout:
        Retransmit timeout in seconds.
    window_size:
        Number of in-flight (unacknowledged) segments allowed.
    max_retries:
        Maximum retransmit attempts per segment (0 = unlimited).
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 2.0,
        window_size: int = 4,
        max_retries: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.window_size = window_size
        self.max_retries = max_retries
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(timeout)

    def send(self, data: bytes) -> None:
        """Reliably send *data* to the server.

        The data is split into chunks of at most ``RUDP_MAX_PAYLOAD`` bytes.
        Each chunk is sent as a DATA segment, and the server must ACK it.
        After all data, a FIN is sent and FIN-ACK is awaited.

        Parameters
        ----------
        data:
            Application data to send.

        Raises
        ------
        ConnectionError
            If the server does not respond after *max_retries* attempts.
        """
        # Split data into segments (empty data → one empty chunk so FIN is still sent)
        chunks = (
            [data[i: i + RUDP_MAX_PAYLOAD] for i in range(0, len(data), RUDP_MAX_PAYLOAD)]
            if data else [b""]
        )

        seq = 0
        # Simple sliding-window: window_size=1 → stop-and-wait
        base = 0  # index of first unacked segment

        print(f"[RUDP] Sending {len(data)} bytes in {len(chunks)} segments "
              f"(window={self.window_size}, timeout={self.timeout}s)")

        while base < len(chunks):
            # Send window worth of segments
            window_end = min(base + self.window_size, len(chunks))
            for idx in range(base, window_end):
                chunk = chunks[idx]
                pkt = _build_packet(RUDP_TYPE_DATA, seq=idx, payload=chunk)
                self._sock.sendto(pkt, (self.host, self.port))

            # Wait for cumulative ACK
            retries = 0
            while base < window_end:
                try:
                    raw, _ = self._sock.recvfrom(RUDP_HEADER_SIZE + RUDP_MAX_PAYLOAD)
                    parsed = _parse_packet(raw)
                    if parsed and parsed["type"] == RUDP_TYPE_ACK:
                        acked_seq = parsed["seq"]
                        if acked_seq > base:
                            base = acked_seq  # cumulative ACK
                except socket.timeout:
                    retries += 1
                    if self.max_retries and retries >= self.max_retries:
                        raise ConnectionError(
                            f"[RUDP] Server not responding after {retries} retries."
                        )
                    # Retransmit unacked segments
                    print(f"[RUDP] Timeout – retransmitting from seq={base} (retry {retries})")
                    for idx in range(base, window_end):
                        chunk = chunks[idx]
                        pkt = _build_packet(
                            RUDP_TYPE_DATA, seq=idx, payload=chunk,
                            flags=RUDP_FLAG_RETRANSMIT,
                        )
                        self._sock.sendto(pkt, (self.host, self.port))

        # Send FIN and wait for FIN-ACK
        fin_pkt = _build_packet(RUDP_TYPE_FIN, seq=len(chunks))
        for attempt in range(max(1, self.max_retries)):
            self._sock.sendto(fin_pkt, (self.host, self.port))
            try:
                raw, _ = self._sock.recvfrom(RUDP_HEADER_SIZE)
                parsed = _parse_packet(raw)
                if parsed and parsed["type"] == RUDP_TYPE_FIN_ACK:
                    print("[RUDP] Transfer complete – FIN-ACK received.")
                    break
            except socket.timeout:
                print(f"[RUDP] FIN timeout (attempt {attempt + 1})")

    def close(self) -> None:
        """Close the underlying UDP socket."""
        self._sock.close()


# ---------------------------------------------------------------------------
# Server (receiver)
# ---------------------------------------------------------------------------

class RUDPServer:
    """Reliable UDP receiver.

    Parameters
    ----------
    host:
        Local bind address.
    port:
        Local UDP port to listen on.
    timeout:
        Socket receive timeout in seconds.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9100,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.settimeout(timeout)
        print(f"[RUDP] Server listening on {host}:{port}")

    def receive(self) -> bytes:
        """Block until a complete transfer is received.

        Returns
        -------
        bytes
            The reassembled application data in correct order.

        Raises
        ------
        TimeoutError
            If no complete transfer arrives within *timeout* seconds.
        """
        # Buffer: {seq: payload_bytes}
        buffer: dict = {}
        expected_seq = 0
        client_addr: Optional[tuple] = None
        fin_seq: Optional[int] = None

        while True:
            try:
                raw, addr = self._sock.recvfrom(RUDP_HEADER_SIZE + RUDP_MAX_PAYLOAD)
            except socket.timeout:
                raise TimeoutError("[RUDP] Receive timeout – no data arrived.")

            client_addr = addr
            parsed = _parse_packet(raw)
            if not parsed:
                continue  # Bad checksum or wrong magic – discard

            pkt_type = parsed["type"]

            if pkt_type == RUDP_TYPE_DATA:
                seq = parsed["seq"]
                buffer[seq] = parsed["payload"]

                # Send cumulative ACK for the highest consecutive seq received
                while expected_seq in buffer:
                    expected_seq += 1
                ack_pkt = _build_packet(RUDP_TYPE_ACK, seq=expected_seq)
                self._sock.sendto(ack_pkt, addr)

            elif pkt_type == RUDP_TYPE_FIN:
                fin_seq = parsed["seq"]
                # Reply with FIN-ACK
                fin_ack = _build_packet(RUDP_TYPE_FIN_ACK, seq=fin_seq)
                self._sock.sendto(fin_ack, addr)
                break  # Transfer complete

        # Reassemble in order
        result = b"".join(buffer[i] for i in sorted(buffer))
        print(f"[RUDP] Received {len(result)} bytes from {client_addr}.")
        return result

    def close(self) -> None:
        """Close the server socket."""
        self._sock.close()


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for the reliable UDP protocol.

    Usage:
        python -m unit_cps rudp --server [--host 0.0.0.0] [--port 9100]
        python -m unit_cps rudp --client --host 127.0.0.1 --port 9100 \\
                                          --message "Hello"
        python -m unit_cps rudp --demo   (run server+client in-process)
        python -m unit_cps rudp --design (print protocol design summary)
    """
    import argparse
    p = argparse.ArgumentParser(
        prog="unit_cps rudp",
        description="Reliable ordered UDP transfer (RUDP-CPS protocol)",
    )
    p.add_argument("--server", action="store_true", help="Start RUDP server")
    p.add_argument("--client", action="store_true", help="Send data via RUDP")
    p.add_argument("--demo", action="store_true", help="In-process sender+receiver demo")
    p.add_argument("--design", action="store_true", help="Print protocol design doc")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--message", default="Hello from RUDP-CPS!")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--window", type=int, default=4)
    p.add_argument("--retries", type=int, default=5)
    ns = p.parse_args(args)

    if ns.design:
        # Print the module docstring (contains the design doc)
        import textwrap
        print(textwrap.dedent(__doc__))
        return

    if ns.demo:
        _run_demo(ns.port, ns.window, ns.timeout)
        return

    if ns.server:
        srv = RUDPServer(host=ns.host, port=ns.port, timeout=60.0)
        try:
            data = srv.receive()
            print(f"[RUDP] Data: {data.decode(errors='replace')!r}")
        finally:
            srv.close()

    elif ns.client:
        cli_obj = RUDPClient(
            host=ns.host, port=ns.port,
            timeout=ns.timeout, window_size=ns.window, max_retries=ns.retries,
        )
        cli_obj.send(ns.message.encode())
        cli_obj.close()

    else:
        p.print_help()


def _run_demo(port: int = 9100, window: int = 4, timeout: float = 2.0) -> None:
    """Run a loopback sender/receiver demo in the same process."""
    result_holder: list = []
    error_holder: list = []

    def server_thread() -> None:
        try:
            srv = RUDPServer(host="127.0.0.1", port=port, timeout=10.0)
            data = srv.receive()
            result_holder.append(data)
            srv.close()
        except Exception as exc:
            error_holder.append(exc)

    t = threading.Thread(target=server_thread, daemon=True)
    t.start()
    time.sleep(0.2)  # Give server time to bind

    message = (
        "RUDP-CPS demo: This message is sent reliably over UDP with "
        "sequence numbers, ACKs, and automatic retransmit. " * 5
    )
    client = RUDPClient(
        host="127.0.0.1", port=port,
        timeout=timeout, window_size=window, max_retries=5,
    )
    client.send(message.encode())
    client.close()

    t.join(timeout=15)

    if error_holder:
        print(f"[RUDP Demo] Server error: {error_holder[0]}")
    elif result_holder:
        received = result_holder[0].decode(errors="replace")
        match = received == message
        print(f"\n[RUDP Demo] Sent:     {len(message)} bytes")
        print(f"[RUDP Demo] Received: {len(received)} bytes")
        print(f"[RUDP Demo] Data integrity: {'✓ PASS' if match else '✗ FAIL'}")
        print(f"[RUDP Demo] Preview: {received[:80]!r}…")
    else:
        print("[RUDP Demo] No data received (timeout?).")
