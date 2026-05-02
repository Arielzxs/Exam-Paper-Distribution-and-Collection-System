"""
unit_cps – Unit-level CPS (Cyber-Physical System) network modules.

Sub-modules:
    arp              – ARP frame build / send / parse
    tcp              – TCP segment build / send / receive (raw sockets)
    icmp_discovery   – ICMP-based active-host discovery (ping sweep)
    ip_monitor       – IP traffic monitoring with time-window counters
    ip_parser        – IP packet capture and header / payload parsing
    net_analysis     – TCP stream analysis (seq/ack/flags/window/payload)
    reliable_udp     – Reliable ordered-delivery protocol over UDP

Run via CLI:
    python -m unit_cps --help
"""

__version__ = "1.0.0"
