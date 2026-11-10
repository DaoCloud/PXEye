"""Validate target YAML in the UI backend without a target PyYAML dependency."""

import ipaddress

import yaml


def validate_network(documents, result, device, task):
    net = yaml.safe_load(documents["netplan"])
    network = net.get("network", net)
    interface = result["report"].get("management_interface")
    plan = task.get("installation_plan") or {}
    mac = plan.get("boot_mac") or device["boot_mac"]
    matches = [
        nic
        for name, nic in network.get("ethernets", {}).items()
        if (interface and (name == interface or nic.get("set-name") == interface))
        or str(nic.get("match", {}).get("macaddress", "")).lower() == mac.lower()
    ]
    if len(matches) != 1:
        raise ValueError("NETPLAN_MANAGEMENT_INTERFACE_MISMATCH")
    nic = matches[0]
    address = str(
        ipaddress.ip_interface(
            str(plan.get("management_ip", device["management_ip"]))
            + "/"
            + str(plan.get("prefixlen", device["prefixlen"]))
        )
    )
    if nic.get("dhcp4") is not False or address not in [
        str(ipaddress.ip_interface(a)) for a in nic.get("addresses", [])
    ]:
        raise ValueError("NETPLAN_MANAGEMENT_ADDRESS_MISMATCH")
    gateway = plan.get("gateway", device["gateway"])
    if not (
        nic.get("gateway4") == gateway
        or any(
            route.get("to") in ("default", "0.0.0.0/0") and route.get("via") == gateway
            for route in nic.get("routes", [])
        )
    ):
        raise ValueError("NETPLAN_DEFAULT_ROUTE_MISMATCH")
    expected_dns = plan.get("dns_servers") or [device["dns"]]
    actual_dns = nic.get("nameservers", {}).get("addresses", [])
    if [str(ipaddress.ip_address(a)) for a in actual_dns] != [
        str(ipaddress.ip_address(a)) for a in expected_dns
    ]:
        raise ValueError("NETPLAN_DNS_MISMATCH")
    for extra in plan.get("os_interfaces", []):
        matches = [
            n
            for n in network.get("ethernets", {}).values()
            if str(n.get("match", {}).get("macaddress", "")).lower() == extra["mac"]
        ]
        if len(matches) != 1:
            raise ValueError("NETPLAN_ADDITIONAL_INTERFACE_MISMATCH")
        n = matches[0]
        if (
            n.get("dhcp4") is not False
            or extra["address"] not in n.get("addresses", [])
            or n.get("mtu") != extra["mtu"]
        ):
            raise ValueError("NETPLAN_ADDITIONAL_ADDRESS_MISMATCH")
        if n.get("gateway4") or any(
            r.get("to") in ("default", "0.0.0.0/0") for r in n.get("routes", [])
        ):
            raise ValueError("NETPLAN_ADDITIONAL_DEFAULT_ROUTE")


def validate_installer(documents, task):
    installer = yaml.safe_load(documents["installer"])
    if installer["autoinstall"]["identity"]["hostname"] != task["hostname"]:
        raise ValueError("INSTALLER_HOSTNAME_MISMATCH")


def validate_config(result, device, task):
    # Do not persist the raw installer document: it can contain password hashes.
    documents = result.pop("_config_yaml", None)
    if not result.get("report"):
        return result
    report = result["report"]
    checks = report.setdefault("checks", {})
    errors = report.setdefault("check_errors", {})
    if not result.get("passed") and not errors:
        # Preserve unexpected collection failures rather than accepting partial evidence.
        errors["identity"] = [result.get("error") or "CONFIG_EVIDENCE_MISSING"]
        checks["identity"] = False
    for name, validate in (
        ("network", lambda: validate_network(documents, result, device, task)),
        ("installer", lambda: validate_installer(documents, task)),
    ):
        if name in report.get("acceptance_skips", {}):
            checks[name] = None
            continue
        try:
            if not isinstance(documents, dict):
                raise ValueError("CONFIG_EVIDENCE_MISSING")
            validate()
            checks.setdefault(name, True)
        except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as error:
            # Parser errors can quote the source. Never expose raw YAML in task errors.
            message = (
                str(error)
                if isinstance(error, ValueError)
                and str(error).startswith(("NETPLAN_", "INSTALLER_", "CONFIG_"))
                else "CONFIG_YAML_INVALID"
            )
            checks[name] = False
            errors.setdefault(name, []).append(message)
    result["passed"] = not errors
    result["error"] = "；".join(message for messages in errors.values() for message in messages)
    return result
