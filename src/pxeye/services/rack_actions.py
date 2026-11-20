"""NICo-native operations on managed devices ("rack actions").

Every operation here is a NICo Core RPC; PXEye never talks to a BMC or to RMS for
them. The flow is preview -> execute, following the draft rules for operations:

- Preview runs the server-side checks for each target and returns a token bound
  to the action, the targets and the parameters, valid for five minutes.
- Execute consumes the token once, runs the checks again, records "sent" before
  calling Core, calls Core once per target and reads the state back. A timeout or
  an unknown result is never resent: the read-back decides between succeeded and
  unknown, and the operator decides what to do next.

Yielding to installation (kept deliberately simple):

1. A target whose serial has an installation task in status queued, running or
   needs_attention is refused, whatever the action. For a rack the serials of the
   machines placed in it are checked.
2. Actions marked ``state_guard`` (power, quarantine, reset, validation) are
   refused while the machine's NICo lifecycle state is installation-related:
   it starts with ``HostInit``, or it starts with ``Assigned`` and is not
   ``Assigned/Ready``. Maintenance marks and SKU checks are not guarded.

The switch is ``rack_actions``; it only counts with ``rack_operations`` on and the
instance not a read-only observer.
"""

import hashlib
import json
import time
import uuid

from pxeye import read_only
from pxeye.common import value_id
from pxeye.services.device_status import health, lifecycle, state_text
from pxeye.services.equipment import object_id, snake

PREVIEW_SECONDS = 300
MAX_TARGETS = 10
ACTIVE_TASK = ("queued", "running", "needs_attention")
REDACTED_KEYS = ("token", "password", "secret", "credential")


def enabled(config):
    return (
        config.get("rack_operations") is True
        and config.get("rack_actions") is True
        and not read_only.enabled(config)
    )


class RackActionsInvalid(ValueError):
    """A request the API answers with 400 and the message."""


# ---- request builders ----------------------------------------------------------


def _mid(target):
    return {"id": target}


def _admin_power(action):
    return lambda target, params: {"machineId": target, "action": action}


def _component_ids(kind, target):
    if kind == "machine":
        return {"machineIds": {"machineIds": [_mid(target)]}}
    if kind == "switch":
        return {"switchIds": {"ids": [_mid(target)]}}
    return {"powerShelfIds": {"ids": [_mid(target)]}}


def _component_power(kind, action):
    return lambda target, params: _component_ids(kind, target) | {
        "action": "SYSTEM_POWER_CONTROL_" + action
    }


def _maintenance(target, params, operation):
    body = {"operation": operation, "hostId": _mid(target)}
    if operation == "Enable":
        body["reference"] = params["reference"]
    return body


def _quarantine_set(target, params):
    return {
        "machineId": _mid(target),
        "quarantineState": {"mode": "BLOCK_ALL_TRAFFIC", "reason": params["reason"]},
    }


def _validation(target, params):
    body = {"machineId": _mid(target), "action": "Start"}
    for key in ("tags", "contexts"):
        if params.get(key):
            body[key] = list(params[key])
    return body


def _shelf_power(operation):
    def build(target, params):
        body = {
            "powerShelfIds": [_mid(target)],
            "operation": "POWER_SHELF_MAINTENANCE_OPERATION_" + operation,
        }
        if params.get("reference"):
            body["reference"] = params["reference"]
        if operation == "POWER_OFF":
            body["graceful"] = params.get("graceful") is True
        return body

    return build


def _rack_maintenance(target, params):
    activities = []
    for name in params["activities"]:
        if name == "firmware_upgrade":
            activity = {"firmwareVersion": params["sot_json"]}
            if params.get("components"):
                activity["components"] = list(params["components"])
            if params.get("force_update") is True:
                activity["forceUpdate"] = True
            activities.append({"firmwareUpgrade": activity})
        elif name == "nvos_update":
            activities.append({"nvosUpdate": {"configJson": params["sot_json"]}})
        elif name == "power_sequence":
            activities.append({"powerSequence": {}})
        elif name == "configure_nmx_cluster":
            activities.append({"configureNmxCluster": {}})
    scope = {"activities": activities}
    for key, field in (
        ("machine_ids", "machineIds"),
        ("switch_ids", "switchIds"),
        ("power_shelf_ids", "powerShelfIds"),
    ):
        if params.get(key):
            scope[field] = list(params[key])
    return {"rackId": _mid(target), "scope": scope}


def _firmware(kind):
    def build(target, params):
        if kind == "machine":
            body = {"computeTrays": {"machineIds": {"machineIds": [_mid(target)]}}}
            if params.get("components"):
                body["computeTrays"]["components"] = list(params["components"])
        elif kind == "switch":
            body = {"switches": {"switchIds": {"ids": [_mid(target)]}}}
            if params.get("components"):
                body["switches"]["components"] = list(params["components"])
        else:
            body = {"racks": {"rackIds": {"rackIds": [_mid(target)]}}}
        body["targetVersion"] = params["target_version"]
        if params.get("force_update") is True:
            body["forceUpdate"] = True
        return body

    return build


