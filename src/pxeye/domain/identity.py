"""Read-only device selection context; history never asserts a live OS exists."""

import ipaddress


def selection_identity(device, networks, hardware=None, history=None):
    hardware = hardware or {}
    primary = next(
        (
            n
            for n in device.get("interfaces", [])
            if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
        ),
        {},
    )
    mac = primary.get("mac_address", "").lower()
    network_id = device.get("intent", {}).get("network_bindings", {}).get(mac)
    network = next((n for n in networks if n["id"] == network_id), {})
    address = primary.get("fixed_ip") or device.get("planned_ip")
    try:
        ip = ipaddress.ip_address(address) if address else None
    except ValueError:
        ip = None

    def prefixes(segment):
        found = set()
        for entry in segment.get("prefixes", []):
            try:
                net = ipaddress.ip_network(entry["prefix"])
            except (KeyError, TypeError, ValueError):
                continue
            if net.version == 4 and (ip is None or ip in net):
                found.add(str(net))
        return found

    # Use observed NICo prefixes. A device mask must not invent a subnet.
    # An explicit binding is authoritative, even if it is currently missing.
    if not network_id and ip is not None:
        matches = [n for n in networks if n["segment_type"] == "HOST_INBAND" and prefixes(n)]
        if len(matches) == 1:
            network = matches[0]
    actual_prefixes = prefixes(network)
    prefix = next(iter(actual_prefixes)) if len(actual_prefixes) == 1 else None
    return {
        "architecture": hardware.get("architecture"),
        "cpu_models": list(
            dict.fromkeys(c["model"] for c in hardware.get("cpus", []) if c.get("model"))
        ),
        "manufacturer": hardware.get("manufacturer"),
        "model": hardware.get("model"),
        "hardware_source": "NICo / Scout最近回报" if hardware else None,
        "management_network_id": network.get("id") or network_id,
        "management_network_name": network.get("name"),
        "management_prefix": prefix,
        "management_ip": address,
        "management_mac": mac,
        "os_history": history,
        "current_os": "unknown",
    }


def installation_history(task):
    report = task.get("after_reboot") or task.get("initial") or {}
    device = task.get("execution_device") or {}
    return {
        "task_id": task["id"],
        "completed_at": task.get("completed_at"),
        "instance_id": task.get("instance_id"),
        "hostname": report.get("hostname") or task.get("hostname"),
        "os_release": report.get("os_release") or device.get("os_release"),
        "management_ip": task.get("management_ip"),
    }
