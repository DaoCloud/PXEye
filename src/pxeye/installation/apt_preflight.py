"""Run in the Ubuntu installer before partitioning, with isolated APT state."""

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import yaml


def check(config, release, architecture, root):
    """Resolve required packages from fresh signed indices without installing anything."""
    apt = config.get("apt", {})
    if apt.get("preserve_sources_list"):
        raise ValueError("APT_SOURCE_PREFLIGHT_REQUIRES_EXPLICIT_MIRRORS")
    default = (
        "http://archive.ubuntu.com/ubuntu/"
        if architecture in ("amd64", "i386")
        else "http://ports.ubuntu.com/ubuntu-ports/"
    )

    def mirror(key, fallback):
        rows = apt.get(key, [])
        matches = [r for r in rows if architecture in r.get("arches", [])]
        if not matches:
            matches = [r for r in rows if "default" in r.get("arches", ["default"])]
        uri = matches[0]["uri"] if matches else fallback
        parsed = urlsplit(uri)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(c.isspace() for c in uri)
        ):
            raise ValueError("APT_SOURCE_URI_UNSUPPORTED")
        return uri

    if not re.fullmatch(r"[a-z][a-z0-9-]*", release):
        raise ValueError("APT_RELEASE_INVALID")
    primary = mirror("primary", default)
    security = mirror(
        "security", "http://security.ubuntu.com/ubuntu/" if architecture == "amd64" else default
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for folder in ("lists/partial", "archives/partial"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "status").write_text("")
    sources = root / "sources.list"
    sources.write_text(
        "".join(
            f"deb {primary} {suite} main restricted universe multiverse\n"
            for suite in (release, release + "-updates", release + "-backports")
        )
        + f"deb {security} {release}-security main restricted universe multiverse\n"
    )
    options = [
        "-o",
        "Dir::Etc::sourcelist=" + str(sources),
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        "Dir::Etc::parts=-",
        "-o",
        "Dir::Etc::main=-",
        "-o",
        "Dir::Cache::pkgcache=" + str(root / "pkgcache.bin"),
        "-o",
        "Dir::Cache::srcpkgcache=" + str(root / "srcpkgcache.bin"),
        "-o",
        "Dir::State::status=" + str(root / "status"),
        "-o",
        "Dir::State::lists=" + str(root / "lists"),
        "-o",
        "Dir::Cache::archives=" + str(root / "archives"),
        "-o",
        "Acquire::Retries=1",
        "-o",
        "Acquire::http::Timeout=15",
        "-o",
        "Acquire::https::Timeout=15",
        "-o",
        "APT::Update::Error-Mode=any",
    ]
    kernel = config.get("kernel", {}).get("package", "linux-generic")
    packages = sorted(set([kernel, "openssh-server", *config.get("packages", [])]))
    if any(
        not isinstance(p, str) or not re.fullmatch(r"[a-z0-9][a-z0-9+.:_-]*", p) for p in packages
    ):
        raise ValueError("APT_PACKAGE_UNSUPPORTED")
    with (root / "check.log").open("w") as log:
        for args in (["update"], ["--simulate", "--no-install-recommends", "install", *packages]):
            subprocess.run(
                ["apt-get", *options, *args],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=300,
            )
    (root / "result.json").write_text(
        json.dumps(
            {"passed": True, "release": release, "architecture": architecture, "packages": packages}
        )
    )


def main():
    data = yaml.safe_load(Path("/autoinstall.yaml").read_text())
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    try:
        check(
            data.get("autoinstall", data),
            release["VERSION_CODENAME"].strip('"'),
            architecture,
            Path("/run/nico-apt-check"),
        )
    except (ValueError, KeyError, subprocess.SubprocessError):
        print(
            "NICO_APT_PRECHECK_FAILED: 软件源索引或依赖不可用；尚未分区，日志 /run/nico-apt-check/check.log",
            flush=True,
        )
        raise
    print("NICO_APT_PRECHECK_PASSED", flush=True)


if __name__ == "__main__":
    main()
