"""Transport client with explicit target and authentication inputs."""

from pathlib import Path
from pxeye.clients.process import run


class SSHClient:
    def ssh(self, device, script, *, known=None, timeout=45):
        known = Path(known) if known else self.secrets / "known_hosts"
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=2",
            "-o",
            "UserKnownHostsFile=" + str(known),
            "-i",
            str(self.identity / "ssh_key"),
            device["ssh_user"] + "@" + device["management_ip"],
            "sudo -n python3 -",
        ]
        return run(argv, text=script, timeout=timeout)