# ---- read-backs ----------------------------------------------------------------
# Each returns (matched, observed): matched is True when the state read back is
# what the action asks for, False when it contradicts it, None when Core gives no
# way to tell; only True counts as succeeded.


def _machine_row(adapter, target):
    rows = snake(
        adapter.rpc("FindMachinesByIds", {"machineIds": [_mid(target)], "includeHistory": False})
        or {}
    ).get("machines", [])
    return next((row for row in rows if object_id(row.get("id")) == target), None)


def _power_state(adapter, kind, target):
    response = snake(adapter.rpc("GetComponentPowerDetails", _component_ids(kind, target)) or {})
    entry = next(iter(response.get("entries") or []), {})
    actual = entry.get("actual") or {}
    if actual.get("error") is not None:
        return None
    # Proto JSON omits enum zero: an observation with no state is UNKNOWN.
    return str(actual.get("state") or "COMPONENT_POWER_STATE_UNKNOWN").removeprefix(
        "COMPONENT_POWER_STATE_"
    )


def _power_readback(kind, expected):
    def read(adapter, target, response):
        state = _power_state(adapter, kind, target)
        observed = {"power_state": state}
        if state in (None, "UNKNOWN") or expected is None:
            return None, observed
        return state in expected, observed

    return read


def _machine_readback(check):
    def read(adapter, target, response):
        row = _machine_row(adapter, target)
        if row is None:
            return None, {"found": False}
        config, status = row.get("config") or {}, row.get("status") or {}
        observed = {
            "state": lifecycle(row)["state"],
            "maintenance": config.get("maintenance_reference") or "",
            "quarantine": status.get("quarantine") or None,
            "sku_verify_requested": (status.get("hw_sku") or {}).get("verify_request_time") or "",
        }
        return (check(observed) if check else None), observed

    return read


def _validation_readback(adapter, target, response):
    validation = value_id(object_id((response or {}).get("validationId"))) or ""
    return (True if validation else None), {"validation_id": validation}


def _rack_readback(check):
    def read(adapter, target, response):
        rows = snake(adapter.rpc("FindRacksByIds", {"rackIds": [_mid(target)]}) or {}).get(
            "racks", []
        )
        row = next((r for r in rows if object_id(r.get("id")) == target), None)
        if row is None:
            return None, {"found": False}
        state = _rack_state(row)
        return check(state), {"state": state}

    return read


def _decommission_readback(kind):
    def read(adapter, target, response):
        row = _find_component(adapter, kind, target)
        if row is None:
            return True, {"found": False}
        state = lifecycle(row)["state"]
        gone = bool(row.get("deleted")) or "decommission" in state.lower()
        return (True if gone else None), {"state": state, "deleted": bool(row.get("deleted"))}

    return read


def _accepted_only(adapter, target, response):
    return None, {}


# ---- catalog -------------------------------------------------------------------

P_REASON = {"name": "reason", "label": "原因", "type": "text", "required": False}
P_REFERENCE = {
    "name": "reference",
    "label": "原因或工单链接",
    "type": "text",
    "required": True,
}
P_FORCE = {"name": "force_update", "label": "强制刷写", "type": "bool", "required": False}
RMS_TRAY = "compute_tray_backend 为 rms 时经 RMS 执行；为 core 时由 NICo 直接执行，不需要 RMS。"
RMS_SWITCH = "交换机电源与复位经 RMS 执行。"
RMS_SHELF = "power_shelf_backend 为 rms 时经 RMS 执行。"
RMS_RACK = "机柜维护由 NICo 编排，固件、NVOS 与 NMX-C 步骤经 RMS 执行。"
RMS_FIRMWARE = "组件固件更新经 RMS 执行。"

ON = ("ON", "POWERING_ON")
OFF = ("OFF", "POWERING_OFF")
RUNNING = ("ON", "POWERING_ON", "RESET")


def _entry(id, label, kind, rpc, risk, build, readback, **extra):
    return {
        "id": id,
        "label": label,
        "kind": kind,
        "rpc": rpc,
        "risk": risk,
        "needs_rms": extra.pop("needs_rms", False),
        "rms_reason": extra.pop("rms_reason", ""),
        "needs_confirm_serial": risk == "high",
        "state_guard": extra.pop("state_guard", False),
        "params": extra.pop("params", [P_REASON]),
        "effect": extra.pop("effect"),
        "available": True,
        "unavailable_reason": "",
        "build": build,
        "readback": readback,
        **extra,
    }


def _unavailable(id, label, kind, reason):
    return {
        "id": id,
        "label": label,
        "kind": kind,
        "rpc": "",
        "risk": "high",
        "needs_rms": False,
        "rms_reason": "",
        "needs_confirm_serial": True,
        "state_guard": False,
        "params": [],
        "effect": "",
        "available": False,
        "unavailable_reason": reason,
        "build": None,
        "readback": None,
    }


