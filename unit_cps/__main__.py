"""
unit_cps – CLI entry point.

Run with:
    python -m unit_cps <subcommand> [options]

Available subcommands
---------------------
  arp           ARP frame build / send / parse
  tcp           TCP segment build / send / receive
  icmp          ICMP echo-based host discovery (ping sweep)
  ip-monitor    IP traffic monitoring (packet count per source IP)
  ip-parser     IP packet capture and header parsing
  net-analysis  TCP stream analysis (seq/ack/flags/window/payload)
  rudp          Reliable ordered UDP transfer (RUDP-CPS protocol)

Examples
--------
  python -m unit_cps arp --build --sender-mac aa:bb:cc:dd:ee:ff \\
         --sender-ip 192.168.1.10 --target-ip 192.168.1.1

  python -m unit_cps icmp --ping 8.8.8.8

  python -m unit_cps icmp --sweep 192.168.1.0/24 --timeout 0.5

  python -m unit_cps tcp --build --src-ip 10.0.0.1 --dst-ip 10.0.0.2 \\
         --src-port 54321 --dst-port 80

  python -m unit_cps ip-monitor --window 10 --duration 30   # needs sudo

  python -m unit_cps ip-parser --hex 45000028...            # parse hex dump

  python -m unit_cps net-analysis --demo

  python -m unit_cps rudp --demo

  python -m unit_cps rudp --design
"""

import sys


_SUBCOMMANDS = {
    "arp": "unit_cps.arp",
    "tcp": "unit_cps.tcp",
    "icmp": "unit_cps.icmp_discovery",
    "ip-monitor": "unit_cps.ip_monitor",
    "ip-parser": "unit_cps.ip_parser",
    "net-analysis": "unit_cps.net_analysis",
    "rudp": "unit_cps.reliable_udp",
}


def _usage() -> None:
    print(__doc__)


def main(argv: list | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _usage()
        return 0

    subcommand = argv[0]
    sub_args = argv[1:]

    if subcommand not in _SUBCOMMANDS:
        print(f"[unit_cps] Unknown subcommand: {subcommand!r}", file=sys.stderr)
        print(f"Available: {', '.join(_SUBCOMMANDS)}", file=sys.stderr)
        return 1

    module_name = _SUBCOMMANDS[subcommand]
    try:
        import importlib
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"[unit_cps] Could not import {module_name}: {exc}", file=sys.stderr)
        return 1

    try:
        mod.cli(sub_args)
    except PermissionError as exc:
        print(f"\n[unit_cps] Permission denied:\n  {exc}", file=sys.stderr)
        print("  Hint: Re-run with sudo, e.g.:", file=sys.stderr)
        print(f"    sudo python -m unit_cps {subcommand} {' '.join(sub_args)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[unit_cps] Interrupted.")
        return 0
    except Exception as exc:
        print(f"[unit_cps] Error in {subcommand}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
