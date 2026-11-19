"""Operational state of managed devices as NICo Core reports it.

The equipment view owns declarations, addresses and enrollment. This module adds
what the Core state controllers observe for the same objects: lifecycle, health,
power, firmware and placement. It only reads, keeps no state, and is keyed by the
identifiers the equipment view already exposes, so the two never disagree about
which device is which.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from pxeye.common import value_id
from pxeye.services.equipment import object_id, snake

MACHINE_TYPES = {"HOST": "host", "DPU": "dpu", "POWER_SHELF": "power_shelf"}
CAPABILITIES = ("cpu", "gpu", "memory", "storage", "network", "infiniband", "dpu")
FABRIC_MANAGER = {
    "FABRIC_MANAGER_STATE_OK": "ok",
    "FABRIC_MANAGER_STATE_NOT_OK": "not_ok",
    "FABRIC_MANAGER_STATE_UNKNOWN": "unknown",
}


def state_text(value):
    """Core renders a state either as plain text or as a JSON document."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = json.loads(value)
    except ValueError:
        return value.strip()
    parts = []
    while isinstance(parsed, dict):
        name = parsed.get("state")
        if not isinstance(name, str):
            break
        parts.append(name)
        parsed = next((v for k, v in parsed.items() if k != "state" and isinstance(v, dict)), None)
    return "/".join(parts) if parts else value.strip()


def lifecycle(row):
    status = row.get("status") or {}
    current = status.get("lifecycle") or {}
    reason = current.get("state_reason") or status.get("state_reason") or row.get("state_reason")
    sla = current.get("sla") or status.get("state_sla") or row.get("state_sla") or {}
    reason = reason or {}
    return {
        "state": state_text(
            current.get("state")
            or status.get("controller_state")
            or row.get("controller_state")
            or row.get("state")
        ),
        # Proto JSON omits enum zero; WAIT is zero in ControllerStateOutcome.
        "outcome": str(reason.get("outcome") or "WAIT").lower() if reason else "",
        "reason": reason.get("outcome_msg") or "",
        "above_sla": sla.get("time_in_state_above_sla") is True,
    }


def health(row):
    status = row.get("status") or {}
    report = status.get("health")
    alerts = [
        {
            "id": alert.get("id", ""),
            "target": alert.get("target") or "",
            "message": alert.get("message", ""),
            "since": alert.get("in_alert_since") or "",
            "classifications": alert.get("classifications") or [],
        }
        for alert in (report or {}).get("alerts") or []
    ]
    reported = str(status.get("health_status") or "").lower()
    if reported in ("ok", "warning", "critical"):
        level = reported
    elif alerts:
        level = "alert"
    else:
        # An absent report is not a healthy report.
        level = "ok" if report is not None else "unknown"
    return {
        "level": level,
        "alerts": alerts,
        "observed_at": (report or {}).get("observed_at") or "",
        "source": (report or {}).get("source") or "",
    }


def common(row):
    bmc = row.get("bmc") or row.get("bmc_info") or {}
    firmware = (row.get("status") or {}).get("bmc_status") or row.get("bmc_info") or {}
    placement = row.get("placement_in_rack") or {}
    return {
        "id": object_id(row.get("id")),
        "name": (row.get("metadata") or {}).get("name", ""),
        "rack_id": value_id(row.get("rack_id")),
        "placement": {
            "slot": placement.get("slot_number"),
            "tray": placement.get("tray_index"),
        },
        "lifecycle": lifecycle(row),
        "health": health(row),
        "bmc": {
            "ip": bmc.get("ip") or "",
            "mac": str(bmc.get("mac") or "").lower(),
            "version": firmware.get("version") or "",
            "firmware_version": firmware.get("firmware_version") or "",
        },
    }


def lldp_neighbor(item):
    """One host interface and the switch port Scout heard on it."""
    data = item.get("lldp") or {}
    inventory = data.get("med_inventory") or {}
    return {
        "mac_address": str(item.get("mac_address") or "").lower(),
        "local_port": data.get("local_port") or "",
        "switch": data.get("name") or "",
        "switch_id": data.get("id_value") or "",
        "switch_model": inventory.get("model") or inventory.get("manufacturer") or "",
        "switch_serial": inventory.get("serial") or "",
        "remote_port": data.get("remote_port_value") or "",
        "remote_port_type": data.get("remote_port_type") or "",
        "description": data.get("description") or "",
    }


def server(row):
    status, config = row.get("status") or {}, row.get("config") or {}
    capabilities = status.get("capabilities") or {}
    quarantine = status.get("quarantine")
    return common(row) | {
        "type": MACHINE_TYPES.get(str(row.get("machine_type") or ""), "unknown"),
        "host_id": object_id(status.get("associated_host_machine_id")),
        "dpu_ids": [object_id(item) for item in status.get("associated_dpu_machine_ids") or []],
        "sku": {
            "id": config.get("hw_sku") or "",
            "device_type": status.get("hw_sku_device_type") or "",
            "last_match_attempt": (status.get("hw_sku") or {}).get("last_match_attempt") or "",
            "verify_requested": (status.get("hw_sku") or {}).get("verify_request_time") or "",
        },
        "quarantine": (
            {"mode": str(quarantine.get("mode") or ""), "reason": quarantine.get("reason") or ""}
            if isinstance(quarantine, dict)
            else None
        ),
        "maintenance": config.get("maintenance_reference") or "",
        "instance_type": config.get("instance_type_id") or "",
        "capabilities": {
            kind: [
                {
                    "name": item.get("name", ""),
                    "count": item.get("count", 0),
                    "vendor": item.get("vendor") or "",
                    "capacity": item.get("capacity") or "",
                }
                for item in capabilities.get(kind) or []
            ]
            for kind in CAPABILITIES
            if capabilities.get(kind)
        },
        "lldp": [lldp_neighbor(item) for item in status.get("lldp_neighbors") or []],
        "failure": status.get("failure_details") or "",
        "scout_version": status.get("last_scout_observed_version") or "",
        "dpu_agent_version": status.get("dpu_agent_version") or "",
        "last_reboot": status.get("last_reboot_time") or "",
        "last_observation": status.get("last_observation_time") or "",
    }


