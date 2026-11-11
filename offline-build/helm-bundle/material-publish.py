#!/usr/bin/env python3
"""Copy one immutable image payload to a versioned volume, then verify it."""
import hashlib
import json
import os
from pathlib import Path
import shutil

source = Path('/payload')
manifest = json.loads((source / 'manifest.json').read_text())
base = Path('/materials')
target = base / manifest['id'] / manifest['version']
if target.is_symlink() or target.parent.is_symlink():
    raise ValueError('Material destination must not be a symlink')


def verify(root):
    for row in manifest['files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe material path')
        path = root / row['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size != row['bytes']:
            raise ValueError('Missing or invalid material: ' + row['path'])
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                digest.update(block)
        if digest.hexdigest() != row['sha256']:
            raise ValueError('Material checksum mismatch: ' + row['path'])


target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    if not (target / 'manifest.json').is_file() or json.loads((target / 'manifest.json').read_text()) != manifest:
        raise ValueError('Existing material version differs; choose a new version')
    verify(target)
    if not (target / '.complete').is_file():
        (target / '.complete').write_text('verified\n')
else:
    temporary = target.parent / ('.' + target.name + '.copy-' + str(os.getpid()))
    shutil.copytree(source, temporary)
    verify(temporary)
    (temporary / '.complete').write_text('verified\n')
    temporary.rename(target)
print('MATERIAL_READY', manifest['id'], manifest['version'], flush=True)
