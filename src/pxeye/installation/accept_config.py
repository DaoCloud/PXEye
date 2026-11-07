"""Validate target YAML in the UI backend without a target PyYAML dependency."""

import ipaddress

import yaml


def validate_config(result, device, task):
    # Do not persist the raw installer document: it can contain password hashes.
    documents = result.pop("_config_yaml", None)
    if not result.get("passed"):
        return result
    try:
        if not isinstance(documents, dict):
            raise ValueError("CONFIG_EVIDENCE_MISSING")
        net = yaml.safe_load(documents["netplan"])
        network = net.get("network", net)
        interface = result["report"]["management_interface"]
        plan = task.get("installation_plan") or {}
        mac = plan.get("boot_mac") or device["boot_mac"]
        matches = [
            nic
            for name, nic in network.get("ethernets", {}).items()
            if name == interface
            or nic.get("set-name") == interface
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
        installer = yaml.safe_load(documents["installer"])
        if installer["autoinstall"]["identity"]["hostname"] != task["hostname"]:
            raise ValueError("INSTALLER_HOSTNAME_MISMATCH")
        result["report"]["checks"]["network"] = True
        return result
    except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as error:
        # Parser errors can quote the source. Never expose raw YAML in task errors.
        message = (
            str(error)
            if isinstance(error, ValueError)
            and str(error).startswith(("NETPLAN_", "INSTALLER_", "CONFIG_"))
            else "CONFIG_YAML_INVALID"
        )
        return {"passed": False, "error": message, "type": type(error).__name__}
