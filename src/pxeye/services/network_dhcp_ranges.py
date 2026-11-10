"""NICo-owned DHCP ranges; PXEye validates inputs and verifies native readback."""

import ipaddress

from pxeye.clients.errors import RPCMethodUnavailableError
from pxeye.common import value_id


def validate_range(prefix, gateway, start, end):
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("DHCP 起止地址必须为 IPv4 地址。")
    start, end = start.strip(), end.strip()
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError("请同时填写 DHCP 起始地址和结束地址，或同时留空。")
    try:
        network = ipaddress.IPv4Network(prefix, strict=True)
        first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
        route = ipaddress.IPv4Address(gateway) if gateway else None
    except (ValueError, TypeError):
        raise ValueError("DHCP 范围仅支持 IPv4 子网及 IPv4 起止地址。") from None
    if first > last:
        raise ValueError("DHCP 起始地址不能大于结束地址。")
    if first not in network or last not in network:
        raise ValueError("DHCP 起止地址必须属于当前子网。")
    if first == network.network_address or last == network.broadcast_address:
        raise ValueError("DHCP 范围不能包含网络地址或广播地址。")
    if route is not None and first <= route <= last:
        raise ValueError("DHCP 范围不能包含网关地址。")
    return {"start": str(first), "end": str(last)}


def read_ranges(adapter, ids):
    try:
        rows = adapter.rpc("FindNetworkSegmentDhcpRanges", {"network_segments_ids": ids}).get(
            "ranges", []
        )
    except RPCMethodUnavailableError:
        return False, {}
    return True, {value_id(row["segmentId"]): row for row in rows}


def require_support(adapter):
    supported, _ = read_ranges(adapter, [])
    if not supported:
        raise ValueError("当前 NICo Core 不支持 DHCP 地址池范围，请先升级 Core；未创建子网。")


def verify_range(adapter, sid, expected, *, revision=None):
    supported, rows = read_ranges(adapter, [{"value": sid}])
    row = rows.get(sid)
    if (
        not supported
        or not row
        or row.get("range") != expected
        or revision is not None
        and str(row.get("revision", "0")) != str(revision)
    ):
        raise RuntimeError("DHCP 地址池读回不匹配，请刷新核对 NICo 当前配置；不要重复提交。")
    return row


def save_range(resources, body):
    if set(body) != {"id", "revision", "start", "end"}:
        raise ValueError("DHCP 地址池配置字段无效。")
    sid = body["id"]
    live = next((row for row in resources.networks() if row["id"] == sid), None)
    if (
        not live
        or live["name"] == "static-assignments"
        or live["segment_type"] not in ("HOST_INBAND", "ADMIN", "UNDERLAY")
    ):
        raise ValueError("请选择活动的站点子网。")
    prefixes = [p for p in live["prefixes"] if ipaddress.ip_network(p["prefix"]).version == 4]
    if len(prefixes) != 1:
        raise ValueError("DHCP 地址池要求子网只有一个 IPv4 前缀。")
    prefix = prefixes[0]
    expected = validate_range(prefix["prefix"], prefix.get("gateway"), body["start"], body["end"])
    revision = body["revision"]
    if not isinstance(revision, str) or not revision.isascii() or not revision.isdecimal():
        raise ValueError("DHCP 地址池版本无效，请刷新。")
    if not 0 <= int(revision) < 2**63 - 1:
        raise ValueError("DHCP 地址池版本超出范围，请刷新。")
    supported, rows = read_ranges(resources.adapter, [{"value": sid}])
    if not supported:
        raise ValueError("当前 NICo Core 不支持 DHCP 地址池范围，请先升级 Core。")
    if str(rows.get(sid, {}).get("revision", "0")) != revision:
        raise ValueError("DHCP 地址池已变化，请刷新后重新配置。")
    request = {"segment_id": {"value": sid}, "if_revision": revision}
    if expected is not None:
        request["range"] = expected
    # Do not retry a write with an unknown outcome. A refresh reads NICo's policy.
    result = resources.adapter.rpc("SetNetworkSegmentDhcpRange", request)
    if value_id(result.get("segmentId")) != sid or result.get("range") != expected:
        raise RuntimeError("DHCP 地址池写入回执不匹配，请刷新核对。")
    observed = verify_range(resources.adapter, sid, expected, revision=int(revision) + 1)
    resources.invalidate()
    return {"status": "applied", "range": observed.get("range"), "revision": observed["revision"]}