TRAY_COMPONENTS = [
    "COMPUTE_TRAY_COMPONENT_" + name
    for name in (
        "BMC",
        "BIOS",
        "CEC",
        "NIC",
        "CPLD_MB",
        "CPLD_PDB",
        "HGX_BMC",
        "COMBINED_BMC_UEFI",
        "GPU",
        "CX7",
    )
]
SWITCH_COMPONENTS = ["NV_SWITCH_COMPONENT_" + name for name in ("BMC", "CPLD", "BIOS", "NVOS")]
RESET_ACTIONS = [
    "COMPONENT_RESET_ACTION_" + name
    for name in ("BMC_RESET", "BMC_FACTORY_RESET", "NVOS_FACTORY_RESET", "SDN_FACTORY_RESET")
]
RACK_ACTIVITIES = ["firmware_upgrade", "nvos_update", "power_sequence", "configure_nmx_cluster"]


def _firmware_params(components):
    params = [
        {"name": "target_version", "label": "目标版本", "type": "text", "required": True},
        P_FORCE,
        P_REASON,
    ]
    if components:
        params.insert(
            1,
            {
                "name": "components",
                "label": "组件",
                "type": "multi",
                "required": False,
                "choices": components,
            },
        )
    return params


CATALOG = [
    # Machines: AdminPowerControl goes through the host BMC and needs no RMS.
    _entry(
        "power_on",
        "上电",
        "machine",
        "AdminPowerControl",
        "medium",
        _admin_power("On"),
        _power_readback("machine", ON),
        state_guard=True,
        effect="主机上电，可能从 PXE 或本地系统启动。",
    ),
    _entry(
        "graceful_shutdown",
        "正常关机",
        "machine",
        "AdminPowerControl",
        "medium",
        _admin_power("GracefulShutdown"),
        _power_readback("machine", OFF),
        state_guard=True,
        effect="由操作系统执行关机；系统无响应时可能不生效。",
    ),
    _entry(
        "force_off",
        "强制下电",
        "machine",
        "AdminPowerControl",
        "high",
        _admin_power("ForceOff"),
        _power_readback("machine", OFF),
        state_guard=True,
        effect="绕过操作系统直接断电，可能损坏正在写入的数据。",
    ),
    _entry(
        "graceful_restart",
        "正常重启",
        "machine",
        "AdminPowerControl",
        "medium",
        _admin_power("GracefulRestart"),
        _power_readback("machine", RUNNING),
        state_guard=True,
        effect="由操作系统执行重启；系统无响应时可能不生效。",
    ),
    _entry(
        "force_restart",
        "强制重启",
        "machine",
        "AdminPowerControl",
        "high",
        _admin_power("ForceRestart"),
        _power_readback("machine", RUNNING),
        state_guard=True,
        effect="相当于按下复位键，绕过操作系统，可能损坏正在写入的数据。",
    ),
    _entry(
        "ac_powercycle",
        "AC 断电重启",
        "machine",
        "AdminPowerControl",
        "high",
        _admin_power("ACPowercycle"),
        _power_readback("machine", RUNNING),
        state_guard=True,
        effect="相当于拔插电源线，绕过操作系统，可能损坏正在写入的数据；部分机型不支持。",
    ),
    _entry(
        "maintenance_enable",
        "设置维护标记",
        "machine",
        "SetMaintenance",
        "low",
        lambda target, params: _maintenance(target, params, "Enable"),
        _machine_readback(lambda o: bool(o["maintenance"])),
        params=[P_REFERENCE],
        effect="不改变硬件；NICo 停止向该主机分配实例。",
    ),
    _entry(
        "maintenance_disable",
        "清除维护标记",
        "machine",
        "SetMaintenance",
        "low",
        lambda target, params: _maintenance(target, params, "Disable"),
        _machine_readback(lambda o: not o["maintenance"]),
        effect="不改变硬件；NICo 恢复向该主机分配实例。",
    ),
    _entry(
        "quarantine_set",
        "隔离",
        "machine",
        "SetManagedHostQuarantineState",
        "high",
        _quarantine_set,
        _machine_readback(lambda o: bool(o["quarantine"])),
        state_guard=True,
        params=[{"name": "reason", "label": "隔离原因", "type": "text", "required": True}],
        effect="切断该主机的全部租户网络流量。",
    ),
    _entry(
        "quarantine_clear",
        "解除隔离",
        "machine",
        "ClearManagedHostQuarantineState",
        "medium",
        lambda target, params: {"machineId": _mid(target)},
        _machine_readback(lambda o: not o["quarantine"]),
        state_guard=True,
        effect="恢复该主机的租户网络流量。",
    ),
    _entry(
        "host_reset",
        "重置主机",
        "machine",
        "TriggerManagedHostReset",
        "high",
        lambda target, params: {"machineId": _mid(target), "mode": "Set", "initiator": "AdminCli"},
        _machine_readback(None),
        state_guard=True,
        effect="移除主机的实例与 DPF 资源后重新接入；有实例的主机 NICo 会拒绝。",
    ),
    _entry(
        "bmc_reset",
        "重启 BMC",
        "machine",
        "AdminBmcReset",
        "medium",
        lambda target, params: {"deviceId": {"machineId": _mid(target)}},
        _accepted_only,
        effect="重启主机 BMC，期间带外管理暂不可用，不影响主机运行。",
    ),
    _entry(
        "validation_on_demand",
        "按需硬件校验",
        "machine",
        "OnDemandMachineValidation",
        "high",
        _validation,
        _validation_readback,
        state_guard=True,
        params=[
            {"name": "tags", "label": "标签", "type": "list", "required": False},
            {"name": "contexts", "label": "上下文", "type": "list", "required": False},
            P_REASON,
        ],
        effect="在主机上运行测试，可能重启主机并改变状态机。",
    ),
    _entry(
        "sku_verify",
        "核对 SKU",
        "machine",
        "VerifySkuForMachine",
        "low",
        lambda target, params: {"id": target},
        _machine_readback(lambda o: bool(o["sku_verify_requested"])),
        effect="请求 NICo 重新核对主机硬件与 SKU 是否一致。",
    ),
    _entry(
        "tray_power_on",
        "计算托盘上电",
        "machine",
        "ComponentPowerControl",
        "medium",
        _component_power("machine", "ON"),
        _power_readback("machine", ON),
        state_guard=True,
        needs_rms=True,
        rms_reason=RMS_TRAY,
        effect="计算托盘上电。",
    ),
    _entry(
        "tray_power_off",
        "计算托盘下电",
        "machine",
        "ComponentPowerControl",
        "high",
        _component_power("machine", "FORCE_OFF"),
        _power_readback("machine", OFF),
        state_guard=True,
        needs_rms=True,
        rms_reason=RMS_TRAY,
        effect="计算托盘强制下电，可能损坏正在写入的数据。",
    ),
    _entry(
        "tray_power_restart",
        "计算托盘重启",
        "machine",
        "ComponentPowerControl",
        "high",
        _component_power("machine", "FORCE_RESTART"),
        _power_readback("machine", RUNNING),
        state_guard=True,
        needs_rms=True,
        rms_reason=RMS_TRAY,
        effect="计算托盘强制重启，可能损坏正在写入的数据。",
    ),
    # Switches.
    _entry(
        "switch_power_on",
        "交换机上电",
        "switch",
        "ComponentPowerControl",
        "medium",
        _component_power("switch", "ON"),
        _power_readback("switch", ON),
        needs_rms=True,
        rms_reason=RMS_SWITCH,
        effect="交换机上电。",
    ),
    _entry(
        "switch_power_off",
        "交换机下电",
        "switch",
        "ComponentPowerControl",
        "high",
        _component_power("switch", "FORCE_OFF"),
        _power_readback("switch", OFF),
        needs_rms=True,
        rms_reason=RMS_SWITCH,
        effect="交换机下电，经过它的链路全部中断。",
    ),
    _entry(
        "switch_power_restart",
        "交换机重启",
        "switch",
        "ComponentPowerControl",
        "high",
        _component_power("switch", "FORCE_RESTART"),
        _power_readback("switch", RUNNING),
        needs_rms=True,
        rms_reason=RMS_SWITCH,
        effect="交换机重启，期间经过它的链路中断。",
    ),
    _entry(
        "switch_reset",
        "交换机复位",
        "switch",
        "ComponentReset",
        "high",
        lambda target, params: _component_ids("switch", target) | {"action": params["action"]},
        _accepted_only,
        needs_rms=True,
        rms_reason=RMS_SWITCH,
        params=[
            {
                "name": "action",
                "label": "复位类型",
                "type": "choice",
                "required": True,
                "choices": RESET_ACTIONS,
            },
            P_REASON,
        ],
        effect="复位交换机 BMC，或恢复 BMC、NVOS、SDN 的出厂配置。",
    ),
    _entry(
        "switch_decommission",
        "交换机退役",
        "switch",
        "DecommissionSwitch",
        "high",
        lambda target, params: {"switchId": _mid(target)},
        _decommission_readback("switch"),
        effect="NICo 不再管理该交换机。",
    ),
    # Power shelves.
    _entry(
        "shelf_power_on",
        "供电框上电",
        "power_shelf",
        "SetPowerShelfMaintenance",
        "medium",
        _shelf_power("POWER_ON"),
        _power_readback("power_shelf", ON),
        needs_rms=True,
        rms_reason=RMS_SHELF,
        params=[
            {"name": "reference", "label": "原因或工单链接", "type": "text", "required": False}
        ],
        effect="供电框上电。",
    ),
    _entry(
        "shelf_power_off",
        "供电框下电",
        "power_shelf",
        "SetPowerShelfMaintenance",
        "high",
        _shelf_power("POWER_OFF"),
        _power_readback("power_shelf", OFF),
        needs_rms=True,
        rms_reason=RMS_SHELF,
        params=[
            {"name": "graceful", "label": "按操作系统顺序关机", "type": "bool", "required": False},
            {"name": "reference", "label": "原因或工单链接", "type": "text", "required": False},
        ],
        effect="供电框下电，由它供电的设备全部断电；未选按顺序关机时为强制下电。",
    ),
    _entry(
        "shelf_decommission",
        "供电框退役",
        "power_shelf",
        "DecommissionPowerShelf",
        "high",
        lambda target, params: {"powerShelfId": _mid(target)},
        _decommission_readback("power_shelf"),
        effect="NICo 不再管理该供电框。",
    ),
    # Racks.
    _entry(
        "rack_maintenance",
        "机柜维护",
        "rack",
        "OnDemandRackMaintenance",
        "high",
        _rack_maintenance,
        _rack_readback(lambda state: "maintenance" in state.lower()),
        needs_rms=True,
        rms_reason=RMS_RACK,
        params=[
            {
                "name": "activities",
                "label": "维护项目",
                "type": "multi",
                "required": True,
                "choices": RACK_ACTIVITIES,
            },
            {
                "name": "sot_json",
                "label": "SOT JSON",
                "type": "json",
                "required": False,
                "required_with": ["firmware_upgrade", "nvos_update"],
            },
            {"name": "components", "label": "固件组件", "type": "list", "required": False},
            P_FORCE,
            {"name": "machine_ids", "label": "限定主机", "type": "list", "required": False},
            {"name": "switch_ids", "label": "限定交换机", "type": "list", "required": False},
            {"name": "power_shelf_ids", "label": "限定供电框", "type": "list", "required": False},
            P_REASON,
        ],
        effect=(
            "按固件、NVOS、电源序列、NMX-C 的顺序执行所选项目；"
            "电源序列会正常重启机柜内全部计算主机。"
        ),
    ),
    _entry(
        "rack_maintenance_terminate",
        "终止机柜维护",
        "rack",
        "TerminateRackMaintenance",
        "medium",
        lambda target, params: {"rackId": _mid(target)},
        _rack_readback(lambda state: None if "maintenance" in state.lower() else True),
        needs_rms=True,
        rms_reason=RMS_RACK,
        effect="终止机柜当前的维护流程；已完成的步骤不会回退。",
    ),
    # Firmware. Power shelf firmware is not implemented by NICo and is not offered.
    _entry(
        "component_firmware_update_tray",
        "计算托盘固件更新",
        "machine",
        "UpdateComponentFirmware",
        "high",
        _firmware("machine"),
        _accepted_only,
        state_guard=True,
        needs_rms=True,
        rms_reason=RMS_FIRMWARE,
        params=_firmware_params(TRAY_COMPONENTS),
        effect="刷写计算托盘固件，不可回退；期间可能重启。",
    ),
    _entry(
        "component_firmware_update_switch",
        "交换机固件更新",
        "switch",
        "UpdateComponentFirmware",
        "high",
        _firmware("switch"),
        _accepted_only,
        needs_rms=True,
        rms_reason=RMS_FIRMWARE,
        params=_firmware_params(SWITCH_COMPONENTS),
        effect="刷写交换机固件，不可回退；期间链路可能中断。",
    ),
    _entry(
        "component_firmware_update_rack",
        "机柜固件更新",
        "rack",
        "UpdateComponentFirmware",
        "high",
        _firmware("rack"),
        _accepted_only,
        needs_rms=True,
        rms_reason=RMS_FIRMWARE,
        params=_firmware_params(None),
        effect="按 SOT 刷写机柜内组件固件，不可回退。",
    ),
    _unavailable("rack_power_on", "机柜上电", "rack", "NICo 机柜电源序列的上电/下电为空实现。"),
    _unavailable("rack_power_off", "机柜下电", "rack", "NICo 机柜电源序列的上电/下电为空实现。"),
    _unavailable("rack_cold_reboot", "机柜冷重启", "rack", "仅 RMS 直接提供，NICo 未接入。"),
]
ACTIONS = {entry["id"]: entry for entry in CATALOG}
PUBLIC_FIELDS = (
    "id",
    "label",
    "kind",
    "rpc",
    "risk",
    "needs_rms",
    "rms_reason",
    "needs_confirm_serial",
    "state_guard",
    "params",
    "effect",
    "available",
    "unavailable_reason",
)


