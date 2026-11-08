"""Create an Ubuntu autoinstall template with no machine-specific disk or NIC identity."""

import copy
import re

import yaml


OFFLINE_MIRROR = "http://127.0.0.1/pxeye-offline"


def apply_software_install(ai, packages=None, apt=None):
    """Apply only explicitly configured packages and mirrors."""
    ai.pop("packages", None)
    if packages:
        ai["packages"] = copy.deepcopy(packages)
    if apt:
        ai["apt"] = copy.deepcopy(apt)
    else:
        ai["apt"] = {
            "geoip": False,
            # Keep the legacy primary shape for Ubuntu 22.04 media compatibility.
            # Loopback fails immediately, then Subiquity selects its ISO-backed
            # offline path without sending mirror traffic outside the installer.
            "primary": [{"arches": ["default"], "uri": OFFLINE_MIRROR}],
            "fallback": "offline-install",
        }
    ai.setdefault("source", {})["search_drivers"] = False
    ai["drivers"] = {"install": False}
    return ai


def generic_ubuntu(source, username, dns, timezone, ntp):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
        raise ValueError("安装用户名称无效。")
    original = yaml.safe_load(source["user_data"])["autoinstall"]
    ai = {
        "version": 1,
        "locale": original.get("locale", "en_US.UTF-8"),
        "keyboard": original.get("keyboard", {"layout": "us"}),
        "identity": {"hostname": "pending", "username": username, "password": "!"},
        "ssh": {
            "install-server": True,
            "allow-pw": False,
            "authorized-keys": original["ssh"]["authorized-keys"],
        },
        "network": {
            "version": 2,
            "ethernets": {
                "management": {
                    "dhcp4": False,
                    "dhcp6": False,
                    "addresses": ["192.0.2.2/24"],
                    "routes": [{"to": "default", "via": "192.0.2.1"}],
                    "nameservers": {"addresses": [dns]},
                }
            },
        },
        "storage": {
            "swap": {"size": 0},
            "config": [
                {
                    "type": "disk",
                    "id": "os-disk",
                    "ptable": "gpt",
                    "preserve": False,
                    "wipe": "superblock-recursive",
                    "grub_device": False,
                },
                {
                    "type": "partition",
                    "id": "efi",
                    "device": "os-disk",
                    "number": 1,
                    "size": "1G",
                    "flag": "boot",
                    "preserve": False,
                    "grub_device": True,
                },
                {"type": "format", "id": "efi-format", "volume": "efi", "fstype": "fat32"},
                {
                    "type": "partition",
                    "id": "root",
                    "device": "os-disk",
                    "number": 2,
                    "size": -1,
                    "preserve": False,
                },
                {"type": "format", "id": "root-format", "volume": "root", "fstype": "ext4"},
                {"type": "mount", "id": "root-mount", "device": "root-format", "path": "/"},
                {"type": "mount", "id": "efi-mount", "device": "efi-format", "path": "/boot/efi"},
            ],
        },
        "late-commands": [
            "printf '%s\\n' '"
            + username
            + " ALL=(ALL) NOPASSWD:ALL' > /target/etc/sudoers.d/90-nico-operator",
            "chmod 0440 /target/etc/sudoers.d/90-nico-operator",
        ],
        "user-data": {
            "ssh_deletekeys": False,
            "timezone": timezone,
            "ntp": {"enabled": True, "servers": [ntp]},
        },
        "shutdown": "reboot",
        "refresh-installer": {"update": False},
    }
    apply_software_install(ai)
    result = {k: copy.deepcopy(v) for k, v in source.items() if k != "user_data"}
    result["run_provisioning_instructions_on_every_boot"] = False
    result["phone_home_enabled"] = False
    result["user_data"] = "#cloud-config\n" + yaml.safe_dump({"autoinstall": ai}, sort_keys=False)
    return result
