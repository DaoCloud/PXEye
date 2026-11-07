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
    return {
        "method": "oem-order",
        "suffix": suffix,
        "before": current,
        "body": {"BootOrderNext": wanted},
    }


def apply(adapter, device, plan):
    adapter.redfish(device, plan["suffix"], "PATCH", plan["body"])
    actual = adapter.redfish(device, plan["suffix"])
    expected = plan["body"]
    if plan["method"] == "redfish-once":
        expected = expected["Boot"]
        actual = actual.get("Boot", {})
    if any(actual.get(k) != v for k, v in expected.items()):
        raise RuntimeError("启动目标未读回确认，不发送重启或重复写请求。")
