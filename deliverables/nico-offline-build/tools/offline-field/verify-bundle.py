#!/usr/bin/env python3
"""Verify the complete inventory without third-party modules or large reads."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('bundle',type=Path);a=p.parse_args();root=a.bundle.resolve()
inv=json.loads((root/'manifests/file-inventory.json').read_text());known=set()
for row in inv['files']:
    path=(root/row['path']).resolve()
    assert path.is_relative_to(root) and not (root/row['path']).is_symlink(),row['path']
    assert path.is_file() and path.stat().st_size==row['bytes'],row['path']
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    assert h.hexdigest()==row['sha256'],row['path']
    known.add(row['path'])
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
assert actual==known|{'manifests/file-inventory.json'},'Unlisted/missing files in delivery'
descriptor=json.loads((root/'bundle.json').read_text())
if descriptor.get('kind')=='nico-materials':
    assert descriptor.get('recipe_ready') is False and not (root/'deployment/deployment.json').exists()
    print('BUNDLE_VERIFIED',len(known),'files; site initialization required')
else:
    m=json.loads((root/'deployment/deployment.json').read_text())
    for name,digest in m['files'].items():
        path=(root/'deployment'/name).resolve()
        assert path.is_relative_to(root/'deployment'),name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
    assert m['version']==descriptor['version']
    print('BUNDLE_VERIFIED',len(known),'files; recipe and descriptor agree')
