"""
unit_cps.net_analysis – TCP stream analysis.

Analyses TCP segments captured from the network and tracks:
  • Sequence numbers and acknowledgment numbers
  • All six (well, eight) control flag changes:
      FIN SYN RST PSH ACK URG ECE CWR
  • Window size changes per flow
  • Payload content summary (printable text extraction + byte histogram)

TCP Segment quick reference
============================
  seq       – byte number of the first byte in this segment's payload
  ack       – next expected byte from the remote side (when ACK flag is set)
  flags     – 8-bit field: CWR ECE URG ACK PSH RST SYN FIN
  window    – receiver's available buffer space (flow control)

Flow key convention: (src_ip, src_port, dst_ip, dst_port) – or the canonical
sorted pair for bidirectional tracking.

Permissions note (macOS / Linux)
==================================
Live capture via raw socket requires ``sudo``.  You can also feed pre-built
:class:`SegmentInfo` objects (e.g. from a pcap library) without any privileges.

Usage example
=============
    from unit_cps.net_analysis import TCPStreamAnalyzer, SegmentInfo

    analyzer = TCPStreamAnalyzer()
    analyzer.start_live_capture(count=50, timeout=30)
    analyzer.print_report()
"""

import socket
import struct
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SegmentInfo:
    """Parsed information from a single TCP segment.

    Attributes
    ----------
    timestamp:
        Capture time (``time.time()``).
    src_ip, dst_ip:
        Source and destination IPv4 addresses.
    src_port, dst_port:
        TCP ports.
    seq:
        TCP sequence number.
    ack:
        TCP acknowledgment number.
    flags_byte:
        Raw flags byte (use :func:`flags_dict` to decode).
    window:
        TCP window size.
    payload:
        Raw payload bytes.
    """
    timestamp: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    seq: int
    ack: int
    flags_byte: int
    window: int
    payload: bytes = field(default_factory=bytes)

    @property
    def flags_dict(self) -> dict:
        """Decode the flags byte into a dict of flag-name → bool."""
        return {
            "CWR": bool(self.flags_byte & 0x80),
            "ECE": bool(self.flags_byte & 0x40),
            "URG": bool(self.flags_byte & 0x20),
            "ACK": bool(self.flags_byte & 0x10),
            "PSH": bool(self.flags_byte & 0x08),
            "RST": bool(self.flags_byte & 0x04),
            "SYN": bool(self.flags_byte & 0x02),
            "FIN": bool(self.flags_byte & 0x01),
        }

    @property
    def active_flags(self) -> list:
        """Return list of set flag names, e.g. ``['SYN']``."""
        return [name for name, val in self.flags_dict.items() if val]

    @property
    def flow_key(self) -> tuple:
        """Canonical bidirectional flow identifier."""
        ep1 = (self.src_ip, self.src_port)
        ep2 = (self.dst_ip, self.dst_port)
        if ep1 <= ep2:
            return (*ep1, *ep2)
        return (*ep2, *ep1)


# ---------------------------------------------------------------------------
# Stream state tracker
# ---------------------------------------------------------------------------

@dataclass
class FlowState:
    """Track the state of a single TCP flow."""
    flow_key: tuple
    segments: List[SegmentInfo] = field(default_factory=list)

    def add(self, seg: SegmentInfo) -> None:
        self.segments.append(seg)

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    def seq_ack_progression(self) -> list:
        """Return list of (timestamp, src_ip:src_port, seq, ack, flags) tuples."""
        return [
            (
                s.timestamp,
                f"{s.src_ip}:{s.src_port}",
                s.seq,
                s.ack,
                s.active_flags,
            )
            for s in self.segments
        ]

    def window_changes(self) -> list:
        """Return (timestamp, direction, window) for every window-size change."""
        result = []
        last: dict = {}
        for s in self.segments:
            direction = f"{s.src_ip}:{s.src_port}"
            if last.get(direction) != s.window:
                result.append((s.timestamp, direction, s.window))
                last[direction] = s.window
        return result

    def payload_summary(self) -> dict:
        """Summarise all payloads in this flow.

        Returns
        -------
        dict with keys:
            total_bytes, segments_with_data,
            printable_text (first 256 printable chars),
            byte_histogram (most common 10 byte values)
        """
        all_data = b"".join(s.payload for s in self.segments)
        printable = "".join(chr(b) for b in all_data if 32 <= b < 127)

        # Byte histogram (top-10 most frequent bytes)
        if all_data:
            from collections import Counter
            hist = Counter(all_data)
            histogram = {
                f"0x{k:02X} ({chr(k) if 32 <= k < 127 else '?'})": v
                for k, v in hist.most_common(10)
            }
        else:
            histogram = {}

        return {
            "total_bytes": len(all_data),
            "segments_with_data": sum(1 for s in self.segments if s.payload),
            "printable_text": printable[:256] + ("…" if len(printable) > 256 else ""),
            "byte_histogram": histogram,
        }


