"""Collect optional host NIC and physical port facts without guessing port order."""

import time

from pxeye.domain.nic_inventory import nic_mac
from pxeye.domain.pci import merge_host_nics, redfish_pci_address


def host_nics(read, system, chassis, ethernet, bmc):
    observed = []
    cache = {}
    lenovo = "lenovo" in str(system.get("Manufacturer", "")).lower()
    read_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def resources(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, list):
            for item in value[:256]:
                yield from resources(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        path = value.get("@odata.id")
        if not path:
            return
        if path not in cache:
            if len(cache) >= 256:
                return
            cache[path] = None
            try:
                cache[path] = read(path)
            except (ValueError, RuntimeError):
                return  # Optional inventory may be unsupported on older firmware.
        report = cache[path]
        if not isinstance(report, dict):
            return
        if "Members" in report:
            yield from resources(report["Members"], depth + 1)
        else:
            yield report

    def links(report, name):
        return resources((report.get("Links") or {}).get(name))

    def network_functions(report):
        yield from resources(report.get("NetworkDeviceFunctions"))
        yield from links(report, "NetworkDeviceFunctions")

    def nic_values(report):
        eth = report.get("Ethernet") or report
        hardware = eth.get("MACAddress") or eth.get("PermanentMACAddress")
        fields = {
            "interface_id": report.get("Id") if report.get("MACAddress") else None,
            "permanent_mac": nic_mac(eth.get("PermanentMACAddress")),
            "speed_mbps": report.get("SpeedMbps"),
            "link_status": str(report.get("LinkStatus") or "").removeprefix("Link"),
            "interface_enabled": report.get("InterfaceEnabled", report.get("DeviceEnabled")),
            "health": (report.get("Status") or {}).get("Health"),
            "state": (report.get("Status") or {}).get("State"),
            "auto_neg": report.get("AutoNeg"),
            "full_duplex": report.get("FullDuplex"),
            "mtu": eth.get("MTUSize"),
            "description": report.get("Description"),
            "interface_kind": "host_to_bmc"
            if (report.get("Links") or {}).get("HostInterface")
            else "",
            "observed_ipv4": "; ".join(
                str(a.get("Address")) for a in report.get("IPv4Addresses") or [] if a.get("Address")
            ),
            "observed_ipv6": "; ".join(
                str(a.get("Address")) for a in report.get("IPv6Addresses") or [] if a.get("Address")
            ),
            "inventory_source": "Redfish",
            "inventory_read_at": read_at,
        }
        return (
            [
                {
                    "mac_address": hardware,
                    "name": report.get("Name") or report.get("Id", ""),
                    **{k: v for k, v in fields.items() if v is not None and v != ""},
                }
            ]
            if hardware
            else []
        )

    def adapter_ports(adapter, functions):
        controllers = adapter.get("Controllers") or []
        locations = [c.get("Location") or {} for c in controllers]
        if adapter.get("Location"):
            locations.append(adapter["Location"])
        labels, slots = set(), set()
        for loc in locations:
            part = loc.get("PartLocation") or {}
            label = part.get("ServiceLabel") or loc.get("Info")
            if label:
                labels.add(str(label))
            if part.get("LocationOrdinalValue") is not None:
                slots.add(str(part["LocationOrdinalValue"]))
        versions = {
            str(c["FirmwarePackageVersion"]) for c in controllers if c.get("FirmwarePackageVersion")
        }
        context = {
            "adapter_id": adapter.get("Id"),
            "adapter_name": adapter.get("Name"),
            "redfish_adapter_path": adapter.get("@odata.id"),
            "vendor": adapter.get("Manufacturer"),
            "model": adapter.get("Name")
            if adapter.get("Model") in (None, "", "N/A")
            else adapter.get("Model"),
            "adapter_serial": adapter.get("SerialNumber"),
            "part_number": adapter.get("PartNumber"),
            "firmware_version": next(iter(versions)) if len(versions) == 1 else "",
            "location": next(iter(labels)) if len(labels) == 1 else "",
            "slot": next(iter(slots)) if len(slots) == 1 else "",
            "inventory_source": "Redfish",
            "inventory_read_at": read_at,
        }
        context = {k: v for k, v in context.items() if v is not None and v not in ("", "N/A")}
        ports = {}
        for key in ("NetworkPorts", "Ports"):
            for port in [*resources(adapter.get(key)), *links(adapter, key)]:
                ports[port.get("@odata.id")] = port
            for controller in controllers:
                for port in links(controller, key):
                    ports[port.get("@odata.id")] = port
        assigned = {}
        for function in functions:
            values = nic_values(function)
            observed.extend({**n, **context} for n in values)
            for key in ("PhysicalPortAssignment", "PhysicalNetworkPortAssignment"):
                for port in [*resources(function.get(key)), *links(function, key)]:
                    path = port.get("@odata.id")
                    ports[path] = port
                    assigned.setdefault(path, []).extend(values)
        for path, port in ports.items():
            hardware = {nic_mac(m) for m in port.get("AssociatedNetworkAddresses") or []}
            hardware.update(n["mac_address"] for n in assigned.get(path, []))
            speed = port.get("CurrentLinkSpeedMbps")
            if speed is None and isinstance(port.get("CurrentSpeedGbps"), (int, float)):
                speed = port["CurrentSpeedGbps"] * 1000
            capable = [
                v
                for c in port.get("SupportedLinkCapabilities") or []
                for v in c.get("CapableLinkSpeedMbps") or []
                if type(v) in (int, float) and v > 0
            ]
            maximum = port.get("MaxSpeedGbps")
            maximum = maximum * 1000 if type(maximum) in (int, float) else None
            suspect = any(v > 1000000 for v in capable)
            if maximum is None and capable and not suspect:
                maximum = max(capable)
            lldp = (port.get("Ethernet") or {}).get("LLDPReceive") or {}
            fields = {
                **context,
                "physical_port": port.get("PhysicalPortNumber"),
                "interface_kind": "physical_port",
                "redfish_port_path": path,
                "speed_mbps": speed,
                "max_speed_mbps": maximum,
                "link_status": str(port.get("LinkStatus") or "").removeprefix("Link"),
                "port_maximum_mtu": port.get("PortMaximumMTU"),
                "link_technology": port.get("ActiveLinkTechnology")
                or port.get("LinkNetworkTechnology"),
                "reported_capable_speeds_mbps": ", ".join(str(v) for v in capable),
                "reported_max_speed_bps": (port.get("Oem") or {})
                .get("Lenovo", {})
                .get("PortMaxSpeedbps"),
                "lldp_chassis_id": lldp.get("ChassisId"),
                "lldp_port_id": lldp.get("PortId"),
                "lldp_system_name": lldp.get("SystemName"),
                "inventory_note": "Reported maximum speed has suspect units; raw values retained."
                if suspect
                else "",
            }
            fields = {k: v for k, v in fields.items() if v is not None and v != ""}
            for address in hardware - {""}:
                observed.append({"mac_address": address, **fields})

    def function_nics(function, attached=()):
        nics = list(attached) + nic_values(function)
        for key in ("EthernetInterfaces", "NetworkDeviceFunctions"):
            for related in links(function, key):
                nics += nic_values(related)
                for eth in links(related, "EthernetInterface"):
                    nics += nic_values(eth)
        address = redfish_pci_address(function, lenovo=lenovo)
        observed.extend({**nic, "pci_address": address} for nic in nics)

    def network_function(report, attached=()):
        nics = list(attached) + nic_values(report)
        for key in ("EthernetInterface", "EthernetInterfaces"):
            for eth in links(report, key):
                nics += nic_values(eth)
        observed.extend(nics)
        for key in ("PCIeFunction", "PCIeFunctions"):
            for function in links(report, key):
                function_nics(function, nics)

    for nic in ethernet:
        observed.extend(nic_values(nic))

    # Traverse only chassis associated with this System. Single-chassis legacy
    # BMCs may omit the association; never use an unrelated multi-chassis card.
    chassis_ids = {
        r.get("@odata.id")
        for r in (system.get("Links") or {}).get("Chassis", [])
        if isinstance(r, dict)
    }
    relevant = [c for c in chassis if c.get("@odata.id") in chassis_ids]
    relevant += [
        c
        for c in chassis
        if c not in relevant
        and system.get("@odata.id")
        and any(
            isinstance(link, dict) and link.get("@odata.id") == system["@odata.id"]
            for link in (c.get("Links") or {}).get("ComputerSystems", [])
        )
    ]
    if not relevant and not chassis_ids and len(chassis) == 1:
        relevant = chassis
    # A shared chassis can contain adapters belonging to another blade/System.
    # Only explicit System NIC/function links are safe in that case.
    relevant = [
        c
        for c in relevant
        if not any(
            isinstance(link, dict) and link.get("@odata.id") != system.get("@odata.id")
            for link in (c.get("Links") or {}).get("ComputerSystems", [])
        )
    ]
    # Prioritize physical port facts within the existing bounded identity-read budget.
    for container in [system, *relevant]:
        adapters = list(resources(container.get("NetworkAdapters")))
        adapters += list(links(container, "NetworkAdapters"))
        interface_functions = []
        for interface in resources(container.get("NetworkInterfaces")):
            adapters += list(links(interface, "NetworkAdapter"))
            interface_functions += list(network_functions(interface))
        for adapter in adapters:
            functions = list(network_functions(adapter))
            for controller in adapter.get("Controllers") or []:
                functions += list(links(controller, "NetworkDeviceFunctions"))
            adapter_ports(adapter, functions)
            for function in functions:
                network_function(function)
        for function in interface_functions:
            network_function(function)
    for nic in ethernet:
        network_function(nic)
        for key in ("NetworkDeviceFunction", "NetworkDeviceFunctions"):
            for function in links(nic, key):
                network_function(function, nic_values(nic))

    for container in [system, *relevant]:
        functions = list(resources(container.get("PCIeFunctions")))
        functions += list(links(container, "PCIeFunctions"))
        for function in functions:
            function_nics(function)
        devices = list(resources(container.get("PCIeDevices")))
        devices += list(links(container, "PCIeDevices"))
        for device in devices:
            functions = list(resources(device.get("PCIeFunctions")))
            functions += list(links(device, "PCIeFunctions"))
            for function in functions:
                function_nics(function)
    return merge_host_nics([observed], bmc)