def rms_status(adapter):
    """Whether RMS answers through Core; shown, never used to block an action."""
    try:
        response = adapter.rpc("GetRmsVersion", {}) or {}
    except Exception as error:  # noqa: BLE001 - any failure means "did not answer"
        return {"reachable": False, "version": "", "error": str(error) or "RMS 未响应。"}
    return {"reachable": True, "version": str(response.get("version") or ""), "error": ""}


def catalog(adapter):
    return {
        "actions": [{key: entry[key] for key in PUBLIC_FIELDS} for entry in CATALOG],
        "rms": rms_status(adapter),
        "limits": {"max_targets": MAX_TARGETS, "preview_seconds": PREVIEW_SECONDS},
    }


# ---- parameters ----------------------------------------------------------------


def _text(value):
    return isinstance(value, str) and value.strip() != ""


def normalize_params(entry, params):
    """Return the parameters the action accepts, or raise with the first problem."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RackActionsInvalid("参数格式无效。")
    known = {p["name"]: p for p in entry["params"]}
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise RackActionsInvalid("不支持的参数：" + "、".join(unknown) + "。")
    result = {}
    for name, spec in known.items():
        value = params.get(name)
        kind = spec["type"]
        if value in (None, "", []):
            if spec["required"]:
                raise RackActionsInvalid("缺少参数：" + spec["label"] + "。")
            continue
        if kind in ("text", "json"):
            if not _text(value) or len(value) > (1024 * 1024 if kind == "json" else 2000):
                raise RackActionsInvalid(spec["label"] + "应为非空文本。")
            if kind == "json":
                try:
                    json.loads(value)
                except ValueError:
                    raise RackActionsInvalid(spec["label"] + "不是有效的 JSON。") from None
            value = value.strip()
        elif kind == "bool":
            if not isinstance(value, bool):
                raise RackActionsInvalid(spec["label"] + "应为是或否。")
        elif kind == "choice":
            if value not in spec["choices"]:
                raise RackActionsInvalid(spec["label"] + "取值无效。")
        elif kind in ("list", "multi"):
            if not isinstance(value, list) or not all(_text(item) for item in value):
                raise RackActionsInvalid(spec["label"] + "应为非空文本列表。")
            value = list(dict.fromkeys(item.strip() for item in value))
            if kind == "multi" and any(item not in spec["choices"] for item in value):
                raise RackActionsInvalid(spec["label"] + "取值无效。")
        result[name] = value
    for name, spec in known.items():
        needed = [a for a in spec.get("required_with", []) if a in result.get("activities", [])]
        if needed and name not in result:
            raise RackActionsInvalid(f"所选维护项目需要{spec['label']}。")
    return result


def redact(params):
    """Parameters as recorded: credentials dropped, SOT JSON reduced to its digest."""
    recorded = {}
    for key, value in params.items():
        if any(word in key.lower() for word in REDACTED_KEYS):
            continue
        if key in ("sot_json", "target_version") and isinstance(value, str) and len(value) > 200:
            recorded[key] = {
                "sha256": hashlib.sha256(value.encode()).hexdigest(),
                "bytes": len(value.encode()),
            }
        else:
            recorded[key] = value
    return recorded


# ---- targets and checks --------------------------------------------------------


def _find_component(adapter, kind, target):
    if kind == "switch":
        rows = snake(adapter.rpc("FindSwitchesByIds", {"switchIds": [_mid(target)]}) or {}).get(
            "switches", []
        )
    else:
        rows = snake(
            adapter.rpc("FindPowerShelvesByIds", {"powerShelfIds": [_mid(target)]}) or {}
        ).get("power_shelves", [])
    return next((row for row in rows if object_id(row.get("id")) == target), None)


def _machine_serial(row):
    info = (row.get("status") or {}).get("discovery_info") or row.get("discovery_info") or {}
    dmi = (info.get("dmi_data") if isinstance(info, dict) else None) or {}
    return dmi.get("product_serial") or dmi.get("chassis_serial") or ""


def _rack_state(row):
    status = row.get("status") or {}
    return state_text((status.get("lifecycle") or {}).get("state") or row.get("rack_state"))


def _all_machines(adapter):
    ids = (adapter.rpc("FindMachineIds", {}) or {}).get("machineIds", [])
    if not ids:
        return []
    return snake(
        adapter.rpc("FindMachinesByIds", {"machineIds": ids, "includeHistory": False}) or {}
    ).get("machines", [])


def installation_state(state):
    """True for NICo lifecycle states in which PXEye or NICo is installing the host."""
    return state.startswith("HostInit") or (
        state.startswith("Assigned") and state != "Assigned/Ready"
    )


def _describe(adapter, kind, target):
    """What the checks need to know about one target; None when Core has no such object."""
    if kind == "machine":
        row = _machine_row(adapter, target)
        if row is None:
            return None
        serial = _machine_serial(row)
        return {
            "serial": serial,
            "name": (row.get("metadata") or {}).get("name", ""),
            "state": lifecycle(row)["state"],
            "host": str(row.get("machine_type") or "HOST") == "HOST",
            "serials": [serial] if serial else [],
        }
    if kind in ("switch", "power_shelf"):
        row = _find_component(adapter, kind, target)
        if row is None or row.get("deleted"):
            return None
        status = row.get("status") or {}
        serial = status.get("serial_number") or ""
        return {
            "serial": serial,
            "name": (row.get("metadata") or {}).get("name")
            or status.get("switch_name")
            or status.get("shelf_name")
            or "",
            "state": lifecycle(row)["state"],
            "host": True,
            "serials": [serial] if serial else [],
        }
    rows = snake(adapter.rpc("FindRacksByIds", {"rackIds": [_mid(target)]}) or {}).get("racks", [])
    row = next((r for r in rows if object_id(r.get("id")) == target), None)
    if row is None:
        return None
    members = [m for m in _all_machines(adapter) if value_id(m.get("rack_id")) == target]
    return {
        "serial": "",
        "name": (row.get("metadata") or {}).get("name", ""),
        "state": _rack_state(row),
        "host": True,
        "serials": [s for s in (_machine_serial(m) for m in members) if s],
    }


def check_target(app, entry, target):
    """One target's eligibility, with every reason it is refused."""
    result = {"target": target, "serial": "", "name": "", "state": "", "eligible": False}
    reasons = []
    try:
        described = _describe(app.adapter, entry["kind"], target)
    except Exception as error:  # noqa: BLE001 - an unreadable target is not eligible
        result["reasons"] = ["无法从 NICo 读取该对象：" + (str(error) or "未知错误") + "。"]
        return result
    if described is None:
        result["reasons"] = ["NICo 中不存在该对象。"]
        return result
    result.update({k: described[k] for k in ("serial", "name", "state")})
    if not described["host"]:
        reasons.append("仅支持主机，不支持 DPU 等其他机器类型。")
    busy = [serial for serial in described["serials"] if app.store.active(serial) is not None]
    if busy:
        reasons.append("设备有进行中的安装任务（" + "、".join(busy) + "），请先处理安装任务。")
    if entry["state_guard"] and entry["kind"] == "machine" and installation_state(result["state"]):
        reasons.append("主机处于安装相关状态（" + result["state"] + "），不执行该操作。")
    result["confirm_with"] = "serial" if result["serial"] else "id"
    result["eligible"] = not reasons
    result["reasons"] = reasons
    return result


