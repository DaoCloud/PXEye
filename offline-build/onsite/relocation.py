"""Adapt root scalar image hints for relok8s 0.5.4 without changing image blobs."""
import copy
import io
from pathlib import Path
import re
import tarfile

import yaml

ROOT_FIELDS = '__pxeye_relocation_root_fields__'
FIELD = re.compile(r'{{\s*\.([A-Za-z_][A-Za-z0-9_.]*)\s*}}')


def get_path(value, path):
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise ValueError('Relocation image hint is not a scalar value: ' + path)
        value = value[part]
    if not isinstance(value, str):
        raise ValueError('Relocation image hint is not a scalar value: ' + path)
    return value


def set_path(value, path, replacement):
    parts = path.split('.')
    for part in parts[:-1]:
        if not isinstance(value, dict) or part not in value:
            raise ValueError('Relocation image path disappeared: ' + path)
        value = value[part]
    if not isinstance(value, dict) or parts[-1] not in value:
        raise ValueError('Relocation image path disappeared: ' + path)
    value[parts[-1]] = replacement


def prepare_intermediate(source, destination):
    """Return source unchanged, or create a derived archive with nested aliases."""
    source, destination = Path(source), Path(destination)
    with tarfile.open(source, 'r:') as incoming:
        def read(name):
            member = incoming.getmember(name)
            if not member.isfile() or member.size > 4 * 1024**2:
                raise ValueError('Invalid relocation metadata: ' + name)
            return incoming.extractfile(member).read()
        hints = yaml.safe_load(read('hints.yaml'))
        values = yaml.safe_load(read('original-chart/values.yaml'))
        fields = {m[1] for hint in hints for m in FIELD.finditer(hint)}
        if not fields:
            return source
        if ROOT_FIELDS in values:
            raise ValueError('Reserved relocation field already exists')
        aliases = {field.replace('.', '__'): field for field in sorted(fields)}
        if len(aliases) != len(fields):
            raise ValueError('Relocation image hint aliases collide')
        values[ROOT_FIELDS] = {alias: get_path(values, field) for alias, field in aliases.items()}
        def nest(match):
            return '{{ .' + ROOT_FIELDS + '.' + match[1].replace('.', '__') + ' }}'
        hints = [FIELD.sub(nest, hint) for hint in hints]
        updates = {'hints.yaml': yaml.safe_dump(hints).encode(),
                   'original-chart/values.yaml': yaml.safe_dump(values, sort_keys=False).encode(),
                   'original-chart/.relok8s-images.yaml': yaml.safe_dump(hints).encode()}
        # Only metadata changes. Stream the original image payload byte-for-byte;
        # never modify the verified input archive or recompress its images.
        with tarfile.open(destination, 'w:') as outgoing:
            for member in incoming:
                if member.name in updates:
                    data = updates[member.name]
                    metadata = copy.copy(member); metadata.size = len(data)
                    outgoing.addfile(metadata, io.BytesIO(data))
                else:
                    outgoing.addfile(member, incoming.extractfile(member) if member.isfile() else None)
    print('ADAPT_ROOT_IMAGE_HINTS', ','.join(sorted(fields)), flush=True)
    return destination


def restore_root_fields(root):
    """Restore the original public values shape after relok8s rewrites aliases."""
    path = Path(root) / 'values.yaml'
    values = yaml.safe_load(path.read_text())
    aliases = values.pop(ROOT_FIELDS, None)
    if aliases is None:
        return
    if not isinstance(aliases, dict) or any(not isinstance(value, str) for value in aliases.values()):
        raise ValueError('Invalid relocated root image aliases')
    for alias, replacement in aliases.items():
        set_path(values, alias.replace('__', '.'), replacement)
    path.write_text(yaml.safe_dump(values, sort_keys=False))
    hints = Path(root) / '.relok8s-images.yaml'
    if hints.is_file():
        text = hints.read_text()
        for alias in aliases:
            text = text.replace('.' + ROOT_FIELDS + '.' + alias, '.' + alias.replace('__', '.'))
        hints.write_text(text)
