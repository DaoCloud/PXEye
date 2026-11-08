"""Capability-based Redfish boot selection, with isolated observed OEM adapters."""


def in_uefi(system):
    progress = system.get("BootProgress", {}).get("LastState")
    return progress == "SetupEntered" or any(
        isinstance(v, dict) and v.get("SystemStatus") == "SystemRunningInUEFI"
        for v in system.get("Oem", {}).values()
    )


def selection(adapter, device, system, target):
    if system.get("SerialNumber") != device["serial"] or target not in ("Hdd", "Pxe"):
        raise RuntimeError("启动控制目标或BMC身份不一致。")
    boot = system.get("Boot", {})
    preferred = (
        adapter.config.get("boot_handoff", {}).get(device["serial"], {}).get("method", "auto")
    )
    if (
        preferred != "oem_order"
        and target in boot.get("BootSourceOverrideTarget@Redfish.AllowableValues", [])
        and "Once" in boot.get("BootSourceOverrideEnabled@Redfish.AllowableValues", [])
    ):
        return {
            "method": "redfish-once",
            "suffix": "",
            "before": boot,
            "body": {
                "Boot": {"BootSourceOverrideTarget": target, "BootSourceOverrideEnabled": "Once"}
            },
        }
    # This adapter is selected by discovered links/schema, never by CPU architecture.
    links = system.get("Oem", {}).get("Lenovo", {}).get("BootSettings", {})
    root = device["redfish_system"]
    uri = links.get("@odata.id", "")
    if not uri.startswith(root + "/") or ".." in uri or "?" in uri:
        raise RuntimeError("BMC未提供可核实的启动目标设置能力；保留现场。")
    suffix = uri[len(root) :] + "/BootOrder.BootOrder"
    try:
        current = adapter.redfish(device, suffix)
    except RuntimeError as first_error:
        # Older Lenovo XCC can leave an advertised child resource temporarily
        # stale during UEFI POST.  Re-read the public collection, prove that the
        # exact child is still advertised, then retry this read once.  No write
        # plan is returned unless the complete child resource is available.
        collection = adapter.redfish(device, uri[len(root) :])
        members = {
            member.get("@odata.id")
            for member in collection.get("Members", [])
            if isinstance(member, dict)
        }
        child_uri = uri + "/BootOrder.BootOrder"
        if child_uri not in members:
            raise first_error
        current = adapter.redfish(device, suffix)
    name = {"Hdd": "Hard Disk", "Pxe": "Network"}[target]
    supported = current.get("BootOrderSupported", [])
    order = current.get("BootOrderNext", [])
    if (
        not current.get("@odata.type", "").startswith("#LenovoBootManager.")
        or name not in supported
        or not order
        or any(x not in supported for x in order)
    ):
        raise RuntimeError("BMC启动顺序能力或目标读回不完整。")
    wanted = [name] + list(dict.fromkeys(x for x in order if x != name))
    plan = {
        "method": "oem-order",
        "suffix": suffix,
        "before": current,
        "body": {"BootOrderNext": wanted},
    }
    if target == "Hdd":
        # Older Lenovo firmware represents Hard Disk as a category with its own
        # order.  A valid Ubuntu NVRAM entry can still hang when it is first in
        # that category, while the unique physical-disk entry boots the same ESP
        # through EFI/BOOT.  Change this nested order only when the physical
        # target is unambiguous; never guess among multiple disks.
        disk_suffix = uri[len(root) :] + "/BootOrder.HardDiskBootOrder"
        disk_order = adapter.redfish(device, disk_suffix)
        supported = disk_order.get("BootOrderSupported", [])
        order = disk_order.get("BootOrderNext", [])
        physical = [entry for entry in order if entry.startswith("UEFI:")]
        if (
            disk_order.get("@odata.type", "").startswith("#LenovoBootManager.")
            and len(physical) == 1
            and order
            and all(entry in supported for entry in order)
            and order[0] != physical[0]
        ):
            plan["suborders"] = [
                {
                    "suffix": disk_suffix,
                    "before": disk_order,
                    "body": {
                        "BootOrderNext": [physical[0]]
                        + [entry for entry in order if entry != physical[0]]
                    },
                }
            ]
    return plan


def apply(adapter, device, plan):
    writes = [*plan.get("suborders", []), plan]
    for write in writes:
        adapter.redfish(device, write["suffix"], "PATCH", write["body"])
        actual = adapter.redfish(device, write["suffix"])
        expected = write["body"]
        if plan["method"] == "redfish-once":
            expected = expected["Boot"]
            actual = actual.get("Boot", {})
        if any(actual.get(k) != v for k, v in expected.items()):
            raise RuntimeError("启动目标未读回确认，不发送重启或重复写请求。")
