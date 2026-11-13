#!/usr/bin/env python3
"""Install one PXEye/NICo offline delivery with its archive path as the only input."""

import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
import onsite
from progress import Progress, atomic_json, install_signal_handlers, transcript

HOME = Path(__file__).resolve().parent
NAMESPACE = "nico-system"


def require_archive(value):
    archive = Path(value)
    onsite.require(archive.is_absolute(), "Use an absolute archive path")
    onsite.require(
        archive.is_file() and not archive.is_symlink(),
        "Archive is missing or is a symlink: " + str(archive),
    )
    return archive.resolve()


def archive_stem(archive):
    name = archive.name
    for suffix in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".tar"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    onsite.require(name and name not in (".", ".."), "Archive filename cannot derive a safe work directory")
    return name


def archive_identity(archive):
    info = archive.stat()
    # This is deliberately metadata only. The field workflow no longer
    # consumes a sibling SHA256SUMS file; the extracted bundle is still
    # verified against its embedded immutable inventory.
    return {"name": archive.name, "bytes": info.st_size, "mtime_ns": info.st_mtime_ns}


def paths_for(archive):
    stem = archive_stem(archive)
    return archive.parent / stem, archive.parent / (stem + ".onsite")


def bundle_from_result(target):
    result = json.loads((target / "unpack-result.json").read_text())
    relative = Path(result["root"])
    onsite.require(
        len(relative.parts) == 1 and relative.name not in (".", "..") and not relative.is_absolute(),
        "Invalid bundle root",
    )
    bundle = target / relative
    onsite.require(bundle.is_dir(), "Completed extraction no longer contains its bundle root")
    return bundle, result


def extract(archive, target):
    if not target.exists():
        onsite.unpack(SimpleNamespace(archive=archive, output=target))
    else:
        marker = target / "unpack-result.json"
        onsite.require(
            marker.is_file(),
            "Extraction directory already exists without a completion marker: " + str(target),
        )
        bundle, completed = bundle_from_result(target)
        onsite.require(
            completed.get("archive") == archive_identity(archive),
            "Archive metadata differs from completed extraction; use a different archive name or remove the incomplete extraction after inspection",
        )
        print("REUSE_EXTRACTION", bundle, flush=True)
    bundle, _ = bundle_from_result(target)
    return bundle


def resolved_install_config(bundle, work):
    path = work / "install-config.json"
    if path.exists():
        document = json.loads(path.read_text())
        expected = {
            "schema_version": 3,
            "namespace": NAMESPACE,
            "bundle": str(bundle),
            "work_directory": str(work / "deployment"),
        }
        onsite.require(
            all(document.get(key) == value for key, value in expected.items()),
            "Resolved installation configuration targets another bundle or site; use a different archive name",
        )
        print("REUSE_INSTALL_CONFIG", path, flush=True)
        return path

    context = onsite.select_install_context()
    registry_args = SimpleNamespace(
        context=context,
        namespace=NAMESPACE,
        ca_file=None,
        skip_tls_verify=True,
    )
    registry_url, discovery = onsite.detect_registry(registry_args)
    document = {
        # This is generated state, never a site-supplied configuration file.
        # Keep only values that the installer discovered or derived from the
        # selected archive.  The release identity is deliberately not exposed:
        # this entrypoint always manages nico-system/nico.
        "schema_version": 3,
        "context": context,
        "namespace": NAMESPACE,
        "site_name": "PXEye",
        "bundle": str(bundle),
        "work_directory": str(work / "deployment"),
        "registry": {
            "url": registry_url,
            "repository_prefix": "nico-offline",
            "ca_file": None,
            "skip_tls_verify": True,
            "docker_config_directory": None,
            "discovery": discovery,
        },
    }
    atomic_json(path, document)
    print("INSTALL_CONFIG_RESOLVED", path, flush=True)
    return path


def write_environment(path):
    """Write a per-run inspection helper; it is never an installer input."""
    config = json.loads(path.read_text())
    required = {
        "CONTEXT": config["context"],
        "NICO_NAMESPACE": config["namespace"],
        "NICO_RELEASE": onsite.RELEASE,
        "PXEYE_RELEASE": config["namespace"] + "-pxeye",
        "BUNDLE": config["bundle"],
        "WORK": config["work_directory"],
        "REGISTRY_URL": config["registry"]["url"],
    }
    environment = path.with_name("environment.sh")
    lines = [
        "# Generated by the one-command onsite installer; source only for inspection.",
        "# Do not edit this file or use it as installer input.",
    ]
    lines.extend("export " + name + "=" + shlex.quote(value) for name, value in required.items())
    environment.write_text("\n".join(lines) + "\n")
    environment.chmod(0o600)
    print("ENVIRONMENT_READY", environment, flush=True)
    return environment


