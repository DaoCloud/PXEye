"""Read-only discovery of versioned NICo field bundles.

A field bundle is deliberately kept outside PXEye's writable deployment data.  The
bundle may contain a large OCI archive, boot media and source material; only the
small Helm recipe is copied into ``/data/nico-deployment/packages`` when it is
present.  This module never extracts or hashes the large image archive while the
page is being rendered.
"""

import json
import os
import re
import shutil
from pathlib import Path

from pxeye.common import atomic_json


PACKAGE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}")
MAX_RECIPE_BYTES = 1024**3


def _safe_id(value):
    value = str(value or "").strip()
    return value if PACKAGE_ID.fullmatch(value) else ""


def _read_json(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class FieldBundles:
    """Discover bundle directories mounted read-only into the PXEye Pod."""

    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def _candidates(self):
        if not self.root.is_dir():
            return []
        # A deployment may mount either the parent directory containing several
        # releases or one release directory directly.
        if (self.root / "manifests").is_dir():
            return [self.root]
        return sorted(path for path in self.root.iterdir() if path.is_dir())

    def discover(self):
        rows = []
        for path in self._candidates():
            inventory_path = path / "manifests" / "file-inventory.json"
            inventory = _read_json(inventory_path)
            descriptor = _read_json(path / "bundle.json") or {}
            name = _safe_id(descriptor.get("id") or (inventory or {}).get("package"))
            if not name:
                name = _safe_id(path.name) or "unnamed"
            image_archive = str(
                descriptor.get("image_archive") or "images/nico-amd64.oci.tar"
            ).strip()
            image_path = (path / image_archive).resolve()
            recipe = (path / str(descriptor.get("recipe_directory") or "deployment")).resolve()
            if not image_path.is_relative_to(path) or not recipe.is_relative_to(path):
                # A bundle descriptor must not make PXEye inspect arbitrary host paths.
                image_path = path / "__invalid_image__"
                recipe = path / "__invalid_recipe__"
            recipe_manifest = recipe / "deployment.json"
            image_lock = path / "manifests" / "images-lock.json"
            lock = None
            try:
                lock = json.loads(image_lock.read_text())
            except (OSError, ValueError):
                pass
            if not isinstance(lock, list):
                lock = []
            errors = []
            if inventory is None:
                errors.append("缺少 manifests/file-inventory.json")
            if not image_path.is_file():
                errors.append(f"缺少 OCI 镜像归档：{image_archive}")
            if not image_lock.is_file():
                errors.append("缺少 manifests/images-lock.json")
            recipe_ready = recipe_manifest.is_file()
            if not recipe_ready:
                errors.append("未提供 deployment/deployment.json，不能直接执行页面 Helm 部署")
            row = {
                "id": name,
                "name": descriptor.get("name") or (inventory or {}).get("package") or name,
                "version": str(
                    descriptor.get("version")
                    or (inventory or {}).get("updated")
                    or (inventory or {}).get("upstream_commit")
                    or "—"
                ),
                "path": str(path),
                "architecture": descriptor.get("architecture")
                or (inventory or {}).get("controller_architecture", "linux/amd64"),
                "target_host_architecture": (inventory or {}).get(
                    "target_host_architecture", ""
                ),
                "image_archive": image_archive,
                "image_bytes": image_path.stat().st_size if image_path.is_file() else 0,
                "image_count": len(lock),
                "recipe_directory": str(recipe),
                "recipe_ready": recipe_ready,
                "valid": not errors,
                "errors": errors,
                "source": "field-bundle",
                "upstream_commit": (inventory or {}).get("upstream_commit", ""),
            }
            rows.append(row)
        return rows

    def materialize_recipes(self, destination):
        """Copy only recipe files into writable PXEye storage.

        The copy is bounded and does not follow symlinks.  The OCI archive and
        other large field materials remain on the mounted read-only bundle.
        """

        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = {}
        for row in self.discover():
            if not row["recipe_ready"]:
                continue
            source = Path(row["recipe_directory"])
            package_id = "bundle-" + row["id"]
            target = (destination / package_id).resolve()
            if target.parent != destination:
                continue
            total = sum(
                file.stat().st_size
                for file in source.rglob("*")
                if file.is_file() and not file.is_symlink()
            )
            if total > MAX_RECIPE_BYTES:
                row["recipe_ready"] = False
                row["valid"] = False
                row["errors"].append("Helm recipe 超过 1 GiB，未复制到 PXEye 数据目录")
                continue
            marker = target / ".bundle-source.json"
            marker_value = {"bundle_id": row["id"], "version": row["version"]}
            if marker.is_file() and _read_json(marker) == marker_value:
                result[row["id"]] = {"package_id": package_id, **row}
                continue
            temporary = destination / ("." + package_id + ".tmp")
            if temporary.exists():
                shutil.rmtree(temporary)
            if any(candidate.is_symlink() for candidate in source.rglob("*")):
                row["recipe_ready"] = False
                row["valid"] = False
                row["errors"].append("Helm recipe 不能包含符号链接")
                continue
            shutil.copytree(source, temporary, symlinks=True)
            atomic_json(temporary / ".bundle-source.json", marker_value)
            if target.exists():
                shutil.rmtree(target)
            os.replace(temporary, target)
            result[row["id"]] = {"package_id": package_id, **row}
        return result

