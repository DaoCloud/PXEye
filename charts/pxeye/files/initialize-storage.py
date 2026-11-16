"""Initialize deployment-owned directories and defaults without importing PXEye."""

import json
import os
from pathlib import Path
import tempfile


def directory(root, relative, mode):
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise RuntimeError("Storage directory must not be a symlink: " + str(path))
        try:
            path.mkdir(mode=mode)
        except FileExistsError:
            if not path.is_dir():
                raise RuntimeError("Storage path is not a directory: " + str(path))
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError("Storage directory is not writable: " + str(path))
    return path


def main():
    root = Path("/storage")
    os.umask(0o022)
    for relative, mode in (
        ("data", 0o700), ("data/config", 0o700),
        ("iso-sources", 0o755), ("staging", 0o700),
        ("http", 0o755), ("http/nico", 0o755),
        ("http/nico/os-library", 0o755),
    ):
        path = directory(root, relative, mode)
        if relative.startswith("http") and path.stat().st_mode & 0o005 != 0o005:
            raise RuntimeError("HTTP directory must be readable/traversable by the PXE account: " + str(path))
    # __main__ overlays this file at the top level, so deployment defaults must
    # also be filled here when an older persisted os_library already exists.
    target = root / "data/config/deployment-site.json"
    if target.is_symlink():
        raise RuntimeError("Persisted configuration must not be a symlink")
    if target.exists():
        saved = json.loads(target.read_text())
        settings = saved.get("os_library")
        if settings is not None:
            if not isinstance(settings, dict):
                raise RuntimeError("Persisted os_library must be an object")
            before = dict(settings)
            if settings.get("directory", "/materials") != "/materials":
                raise RuntimeError("Migrate the custom material directory before switching storage")
            settings.setdefault("directory", "/materials")
            if not settings.get("sources"):
                defaults = json.loads(Path("/config/site.json").read_text())
                settings["sources"] = defaults["os_library"]["sources"]
            if settings != before:
                with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(saved, stream, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
    print("Storage directories ready; existing files preserved; ISO source configured.")


if __name__ == "__main__":
    main()
