# Unit-level CPS Network Modules (`unit_cps`)

This package implements the **unit-level CPS (Cyber-Physical System)** network
functions required by the assignment.  It lives in the `unit_cps/` directory
and does **not** modify any existing exam-server/client code.

---

## Table of Contents

1. [Installation / Requirements](#installation--requirements)
2. [Permissions (macOS)](#permissions-macos)
3. [Subcommands at a Glance](#subcommands-at-a-glance)
4. [1 – ARP: Ethernet ARP frame build / send / parse](#1--arp)
5. [2 – TCP: TCP segment build / send / receive](#2--tcp)
6. [3 – ICMP Host Discovery](#3--icmp-host-discovery)
7. [4 – IP Traffic Monitoring](#4--ip-traffic-monitoring)
8. [5 – IP Packet Parsing](#5--ip-packet-parsing)
9. [6 – Network (TCP Stream) Analysis](#6--network-tcp-stream-analysis)
10. [7 – Reliable UDP Protocol (RUDP-CPS)](#7--reliable-udp-protocol-rudp-cps)

---

## Installation / Requirements

All code is **pure Python 3.10+** (uses `struct`, `socket`, `threading`,
`ipaddress` from the standard library).

No extra packages are required unless you need raw Ethernet send/capture on
**macOS** without `sudo`, in which case `scapy` can be used:

```bash
pip install scapy
```

---

## Permissions (macOS)

| Feature | Requires `sudo`? | Alternative |
|---------|-----------------|-------------|
| ARP send (raw Ethernet) | Yes (or scapy) | Inspect parsed frame without sending |
| TCP raw send/receive | Yes | Use `--server` / `--client` mode (no sudo) |
| ICMP ping | **No** – falls back to system `ping` binary | — |
| IP traffic monitor | Yes | `--parse-header` parses a hex string |
| IP parser capture | Yes | `--hex` / `--file` parse without capture |
| TCP stream analysis | Yes for live | `--demo` runs without privileges |
| RUDP demo | No | Full loopback test without sudo |

Always use the form:

```bash
sudo python -m unit_cps <subcommand> ...
```

when raw socket access is needed.

---

## Subcommands at a Glance

```
python -m unit_cps --help
python -m unit_cps arp          --help
python -m unit_cps tcp          --help
python -m unit_cps icmp         --help
python -m unit_cps ip-monitor   --help
python -m unit_cps ip-parser    --help
python -m unit_cps net-analysis --help
python -m unit_cps rudp         --help
```

---

## 1 – ARP

**File:** `unit_cps/arp.py`

### Frame Structure

| Field | Size | Value |
|-------|------|-------|
| Destination MAC | 6 B | `ff:ff:ff:ff:ff:ff` (broadcast for request) |
| Source MAC | 6 B | Sender MAC |
| EtherType | 2 B | `0x0806` |
| Hardware type | 2 B | `1` (Ethernet) |
| Protocol type | 2 B | `0x0800` (IPv4) |
| HW address length | 1 B | `6` |
| Protocol addr length | 1 B | `4` |
| Operation | 2 B | `1`=request / `2`=reply |
| Sender MAC | 6 B | |
| Sender IP | 4 B | |
| Target MAC | 6 B | `00:00:00:00:00:00` in request |
| Target IP | 4 B | IP to resolve |

### Examples

```bash
# Build and display an ARP request (no privileges needed)
python -m unit_cps arp --build \
    --sender-mac aa:bb:cc:dd:ee:ff \
    --sender-ip  192.168.1.10 \
    --target-ip  192.168.1.1

# Send the ARP request on interface en0 (needs sudo on macOS)
sudo python -m unit_cps arp --send \
    --sender-mac aa:bb:cc:dd:ee:ff \
    --sender-ip  192.168.1.10 \
    --target-ip  192.168.1.1 \
    --iface en0

# Listen for ARP packets on en0 (needs sudo)
sudo python -m unit_cps arp --listen --iface en0 --count 5
```

---

## 2 – TCP

**File:** `unit_cps/tcp.py`

### Segment Structure

| Field | Size |
|-------|------|
| Source port | 2 B |
| Destination port | 2 B |
| Sequence number | 4 B |
| Acknowledgment number | 4 B |
| Data offset + Reserved | 1 B |
| Flags (CWR ECE URG ACK PSH RST SYN FIN) | 1 B |
| Window size | 2 B |
| Checksum | 2 B |
| Urgent pointer | 2 B |
| Payload | variable |

### Examples

```bash
# Build and display a TCP SYN segment
python -m unit_cps tcp --build \
    --src-ip 10.0.0.1 --dst-ip 10.0.0.2 \
    --src-port 54321  --dst-port 80

# Start a TCP echo server on port 9000
python -m unit_cps tcp --server --port 9000

# Connect and send a message (in a second terminal)
python -m unit_cps tcp --client --host 127.0.0.1 --port 9000 \
    --message "Hello, TCP!"

# Capture raw TCP packets (needs sudo)
sudo python -m unit_cps tcp --receive --count 5 --timeout 10
```

---

## 3 – ICMP Host Discovery

**File:** `unit_cps/icmp_discovery.py`

### ICMP Echo Request Structure

| Field | Size | Value |
|-------|------|-------|
| Type | 1 B | `8` (echo request) |
| Code | 1 B | `0` |
| Checksum | 2 B | |
| Identifier | 2 B | PID (to match replies) |
| Sequence | 2 B | Increments per probe |
| Payload | variable | Optional padding |

### Examples

```bash
# Build and display an ICMP echo request packet
python -m unit_cps icmp --build --seq 1

# Ping a single host (no sudo on macOS – uses system ping as fallback)
python -m unit_cps icmp --ping 8.8.8.8

# Ping sweep a /24 subnet
python -m unit_cps icmp --sweep 192.168.1.0/24 --timeout 0.5 --workers 64

# Ping sweep a range
python -m unit_cps icmp --sweep 192.168.1.1-192.168.1.20
```

---

## 4 – IP Traffic Monitoring

**File:** `unit_cps/ip_monitor.py`

Captures raw IP packets on a network interface and maintains a rolling
**time-window packet counter per source IP**.

### Examples

```bash
# Monitor for 30 s, report every 5 s (needs sudo)
sudo python -m unit_cps ip-monitor --window 10 --duration 30

# Parse an IP header from a hex string (no sudo)
python -m unit_cps ip-monitor \
    --parse-header 4500003c1c4640004006b1e1c0a80001c0a80002
```

---

## 5 – IP Packet Parsing

**File:** `unit_cps/ip_parser.py`

### IPv4 Header Fields Parsed

| Field | Size |
|-------|------|
| Version | 4 bits |
| IHL | 4 bits |
| DSCP / ECN | 1 B |
| Total Length | 2 B |
| Identification | 2 B |
| Flags (DF, MF) | 3 bits |
| Fragment Offset | 13 bits |
| TTL | 1 B |
| Protocol | 1 B |
| Checksum | 2 B |
| Source IP | 4 B |
| Destination IP | 4 B |

### Examples

```bash
# Parse from a hex string (no sudo)
python -m unit_cps ip-parser \
    --hex 4500003c1c4640004006b1e1c0a80001c0a80002

# Parse from a file of hex strings
python -m unit_cps ip-parser --file /tmp/packets.hex

# Live capture 10 TCP packets (needs sudo)
sudo python -m unit_cps ip-parser --capture --count 10 --proto 6
```

---

## 6 – Network (TCP Stream) Analysis

**File:** `unit_cps/net_analysis.py`

Tracks per-flow: sequence numbers, acknowledgment numbers, flag changes,
window size evolution, and payload content (printable text + byte histogram).

### Examples

```bash
# Run demo with synthetic data (no sudo needed)
python -m unit_cps net-analysis --demo

# Live capture 50 TCP segments (needs sudo)
sudo python -m unit_cps net-analysis --live --count 50 --timeout 30
```

**Demo output** shows:
- 3-way handshake SYN → SYN-ACK → ACK
- Data exchange with PSH|ACK
- FIN teardown
- Payload text preview (HTTP request/response in the demo)

---

## 7 – Reliable UDP Protocol (RUDP-CPS)

**File:** `unit_cps/reliable_udp.py`

### Protocol Design Summary

**Goal:** Guarantee ordered, reliable delivery of CPS monitoring data over UDP.

**Header (12 bytes):**

| Field | Size | Description |
|-------|------|-------------|
| Magic | 2 B | `0xCAAF` – identifies RUDP-CPS packets |
| Type | 1 B | `0x01`=DATA `0x02`=ACK `0x03`=FIN `0x04`=FIN-ACK |
| Flags | 1 B | `0x01`=retransmit (diagnostic) |
| Sequence | 4 B | 32-bit segment sequence number |
| Length | 2 B | Payload length |
| Checksum | 2 B | Internet checksum of header + payload |

**Reliability mechanism:**
- Sliding window ARQ (default window = 4 segments)
- Cumulative ACKs
- Configurable retransmit timeout and max-retry count
- FIN / FIN-ACK teardown

### Examples

```bash
# In-process loopback demo (no sudo, no separate terminal)
python -m unit_cps rudp --demo

# Print the full protocol design document
python -m unit_cps rudp --design

# Start a server (Terminal 1)
python -m unit_cps rudp --server --host 0.0.0.0 --port 9100

# Send data (Terminal 2)
python -m unit_cps rudp --client --host 127.0.0.1 --port 9100 \
    --message "Sensor reading: temp=36.5C pressure=1013hPa" \
    --window 4 --timeout 2.0 --retries 5
```

---

## File Layout

```
unit_cps/
├── __init__.py          Package init + version
├── __main__.py          CLI dispatcher (python -m unit_cps)
├── arp.py               ARP frame build / send / parse
├── tcp.py               TCP segment build / send / receive
├── icmp_discovery.py    ICMP echo request/reply + ping sweep
├── ip_monitor.py        IP traffic monitoring
├── ip_parser.py         IP packet capture and parsing
├── net_analysis.py      TCP stream analysis
└── reliable_udp.py      Reliable ordered UDP (RUDP-CPS protocol)
README_unit_cps.md       This file
```
