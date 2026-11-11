#!/usr/bin/env python3
"""Verify an extracted Helm delivery with only Python's standard library."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def sha(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(8 * 1024**2), b''):
        digest.update(block)
    return digest.hexdigest()


def verify(root):
    root = Path(root).resolve()
    inventory = json.loads((root / 'manifests/file-inventory.json').read_text())
    known = {'manifests/file-inventory.json'}
    for row in inventory['files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or row['path'] in known:
            raise ValueError('Unsafe or duplicate inventory path: ' + row['path'])
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError('Missing/unsafe file: ' + row['path'])
        with path.open('rb') as stream:
            if path.stat().st_size != row['bytes'] or sha(stream) != row['sha256']:
                raise ValueError('Checksum mismatch: ' + row['path'])
        known.add(row['path'])
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if known != actual or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('Unlisted/missing files or symlinks in delivery')
    descriptor = json.loads((root / 'bundle.json').read_text())
    for chart in descriptor['charts']:
        with tarfile.open(root / chart['relocation'], 'r:') as archive:
            names = archive.getnames()
            if not {'hints.yaml', 'original-chart/Chart.yaml', 'original-chart/values.yaml', 'images.tar'} <= set(names):
                raise ValueError('Invalid relok8s intermediate bundle: ' + chart['relocation'])
    print('HELM_BUNDLE_VERIFIED', len(known), 'files', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    verify(parser.parse_args().bundle)
