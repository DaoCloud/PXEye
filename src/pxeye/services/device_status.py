"""Operational state of managed devices as NICo Core reports it.

The equipment view owns declarations, addresses and enrollment. This module adds
what the Core state controllers observe for the same objects: lifecycle, health,
power, firmware and placement. It only reads, keeps no state, and is keyed by the
identifiers the equipment view already exposes, so the two never disagree about
which device is which.
"""

import datetime
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

    def machine_history(self, machine_id):
        """State timeline of one machine; an unknown machine has an empty timeline."""
        if not isinstance(machine_id, str) or not MACHINE_ID.fullmatch(machine_id):
            raise ValueError("机器 ID 格式不正确。")
        response = self.adapter.rpc(
            "FindMachineStateHistories", {"machineIds": [{"id": machine_id}]}
        )
        histories = (response or {}).get("histories") or {}
        records = (histories.get(machine_id) or {}).get("records") or []
        now = time.time()
        return {"observed_at": now, "records": state_timeline(records, now)}

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


def record_time(value):
    """Core writes record times as RFC 3339 text; anything else is unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    # Python before 3.11 accepts at most six fraction digits.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def state_timeline(records, now):
    """Order history records by time and say how long the machine stayed in each state.

    Consecutive records with the same state text are one stay. The last stay runs to now.
    """
    timed = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        moment = record_time(record.get("time"))
        if moment is None:
            continue
        timed.append((moment, state_text(record.get("event")), record.get("time")))
    timed.sort(key=lambda item: item[0])
    stays = []
    for moment, state, raw in timed:
        if stays and stays[-1]["state"] == state:
            continue
        stays.append({"state": state, "entered_at": raw, "_at": moment})
    for index, stay in enumerate(stays):
        last = index == len(stays) - 1
        end = now if last else stays[index + 1]["_at"]
        stay["duration_seconds"] = max(0, int(end - stay.pop("_at")))
        stay["current"] = last
    return stays


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


def machine_health_history(adapter, machine_id):
    """Alert periods of one machine from the health records Core keeps. Reads only.

    An alert is identified by its probe id and target. It started when Core says it
    went into alert (inAlertSince), or else at the first record that shows it; it was
    last seen at the last record that still shows it, and it is still present when the
    latest record shows it. A record without alerts is a healthy observation. When a
    record no longer shows an alert, its period ends; a later recurrence is a new period.
    """
    if not valid_machine_id(machine_id):
        raise ValueError("机器 ID 无效。")
    response = adapter.rpc("FindMachineHealthHistories", {"machineIds": [{"id": machine_id}]})
    histories = (response or {}).get("histories") or {}
    entry = histories.get(machine_id) if isinstance(histories, dict) else None
    records = []
    for record in (entry or {}).get("records") or []:
        if not isinstance(record, dict):
            continue
        moment = record_time(record.get("time"))
        if moment is not None:
            records.append((moment, record.get("time"), record.get("health") or {}))
    records.sort(key=lambda item: item[0])
    periods = []
    open_periods = {}
    for moment, raw, report in records:
        seen = {}
        for alert in (report if isinstance(report, dict) else {}).get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            key = (str(alert.get("id") or ""), str(alert.get("target") or ""))
            since = alert.get("inAlertSince") or ""
            period = seen.get(key) or open_periods.get(key)
            if period is None:
                period = {
                    "id": key[0],
                    "target": key[1],
                    "since": since or raw,
                    "_since": record_time(since) or moment,
                }
                periods.append(period)
            elif since and (record_time(since) or moment) < period["_since"]:
                period["since"], period["_since"] = since, record_time(since)
            seen[key] = period
            period.update(
                last_seen=raw,
                _last=moment,
                message=alert.get("message") or "",
                classifications=[
                    str(c) for c in alert.get("classifications") or [] if isinstance(c, str)
                ],
            )
        # A record without the alert closes its period; a later recurrence is a new row.
        open_periods = seen
    latest = records[-1][0] if records else None
    alerts = sorted(periods, key=lambda p: p["_since"], reverse=True)
    for period in alerts:
        period["active"] = period.pop("_last") == latest
        period.pop("_since")
    return {
        "machine_id": machine_id,
        "observed_at": time.time(),
        "record_count": len(records),
        "first_record": records[0][1] if records else "",
        "last_record": records[-1][1] if records else "",
        "alerts": alerts,
    }


VALIDATION_OUTPUT_LIMIT = 2000
# forge.MachineValidationStatus is a oneof; proto JSON may leave a zero enum empty.
VALIDATION_STATES = {
    "started": ("started", "Started"),
    "inProgress": ("in_progress", "InProgress"),
    "completed": ("completed", "Success"),
}


def validation_status(status):
    """A short state for a run status, e.g. {"completed": "Skipped"} -> completed/Skipped."""
    if not isinstance(status, dict):
        return {"phase": "", "outcome": "", "text": "", "total": None, "completed_tests": None}
    phase, outcome = "", ""
    for key, (name, zero) in VALIDATION_STATES.items():
        if key in status:
            value = status.get(key)
            phase, outcome = name, value if isinstance(value, str) and value else zero
            break
    return {
        "phase": phase,
        "outcome": outcome,
        "text": outcome or "",
        "total": status.get("total"),
        "completed_tests": status.get("completedTests"),
    }


def proto_duration(value):
    """Proto JSON durations are text such as "12.5s"; anything else is unknown."""
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?s", value.strip()):
        return float(value.strip()[:-1])
    return None


def clipped(value):
    text = value if isinstance(value, str) else ""
    return text[:VALIDATION_OUTPUT_LIMIT]


def validation_result(item):
    return {
        "validation_id": value_id(item.get("validationId")) or "",
        "test_id": item.get("testId") or "",
        "name": item.get("name") or "",
        "description": item.get("description") or "",
        "context": item.get("context") or "",
        "command": item.get("command") or "",
        "args": item.get("args") or "",
        # Proto JSON omits a zero exit code; zero is the default, not unknown.
        "exit_code": item.get("exitCode") if isinstance(item.get("exitCode"), int) else 0,
        "start": item.get("startTime") or "",
        "end": item.get("endTime") or "",
        "std_out": clipped(item.get("stdOut")),
        "std_err": clipped(item.get("stdErr")),
    }


def machine_validation(adapter, machine_id):
    """Hardware validation runs of one machine and their results. Reads only."""
    if not valid_machine_id(machine_id):
        raise ValueError("机器 ID 无效。")
    body = {"machineId": {"id": machine_id}, "includeHistory": True}
    runs_response = adapter.rpc("GetMachineValidationRuns", body) or {}
    results_response = adapter.rpc("GetMachineValidationResults", body) or {}
    results = {}
    for item in results_response.get("results") or []:
        if isinstance(item, dict):
            shaped = validation_result(item)
            results.setdefault(shaped["validation_id"], []).append(shaped)
    runs = []
    for run in runs_response.get("runs") or []:
        if not isinstance(run, dict):
            continue
        status = run.get("status")
        runs.append(
            {
                "validation_id": value_id(run.get("validationId")) or "",
                "name": run.get("name") or "",
                "context": run.get("context") or "",
                "start": run.get("startTime") or "",
                "end": run.get("endTime") or "",
                "duration_seconds": proto_duration(run.get("durationToComplete")),
                "status": validation_status(status),
                "status_raw": status if isinstance(status, dict) else None,
            }
        )
    runs.sort(key=lambda r: record_time(r["start"]) or 0, reverse=True)
    return {
        "machine_id": machine_id,
        "observed_at": time.time(),
        "runs": runs,
        "results": results,
    }
