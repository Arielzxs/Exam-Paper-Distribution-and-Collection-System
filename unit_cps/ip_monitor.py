"""
unit_cps.ip_monitor – IP traffic monitoring with time-window packet counters.

IP Header Structure (RFC 791)
================================
Offset  Field               Size   Notes
------  ----------------    -----  ----------------------------------------
0       Version + IHL       1 byte  upper 4 bits = version (4), lower 4 = IHL
1       DSCP / ECN          1 byte  (formerly TOS)
2       Total length        2 bytes
4       Identification      2 bytes
6       Flags + Fragment    2 bytes
8       TTL                 1 byte
9       Protocol            1 byte  6=TCP 17=UDP 1=ICMP
10      Header checksum     2 bytes
12      Source IP           4 bytes
16      Destination IP      4 bytes
20+     Options + Data      variable (IHL > 5)

Monitoring
===========
:class:`IPTrafficMonitor` captures raw IP packets and maintains per-source-IP
packet counters within a rolling time window.  Call :meth:`get_stats` at any
time to retrieve the counts; call :meth:`reset` to clear them.

Permissions note (macOS / Linux)
==================================
Raw IP capture requires elevated privileges (``sudo``).  The module will raise
``PermissionError`` with a descriptive hint if privileges are insufficient.

Usage example
=============
    from unit_cps.ip_monitor import IPTrafficMonitor

    mon = IPTrafficMonitor(window_seconds=10)
    mon.start(iface_ip="0.0.0.0")   # blocks; Ctrl-C to stop
    stats = mon.get_stats()
    print(stats)
"""

import socket
import struct
import sys
import threading
import time
from collections import defaultdict


# ---------------------------------------------------------------------------
# IP header parser (standalone)
# ---------------------------------------------------------------------------

def parse_ip_header(data: bytes) -> dict:
    """Parse the first 20 bytes of an IPv4 header.

    Parameters
    ----------
    data:
        Raw bytes starting at the IP header.

    Returns
    -------
    dict with keys:
        version, ihl, tos, total_length, identification, flags, fragment_offset,
        ttl, protocol, checksum, src_ip, dst_ip
    """
    if len(data) < 20:
        raise ValueError(f"Data too short for IP header: {len(data)} bytes.")

    (
        ver_ihl, tos, total_length, ident,
        flags_frag, ttl, protocol, checksum,
        src_raw, dst_raw,
    ) = struct.unpack("!BBHHHBBH4s4s", data[:20])

    version = (ver_ihl >> 4) & 0x0F
    ihl = (ver_ihl & 0x0F) * 4  # bytes
    flags = (flags_frag >> 13) & 0x07
    fragment_offset = flags_frag & 0x1FFF

    return {
        "version": version,
        "ihl": ihl,
        "tos": tos,
        "total_length": total_length,
        "identification": f"0x{ident:04X}",
        "flags": flags,
        "fragment_offset": fragment_offset,
        "ttl": ttl,
        "protocol": protocol,
        "checksum": f"0x{checksum:04X}",
        "src_ip": socket.inet_ntoa(src_raw),
        "dst_ip": socket.inet_ntoa(dst_raw),
    }


# ---------------------------------------------------------------------------
# Traffic monitor
# ---------------------------------------------------------------------------

