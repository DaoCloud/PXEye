"""Adapt root scalar image hints for relok8s 0.5.4 without changing image blobs."""
import copy
import io
from pathlib import Path
import re
import tarfile

import yaml

ROOT_FIELDS = '__pxeye_relocation_root_fields__'
FIELD = re.compile(r'{{\s*\.([A-Za-z_][A-Za-z0-9_]*)\s*}}')


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
        if any(not isinstance(values.get(field), str) for field in fields):
            raise ValueError('Root image hints must reference existing string fields')
        values[ROOT_FIELDS] = {field: values[field] for field in sorted(fields)}
        def nest(match):
            return '{{ .' + ROOT_FIELDS + '.' + match[1] + ' }}'
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
    if not isinstance(aliases, dict) or any(not isinstance(value, str) or not isinstance(values.get(key), str)
                                            for key, value in aliases.items()):
        raise ValueError('Invalid relocated root image aliases')
    values.update(aliases)
    path.write_text(yaml.safe_dump(values, sort_keys=False))
    hints = Path(root) / '.relok8s-images.yaml'
    if hints.is_file():
        hints.write_text(hints.read_text().replace('.' + ROOT_FIELDS + '.', '.'))