def _request(body):
    action = body.get("action")
    entry = ACTIONS.get(action) if isinstance(action, str) else None
    if entry is None:
        raise RackActionsInvalid("操作不存在。")
    if not entry["available"]:
        raise RackActionsInvalid(entry["unavailable_reason"])
    targets = body.get("targets")
    if not isinstance(targets, list) or not targets or not all(_text(t) for t in targets):
        raise RackActionsInvalid("请选择操作对象。")
    targets = list(dict.fromkeys(t.strip() for t in targets))
    if len(targets) > MAX_TARGETS:
        raise RackActionsInvalid(f"一次最多操作 {MAX_TARGETS} 个对象，当前 {len(targets)} 个。")
    return entry, targets, normalize_params(entry, body.get("params"))


def preview(app, body, owner):
    if not isinstance(body, dict) or set(body) - {"action", "targets", "params"}:
        raise RackActionsInvalid("预览只接受 action、targets、params。")
    entry, targets, params = _request(body)
    checks = [check_target(app, entry, target) for target in targets]
    token = uuid.uuid4().hex
    app.store.preflight(
        token,
        {
            "kind": "rack_actions",
            "owner": owner,
            "action": entry["id"],
            "targets": targets,
            "params": params,
        },
        PREVIEW_SECONDS,
    )
    return {
        "preview_token": token,
        "expires_at": time.time() + PREVIEW_SECONDS,
        "action": {key: entry[key] for key in PUBLIC_FIELDS},
        "params": redact(params),
        "targets": checks,
    }


