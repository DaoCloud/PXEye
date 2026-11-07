"""Native ExpectedMachine contracts, independent of product orchestration."""

import copy
import csv
import io
import ipaddress
import json
import re
from pxeye.common import digest, value_id, omit_unset_fields
from pxeye.domain.csv import convert, REQUIRED_FIELDS, OPTIONAL_FIELDS

CSV_FIELDS = list(REQUIRED_FIELDS) + [
    "dpu_policy",
    "dpf_enabled",
    "bmc_ip_address",
    "bmc_ip_allocation",
    "bmc_retain_credentials",
    "default_pause_ingestion_and_poweron",
    "fallback_dpu_serial_numbers",
    "interfaces",
    "metadata",
    "sku_id",
    "rack_id",
    "server_name",
    "host_lifecycle_profile",
    "id",
]
ROLE = ["unspecified", "host", "dpu_os", "dpu_bmc", "host_bmc"]
POLICY = ["unspecified", "dynamic", "fixed", "retained"]
BMC_POLICY = ["Unspecified", "Auto", "Dynamic", "Fixed", "Retained"]
SEGMENT_TYPE = ["TENANT", "ADMIN", "UNDERLAY", "HOST_INBAND"]


def public_machine(machine):
    return {k: copy.deepcopy(v) for k, v in machine.items() if k != "bmc_password"} | {
        "credential_present": bool(machine.get("bmc_password")),
        "revision": digest(machine),
    }


def confirms_fields(actual, expected):
    """Compare requested inventory values while allowing Core's default Host role."""
    if isinstance(expected, dict):
        if not expected:
            return True
        actual = actual or {}
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if value is None:
                continue
            other = actual.get(key)
            if key in ("mac_address", "bmc_mac_address") and isinstance(value, str):
                if str(other).lower() != value.lower():
                    return False
            elif (
                key == "role" and value in ("host", 0, 1) and other in (None, "host", "unspecified")
            ):
                continue
            elif key == "primary" and value is False and other is None:
                # Core represents a non-primary interface as None in ExpectedMachine readback.
                continue
            elif key == "bmc_retain_credentials" and value is False and other is None:
                # ExpectedMachine RPC intentionally filters Some(false) to None.
                continue
            elif key == "ip_allocation" and other in (None, "unspecified", 0):
                # Core can omit a policy and infer it from fixed_ip and the role.
                inferred = (
                    "fixed"
                    if actual.get("fixed_ip")
                    else "retained"
                    if actual.get("role") in ("host_bmc", 4)
                    else "dynamic"
                )
                requested = (
                    POLICY[value] if type(value) is int and 0 <= value < len(POLICY) else value
                )
                if requested not in ("unspecified", inferred):
                    return False
            elif key in ("bmc_ip_allocation", "dpu_policy", "role", "ip_allocation") and value in (
                "Auto",
                "Unspecified",
                "unspecified",
                0,
            ):
                # These explicitly ask Core to infer/inherit effective policy.
                continue
            elif not confirms_fields(other, value):
                return False
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        if expected and isinstance(expected[0], dict):

            def identity(row):
                return str(
                    row.get("mac_address") or row.get("physical_ifname") or row.get("key", "")
                ).lower()

            actual = sorted(actual, key=identity)
            expected = sorted(expected, key=identity)
        return all(confirms_fields(a, e) for a, e in zip(actual, expected))
    return actual == expected


