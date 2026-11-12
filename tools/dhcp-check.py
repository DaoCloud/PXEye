#!/usr/bin/env python3
"""Discover DHCPv4 servers on a Linux interface without configuring that interface."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time

COOKIE = bytes.fromhex("63825363")


def mac_address(value):
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
        raise argparse.ArgumentTypeError("Expected a MAC such as 02:00:00:00:00:01")
    mac = bytes.fromhex(value.replace(":", ""))
    if mac[0] & 1 or mac == bytes(6):
        raise argparse.ArgumentTypeError("Expected a nonzero unicast MAC")
    return mac


def ipv4(value):
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def subnet(value):
    try:
        return ipaddress.IPv4Network(value, strict=False)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def discover_frame(source_mac, client_mac, xid, elapsed=0):
    bootp = struct.pack(
        "!BBBB4sHH4s4s4s4s16s64s128s",
        1, 1, 6, 0, xid, min(elapsed, 65535), 0x8000,
        bytes(4), bytes(4), bytes(4), bytes(4),
        client_mac.ljust(16, b"\0"), bytes(64), bytes(128),
    )
    options = (
        COOKIE + b"\x35\x01\x01\x3d\x07\x01" + client_mac
        + b"\x37\x09\x01\x03\x06\x1a\x2a\x33\x36\x42\x43\xff"
    )
    payload = (bootp + options).ljust(300, b"\0")
    udp = struct.pack("!HHHH", 68, 67, 8 + len(payload), 0) + payload
    ip = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), int.from_bytes(xid[:2], "big"),
        0, 64, 17, 0, bytes(4), b"\xff" * 4,
    )
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    return b"\xff" * 6 + source_mac + b"\x08\x00" + ip + udp


def parse_options(data):
    options, offset = {}, 0
    while offset < len(data):
        code = data[offset]
        offset += 1
        if code == 255:
            break
        if code == 0:
            continue
        if offset >= len(data):
            raise ValueError("Truncated DHCP option length")
        length = data[offset]
        offset += 1
        if offset + length > len(data):
            raise ValueError("Truncated DHCP option value")
        options[code] = options.get(code, b"") + data[offset:offset + length]
        offset += length
    return options


def addresses(options, code):
    value = options.get(code, b"")
    if len(value) % 4:
        raise ValueError("Invalid DHCP IPv4 option")
    return [socket.inet_ntoa(value[i:i + 4]) for i in range(0, len(value), 4)]


def text_option(value):
    # Keep untrusted option text on one printable line.
    return "".join(c if c.isprintable() else "?" for c in value.rstrip(b"\0").decode(
        "utf-8", errors="replace"
    ))


def parse_offer(frame, xid, client_mac):
    if len(frame) < 14:
        return None
    offset, kind = 14, int.from_bytes(frame[12:14], "big")
    while kind in (0x8100, 0x88A8):
        if len(frame) < offset + 4:
            return None
        kind = int.from_bytes(frame[offset + 2:offset + 4], "big")
        offset += 4
    if kind != 0x0800 or len(frame) < offset + 20:
        return None
    ip = frame[offset:]
    ihl, total = (ip[0] & 15) * 4, int.from_bytes(ip[2:4], "big")
    if ip[0] >> 4 != 4 or ihl < 20 or total < ihl + 8 or len(ip) < total:
        return None
    if ip[9] != 17 or int.from_bytes(ip[6:8], "big") & 0x3FFF:
        return None
    udp = ip[ihl:total]
    src, dst, size, _ = struct.unpack("!HHHH", udp[:8])
    if (src, dst) != (67, 68) or size < 248 or size > len(udp):
        return None
    packet = udp[8:size]
    if (packet[:3] != b"\x02\x01\x06" or packet[4:8] != xid
            or packet[28:34] != client_mac or packet[236:240] != COOKIE):
        return None
    try:
        options = parse_options(packet[240:])
        overload = options.get(52, b"\0")
        if len(overload) != 1 or overload[0] > 3:
            return None
        for bit, data in ((1, packet[108:236]), (2, packet[44:108])):
            if overload[0] & bit:
                for code, value in parse_options(data).items():
                    options[code] = options.get(code, b"") + value
        if options.get(53) != b"\x02" or len(options.get(54, b"")) != 4:
            return None
        offer = {
            "source_ip": socket.inet_ntoa(ip[12:16]),
            "server_identifier": socket.inet_ntoa(options[54]),
            "offered_ip": socket.inet_ntoa(packet[16:20]),
            "subnet_masks": addresses(options, 1),
            "gateways": addresses(options, 3),
            "dns_servers": addresses(options, 6),
            "ntp_servers": addresses(options, 42),
            "next_server": socket.inet_ntoa(packet[20:24]),
            "boot_server": text_option(options.get(66, b"")),
            "boot_file": text_option(options.get(
                67, b"" if overload[0] & 1 else packet[108:236]
            )),
        }
        offered = ipaddress.IPv4Address(offer["offered_ip"])
        if offered.is_unspecified or offered.is_multicast or str(offered) == "255.255.255.255":
            return None
        return offer
    except (ValueError, OSError):
        return None


def arguments():
    parser = argparse.ArgumentParser(
        description="Linux DHCPv4 Discover/Offer check; never requests a lease or changes IP/routes."
    )
    parser.add_argument("-i", "--interface", required=True, help="Client interface on the target VLAN")
    parser.add_argument("--mac", type=mac_address, help="BOOTP client MAC; default: interface MAC")
    parser.add_argument("--timeout", type=int, default=15, help="Total wait in seconds (1–120)")
    parser.add_argument("--attempts", type=int, default=3, help="Discover transmissions (1–5)")
    parser.add_argument("--server", type=ipv4, help="Expected DHCP Server Identifier (option 54)")
    parser.add_argument("--subnet", type=subnet, help="Expected offered IPv4 subnet, e.g. 192.0.2.0/24")
    parser.add_argument("--report", type=Path, help="Write a JSON result to this file")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120 or not 1 <= args.attempts <= 5:
        parser.error("timeout must be 1–120 and attempts must be 1–5")
    return args


def probe(args):
    if args.report and (args.report.exists() or args.report.is_symlink() or not args.report.parent.is_dir()):
        raise ValueError("Report must be a new file in an existing directory")
    if not sys.platform.startswith("linux") or not hasattr(socket, "AF_PACKET"):
        raise ValueError("Requires Linux and raw packet access (run as root)")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", args.interface):
        raise ValueError("Invalid Linux interface name")
    socket.if_nametoindex(args.interface)
    net = Path("/sys/class/net") / args.interface
    if int((net / "type").read_text()) != 1:
        raise ValueError("Requires an Ethernet interface or VLAN interface")
    if not int((net / "flags").read_text().strip(), 16) & 1:
        raise ValueError("Interface is down; this tool will not bring it up")
    source_mac = mac_address((net / "address").read_text().strip())
    client_mac, xid = args.mac or source_mac, os.urandom(4)
    result = {
        "schema": 1, "mode": "discover-only", "interface": args.interface,
        "client_mac": client_mac.hex(":"), "transaction_id": xid.hex(),
        "expected_server": args.server, "expected_subnet": str(args.subnet) if args.subnet else None,
        "offers": [], "sent": 0,
    }
    print(f"DHCP_CHECK interface={args.interface} MAC={client_mac.hex(':')} "
          f"timeout={args.timeout}s attempts={args.attempts}", flush=True)
    if client_mac != source_mac:
        print("NOTE custom client MAC differs from Ethernet MAC; DHCP snooping may reject it.")
    start = time.monotonic()
    deadline, interval = start + args.timeout, args.timeout / args.attempts
    seen = set()
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as sock:
        sock.bind((args.interface, 0))
        while time.monotonic() < deadline:
            now = time.monotonic()
            if result["sent"] < args.attempts and now >= start + result["sent"] * interval:
                sock.send(discover_frame(source_mac, client_mac, xid, int(now - start)))
                result["sent"] += 1
                print(f"SEND Discover {result['sent']}/{args.attempts}", flush=True)
            wake = deadline
            if result["sent"] < args.attempts:
                wake = min(wake, start + result["sent"] * interval)
            sock.settimeout(max(0.001, wake - time.monotonic()))
            try:
                frame = sock.recv(65535)
            except socket.timeout:
                continue
            offer = parse_offer(frame, xid, client_mac)
            if not offer:
                continue
            key = (offer["server_identifier"], offer["offered_ip"])
            if key in seen:
                continue
            seen.add(key)
            reasons = []
            if args.server and offer["server_identifier"] != args.server:
                reasons.append("Server Identifier differs from expected server")
            if args.subnet and ipaddress.IPv4Address(offer["offered_ip"]) not in args.subnet:
                reasons.append("Offered address is outside expected subnet")
            offer.update(matches_expectations=not reasons, mismatch_reasons=reasons)
            result["offers"].append(offer)
            print("OFFER " + json.dumps(offer, ensure_ascii=False), flush=True)
    matched = sum(o["matches_expectations"] for o in result["offers"])
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    result["status"] = "pass" if matched else "mismatch" if result["offers"] else "no_offer"
    result["exit_code"] = {"pass": 0, "no_offer": 1, "mismatch": 3}[result["status"]]
    print(f"RESULT {result['status']} offers={len(result['offers'])} matched={matched}")
    if len({o["server_identifier"] for o in result["offers"]}) > 1:
        print("NOTE multiple DHCP servers replied; check whether all are intended.")
    if not args.server and result["offers"]:
        print("NOTE received an Offer; NICo identity is unverified without an expected --server.")
    if not result["offers"]:
        print("CHECK VLAN/Relay/UDP ingress and return path, then NICo subnet/pool/MAC policy; "
              "no Offer does not prove the server is down.")
    print("LIMIT Discover/Offer only; full DORA and boot/DNS/NTP reachability remain untested.")
    return result


def main():
    args = arguments()
    try:
        result = probe(args)
    except (OSError, ValueError, argparse.ArgumentTypeError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        result = {"schema": 1, "status": "error", "exit_code": 2, "error": str(error)}
    except KeyboardInterrupt:
        print("INTERRUPTED; no IP or route configuration was changed", file=sys.stderr)
        return 130
    if args.report:
        try:
            # Never silently replace evidence from an earlier run.
            with args.report.open("x") as report:
                json.dump(result, report, ensure_ascii=False, indent=2)
                report.write("\n")
            print(f"REPORT {args.report}")
        except OSError as error:
            print(f"ERROR saving report: {error}", file=sys.stderr)
            return 2
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