# ---- execution -----------------------------------------------------------------

RESULT_STATUS = {
    "COMPONENT_MANAGER_STATUS_CODE_SUCCESS": None,
    "COMPONENT_MANAGER_STATUS_CODE_OUTCOME_UNKNOWN": "unknown",
}


def _response_outcome(response):
    """None when Core accepted; else (status, message) from per-component results."""
    for item in (response or {}).get("results") or []:
        # Proto JSON omits enum zero: an absent status is SUCCESS.
        code = str(item.get("status") or "COMPONENT_MANAGER_STATUS_CODE_SUCCESS")
        status = RESULT_STATUS.get(code, "failed")
        if status:
            return status, (item.get("error") or code)
    return None


def operator(session, address):
    token = str((session or {}).get("token") or "")
    return "session:" + hashlib.sha256(token.encode()).hexdigest()[:12] + "@" + str(address)


def execute(app, body, session, address):
    if not isinstance(body, dict) or set(body) - {"preview_token", "confirm_serials"}:
        raise RackActionsInvalid("执行只接受 preview_token、confirm_serials。")
    confirms = body.get("confirm_serials") or {}
    if not isinstance(confirms, dict):
        raise RackActionsInvalid("确认序列号格式无效。")
    owner = (session or {}).get("token")
    request = app.store.claim_rack_action_preview(str(body.get("preview_token") or ""), owner)
    if request is None:
        raise RackActionsInvalid("预览已失效或已执行，请重新预览。")
    entry = ACTIONS[request["action"]]
    params = request["params"]
    who = operator(session, address)
    reason = params.get("reference") or params.get("reason") or ""
    results = []
    for target in request["targets"]:
        check = check_target(app, entry, target)
        expected = check["serial"] if check.get("confirm_with") == "serial" else target
        if check["eligible"] and entry["needs_confirm_serial"]:
            if str(confirms.get(target) or "").strip() != expected:
                check["eligible"] = False
                check["reasons"].append("高风险操作需要输入正确的序列号确认。")
        row = {
            "id": uuid.uuid4().hex,
            "operator": who,
            "action": entry["id"],
            "kind": entry["kind"],
            "targets": [{"target": target, "serial": check["serial"], "name": check["name"]}],
            "params": redact(params),
            "reason": reason,
            "checks": check,
            "status": "sent" if check["eligible"] else "refused",
            "core_message": "",
            "readback": None,
        }
        app.store.add_rack_action(row)
        if not check["eligible"]:
            results.append(_result(row))
            continue
        results.append(_result(_send(app, entry, target, params, row)))
    return {"action": entry["id"], "results": results}


