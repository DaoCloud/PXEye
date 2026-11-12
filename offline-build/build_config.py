"""Shared build configuration; stage initialization preserves other stages and user values."""
import fcntl
import json
import os
from pathlib import Path
import tempfile

HOME = Path(__file__).resolve().parent
IMAGE_KEYS = {'image_list', 'containerd_content', 'containerd_address', 'containerd_namespace', 'ctr'}


def read(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('build-config.json must contain an object')
    return value


def relative(path, value):
    result = Path(value).expanduser()
    return (path.parent / result).resolve() if not result.is_absolute() else result.resolve()


def initialize(path, section, work_directory=None):
    """Fill only the calling stage's missing fields and its absent example file."""
    path = path.expanduser().absolute()
    if path.name != 'build-config.json' or path.is_symlink():
        raise ValueError('Use a non-symlink build-config.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = json.loads((HOME / 'build-config.example.json').read_text())
    with (path.parent / '.build-config.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = read(path) if path.exists() else {}
        proposed = (work_directory or path.parent).expanduser().resolve()
        if 'work_directory' in value:
            configured = Path(value['work_directory']).expanduser().resolve()
            if work_directory is not None and configured != proposed:
                raise ValueError('work_directory differs; existing configuration was not overwritten')
        else:
            value['work_directory'] = str(proposed)
        # Migrate only the image-export fields of the former shared sources object.
        legacy = value.get('sources', {})
        if section == 'image_export' and isinstance(legacy, dict) and any(key in legacy for key in IMAGE_KEYS):
            exported = value.setdefault('image_export', {})
            for key in IMAGE_KEYS & legacy.keys():
                if key in exported and exported[key] != legacy[key]:
                    raise ValueError('Conflicting legacy image-export setting: ' + key)
                exported.setdefault(key, legacy[key])
            value['sources'] = {key: item for key, item in legacy.items() if key not in IMAGE_KEYS}
            if not value['sources']:
                del value['sources']
        owned = value.setdefault(section, {})
        if not isinstance(owned, dict):
            raise ValueError(section + ' must contain an object')
        for key, item in defaults[section].items():
            owned.setdefault(key, item)
        if section == 'image_export':
            key, source = None, None
        else:
            key, source = 'chart_sources', HOME / 'helm-bundle/chart-sources.json'
        if key is None:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.build-config-', delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    json.dump(value, stream, indent=2, ensure_ascii=False)
                    stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            print('BUILD_CONFIG_READY', path, 'section=' + section, flush=True)
            return
        target = relative(path, owned[key])
        # Custom paths belong to the user. Only provision the stage's default filename.
        if owned[key] == defaults[section][key] and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(source.read_bytes())
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.build-config-', delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(value, stream, indent=2, ensure_ascii=False)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    print('BUILD_CONFIG_READY', path, 'section=' + section, flush=True)
