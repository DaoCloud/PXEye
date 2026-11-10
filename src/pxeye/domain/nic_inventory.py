"""Read-only NIC attributes shared by collection, merging and spreadsheet export."""

INVENTORY_FIELDS = (
    "name",
    "vendor",
    "model",
    "adapter_id",
    "adapter_name",
    "interface_id",
    "adapter_serial",
    "part_number",
    "firmware_version",
    "location",
    "slot",
    "physical_port",
    "interface_kind",
    "permanent_mac",
    "speed_mbps",
    "max_speed_mbps",
    "link_status",
    "interface_enabled",
    "health",
    "state",
    "auto_neg",
    "full_duplex",
    "mtu",
    "port_maximum_mtu",
    "link_technology",
    "reported_capable_speeds_mbps",
    "reported_max_speed_bps",
    "lldp_chassis_id",
    "lldp_port_id",
    "lldp_system_name",
    "numa_node",
    "pci_path",
    "description",
    "observed_ipv4",
    "observed_ipv6",
    "redfish_adapter_path",
    "redfish_port_path",
    "inventory_source",
    "inventory_read_at",
    "inventory_note",
)


def nic_mac(value):
    """Normalize firmware's compact AssociatedNetworkAddresses MACs as well."""
    import re

    value = str(value or "").lower().replace(":", "").replace("-", "")
    return (
        ":".join(value[i : i + 2] for i in range(0, 12, 2))
        if re.fullmatch(r"[0-9a-f]{12}", value)
        else ""
    )
