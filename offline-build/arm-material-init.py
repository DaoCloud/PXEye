#!/usr/bin/env python3
"""Publish a verified ARM boot payload into the NICo PXE init volume.

This program is copied into the content-addressed ARM material image.  It runs
as a nico-pxe ``bootArtifactContainer``: the Chart gives that container the
shared boot-artifact volume at ``/forge-boot-artifacts/blobs/internal`` and
does not override this image's ENTRYPOINT.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


PAYLOAD = Path('/payload/aarch64')
MANIFEST = Path('/payload/manifest.json')
DESTINATION = Path('/forge-boot-artifacts/blobs/internal/aarch64')


def fail(message: str) -> None:
    raise SystemExit('ARM material initialization failed: ' + message)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts or value.name != relative:
        fail('unsafe manifest path: ' + relative)
    path = root / value
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        fail('missing or unsafe payload: ' + relative)
    return path


def validate(root: Path, rows: list[dict]) -> None:
    for row in rows:
        if not isinstance(row, dict):
            fail('invalid manifest row')
        name, size, expected = row.get('target'), row.get('bytes'), row.get('sha256')
        if not isinstance(name, str) or not isinstance(size, int) or size <= 0:
            fail('invalid manifest file metadata')
        if not isinstance(expected, str) or len(expected) != 64:
            fail('invalid manifest checksum: ' + name)
        path = safe_file(root, name)
        if path.stat().st_size != size:
            fail('unexpected size: ' + name)
        if checksum(path) != expected:
            fail('checksum mismatch: ' + name)


def copy_atomically(rows: list[dict]) -> None:
    parent = DESTINATION.parent
    parent.mkdir(parents=True, exist_ok=True)
    if DESTINATION.exists():
        if DESTINATION.is_symlink() or not DESTINATION.is_dir():
            fail('destination is not a directory')
        validate(DESTINATION, rows)
        print('ARM_MATERIAL_READY existing', flush=True)
        return
    temporary = parent / ('.aarch64.copy-' + str(os.getpid()))
    try:
        temporary.mkdir(mode=0o755)
        for row in rows:
            source = safe_file(PAYLOAD, row['target'])
            target = temporary / row['target']
            shutil.copyfile(source, target)
            target.chmod(0o644)
        validate(temporary, rows)
        temporary.replace(DESTINATION)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print('ARM_MATERIAL_READY copied', flush=True)


def main() -> None:
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, json.JSONDecodeError) as error:
        fail('cannot read manifest: ' + str(error))
    if not isinstance(manifest, dict) or manifest.get('id') != 'boot-aarch64':
        fail('unexpected material manifest')
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows:
        fail('manifest has no files')
    validate(PAYLOAD, rows)
    copy_atomically(rows)


if __name__ == '__main__':
    main()
