#!/usr/bin/env python3
"""Push a frozen OCI archive into a Harbor/OCI registry.

This command intentionally talks to the registry over HTTPS and never uses a
host Docker or containerd socket.  It is suitable for execution inside the
PXEye Pod when the field bundle and a registry auth file are mounted.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./_-]*:[A-Za-z0-9][A-Za-z0-9._-]*$")


def endpoint(value):
    value = value.strip().rstrip("/")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("registry 地址必须是 http(s)://host，可带 Harbor 项目前缀。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("registry 地址不能包含账号、密码、查询参数或片段。")
    return parsed.netloc + parsed.path.rstrip("/")


def destination(registry, prefix, source):
    source = source.removeprefix("docker://")
    if not IMAGE.fullmatch(source):
        raise ValueError(f"镜像引用格式无效：{source}")
    prefix = prefix.strip("/")
    return "/".join(part for part in (registry, prefix, source) if part)


def run(command, *, dry_run=False):
    print("IMPORT", " ".join(command[0:3]), "…")
    if dry_run:
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("skopeo 执行失败或超时。") from error
    if result.returncode:
        # Do not print stderr: registry clients may echo auth challenge details.
        raise RuntimeError(f"skopeo 返回退出码 {result.returncode}。")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository-prefix", default="nico-offline")
    parser.add_argument("--authfile", type=Path)
    parser.add_argument("--skopeo", default="skopeo")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.archive.is_file() or not args.lock.is_file():
        raise SystemExit("镜像归档或 images-lock.json 不存在。")
    if args.authfile and (not args.authfile.is_file() or os.stat(args.authfile).st_mode & 0o077):
        raise SystemExit("authfile 必须存在且权限不超过 0600。")
    try:
        records = json.loads(args.lock.read_text())
        if not isinstance(records, list) or not records:
            raise ValueError("images-lock.json 不是非空数组。")
        registry = endpoint(args.registry)
        sources = []
        for record in records:
            image = str(record.get("image", ""))
            if not IMAGE.fullmatch(image):
                raise ValueError(f"镜像引用格式无效：{image}")
            sources.append((image, destination(registry, args.repository_prefix, image)))
    except (OSError, ValueError, TypeError) as error:
        raise SystemExit(str(error)) from None
    common = [args.skopeo]
    # Skopeo's archive transport otherwise uses /var/tmp even when TMPDIR is set.
    if os.environ.get("TMPDIR"):
        common += ["--tmpdir", os.environ["TMPDIR"]]
    # These are copy-subcommand options, not skopeo global options.
    common += ["copy"]
    if args.authfile:
        common += ["--authfile", str(args.authfile)]
    if args.insecure:
        common += ["--dest-tls-verify=false"]
    with ExitStack() as stack:
        source_root = f"oci-archive:{args.archive}"
        if not args.dry_run:
            if not hasattr(tarfile, "data_filter"):
                raise RuntimeError("安全解包需要支持 tarfile.data_filter 的 Python 版本。")
            layout = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="pxeye-oci-")))
            print("EXTRACT", args.archive, "->", layout, flush=True)
            # Extract once as the current user. Skopeo's oci-archive extractor
            # preserves root ownership and fails in a non-root PXEye container.
            with tarfile.open(args.archive) as archive:
                archive.extractall(layout, filter="data")
            index = json.loads((layout / "index.json").read_text())
            descriptors = {
                item.get("annotations", {}).get("org.opencontainers.image.ref.name"): item
                for item in index.get("manifests", [])
            }
            for record in records:
                descriptor = descriptors.get(record["image"])
                if descriptor is None:
                    raise ValueError(f"归档缺少锁定镜像：{record['image']}")
                expected = record.get("amd64_manifest")
                if expected:
                    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
                        raise ValueError("锁定 manifest digest 格式无效。")
                    manifest = layout / "blobs" / "sha256" / expected.split(":", 1)[1]
                    if descriptor.get("digest") != expected or hashlib.sha256(manifest.read_bytes()).hexdigest() != expected.split(":", 1)[1]:
                        raise ValueError(f"归档 manifest 与锁定文件不一致：{record['image']}")
            source_root = f"oci:{layout}"
        for position, (image, target) in enumerate(sources, 1):
            print(f"IMAGE {position}/{len(sources)} {image} -> {target}", flush=True)
            run(
                common
                + [
                    "--retry-times",
                    "3",
                    f"{source_root}:{image}",
                    f"docker://{target}",
                ],
                dry_run=args.dry_run,
            )
    if args.dry_run:
        print(f"DRY_RUN {len(sources)} images")
    else:
        print(f"IMPORTED {len(sources)} images into {registry}/{args.repository_prefix.strip('/')}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