def _send(app, entry, target, params, row):
    """Call Core once, then read back; never resend."""
    outcome, message, response = None, "", None
    try:
        response = app.adapter.rpc(entry["rpc"], entry["build"](target, params)) or {}
    except Exception as error:  # noqa: BLE001 - classified below, never retried
        message = str(error) or type(error).__name__
        # Only a refusal proven to happen before sending is a failure; anything
        # else (timeout, Core error text withheld by the transport) may have run.
        outcome = "failed" if getattr(error, "request_not_sent", False) else "unknown"
    if outcome is None:
        rejected = _response_outcome(response)
        if rejected:
            outcome, message = rejected
        else:
            message = str(response.get("msg") or "") or "NICo 已受理。"
    observed, matched = None, None
    if outcome != "failed":
        try:
            matched, observed = entry["readback"](app.adapter, target, response)
        except Exception as error:  # noqa: BLE001 - an unreadable state is unknown
            observed = {"error": str(error) or "读回失败。"}
        if matched is True:
            outcome = "succeeded"
        else:
            outcome = "unknown"
            if matched is None:
                message += " 读回无法确认结果，请在设备页查看状态，不要直接重复提交。"
            else:
                message += " 读回状态与预期不符，请在设备页查看状态，不要直接重复提交。"
    app.store.update_rack_action(row["id"], outcome, message.strip(), observed)
    return row | {"status": outcome, "core_message": message.strip(), "readback": observed}