def switch(row):
    status = row.get("status") or {}
    manager = status.get("fabric_manager_status_details") or {}
    return common(row) | {
        "power_state": str(status.get("power_state") or "").lower(),
        "serial": status.get("serial_number") or "",
        "primary": row.get("is_primary") is True,
        "nvlink_domain": value_id(row.get("nvlink_domain_uuid")) or "",
        "nmxc_enabled": (row.get("config") or {}).get("enable_nmxc") is True,
        "fabric_manager": {
            "state": FABRIC_MANAGER.get(str(manager.get("fabric_manager_state") or ""), ""),
            "summary": status.get("fabric_manager_status") or "",
            "reason": manager.get("reason") or manager.get("error_message") or "",
        },
        "nvos_ports": [
            {
                "mac": str(port.get("mac") or "").lower(),
                "primary": port.get("is_primary") is True,
                "service_port": port.get("service_port"),
                "addresses": [a.get("address") for a in port.get("addresses") or [] if a],
            }
            for port in status.get("nvos_ports") or []
        ],
    }


def power_shelf(row):
    status, config = row.get("status") or {}, row.get("config") or {}
    return common(row) | {
        "power_state": str(status.get("power_state") or "").lower(),
        "capacity_watts": config.get("capacity"),
        "voltage": config.get("voltage"),
        "nvlink_domain": value_id(row.get("nvlink_domain_uuid")) or "",
    }


class DeviceStatus:
    def __init__(self, adapter):
        self.adapter = adapter

    def _machines(self):
        ids = self.adapter.rpc("FindMachineIds", {}).get("machineIds", [])
        if not ids:
            return []
        return snake(
            self.adapter.rpc("FindMachinesByIds", {"machineIds": ids, "includeHistory": False})
        ).get("machines", [])

    def view(self):
        reads = {
            "servers": (
                "服务器",
                self._machines,
                server,
            ),
            "switches": (
                "交换机",
                lambda: snake(self.adapter.rpc("FindSwitches", {})).get("switches", []),
                switch,
            ),
            "power_shelves": (
                "供电框",
                lambda: snake(self.adapter.rpc("FindPowerShelves", {})).get("power_shelves", []),
                power_shelf,
            ),
        }

        def read(item):
            key, (label, fetch, shape) = item
            try:
                rows = [shape(row) for row in fetch() if not row.get("deleted")]
            except (RuntimeError, ValueError, OSError):
                # One unreadable kind must not hide the others; say which one is missing.
                return key, None, "NICo 未返回" + label + "运行状态。"
            return key, {row["id"]: row for row in rows if row["id"]}, None

        result = {"observed_at": time.time(), "errors": []}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for key, rows, error in pool.map(read, reads.items()):
                result[key] = rows or {}
                if error:
                    result["errors"].append(error)
        return result


MACHINE_ID = re.compile(r"[a-z0-9]{1,128}")


def valid_machine_id(value):
    return isinstance(value, str) and MACHINE_ID.fullmatch(value) is not None


def firmware(report):
    """The firmware inventory of one Redfish exploration report.

    Entry ids are vendor names (one vendor's BMC is another's XCC), so entries are
    kept as listed and never matched by name. An empty version stays empty: the
    component exists and its version was not read.
    """
    chassis = next(
        (c for c in report.get("chassis") or [] if isinstance(c, dict) and c.get("model")), {}
    )
    lockdown = report.get("lockdownStatus")
    secure_boot = report.get("secureBootStatus")
    return {
        "vendor": report.get("vendor") or "",
        "endpoint_type": report.get("endpointType") or "",
        "chassis": {
            "model": chassis.get("model") or "",
            "part_number": chassis.get("partNumber") or "",
            "manufacturer": chassis.get("manufacturer") or "",
        },
        "lockdown": (lockdown.get("message") or "") if isinstance(lockdown, dict) else "",
        # Kept as Core gives it; on a verified site it is an empty object.
        "secure_boot": secure_boot if isinstance(secure_boot, dict) else None,
        "entries": [
            {
                "id": str(item.get("id") or ""),
                "description": item.get("description") or "",
                "version": item.get("version") or "",
                "release_date": item.get("releaseDate") or "",
            }
            for service in report.get("service") or []
            if isinstance(service, dict) and service.get("id") == "FirmwareInventory"
            for item in service.get("inventories") or []
            if isinstance(item, dict)
        ],
    }


def machine_firmware(adapter, machine_id):
    """Read the firmware inventory Core holds for one machine. Reads only."""
    if not valid_machine_id(machine_id):
        raise ValueError("机器 ID 无效。")
    response = adapter.rpc(
        "GetComponentInventory", {"machineIds": {"machineIds": [{"id": machine_id}]}}
    )
    report = next(
        (
            entry.get("report")
            for entry in (response or {}).get("entries") or []
            if isinstance(entry, dict) and isinstance(entry.get("report"), dict)
        ),
        None,
    )
    if not report:
        return {
            "machine_id": machine_id,
            "observed_at": time.time(),
            "reported": False,
            "note": "NICo 没有此机器的固件清单。",
            **firmware({}),
        }
    return {
        "machine_id": machine_id,
        "observed_at": time.time(),
        "reported": True,
        "note": "",
        **firmware(report),
    }
