"""Read-only device view combining plans, native resources and observed hardware."""

import json
from pxeye.common import sha, value_id
from pxeye.domain.machines import public_machine
from pxeye.services.device_plans import DevicePlans


class DeviceProjection:
    def __init__(self, resources):
        self.resources = resources
        self.adapter, self.store = resources.adapter, resources.store
        self.plans = DevicePlans(self.adapter, resources)

    def read(self):
        plans = self.plans
        rows = plans.inventory()
        devices = []
        hardware_by_serial = {}
        from pxeye.domain.identity import selection_identity, installation_history

        history_by_serial = {}
        with self.store.db() as db:
            for record in db.execute("""SELECT t.device,t.data FROM tasks t
                    JOIN (SELECT device,max(created) AS latest FROM tasks WHERE status='completed' GROUP BY device) h
                    ON t.device=h.device AND t.created=h.latest
                    WHERE t.status='completed' ORDER BY t.id DESC"""):
                if record["device"] not in history_by_serial:
                    history_by_serial[record["device"]] = installation_history(
                        json.loads(record["data"])
                    )
        configured_rows = self.adapter.config.get("devices", [])
        has_execution = bool(
            configured_rows or list((self.adapter.data / "config" / "execution").glob("*.json"))
        )
        try:
            networks = self.resources.networks() if has_execution else []
            interfaces = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        except (RuntimeError, OSError):
            networks, interfaces = [], []
        for row in rows:
            item = public_machine(row)
            serial = row["chassis_serial_number"]
            configured = next(
                (x for x in self.adapter.config.get("devices", []) if x["serial"] == serial), None
            )
            if (
                not configured
                and (self.adapter.data / "config" / "execution" / (sha(serial) + ".json")).exists()
            ):
                configured = self.adapter.device(serial, bind_intent=False)
            item["serial"] = serial
            item.update(plans.public(serial))
            from pxeye.services.device_config import DeviceConfig

            item["intent"] = DeviceConfig(self.adapter, self.resources).public(serial)
            from pxeye.services.bmc_addresses import BMCAddresses

            item["bmc_address"] = BMCAddresses(self.adapter, self.resources).view(row, interfaces)
            item["bmc_ip"] = item["bmc_address"]["current_ip"] or (configured or {}).get("bmc_ip")
            host = next(
                (
                    x
                    for x in row.get("interfaces", [])
                    if x.get("primary") and x.get("role", "host") in ("host", 0, 1)
                ),
                {},
            )
            item["planned_ip"] = host.get("fixed_ip")
            item["boot_mac"] = host.get("mac_address")
            item["executable"] = bool(configured)
            if configured:
                item.update(
                    {
                        k: configured.get(k)
                        for k in [
                            "architecture",
                            "management_ip",
                            "disk_wwn",
                            "disk_serial",
                            "instance_id",
                            "profile",
                            "os_release",
                        ]
                    }
                )
                try:
                    plan = self.resources.execution_plan(
                        serial, rows=rows, networks=networks, interfaces=interfaces
                    )
                    item["current_management_ip"] = plan["current_management_ip"]
                    item["management_ip"] = plan["management_ip"]
                    item["installation_plan"] = plan
                    if plan["current_management_ip"] != plan["management_ip"]:
                        item["execution_reason"] = (
                            "地址规划将在本次重装生效；当前系统地址保持不变。"
                        )
                except (ValueError, RuntimeError) as error:
                    item["executable"] = False
                    item["execution_reason"] = str(error)
                    from pxeye.services.device_plans import bmc_choice

                    try:
                        with bmc_choice(serial, "use_current"):
                            self.resources.execution_plan(
                                serial, rows=rows, networks=networks, interfaces=interfaces
                            )
                        item["can_install_with_current_bmc"] = True
                    except (ValueError, RuntimeError):
                        pass
            else:
                item["execution_reason"] = "已登记；待发现关联、安装方案和可信 SSH 执行配置。"
            devices.append(item)
        if self.adapter.config.get("first_install_profiles"):
            from pxeye.services.onboarding import Onboarding

            try:
                observed = Onboarding(self.adapter, self.store, self.resources).observed(rows)
            except (RuntimeError, OSError):
                observed = {}
            for item in devices:
                if item["serial"] not in observed:
                    item.update(
                        first_install_ready=False,
                        machine_id=None,
                        discovery_reason="NICo 暂不可用；本地规划仍可查看与保存。",
                    )
                    continue
                state = observed[item["serial"]]
                item.update(
                    {
                        k: state[k]
                        for k in (
                            "disks",
                            "architecture",
                            "first_install_ready",
                            "discovery_state",
                            "discovery_reason",
                            "failure_details",
                        )
                    }
                )
                item["machine_id"] = (state["machine"] or {}).get("id")
                current = state["instances"]
                delivered_id = item.get("instance_id")
                item["instance_id"] = value_id(current[0]["id"]) if len(current) == 1 else None
                if not current or item["instance_id"] != delivered_id:
                    item["executable"] = False
                    item.pop("can_install_with_current_bmc", None)
                    item["execution_reason"] = (
                        "当前无 Instance，可按首次安装下发；设备规划与历史记录保留。"
                        if not current
                        else "当前 Instance 与上次交付不同，请核对执行连接配置。"
                    )
                from pxeye.services.hardware import facts
                from pxeye.services.onboarding import discovery_info

                machine = state["machine"] or {}
                info = discovery_info(machine)
                dmi = info.get("dmi_data", {})
                bmc = machine.get("bmc") or machine.get("bmc_info") or {}
                if bmc.get("mac", "").lower() == item.get("bmc_mac_address", "").lower() and item[
                    "serial"
                ] in {dmi.get("product_serial"), dmi.get("chassis_serial")}:
                    hardware_by_serial[item["serial"]] = facts(machine) | {
                        "manufacturer": dmi.get("sys_vendor"),
                        "model": dmi.get("product_name"),
                    }
                hardware = facts(state["machine"])
                item["hardware_summary"] = (
                    {
                        "nic_count": len(hardware["nics"]),
                        "disk_count": len(hardware["disks"]),
                        "architecture": hardware["architecture"],
                    }
                    if hardware["nics"] or hardware["disks"]
                    else None
                )
        from pxeye.services.instances import release_records

        pending = {
            r["serial"]: r for r in release_records(self.adapter) if r["status"] != "completed"
        }
        for item in devices:
            item["instance_release_pending"] = item["serial"] in pending
            item["instance_release"] = pending.get(item["serial"]) and {
                k: pending[item["serial"]].get(k)
                for k in ("status", "detail", "machine_state", "checked_at")
            }
            if item["instance_release_pending"]:
                item.update(
                    executable=False,
                    first_install_ready=False,
                    can_install_with_current_bmc=False,
                    execution_reason=pending[item["serial"]]["detail"],
                )
        for item in devices:
            item["selection_identity"] = selection_identity(
                item,
                networks,
                hardware_by_serial.get(item["serial"]),
                history_by_serial.get(item["serial"]),
            )
        return devices
