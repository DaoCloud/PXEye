"""Generate raw inputs from locked containerd blobs and explicit material sources.

This module never reads Kubernetes, changes containerd, or discovers running tags.
It replaces the historical hand-assembled input directory, not upstream compilation.
"""
import copy
import fcntl
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

import prepared as contract


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def blob_path(root, record):
    digest = record['digest']
    contract.require(len(digest) == 71 and digest.startswith('sha256:') and
                     all(c in '0123456789abcdef' for c in digest[7:]), 'Invalid source digest')
    path = contract.relative(root, digest[7:])
    contract.require(path.is_file() and ('size' not in record or path.stat().st_size == record['size']),
                     'Missing or invalid containerd content: ' + str(path))
    return path


def graph(root, row):
    path = blob_path(root, row)
    manifest = json.loads(path.read_text())
    contract.require('config' in manifest and 'layers' in manifest,
                     'Recipe must lock a single-platform manifest: ' + row['id'])
    config = json.loads(blob_path(root, manifest['config']).read_text())
    contract.require(config.get('architecture') == 'amd64' and config.get('os') == 'linux',
                     'Wrong source image platform: ' + row['id'])
    descriptor = {'digest': row['digest'], 'size': path.stat().st_size,
                  'mediaType': manifest['mediaType'],
                  'platform': {'architecture': 'amd64', 'os': 'linux'},
                  'annotations': {'io.containerd.image.name': row['reference'],
                                  'org.opencontainers.image.ref.name': row['reference']}}
    records = [descriptor, manifest['config']] + manifest['layers']
    for record in records:
        blob_path(root, record)
    return descriptor, records


def file_sources(c, recipe):
    sources = c['sources']
    for name, digest in recipe['raw_charts'].items():
        yield Path(sources['charts']) / name, 'charts/' + name, {'sha256': digest}
    for row in recipe['materials']:
        if c['include'][row['group']]:
            yield contract.relative(Path(sources['materials'][row['group']]), row['target']), row['path'], row


def validate(c, recipe):
    sources = c['sources']
    contract.require(set(sources) == {'containerd_content', 'charts', 'materials'}, 'Invalid source settings')
    contract.require(set(sources['materials']) == {'aarch64', 'apt', 'bfb'}, 'Specify all material source roots')
    roots = [sources['containerd_content'], sources['charts']] + list(sources['materials'].values())
    for value in roots:
        root = Path(value)
        contract.require(root.is_absolute() and not any(x in str(root) for x in ',\n\r'), 'Source roots must be absolute')
        for key in ('input_root', 'output_root', 'cache_directory', 'package_output_root'):
            target = c[key]
            contract.require(not root.resolve().is_relative_to(target) and not target.is_relative_to(root.resolve()),
                             'Keep original sources separate from generated directories: ' + str(root))
    contract.require(all(r['method'] == 'archive' for r in recipe['images']),
                     'Generated input mode exports every recipe image from containerd content')
    failures = []
    for source, target, row in file_sources(c, recipe):
        if not source.is_file() or source.is_symlink():
            failures.append(target + ' <- ' + str(source))
        elif 'bytes' in row and source.stat().st_size != row['bytes']:
            failures.append('Wrong size: ' + str(source))
    for row in recipe['images']:
        try:
            graph(Path(sources['containerd_content']), row)
        except (ValueError, KeyError, OSError) as error:
            failures.append(row['id'] + ': ' + str(error))
    contract.require(not failures, 'Missing original sources (no build started):\n' + '\n'.join(failures))


def export_archive(root, rows, output):
    descriptors, blobs = [], {}
    for row in rows:
        descriptor, records = graph(root, row)
        descriptors.append(descriptor)
        for record in records:
            if record['digest'] in blobs:
                contract.require(blobs[record['digest']]['size'] == record['size'], 'Inconsistent blob size')
            blobs[record['digest']] = record
    def add_json(archive, name, value):
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
        archive.addfile(info, io.BytesIO(data))
    with tarfile.open(output, 'w') as archive:
        add_json(archive, 'oci-layout', {'imageLayoutVersion': '1.0.0'})
        add_json(archive, 'index.json', {'schemaVersion': 2, 'manifests': descriptors})
        for digest, record in sorted(blobs.items()):
            source = blob_path(root, record)
            contract.require(contract.sha(source) == digest[7:], 'Source blob checksum differs: ' + digest)
            info = tarfile.TarInfo('blobs/sha256/' + digest[7:])
            info.size = record['size']; info.mode = 0o644
            with source.open('rb') as stream:
                archive.addfile(info, stream)


