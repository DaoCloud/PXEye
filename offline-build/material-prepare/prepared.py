"""Independent prepared-material contract shared by preparation and packaging."""
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            value.update(block)
    return value.hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def relative(root, name):
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe prepared path: ' + name)
    target = root / path
    require(not target.is_symlink() and target.resolve().is_relative_to(root.resolve()), 'Unsafe prepared file: ' + name)
    return target


def image(layout, reference, expected=None, checked=None):
    index = json.loads((layout / 'index.json').read_text())
    matches = [r for r in index['manifests'] if r.get('annotations', {}).get('org.opencontainers.image.ref.name') == reference]
    require(len(matches) == 1, 'Image absent or ambiguous: ' + reference)
    desc = matches[0]
    require(not expected or desc['digest'] == expected, 'Manifest digest differs: ' + reference)
    checked = checked if checked is not None else set()
    def blob(record):
        digest = record['digest']
        require(len(digest) == 71 and digest.startswith('sha256:') and all(c in '0123456789abcdef' for c in digest[7:]), 'Invalid blob digest')
        path = relative(layout, 'blobs/sha256/' + digest[7:])
        require(path.is_file() and path.stat().st_size == record['size'], 'Missing or invalid OCI blob: ' + digest)
        if digest not in checked:
            require(sha(path) == digest[7:], 'OCI blob hash differs: ' + digest)
            checked.add(digest)
        return path
    manifest = json.loads(blob(desc).read_text())
    config = json.loads(blob(manifest['config']).read_text())
    require(config.get('os') == 'linux' and config.get('architecture') == 'amd64', 'Only linux/amd64 controller images are supported: ' + reference)
    for layer in manifest['layers']: blob(layer)
    return desc, manifest


def inventory(root):
    rows = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Prepared symlinks are not allowed')
        if path.is_file() and path != root / 'manifests/files.json':
            rows.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)})
    dump(root / 'manifests/files.json', {'files': rows})
    return rows


def verify(root, kinds=('nico-prepared',)):
    root = Path(root)
    descriptor = json.loads((root / 'prepared.json').read_text())
    require(descriptor.get('kind') in kinds and descriptor.get('schema_version') == 1 and descriptor.get('complete') is True, 'Not a complete prepared-material directory')
    rows = json.loads((root / 'manifests/files.json').read_text())['files']
    expected = {r['path'] for r in rows}
    require(len(expected) == len(rows), 'Duplicate prepared inventory records')
    paths = list(root.rglob('*'))
    require(not any(p.is_symlink() for p in paths), 'Prepared symlinks are not allowed')
    actual = {p.relative_to(root).as_posix() for p in paths if p.is_file()}
    require(actual == expected | {'manifests/files.json'}, 'Prepared inventory membership differs')
    for row in rows:
        path = relative(root, row['path'])
        require(path.is_file() and path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], 'Prepared checksum differs: ' + row['path'])
    records = json.loads((root / 'manifests/images-lock.json').read_text())
    require(len({r['image'] for r in records}) == len(records), 'Duplicate prepared images')
    checked = set()
    for row in records: image(root / 'images/layout', row['image'], row['digest'], checked)
    require({r['kind'] for r in records} >= {'core', 'ui', 'bootstrap'}, 'Prepared image roles are incomplete')
    print('PREPARED_VERIFIED', len(rows), 'files;', len(records), 'images', flush=True)
    return descriptor