def validate_machine(machine, *, draft=False):
    # Reuse the published CSV conversion contract for single-row edits too.
    unknown = set(machine) - set(REQUIRED_FIELDS) - OPTIONAL_FIELDS
    if unknown:
        raise ValueError("设备包含非官方字段。")
    machine = copy.deepcopy(machine)
    missing_credentials = (
        {k for k in ("bmc_username", "bmc_password") if not machine.get(k)} if draft else set()
    )
    for k in missing_credentials:
        machine[k] = "draft"
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(machine))
    writer.writeheader()
    row = {
        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else v
        for k, v in machine.items()
    }
    writer.writerow(row)
    stream.seek(0)
    converted = convert(stream)["expected_machines"][0]
    for k in missing_credentials:
        converted[k] = ""
    if "host_nics" in converted:
        converted["interfaces"] = converted.pop("host_nics")
    if "dpu_mode" in converted:
        converted["dpu_policy"] = converted.pop("dpu_mode")
    for k in ["bmc_ip_address"]:
        if converted.get(k):
            try:
                ipaddress.ip_address(converted[k])
            except ValueError:
                raise ValueError("BMC 地址格式无效。") from None
    seen, primaries = set(), 0
    allowed = {
        "mac_address",
        "physical_ifname",
        "logical_ifname",
        "nic_type",
        "role",
        "ip_allocation",
        "network_segment_type",
        "fixed_ip",
        "fixed_mask",
        "fixed_gateway",
        "primary",
    }
    for nic in converted.get("interfaces") or []:
        if set(nic) - allowed or not (nic.get("mac_address") or nic.get("physical_ifname")):
            raise ValueError("接口需要 MAC 或物理接口名，且只能使用官方接口字段。")
        if nic.get("mac_address"):
            mac = nic["mac_address"].replace("-", ":").lower()
            if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac) or mac in seen:
                raise ValueError("接口 MAC 无效或重复。")
            seen.add(mac)
            nic["mac_address"] = mac
        if (
            nic.get("role") is not None
            and nic["role"] not in ROLE
            and not (type(nic["role"]) is int and 0 <= nic["role"] <= 4)
        ):
            raise ValueError("接口角色无效。")
        if (
            nic.get("ip_allocation") is not None
            and nic["ip_allocation"] not in POLICY
            and not (type(nic["ip_allocation"]) is int and 0 <= nic["ip_allocation"] <= 3)
        ):
            raise ValueError("接口地址分配方式无效。")
        if nic.get("network_segment_type") is not None and not (
            type(nic["network_segment_type"]) is int and 0 <= nic["network_segment_type"] <= 3
        ):
            raise ValueError("network_segment_type 使用 0–3 的官方枚举值。")
        if "primary" in nic and nic["primary"] is not None and type(nic["primary"]) is not bool:
            raise ValueError("primary 必须为布尔值。")
        primaries += int(nic.get("primary") is True and nic.get("role", "host") in ("host", 0, 1))
        for k in ["fixed_ip", "fixed_gateway"]:
            if nic.get(k):
                try:
                    ipaddress.ip_address(nic[k])
                except ValueError:
                    raise ValueError("接口固定地址或网关格式无效。") from None
        if nic.get("fixed_mask"):
            try:
                ipaddress.IPv4Network("0.0.0.0/" + nic["fixed_mask"])
            except ValueError:
                raise ValueError("接口掩码无效。") from None
        if not draft and nic.get("ip_allocation") in ("fixed", 2) and not nic.get("fixed_ip"):
            raise ValueError("固定地址策略需要 fixed_ip。")
        if nic.get("ip_allocation") in ("dynamic", "retained", 1, 3) and nic.get("fixed_ip"):
            raise ValueError("动态策略不能包含 fixed_ip。")
    if primaries > 1:
        raise ValueError("一台主机只能声明一个主启动接口。")
    if converted.get("metadata") is not None:
        metadata = converted["metadata"]
        if set(metadata) - {"name", "description", "labels"}:
            raise ValueError("Metadata 仅支持 name、description、labels。")
    if converted.get("host_lifecycle_profile") is not None and set(
        converted["host_lifecycle_profile"]
    ) - {"disable_lockdown"}:
        raise ValueError("生命周期配置仅支持 disable_lockdown。")
    return converted


def machine_rpc(machine):
    result = copy.deepcopy(machine)
    if result.get("id"):
        result["id"] = {"value": value_id(result["id"])}
    if result.get("rack_id"):
        result["rack_id"] = {"value": value_id(result["rack_id"])}
    interfaces = result.pop("interfaces", None)
    if interfaces is not None:
        for nic in interfaces:
            for key, values in [("role", ROLE), ("ip_allocation", POLICY)]:
                if isinstance(nic.get(key), str):
                    nic[key] = values.index(nic[key])
        result["host_nics"] = interfaces
    if "dpf_enabled" in result:
        result["is_dpf_enabled"] = result.pop("dpf_enabled")
    if result.get("bmc_ip_allocation") is not None:
        result["bmc_ip_allocation"] = BMC_POLICY.index(result["bmc_ip_allocation"])
    if result.get("dpu_policy") is not None:
        policy = result.pop("dpu_policy")
        if not isinstance(policy, int):
            low = policy.lower()
            policy = (
                3
                if low in ("ignore", "nodpu", "no_dpu")
                else 2
                if low in ("nic", "useasnic", "use_as_nic", "nicmode", "nic_mode")
                else 0
                if "unspecified" in low
                else 1
            )
        result["dpu_mode"] = policy
    return omit_unset_fields(result)


def machine_from_rpc(row):
    machine = copy.deepcopy(row)
    machine["interfaces"] = machine.pop("host_nics", machine.get("interfaces", []))
    machine["id"] = value_id(machine.get("id"))
    if machine.get("rack_id"):
        machine["rack_id"] = value_id(machine["rack_id"])
    enabled = machine.pop("is_dpf_enabled", None)
    machine["dpf_enabled"] = enabled if enabled is not None else machine.get("dpf_enabled", True)
    for key in ["replace_host_nics"]:
        machine.pop(key, None)
    p = machine.pop("dpu_mode", None)
    if p is not None:
        machine["dpu_policy"] = ["unspecified", "manage", "nic", "ignore"][p]
    if isinstance(machine.get("bmc_ip_allocation"), int):
        machine["bmc_ip_allocation"] = BMC_POLICY[machine["bmc_ip_allocation"]]
    for nic in machine["interfaces"]:
        for k, vals in [("role", ROLE), ("ip_allocation", POLICY)]:
            if isinstance(nic.get(k), int):
                nic[k] = vals[nic[k]]
    return machine
