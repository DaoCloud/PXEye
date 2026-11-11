#!/usr/bin/env python3
"""Generate a reviewable material-lock update; never overwrite the shipped lock."""
import argparse
import json
from pathlib import Path
import re
import sys
import tarfile

sys.dont_write_bytecode = True
import build as b

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
try:
    document = json.loads(args.config.read_text())
    b.require(document.get('schema_version') == 4, 'Use the small schema4 build configuration')
    b.require(not args.output.exists(), 'Write to a new lock file for review; do not overwrite existing files')
    expanded = b.expand_configuration(document)
    lock = json.loads((b.BUILD_HOME / 'materials-lock.json').read_text())
    source = Path(document['build']['source_bundle']).resolve()
    archives = {purpose: (args.config.resolve().parent / document['package'][purpose + '_archive']).resolve() for purpose in ('ui', 'bootstrap')}
    for purpose, archive in archives.items():
        with tarfile.open(archive, 'r:') as tar:
            with tar.extractfile('index.json') as stream:
                rows = json.load(stream)['manifests']
        b.require(len(rows) == 1, 'Use one named leaf image per extra OCI archive')
        reference = rows[0].get('annotations', {}).get('org.opencontainers.image.ref.name', '')
        b.require(reference and re.fullmatch(r'[A-Za-z0-9._-]{1,128}', reference.rsplit(':', 1)[-1]), 'Missing OCI tag annotation')
        image = b.oci_check(archive, reference=reference)[0]
        lock['images'][purpose] = {'tag': reference.rsplit(':', 1)[-1], 'digest': image['digest']}
    selected = {row['source'] for row in expanded['files']['inputs']}
    updated = 0
    for row in lock['files']['inputs']:
        if row['source'] not in selected:
            continue
        path = source / row['source'] if row['root'] == 'bundle' else archives[row['role']]
        b.require(path.is_file() and not path.is_symlink(), 'Missing material: ' + str(path))
        if row['root'] == 'bundle':
            b.require(path.resolve().is_relative_to(source), 'Material escapes source root')
        digest = b.sha(path)
        if row['role'] == 'base_images':
            b.require(digest == b.OCI_SHA, 'Changed base OCI needs a new reviewed compatibility profile')
        if row['role'] in ('nico_chart', 'cert_manager_chart'):
            b.require(digest == b.RAW[path.name], 'Changed raw Chart needs a new reviewed compatibility profile')
        row.update(bytes=path.stat().st_size, sha256=digest)
        updated += 1
    records = json.loads((source / 'manifests/images-lock.json').read_text())
    b.require({r['image']: r['amd64_manifest'] for r in records} == lock['files']['base_image_manifests'], 'Changed base manifest list needs a reviewed profile')
    b.dump(args.output, lock)
    print('MATERIAL_LOCK_WRITTEN', args.output, 'updated=' + str(updated), 'unchanged_optional=' + str(len(lock['files']['inputs']) - updated))
    print('Review the diff, then replace materials-lock.json in the maintained source and commit it before exporting a new kit.')
except (ValueError, KeyError, TypeError, OSError, tarfile.TarError) as error:
    raise SystemExit(str(error)) from None