def print_access_instructions(config):
    """Print a usable host access command without assuming Kind port mappings."""
    command = [
        'kubectl', '--context', config['context'], '-n', config['namespace'],
        'port-forward', '--address', '0.0.0.0',
        'service/' + config['namespace'] + '-pxeye', str(onsite.PXEYE_NODE_PORT) + ':80',
    ]
    print('PXEYE_ACCESS: run this command on the fireseed host and keep the terminal open:', flush=True)
    print(shlex.join(command), flush=True)
    print('PXEYE_LOCAL_URL: http://127.0.0.1:' + str(onsite.PXEYE_NODE_PORT) + '/', flush=True)
    connection = os.environ.get('SSH_CONNECTION', '').split()
    if len(connection) == 4:
        try:
            host = ipaddress.ip_address(connection[2])
        except ValueError:
            host = None
        if isinstance(host, ipaddress.IPv4Address) and not host.is_loopback and not host.is_unspecified:
            print('PXEYE_BROWSER_URL: http://' + str(host) + ':' + str(onsite.PXEYE_NODE_PORT) + '/', flush=True)
    print('Open the URL after port-forward reports Forwarding. Ctrl+C stops this access session.', flush=True)
    password_command = [
        'kubectl', '--context', config['context'], '-n', config['namespace'],
        'get', 'secret', config['namespace'] + '-pxeye',
        '-o', 'jsonpath={.data.bootstrap-password}',
    ]
    print('PXEYE_LOGIN: retrieve the generated password in your terminal, then paste it into the login form:', flush=True)
    print(shlex.join(password_command) + ' | base64 -d', flush=True)


def run(archive):
    target, work = paths_for(archive)
    onsite.require(
        not work.is_relative_to(target) and not target.is_relative_to(work),
        "Derived extraction and work directories overlap",
    )
    onsite.require(
        not target.is_symlink() and not work.is_symlink(),
        "Derived extraction or work directory is a symlink; choose a different archive name",
    )
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (work / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = {
            "archive": archive_identity(archive),
            "implementation": {
                name: onsite.sha(HOME / name)
                for name in ("run.py", "onsite.py", "progress.py", "registry_bridge.py", "relocation.py")
            },
        }
        progress = Progress(work, identity)
        with transcript(work):
            try:
                with progress.stage("01-unpack", "Unpack delivery and verify its embedded inventory"):
                    bundle = extract(archive, target)
                with progress.stage("02-site", "Resolve the cluster, Registry and fixed installation identity"):
                    resolved = resolved_install_config(bundle, work)
                    write_environment(resolved)
                engine = onsite.Onsite(resolved)
                with progress.stage("03-preflight", "Check bundle, target cluster and tools"):
                    engine.preflight()
                with progress.stage("04-import", "Import images and publish Helm OCI Charts"):
                    engine.import_bundle()
                with progress.stage("05-recipe", "Freeze and validate the installation recipe"):
                    if (engine.work / "recipe").exists():
                        engine.validate_recipe()
                        print("REUSE_RECIPE", engine.work / "recipe", flush=True)
                    else:
                        engine.prepare_recipe()
                with progress.stage("06-pxeye", "Install or verify PXEye"):
                    engine.bootstrap(resume=True)
                for phase in engine.validate_recipe()["phases"]:
                    with progress.stage("07-install-" + phase["id"], "Install or verify " + phase["id"]):
                        engine.install(phase["id"], automatic=True)
                with progress.stage("08-pxeye-core", "Verify PXEye's in-cluster Core connection"):
                    engine.check_pxeye_core_connection()
                progress.complete()
                print(
                    "ONSITE_COMPLETE",
                    work,
                    "; Helm readiness passed; physical provisioning remains disabled until site boot settings are configured",
                    flush=True,
                )
                print_access_instructions(engine.config)
            except BaseException as error:
                progress.fail(error)
                raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path, help="Absolute path to bundle.tar.gz")
    args = parser.parse_args()
    install_signal_handlers()
    run(require_archive(args.archive))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit(str(error)) from None