def _result(row):
    return {
        "record_id": row["id"],
        "target": row["targets"][0]["target"],
        "serial": row["targets"][0]["serial"],
        "status": row["status"],
        "reasons": row["checks"].get("reasons", []),
        "core_message": row["core_message"],
        "readback": row["readback"],
    }


def records(app, query):
    try:
        limit = int((query.get("limit") or ["100"])[0])
    except ValueError:
        raise RackActionsInvalid("limit 应为整数。") from None
    target = (query.get("target") or [""])[0].strip()
    return {"records": app.store.rack_actions(max(1, min(limit, 500)), target or None)}


# ---- racks ---------------------------------------------------------------------


def racks(adapter):
    """Racks Core knows, with the expected-rack declarations; empty on general sites."""
    result = {"observed_at": time.time(), "racks": [], "expected": [], "errors": []}
    try:
        ids = (adapter.rpc("FindRackIds", {}) or {}).get("rackIds", [])
        rows = (
            snake(adapter.rpc("FindRacksByIds", {"rackIds": ids}) or {}).get("racks", [])
            if ids
            else []
        )
    except Exception:  # noqa: BLE001 - say which read is missing
        rows = []
        result["errors"].append("NICo 未返回机柜。")
    try:
        expected = snake(adapter.rpc("GetAllExpectedRacks", {}) or {}).get("expected_racks", [])
    except Exception:  # noqa: BLE001
        expected = []
        result["errors"].append("NICo 未返回机柜声明。")
    profiles = {
        value_id(object_id(e.get("rack_id"))): value_id(object_id(e.get("rack_profile_id")))
        for e in expected
    }
    counts = {}
    if rows:
        reads = (
            ("machines", lambda: _all_machines(adapter)),
            (
                "switches",
                lambda: snake(adapter.rpc("FindSwitches", {}) or {}).get("switches", []),
            ),
            (
                "power_shelves",
                lambda: snake(adapter.rpc("FindPowerShelves", {}) or {}).get("power_shelves", []),
            ),
        )
        for key, read in reads:
            try:
                for row in read():
                    rack = value_id(object_id(row.get("rack_id")))
                    if rack and not row.get("deleted"):
                        counts.setdefault(rack, {}).setdefault(key, []).append(
                            object_id(row.get("id"))
                        )
            except Exception:  # noqa: BLE001
                result["errors"].append("NICo 未返回机柜内设备（" + key + "）。")
    for row in rows:
        if row.get("deleted"):
            continue
        rack_id = object_id(row.get("id"))
        result["racks"].append(
            {
                "id": rack_id,
                "name": (row.get("metadata") or {}).get("name", ""),
                "state": _rack_state(row),
                "lifecycle": lifecycle(row),
                "health": health(row),
                "profile": profiles.get(rack_id) or "",
                "group": value_id(object_id(row.get("rack_group_id"))) or "",
                "devices": {
                    key: (counts.get(rack_id) or {}).get(key, [])
                    for key in ("machines", "switches", "power_shelves")
                },
            }
        )
    for item in expected:
        result["expected"].append(
            {
                "rack_id": value_id(object_id(item.get("rack_id"))) or "",
                "profile": value_id(object_id(item.get("rack_profile_id"))) or "",
                "group": value_id(object_id(item.get("rack_group_id"))) or "",
                "name": (item.get("metadata") or {}).get("name", ""),
                "labels": (item.get("metadata") or {}).get("labels") or [],
            }
        )
    return result
