"""Collect optional MAC-to-PCI function links without guessing card port order."""

from pxeye.domain.pci import merge_host_nics, redfish_pci_address


def host_nics(read, system, chassis, ethernet, bmc):
    observed = []
    cache = {}
    lenovo = "lenovo" in str(system.get("Manufacturer", "")).lower()

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
        return (
            [{"mac_address": hardware, "name": report.get("Name") or report.get("Id", "")}]
            if hardware
            else []
        )

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
        network_function(nic)
        for key in ("NetworkDeviceFunction", "NetworkDeviceFunctions"):
            for function in links(nic, key):
                network_function(function, nic_values(nic))

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
        adapters = list(resources(container.get("NetworkAdapters")))
        adapters += list(links(container, "NetworkAdapters"))
        for interface in resources(container.get("NetworkInterfaces")):
            adapters += list(links(interface, "NetworkAdapter"))
            for function in network_functions(interface):
                network_function(function)
        for adapter in adapters:
            functions = list(network_functions(adapter))
            for controller in adapter.get("Controllers") or []:
                functions += list(links(controller, "NetworkDeviceFunctions"))
            for function in functions:
                network_function(function)
    return merge_host_nics([observed], bmc)
