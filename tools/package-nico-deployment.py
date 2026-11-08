#!/usr/bin/env python3
"""Freeze a site-specific Helm recipe as a local PXEye deployment package."""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Destination must be new and outside the source directory")
    recipe = json.loads((source / "deployment.json").read_text())
    paths = sorted(
        {path for phase in recipe["phases"] for path in [phase["chart"]] + phase.get("values", [])}
    )
    files = {}
    for name in paths:
        path = (source / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(source) or not path.is_file():
            raise ValueError("Chart or values path is missing or escapes the source directory")
        if path.stat().st_size > 64 * 1024**2:
            raise ValueError("Chart/values files must not exceed 64 MiB")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    recipe["files"] = files
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir(mode=0o700)
        for name in paths:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
            target.chmod(0o600)
        manifest = staging / "deployment.json"
        manifest.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
        manifest.chmod(0o600)
        shutil.move(str(staging), destination)
    print(f"Deployment package created: {destination.name}; {len(files)} files locked by SHA256")


if __name__ == "__main__":
    main()
