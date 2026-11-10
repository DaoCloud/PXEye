#!/usr/bin/env python3
"""Add the small PXEye bundle descriptor to a prepared NICo field package.

The 17GiB OCI archive is not copied or re-compressed.  A deployment recipe is
optional at packaging time; without it PXEye can show the material inventory but
must refuse to start Helm.
"""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--version")
    parser.add_argument("--architecture", default="linux/amd64")
    parser.add_argument("--recipe-directory", default="deployment")
    args = parser.parse_args()
    root = args.bundle.resolve()
    inventory = root / "manifests" / "file-inventory.json"
    lock = root / "manifests" / "images-lock.json"
    archive = root / "images" / "nico-amd64.oci.tar"
    if not inventory.is_file() or not lock.is_file() or not archive.is_file():
        raise SystemExit("bundle 必须包含 manifests 清单和 images/nico-amd64.oci.tar。")
    data = json.loads(inventory.read_text())
    if not isinstance(data, dict):
        raise SystemExit("file-inventory.json 格式无效。")
    bundle_id = args.id or data.get("package") or root.name
    version = args.version or data.get("updated") or data.get("upstream_commit") or "unknown"
    recipe = Path(args.recipe_directory)
    if recipe.is_absolute() or ".." in recipe.parts:
        raise SystemExit("recipe-directory 必须是 bundle 内部相对路径。")
    recipe_path = root / recipe
    recipe_ready = (recipe_path / "deployment.json").is_file()
    payload = {
        "schema_version": 1,
        "id": bundle_id,
        "name": args.name or data.get("package") or bundle_id,
        "version": str(version),
        "architecture": args.architecture,
        "recipe_directory": recipe.as_posix(),
        "image_archive": "images/nico-amd64.oci.tar",
        "recipe_ready": recipe_ready,
        "image_lock": "manifests/images-lock.json",
    }
    temporary = root / ".bundle.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.chmod(temporary, 0o644)
    os.replace(temporary, root / "bundle.json")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