# ---------------------------------------------------------------------------
# Raw packet parsing helpers
# ---------------------------------------------------------------------------

def _parse_raw_ip_tcp(data: bytes) -> Optional[SegmentInfo]:
    """Parse a raw IP+TCP packet into a :class:`SegmentInfo`.

    Returns None if the packet is not TCP or is malformed.
    """
    if len(data) < 40:
        return None

    # IP header
    ver_ihl = data[0]
    ihl = (ver_ihl & 0x0F) * 4
    protocol = data[9]
    if protocol != 6:  # TCP only
        return None
    src_ip = socket.inet_ntoa(data[12:16])
    dst_ip = socket.inet_ntoa(data[16:20])

    tcp = data[ihl:]
    if len(tcp) < 20:
        return None

    (
        src_port, dst_port, seq, ack,
        data_offset_byte, flags_byte, window, _checksum, _urgent,
    ) = struct.unpack("!HHIIBBHHH", tcp[:20])

    tcp_header_len = (data_offset_byte >> 4) * 4
    payload = tcp[tcp_header_len:]

    return SegmentInfo(
        timestamp=time.time(),
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        seq=seq,
        ack=ack,
        flags_byte=flags_byte,
        window=window,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class TCPStreamAnalyzer:
    """Capture TCP segments and analyse flows.

    Methods
    -------
    feed(seg)
        Feed a :class:`SegmentInfo` directly (no live capture).
    start_live_capture(count, timeout)
        Capture from the network (requires ``sudo``).
    get_flow(flow_key)
        Return :class:`FlowState` for a specific flow.
    all_flows()
        Return dict of all flows.
    print_report()
        Print a human-readable analysis to stdout.
    """

    def __init__(self) -> None:
        # {flow_key: FlowState}
        self._flows: dict = defaultdict(lambda: FlowState(flow_key=()))

    def feed(self, seg: SegmentInfo) -> None:
        """Add a segment to the appropriate flow."""
        key = seg.flow_key
        if key not in self._flows:
            self._flows[key] = FlowState(flow_key=key)
        self._flows[key].add(seg)

    def start_live_capture(
        self,
        bind_ip: str = "0.0.0.0",
        count: int = 50,
        timeout: float = 30.0,
    ) -> None:
        """Capture *count* TCP packets from the network.

        Raises
        ------
        PermissionError
            If raw-socket access is denied.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
            sock.bind((bind_ip, 0))
        except PermissionError:
            raise PermissionError(
                "Live capture requires elevated privileges.\n"
                "Re-run with: sudo python -m unit_cps net-analysis ...\n"
                "Or use --demo to run with synthetic data."
            )

        sock.settimeout(1.0)
        captured = 0
        deadline = time.monotonic() + timeout
        print(f"[NetAnalysis] Capturing up to {count} TCP packets…")

        try:
            while captured < count and time.monotonic() < deadline:
                try:
                    data, _ = sock.recvfrom(65535)
                    seg = _parse_raw_ip_tcp(data)
                    if seg:
                        self.feed(seg)
                        captured += 1
                except socket.timeout:
                    pass
        finally:
            sock.close()

        print(f"[NetAnalysis] Captured {captured} TCP segments in {len(self._flows)} flows.")

    def get_flow(self, flow_key: tuple) -> Optional[FlowState]:
        return self._flows.get(flow_key)

    def all_flows(self) -> dict:
        return dict(self._flows)

    def print_report(self) -> None:
        """Print a structured analysis report to stdout."""
        if not self._flows:
            print("[NetAnalysis] No flows recorded.")
            return

        print(f"\n{'='*60}")
        print(f"  TCP Stream Analysis Report  ({len(self._flows)} flows)")
        print(f"{'='*60}")

        for fk, flow in sorted(self._flows.items()):
            ip1, p1, ip2, p2 = fk
            print(f"\nFlow: {ip1}:{p1}  ↔  {ip2}:{p2}  ({len(flow.segments)} segments)")
            print("-" * 50)

            # Seq/Ack progression (first 5 entries)
            prog = flow.seq_ack_progression()
            print("  Seq/Ack progression (first 5):")
            for ts, ep, seq, ack, flags in prog[:5]:
                flag_str = "|".join(flags) if flags else "—"
                print(f"    {ep:<22}  seq={seq:<12} ack={ack:<12} flags=[{flag_str}]")
            if len(prog) > 5:
                print(f"    … ({len(prog) - 5} more)")

            # Window changes
            wchg = flow.window_changes()
            if wchg:
                print("  Window changes:")
                for ts, ep, win in wchg[:5]:
                    print(f"    {ep:<22}  window={win}")
                if len(wchg) > 5:
                    print(f"    … ({len(wchg) - 5} more)")

            # Payload summary
            ps = flow.payload_summary()
            print(f"  Payload: {ps['total_bytes']} bytes across "
                  f"{ps['segments_with_data']} segments")
            if ps["printable_text"]:
                preview = ps["printable_text"][:80].replace("\n", "\\n")
                print(f"  Text preview: {preview!r}")
            if ps["byte_histogram"]:
                print("  Top bytes:", ps["byte_histogram"])


# ---------------------------------------------------------------------------
# Demo helper
# ---------------------------------------------------------------------------

def _make_demo_segments() -> list:
    """Create synthetic TCP segments for demonstration without live capture."""
    from unit_cps.tcp import TCP_FLAG_SYN, TCP_FLAG_ACK, TCP_FLAG_PSH, TCP_FLAG_FIN

    segs = []
    # 3-way handshake
    segs.append(SegmentInfo(
        timestamp=time.time(), src_ip="10.0.0.1", dst_ip="10.0.0.2",
        src_port=54321, dst_port=80, seq=1000, ack=0,
        flags_byte=TCP_FLAG_SYN, window=65535, payload=b"",
    ))
    segs.append(SegmentInfo(
        timestamp=time.time() + 0.001, src_ip="10.0.0.2", dst_ip="10.0.0.1",
        src_port=80, dst_port=54321, seq=5000, ack=1001,
        flags_byte=TCP_FLAG_SYN | TCP_FLAG_ACK, window=32768, payload=b"",
    ))
    segs.append(SegmentInfo(
        timestamp=time.time() + 0.002, src_ip="10.0.0.1", dst_ip="10.0.0.2",
        src_port=54321, dst_port=80, seq=1001, ack=5001,
        flags_byte=TCP_FLAG_ACK, window=65535, payload=b"",
    ))
    # Data transfer
    payload = b"GET / HTTP/1.1\r\nHost: 10.0.0.2\r\n\r\n"
    segs.append(SegmentInfo(
        timestamp=time.time() + 0.003, src_ip="10.0.0.1", dst_ip="10.0.0.2",
        src_port=54321, dst_port=80, seq=1001, ack=5001,
        flags_byte=TCP_FLAG_PSH | TCP_FLAG_ACK, window=65535, payload=payload,
    ))
    segs.append(SegmentInfo(
        timestamp=time.time() + 0.010, src_ip="10.0.0.2", dst_ip="10.0.0.1",
        src_port=80, dst_port=54321, seq=5001, ack=1001 + len(payload),
        flags_byte=TCP_FLAG_PSH | TCP_FLAG_ACK, window=32768,
        payload=b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!",
    ))
    # FIN
    segs.append(SegmentInfo(
        timestamp=time.time() + 0.011, src_ip="10.0.0.1", dst_ip="10.0.0.2",
        src_port=54321, dst_port=80, seq=1001 + len(payload), ack=5001 + 51,
        flags_byte=TCP_FLAG_FIN | TCP_FLAG_ACK, window=65535, payload=b"",
    ))
    return segs


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for TCP stream analysis.

    Usage:
        python -m unit_cps net-analysis --live [--count 50] [--timeout 30]
        python -m unit_cps net-analysis --demo
    """
    import argparse
    p = argparse.ArgumentParser(
        prog="unit_cps net-analysis",
        description="Analyse TCP stream seq/ack/flags/window/payload",
    )
    p.add_argument("--live", action="store_true", help="Capture from network (needs sudo)")
    p.add_argument("--demo", action="store_true", help="Run with synthetic demo data")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--bind", default="0.0.0.0")
    ns = p.parse_args(args)

    analyzer = TCPStreamAnalyzer()

    if ns.demo:
        for seg in _make_demo_segments():
            analyzer.feed(seg)
        analyzer.print_report()
    elif ns.live:
        analyzer.start_live_capture(bind_ip=ns.bind, count=ns.count, timeout=ns.timeout)
        analyzer.print_report()
    else:
        p.print_help()
