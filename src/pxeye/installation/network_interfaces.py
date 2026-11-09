"""Freeze and render additional static host interfaces without changing boot selection."""

import ipaddress


def additional_interfaces(machine, intent, networks, boot_mac):
    result = []
    segments = {n["id"]: n for n in networks}
    if not any(
        n.get("mac_address", "").lower() == boot_mac.lower() for n in machine["interfaces"]
    ):
        raise ValueError("主启动接口未在设备网卡中找到。")
    for nic in machine.get("interfaces", []):
        mac = nic.get("mac_address", "").lower()
        if (
            mac == boot_mac.lower()
            or nic.get("role", "host") not in ("host", "unspecified", 0, 1)
            or not nic.get("fixed_ip")
        ):
            continue
        try:
            address = ipaddress.IPv4Interface(nic["fixed_ip"] + "/" + nic["fixed_mask"])
            network = segments[intent.get("network_bindings", {})[mac]]
            if network["segment_type"] != "HOST_INBAND" or network["state"] != "READY":
                raise ValueError()
            matches = [
                p
                for p in network["prefixes"]
                if p["prefix"] == str(address.network)
                and (p.get("gateway") or "") == (nic.get("fixed_gateway") or "")
            ]
            if len(matches) != 1 or address.ip in (
                address.network.network_address,
                address.network.broadcast_address,
            ):
                raise ValueError()
            result.append(
                {
                    "mac": mac,
                    "address": str(address),
                    "gateway": nic.get("fixed_gateway") or "",
                    "mtu": network["mtu"],
                    "network_id": network["id"],
                    "network_revision": network["revision"],
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("附加网卡 " + mac + " 地址或子网配置不可用：" + str(error)) from None
    return result


def render_interfaces(network, interfaces):
    ethernets = network.setdefault("ethernets", {})
    for row in interfaces:
        key = "nic_" + row["mac"].replace(":", "")
        if key in ethernets or any(
            n.get("match", {}).get("macaddress", "").lower() == row["mac"]
            for n in ethernets.values()
        ):
            raise ValueError("附加网卡与安装模板中的接口重复。")
        ethernets[key] = {
            "match": {"macaddress": row["mac"]},
            "dhcp4": False,
            "dhcp6": False,
            "addresses": [row["address"]],
            "mtu": row["mtu"],
            "optional": True,
        }
        # A gateway alone cannot specify a destination route. Keep the existing
        # management default; do not invent policy routing or competing defaults.