def generate(c, recipe, plan=False):
    """Produce versioned raw inputs; resume only files recorded with matching hashes."""
    validate(c, recipe)
    spec = {'sources': c['sources'], 'recipe': recipe, 'include': c['include'], 'export_schema': 1}
    root = c['input_root'] / fingerprint(spec)[:24]
    print('SOURCE_PLAN', json.dumps({'directory': str(root), 'image_count': len(recipe['images']),
          'files': [target for _, target, _ in file_sources(c, recipe)]}), flush=True)
    if plan:
        return c, recipe
    c['input_root'].mkdir(parents=True, exist_ok=True)
    # Check before exporting large archives, rather than after consuming the space.
    graph_bytes = 0
    for key in {r['archive'] for r in recipe['images']}:
        records = {}
        for row in recipe['images']:
            if row['archive'] == key:
                _, items = graph(Path(c['sources']['containerd_content']), row)
                records.update({r['digest']: r['size'] for r in items})
        graph_bytes += sum(records.values())
    file_bytes = sum(source.stat().st_size for source, _, _ in file_sources(c, recipe))
    # Existing recorded files are checked below; reserve only missing exports/files.
    present_bytes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0
    contract.require(shutil.disk_usage(c['input_root']).free > max(0, graph_bytes + file_bytes - present_bytes) + 1024**3,
                     'Insufficient space to generate raw inputs (plus 1 GiB reserve)')
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.sources.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = root / 'source-progress.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {'spec': spec, 'files': {}}
        contract.require(state['spec'] == spec, 'Source progress belongs to different inputs')
        def persist():
            temporary = root / '.source-progress.tmp'
            contract.dump(temporary, state); temporary.replace(state_path)
        def produce(target, writer, expected=None):
            destination = contract.relative(root, target)
            previous = state['files'].get(target)
            if destination.exists():
                contract.require(previous and destination.stat().st_size == previous['bytes'] and
                                 contract.sha(destination) == previous['sha256'],
                                 'Unrecorded or changed generated file; inspect before retrying: ' + str(destination))
                print('REUSE_SOURCE', target, flush=True)
                return previous
            print('GENERATE_SOURCE', target, flush=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix='.' + destination.name + '-', dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                writer(temporary)
                record = {'bytes': temporary.stat().st_size, 'sha256': contract.sha(temporary)}
                contract.require(not expected or (record['sha256'] == expected['sha256'] and
                                 ('bytes' not in expected or record['bytes'] == expected['bytes'])),
                                 'Original file checksum differs: ' + target)
                # Journal before rename: a crash never promotes an unrecorded file.
                state['files'][target] = record; persist(); temporary.replace(destination)
                return record
            finally:
                temporary.unlink(missing_ok=True)
        effective = copy.deepcopy(recipe)
        archives = {}
        print('STAGE 1/5 Collect Charts and binary materials', flush=True)
        for source, target, row in file_sources(c, recipe):
            produce(target, lambda dest, src=source: shutil.copyfile(src, dest), row)
        print('STAGE 2/5 Export locked containerd image graphs (read-only)', flush=True)
        for key in sorted({r['archive'] for r in recipe['images']}):
            target = 'images/' + key + '.oci.tar'
            rows = [r for r in recipe['images'] if r['archive'] == key]
            record = produce(target, lambda dest, rs=rows: export_archive(Path(c['sources']['containerd_content']), rs, dest))
            effective['archives'][key] = record
            archives[key] = target
        contract.dump(root / 'manifests/images-lock.json', recipe['images'])
        (root / 'manifests/images.txt').write_text(''.join(r['reference'] + '\n' for r in recipe['images']))
        contract.dump(root / 'manifests/source-files.json', state)
        print('RAW_INPUT_COMPLETE', root, flush=True)
        return c | {'input_root': root, 'archives': archives}, effective
