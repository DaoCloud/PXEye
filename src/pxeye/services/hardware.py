"""Read-only projection of a registered device's NICo/Scout facts, never a second inventory."""

import json
import time
from pxeye.common import sha
from pxeye.services.onboarding import Onboarding, discovery_info, architecture
from pxeye.common import atomic_json, digest
from pxeye.domain.pci import scout_pci_address


def facts(machine):
    info = discovery_info(machine or {})
    nvmes = {d["serial"]: d for d in info.get("nvme_devices", []) if d.get("serial")}
    disks = []
    for d in info.get("block_devices", []):
        if d.get("device_type") != "disk":
            continue
        extra = nvmes.get(d.get("serial"), {})
        disks.append(
            {
                k: v
                for k, v in dict(
                    serial=d.get("serial"), model=d.get("model"), size_mb=extra.get("size_mb")
                ).items()
                if v is not None
            }
        )
    groups = [d for d in info.get("memory_device_groups", []) if d.get("count", 0) > 0]
    memory = (
        sum(d.get("size_mb", 0) * d["count"] for d in groups)
        if groups
        else sum(d.get("size_mb", 0) for d in info.get("memory_devices", []))
    )
    return {
        "architecture": architecture(info),
        "cpus": [
            {k: c.get(k) for k in ("model", "sockets", "cores", "threads")}
            for c in info.get("cpu_info", [])
        ],
        "memory_mb": memory or None,
        "nics": [
            {
                "mac": n.get("mac_address", "").lower(),
                "vendor": n.get("pci_properties", {}).get("vendor"),
                "model": n.get("pci_properties", {}).get("device"),
                "pci_address": scout_pci_address(n.get("pci_properties") or {}),
                "numa_node": (n.get("pci_properties") or {}).get("numa_node"),
                "pci_path": (n.get("pci_properties") or {}).get("path"),
                "description": (n.get("pci_properties") or {}).get("description"),
                "inventory_source": "NICo / Scout",
            }
            for n in info.get("network_interfaces", [])
        ],
        "disks": disks,
        "product_serial": info.get("dmi_data", {}).get("product_serial"),
        "chassis_serial": info.get("dmi_data", {}).get("chassis_serial"),
    }


def conflicts(row, intent, hardware):
    result = []
    nics = {n["mac"] for n in hardware["nics"]}
    for n in row.get("interfaces", []):
        if (
            n.get("role", "host") in ("host", "unspecified")
            and (n.get("primary") or n.get("fixed_ip"))
            and n.get("mac_address", "").lower() not in nics
        ):
            result.append(
                "规划网卡 "
                + n.get("mac_address", "")
                + " 未在 Scout 回报中找到；请核对或编辑规划。"
            )
    if (
        intent.get("disk_serial")
        and sum(d.get("serial") == intent["disk_serial"] for d in hardware["disks"]) != 1
    ):
        result.append(
            "规划系统盘 " + intent["disk_serial"] + " 未在 Scout 回报中唯一匹配；请重新选择。"
        )
    return result


