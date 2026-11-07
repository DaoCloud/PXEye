"""Load the standalone code shipped to a target without depending on process cwd."""

from pathlib import Path


def script_source(name):
    if name not in {
        "disk_identity.py",
        "apt_preflight.py",
        "accept_config.py",
        "accept_host.py",
        "installer_runtime.py",
    }:
        raise ValueError("Unknown installation script")
    return Path(__file__).with_name(name).read_text()
