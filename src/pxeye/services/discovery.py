"""Observed DHCP endpoints and read-only identity verification before declaration."""

import ipaddress
import json
import re
import time
import uuid

from pxeye.common import atomic_json, digest, value_id
from pxeye.services.device_identity import (
    classify_device,
    field,
    text,
    read_device_identity,
)


def report_identity(endpoint, mac):
    report = (endpoint or {}).get("report") or {}
    if str(report.get("endpointType", report.get("endpoint_type", ""))).lower() != "bmc":
        return {}
    manager_macs = {
        text(nic, "MACAddress").lower()
        for manager in report.get("managers", [])
        for nic in field(manager, "EthernetInterfaces") or []
    }
    if mac.lower() not in manager_macs:
        return {"note": "请登录 BMC / PMC 读取设备信息。"}
    try:
        result = classify_device(report.get("chassis", []), report.get("systems", []))
    except ValueError:
        return {"note": "请登录 BMC / PMC 读取设备信息。"}
    return result | {"note": "请验证 BMC / PMC 账号后加入清单。"}


class Discovery:
    def __init__(self, adapter, resources, onboarding):
        self.adapter, self.resources, self.onboarding = adapter, resources, onboarding
        self.directory = adapter.data / "config" / "discovery"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def candidates(self):
        networks = self.resources.networks()
        allowed = {
            n["id"]: n
            for n in networks
            if n["segment_type"] == "UNDERLAY" and n["name"] != "static-assignments"
        }
        links = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        ids = self.adapter.rpc("FindExploredEndpointIds", {}).get("endpointIds", [])
        endpoints = (
            self.adapter.rpc("FindExploredEndpointsByIds", {"endpoint_ids": ids}).get(
                "endpoints", []
            )
            if ids
            else []
        )
        expected = self.resources.planned_inventory()
        # An undeclared BMC's first DHCP lease is typed Data by Core. Admit
        # anonymous Underlay endpoints for authentication, excluding known
        # non-host endpoints even before their interfaces have an owner.
        excluded_macs = {
            nic.get("mac_address", "").lower()
            for machine in expected
            for nic in machine.get("interfaces", [])
            if nic.get("role") != "host_bmc"
        }
        switches = self.adapter.rpc("GetAllExpectedSwitches", {}).get("expectedSwitches", [])
        shelves = self.adapter.rpc("GetAllExpectedPowerShelves", {}).get("expectedPowerShelves", [])
        excluded_macs.update(
            device.get("bmcMacAddress", "").lower() for device in switches + shelves
        )
        excluded_macs.update(
            nic.get("macAddress", "").lower()
            for switch in switches
            for nic in switch.get("nvosInterfaces", [])
        )
        rows = []
        for link in links:
            segment = allowed.get(value_id(link.get("segmentId")))
            if not segment or any(
                link.get(key)
                for key in ("machineId", "attachedDpuMachineId", "switchId", "powerShelfId")
            ):
                continue
            if link.get("interfaceType") not in (
                None,
                0,
                1,
                "DATA",
                "INTERFACE_TYPE_DATA",
                "BMC",
                "INTERFACE_TYPE_BMC",
                "UNKNOWN",
                "UNSPECIFIED",
            ):
                continue
            mac = link.get("macAddress", "").lower()
            if mac in excluded_macs or not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
                continue
            existing = next((r for r in expected if r["bmc_mac_address"].lower() == mac), None)
            for address in link.get("address", []):
                ip = ipaddress.ip_address(address)
                if ip.version != 4:
                    continue
                endpoint = next((e for e in endpoints if e["address"] == address), None)
                if endpoint and endpoint.get("report", {}).get("endpointType", "").lower() not in (
                    "bmc",
                    "unknown",
                    "",
                ):
                    continue
                key = digest({"interface": value_id(link["id"]), "mac": mac})
                saved = self.directory / (key + ".json")
                proof = json.loads(saved.read_text()) if saved.exists() else {}
                if not proof:
                    # Read older v0.7.2 records without deleting their evidence.
                    legacy = self.directory / (
                        digest({"interface": value_id(link["id"]), "mac": mac, "ip": address})
                        + ".json"
                    )
                    proof = json.loads(legacy.read_text()) if legacy.exists() else {}
                report = report_identity(endpoint, mac)
                identity = proof if proof.get("serial") else report
                valid = (
                    proof.get("observation") == digest(link)
                    and proof.get("verified_at", 0) > time.time() - 900
                )
                rows.append(
                    {
                        "id": key,
                        "bmc_ip": address,
                        "bmc_mac": mac,
                        "network_id": segment["id"],
                        "network_name": segment["name"],
                        "last_dhcp": link.get("lastDhcp"),
                        "source": "dhcp" if link.get("lastDhcp") else "interface-record",
                        "registered": bool(existing),
                        "serial": existing["chassis_serial_number"]
                        if existing
                        else identity.get("serial"),
                        "kind": identity.get("kind", "unknown"),
                        "model": identity.get("model"),
                        "nics": proof.get("nics", []),
                        "identity_source": proof.get("identity_source")
                        or (
                            "ui-redfish"
                            if proof.get("verified_at")
                            else "nico-report"
                            if report.get("serial")
                            else None
                        ),
                        "identity_note": report.get("note"),
                        "report_version": (endpoint or {}).get("reportVersion"),
                        "verified_at": proof.get("verified_at"),
                        "verified_ip": proof.get("verified_ip"),
                        "authenticated": valid,
                        "error": proof.get("error") if not valid else None,
                        "observation": digest(link),
                        "exploration_state": (endpoint or {}).get("preingestionState"),
                    }
                )
        settings = self.adapter.config.get("site_explorer_settings", {})
        note = "通过 BMC DHCP 记录发现设备；不扫描静态 IP。未发现设备时，请检查 BMC DHCP、VLAN 和 relay。"
        if settings.get("enabled") is False:
            note += " 站点发现服务未启用，请联系管理员。"
        if settings.get("create_machines") is False:
            note += " 自动接入已关闭；不影响读取设备。"
        if not allowed:
            note += " 请先配置 BMC 发现网络。"
        return {
            "candidates": rows,
            "networks": [
                {
                    "id": n["id"],
                    "name": n["name"],
                    "state": n["state"],
                    "allocation_strategy": n.get("allocation_strategy", "DYNAMIC"),
                    "prefixes": n["prefixes"],
                }
                for n in allowed.values()
            ],
            "observed_at": time.time(),
            "scope": "dedicated-underlay",
            "note": note,
            "site_explorer_settings": settings,
        }

    def selected(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or len(set(ids)) != len(ids):
            raise ValueError("请选择 1–50 个不重复候选。")
        current = {r["id"]: r for r in self.candidates()["candidates"]}
        if any(key not in current or current[key]["registered"] for key in ids):
            raise ValueError("候选已变化或已登记，请刷新列表。")
        return [current[key] for key in ids]

    def authenticate(self, body, owner):
        if (
            set(body) != {"ids", "username", "password"}
            or not isinstance(body["username"], str)
            or not isinstance(body["password"], str)
        ):
            raise ValueError("请选择候选并提供初始 BMC 认证信息。")
        if not 1 <= len(body["username"]) <= 16 or not 1 <= len(body["password"]) <= 20:
            raise ValueError("BMC 用户名/密码超过当前 NICo 字段范围。")
        results = []
        for candidate in self.selected(body["ids"]):
            proof = {
                "serial": candidate.get("serial"),
                "model": candidate.get("model"),
                "nics": candidate.get("nics", []),
                "identity_source": candidate.get("identity_source"),
                "id": candidate["id"],
                "owner": owner,
                "observation": candidate["observation"],
                "verified_at": 0,
            }
            try:
                cred = {"username": body["username"], "password": body["password"]}
                identity = read_device_identity(
                    self.adapter, candidate["bmc_ip"], candidate["bmc_mac"], cred
                )
                proof.update(
                    **identity,
                    credentials=cred,
                    verified_at=time.time(),
                    verified_ip=candidate["bmc_ip"],
                    identity_source="ui-redfish",
                )
                results.append(
                    {
                        "id": candidate["id"],
                        "passed": True,
                        "serial": identity["serial"],
                        "kind": identity["kind"],
                        "model": identity["model"],
                    }
                )
            except (ValueError, RuntimeError) as error:
                proof["error"] = str(error).replace(body["password"], "[已隐藏]")
                results.append({"id": candidate["id"], "passed": False, "detail": proof["error"]})
            atomic_json(self.directory / (candidate["id"] + ".json"), proof)
        return {"results": results}

    def enroll(self, body, owner, actor):
        if set(body) != {"ids", "confirm_registration"} or body["confirm_registration"] is not True:
            raise ValueError("请核对身份并确认加入设备清单；登记不执行接管或安装。")
        candidates = self.selected(body["ids"])
        plans, serials = [], set()
        for c in candidates:
            path = self.directory / (c["id"] + ".json")
            proof = json.loads(path.read_text()) if c["authenticated"] and path.exists() else {}
            if not proof or proof["owner"] != owner or proof.get("status"):
                raise ValueError("请先使用本会话提供的 BMC 凭据重新读取身份。")
            if proof.get("kind", "server") != "server":
                raise ValueError("非服务器请使用统一设备发现入口加入纳管清单。")
            if proof["serial"] in serials:
                raise ValueError("所选候选具有重复主机 SN。")
            serials.add(proof["serial"])
            row = {
                "id": str(uuid.uuid4()),
                "chassis_serial_number": proof["serial"],
                "bmc_mac_address": c["bmc_mac"],
                "bmc_ip_address": c["bmc_ip"],
                "bmc_ip_allocation": "Fixed",
                "bmc_username": proof["credentials"]["username"],
                "bmc_password": proof["credentials"]["password"],
                "bmc_retain_credentials": True,
                "default_pause_ingestion_and_poweron": True,
                "dpu_policy": "unspecified",
                "dpf_enabled": False,
                "interfaces": [
                    {
                        "mac_address": c["bmc_mac"],
                        "role": "host_bmc",
                        "ip_allocation": "fixed",
                        "fixed_ip": c["bmc_ip"],
                        "network_segment_type": 2,
                    }
                ],
            }
            # Reported host NICs are inventory, never guess which one should boot.
            row["interfaces"] += [
                {
                    "mac_address": n["mac_address"],
                    "role": "host",
                    "primary": False,
                    "ip_allocation": "dynamic",
                    "network_segment_type": 3,
                }
                for n in proof["nics"]
                if n["mac_address"] != c["bmc_mac"]
            ]
            plans.append((c, proof, row))
        import csv, io

        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(plans[0][2]))
        writer.writeheader()
        for _, _, row in plans:
            writer.writerow(
                {
                    k: json.dumps(v) if isinstance(v, (dict, list, bool)) else v
                    for k, v in row.items()
                }
            )
        preview = self.resources.preview(stream.getvalue(), owner)
        for c, proof, _ in plans:
            proof["status"] = "registering"
            atomic_json(self.directory / (c["id"] + ".json"), proof)
        try:
            self.resources.apply_import(preview["preview_id"], owner)
        except Exception:
            for c, proof, _ in plans:
                proof["status"] = "needs_attention"
                atomic_json(self.directory / (c["id"] + ".json"), proof)
            raise
        for c, proof, row in plans:
            proof.update(
                status="registered",
                serial=row["chassis_serial_number"],
                expected_id=row["id"],
                actor=actor,
                registered_at=time.time(),
                verified_ip=c["bmc_ip"],
            )
            atomic_json(self.directory / (c["id"] + ".json"), proof)
        return {
            "results": [
                {
                    "serial": row["chassis_serial_number"],
                    "kind": "server",
                    "status": "registered",
                    "detail": "已加入清单，可继续规划。",
                }
                for _, _, row in plans
            ],
            "status": "registered",
        }