class IPTrafficMonitor:
    """Monitor raw IP traffic and count packets per source IP in a rolling window.

    Parameters
    ----------
    window_seconds:
        Length of the time window for counting.  Packets older than this are
        expired.  Set to 0 to keep all packets (no expiry).
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        # {src_ip: [(timestamp, packet_size), ...]}
        self._records: dict = defaultdict(list)
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_packet(self, src_ip: str, pkt_size: int) -> None:
        """Record one packet from *src_ip*."""
        now = time.monotonic()
        with self._lock:
            self._records[src_ip].append((now, pkt_size))

    def _expire(self) -> None:
        """Remove entries outside the current time window."""
        if self.window_seconds <= 0:
            return
        cutoff = time.monotonic() - self.window_seconds
        with self._lock:
            for ip in list(self._records):
                self._records[ip] = [
                    (ts, sz) for ts, sz in self._records[ip] if ts >= cutoff
                ]
                if not self._records[ip]:
                    del self._records[ip]

    def _capture_loop(self, bind_ip: str) -> None:
        """Background thread: capture raw IP packets and record them."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            if sys.platform == "win32":
                sock.bind((bind_ip, 0))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                import ctypes
                sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            else:
                sock.bind((bind_ip, 0))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        except PermissionError:
            raise PermissionError(
                "IP packet capture requires elevated privileges.\n"
                "Re-run with: sudo python -m unit_cps ip-monitor ..."
            )

        sock.settimeout(1.0)
        while self._running:
            try:
                data, _ = sock.recvfrom(65535)
                hdr = parse_ip_header(data)
                self._record_packet(hdr["src_ip"], len(data))
            except socket.timeout:
                pass
            except Exception:
                pass
            self._expire()

        sock.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, bind_ip: str = "0.0.0.0", background: bool = True) -> None:
        """Start capturing.

        Parameters
        ----------
        bind_ip:
            Local IP to bind the raw socket to.  Use ``"0.0.0.0"`` to capture
            all interfaces.
        background:
            If True (default) the capture runs in a daemon thread.
            If False, the call blocks until :meth:`stop` is called from
            another thread.
        """
        self._running = True
        if background:
            self._thread = threading.Thread(
                target=self._capture_loop, args=(bind_ip,), daemon=True
            )
            self._thread.start()
            print(f"[IPMonitor] Capturing on {bind_ip} (window={self.window_seconds}s)…")
        else:
            self._capture_loop(bind_ip)

    def stop(self) -> None:
        """Stop capturing."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("[IPMonitor] Stopped.")

    def get_stats(self) -> dict:
        """Return packet count and total bytes per source IP within the window.

        Returns
        -------
        dict mapping src_ip → {"packets": int, "bytes": int}
        """
        self._expire()
        with self._lock:
            return {
                ip: {
                    "packets": len(entries),
                    "bytes": sum(sz for _, sz in entries),
                }
                for ip, entries in self._records.items()
            }

    def reset(self) -> None:
        """Clear all recorded data."""
        with self._lock:
            self._records.clear()
        print("[IPMonitor] Stats reset.")

    def print_stats(self) -> None:
        """Pretty-print the current stats table."""
        stats = self.get_stats()
        if not stats:
            print("[IPMonitor] No traffic recorded yet.")
            return
        print(f"\n{'Source IP':<20} {'Packets':>10} {'Bytes':>12}")
        print("-" * 45)
        for ip, data in sorted(stats.items(), key=lambda x: -x[1]["packets"]):
            print(f"{ip:<20} {data['packets']:>10} {data['bytes']:>12}")


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(args: list) -> None:
    """CLI entry for IP traffic monitoring.

    Usage:
        python -m unit_cps ip-monitor [--window 10] [--duration 30] [--bind 0.0.0.0]
        python -m unit_cps ip-monitor --parse-header <hex>
    """
    import argparse
    p = argparse.ArgumentParser(
        prog="unit_cps ip-monitor",
        description="Monitor IP traffic and count packets per source IP",
    )
    p.add_argument("--window", type=float, default=10.0, help="Time window in seconds")
    p.add_argument("--duration", type=float, default=30.0,
                   help="How long to capture (seconds)")
    p.add_argument("--bind", default="0.0.0.0", help="Local IP to bind")
    p.add_argument("--parse-header", metavar="HEX",
                   help="Parse an IP header from a hex string and print fields")
    ns = p.parse_args(args)

    if ns.parse_header:
        import pprint
        raw = bytes.fromhex(ns.parse_header)
        pprint.pprint(parse_ip_header(raw))
        return

    mon = IPTrafficMonitor(window_seconds=ns.window)
    mon.start(bind_ip=ns.bind, background=True)
    import time as _time
    try:
        elapsed = 0.0
        interval = 5.0
        while elapsed < ns.duration:
            _time.sleep(min(interval, ns.duration - elapsed))
            elapsed += interval
            print(f"\n[IPMonitor] Stats at t={elapsed:.0f}s:")
            mon.print_stats()
    except KeyboardInterrupt:
        pass
    mon.stop()
    print("\n[IPMonitor] Final stats:")
    mon.print_stats()
