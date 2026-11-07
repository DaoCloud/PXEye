"""Dependency-free value helpers and durable atomic exports."""

import hashlib
import json
import os
import uuid
from pathlib import Path


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")))


def value_id(value):
    return value.get("value") if isinstance(value, dict) else value


def atomic_text(path, text):
    """Replace one export without sharing temporary files between writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def omit_unset_fields(value):
    """Preserve explicit false/zero values when encoding native contracts."""
    if isinstance(value, dict):
        return {key: omit_unset_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_unset_fields(item) for item in value]
    return value


def redact(value):
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if "password" not in key.lower()
            and key not in ("credentials", "owner", "baseline", "request")
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