class Hardware:
    def __init__(self, adapter, resources):
        self.adapter, self.resources = adapter, resources
        self.onboarding = Onboarding(adapter, resources.store, resources)

    def path(self, serial):
        return self.adapter.data / "observations" / "hardware" / (sha(serial) + ".json")

    def cached(self, serial):
        path = self.path(serial)
        return json.loads(path.read_text()) if path.exists() else None

    def read(self, serial):
        row = self.onboarding.inventory_row(serial)
        from pxeye.services.device_config import DeviceConfig
        from pxeye.services.bmc_addresses import BMCAddresses

        previous = self.cached(serial)
        if previous and previous.get("device_id") != row["id"]:
            previous = None
        from pxeye.services.device_plans import DevicePlans

        plan = DevicePlans(self.adapter, self.resources).public(serial)
        result = {
            "serial": serial,
            "kind": "server",
            "device_id": row["id"],
            "read_at": time.time(),
            "source": "NICo / Scout最近回报",
            "hardware": (previous or {}).get("hardware"),
            "hardware_revision": (previous or {}).get("hardware_revision"),
            "hardware_read_at": (previous or {}).get("hardware_read_at"),
            "changes": [],
            "conflicts": [],
            "available": False,
            "can_prepare": False,
            "auto_refresh": False,
            "identity_matches": False,
            "planning": {
                "revision": plan.get("plan_revision"),
                "intent": DeviceConfig(self.adapter, self.resources).public(serial),
            },
        }
        try:
            address = BMCAddresses(self.adapter, self.resources).view(row)
            result["bmc_ip"] = address["current_ip"]
            observed = self.onboarding.observed([row])[serial]
            machine, info = observed["machine"], discovery_info(observed["machine"] or {})
            gate = self.adapter.rpc(
                "DetermineMachineIngestionState",
                {
                    "ip_address": address["current_ip"] or row.get("bmc_ip_address", ""),
                    "mac_address": row["bmc_mac_address"],
                },
            ).get("machineIngestionState")
            result.update(
                available=True,
                gate=gate,
                machine_id=(machine or {}).get("id"),
                machine_state=(machine or {}).get("state"),
                instance_id=next((i.get("id") for i in observed["instances"]), None),
                error=observed["failure_details"],
            )
            if machine:
                bmc = machine.get("bmc") or machine.get("bmc_info") or {}
                mac_matches = bmc.get("mac", "").lower() == row["bmc_mac_address"].lower()
                serials = {
                    info.get("dmi_data", {}).get("product_serial"),
                    info.get("dmi_data", {}).get("chassis_serial"),
                } - {None, ""}
                # No IP-only association is accepted as verified hardware.
                identity = mac_matches and (not serials or serial in serials)
                result["identity_matches"] = identity
                if not identity:
                    result.update(
                        phase="identity_conflict",
                        message="主机的 BMC MAC 或 Scout SN 与设备身份不一致；请核对设备，未采用该硬件信息。",
                    )
                elif info and serial in serials:
                    hardware = facts(machine)
                    revision = digest(hardware)
                    if previous and previous["hardware_revision"] != revision:
                        old = previous["hardware"]
                        for key, field, label in [
                            ("nics", "mac", "网卡"),
                            ("disks", "serial", "磁盘"),
                        ]:
                            old_keys = {x.get(field) for x in old[key] if x.get(field)}
                            new_keys = {x.get(field) for x in hardware[key] if x.get(field)}
                            result["changes"] += [
                                label + "新增：" + x for x in sorted(new_keys - old_keys)
                            ] + [label + "不再回报：" + x for x in sorted(old_keys - new_keys)]
                        if (
                            old.get("cpus") != hardware["cpus"]
                            or old.get("memory_mb") != hardware["memory_mb"]
                        ):
                            result["changes"].append("CPU或内存回报发生变化；请核对硬件。")
                    if previous and previous["hardware_revision"] == revision:
                        result["changes"] = previous.get("changes", [])
                    result.update(
                        hardware=hardware,
                        hardware_revision=revision,
                        hardware_read_at=result["read_at"],
                    )
                    result["conflicts"] = conflicts(row, result["planning"]["intent"], hardware)
                    result["phase"] = (
                        "installed"
                        if observed["instances"]
                        else "ready"
                        if observed["first_install_ready"]
                        else "collecting"
                    )
                    result["message"] = (
                        "已有安装实例，可核对规划后重装。"
                        if observed["instances"]
                        else "硬件已获取，可按 MAC 和磁盘序列号规划安装。"
                        if observed["first_install_ready"]
                        else "Scout已回报硬件，等待NICo完成接入。"
                    )
                    atomic_json(
                        self.path(serial),
                        {
                            k: result[k]
                            for k in (
                                "serial",
                                "device_id",
                                "hardware",
                                "hardware_revision",
                                "hardware_read_at",
                                "changes",
                            )
                        },
                    )
                else:
                    result.update(
                        phase="collecting", message="已找到NICo主机，等待Scout回报硬件和主机SN。"
                    )
                result["auto_refresh"] = (
                    result.get("phase") == "collecting" and not observed["failure_details"]
                )
            else:
                result.update(
                    phase="awaiting_approval" if gate == "WaitingForIngestion" else "awaiting_host",
                    message="先检查启动口与网络，然后启动硬件接入。"
                    if gate == "WaitingForIngestion"
                    else "NICo尚未提供主机和Scout信息；请核对主机网络启动与Scout注册。",
                )
                prior = self.onboarding.admission(row["id"])
                result["can_prepare"] = (
                    gate == "WaitingForIngestion"
                    and not prior
                    and not self.resources.store.active(serial)
                )
                if prior:
                    result["message"] = (
                        "已发送硬件接入请求；查看NICo与Scout回报，结果不明确时先核对现场，不能重复启动。"
                    )
            result["milestones"] = [
                {"label": "身份已登记", "complete": True},
                {
                    "label": "NICo主机已关联",
                    "complete": bool(machine and result["identity_matches"]),
                },
                {
                    "label": "Scout硬件已获取",
                    "complete": bool(
                        info
                        and serial
                        in {
                            info.get("dmi_data", {}).get("product_serial"),
                            info.get("dmi_data", {}).get("chassis_serial"),
                        }
                        and result["identity_matches"]
                    ),
                },
            ]
        except (RuntimeError, OSError, ValueError) as error:
            result.update(
                available=False,
                phase="unavailable",
                message="本次读取失败；保留上次硬件回报，不能据此判断当前可安装。",
                error=str(error),
                milestones=[
                    {"label": "身份已登记", "complete": True},
                    {"label": "NICo主机已关联", "complete": False},
                    {"label": "Scout硬件已获取", "complete": False},
                ],
            )
        from pxeye.services.equipment_planning import EquipmentPlanning

        record = DevicePlans(self.adapter, self.resources).get(serial)
        result["nics"] = (
            EquipmentPlanning(self.adapter, self.resources).host_nics(record) if record else []
        )
        return result
