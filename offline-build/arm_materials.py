"""Validate and lock optional ARM64 boot materials for offline delivery.

This module intentionally has no Docker, Registry, Helm, or network dependency.
The delivery entrypoint decides how to build and publish the resulting material
image.  Keeping source validation and the generated lock here makes the
large optional payload reusable without changing the default image-only path.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping


HOME = Path(__file__).resolve().parent
RECIPE = HOME / 'material-prepare/recipe-e703.json'
MATERIAL_ID = 'boot-aarch64'
ENV_ENABLED = 'INCLUDE_ARM64_MATERIALS'
ENV_DIRECTORY = 'ARM64_MATERIALS_DIR'
LOCK_SCHEMA_VERSION = 1
LAYOUT_VERSION = 'aarch64-pxe-payload-v1'
EXPECTED_TARGETS = (
    'BUILD-INFO.json',
    'ROOTFS-PACKAGES.json',
    'golan.efi',
    'ipxe.efi',
    'scout.efi',
    'scout.squashfs',
)
SHA256 = re.compile(r'^[0-9a-f]{64}$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')


@dataclass(frozen=True)
class MaterialFile:
    """One verified ARM boot file and its intended image payload path."""

    source: Path
    target: str
    payload_path: str
    bytes: int
    sha256: str

    def as_dict(self) -> dict:
        return {
            'target': self.target,
            'payload_path': self.payload_path,
            'bytes': self.bytes,
            'sha256': self.sha256,
        }


@dataclass(frozen=True)
class ArmMaterial:
    """Optional ARM material state supplied to the delivery orchestrator."""

    enabled: bool
    content_id: str | None = None
    source_dir: Path | None = None
    files: tuple[MaterialFile, ...] = ()
    cache_dir: Path | None = None
    lock_path: Path | None = None
    recipe_sha256: str | None = None

    def as_manifest(self) -> dict:
        if not self.enabled:
            return {'enabled': False}
        return {
            'enabled': True,
            'id': MATERIAL_ID,
            'content_id': self.content_id,
            'recipe_sha256': self.recipe_sha256,
            'files': [row.as_dict() for row in self.files],
            'payload_root': '/payload/aarch64',
            'publish_path': 'aarch64',
        }


DISABLED = ArmMaterial(enabled=False)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            value.update(block)
    return value.hexdigest()


def _stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.' + path.name + '-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Parse the strict ARM switch without looking at the source directory."""
    value = (environ or os.environ).get(ENV_ENABLED, '0')
    _require(value in ('0', '1'), ENV_ENABLED + ' must be exactly 0 or 1')
    return value == '1'


def _recipe_rows() -> tuple[list[dict], str]:
    _require(RECIPE.is_file() and not RECIPE.is_symlink(), 'Missing material recipe: ' + str(RECIPE))
    recipe_bytes = RECIPE.read_bytes()
    recipe = json.loads(recipe_bytes)
    rows = [row for row in recipe.get('materials', []) if row.get('group') == 'aarch64']
    _require(len(rows) == len(EXPECTED_TARGETS), 'ARM material recipe must contain exactly six aarch64 files')
    targets = tuple(row.get('target') for row in rows)
    _require(targets == EXPECTED_TARGETS,
             'ARM material recipe targets differ from the supported direct input layout')
    for row in rows:
        _require(isinstance(row.get('path'), str) and row['path'].startswith('boot/aarch64/'),
                 'Unsafe ARM material recipe path')
        _require(isinstance(row.get('bytes'), int) and row['bytes'] > 0,
                 'Invalid ARM material recipe size: ' + str(row.get('target')))
        _require(isinstance(row.get('sha256'), str) and SHA256.fullmatch(row['sha256']) is not None,
                 'Invalid ARM material recipe SHA-256: ' + str(row.get('target')))
    return rows, hashlib.sha256(recipe_bytes).hexdigest()


def _source_dir(environ: Mapping[str, str]) -> Path:
    raw = environ.get(ENV_DIRECTORY, '')
    _require(raw, ENV_DIRECTORY + ' is required when ' + ENV_ENABLED + '=1')
    original = Path(raw).expanduser()
    _require(original.is_absolute(), ENV_DIRECTORY + ' must be an absolute directory')
    _require(not original.is_symlink(), ENV_DIRECTORY + ' must not be a symlink')
    root = original.resolve()
    _require(root.is_dir(), ENV_DIRECTORY + ' is not a directory: ' + str(root))
    return root


def _state(path: Path) -> dict:
    stat = path.stat()
    return {'target': path.name, 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'device': stat.st_dev, 'inode': stat.st_ino}


def _validated_source(cache_root: Path, source: Path, rows: list[dict], recipe_sha256: str) -> tuple[tuple[MaterialFile, ...], bool]:
    """Validate the raw files, reusing a matching local validation record."""
    targets = [row['target'] for row in rows]
    files = []
    for row in rows:
        path = source / row['target']
        _require(path.is_file() and not path.is_symlink() and path.resolve().parent == source,
                 'Missing or unsafe ARM material: ' + str(path))
        _require(path.stat().st_size == row['bytes'], 'ARM material size differs: ' + row['target'])
        files.append(path)
    current_state = [_state(path) for path in files]
    validation = cache_root / 'source-validation.json'
    reused = False
    if validation.is_file() and not validation.is_symlink():
        try:
            previous = json.loads(validation.read_text())
            reused = (previous.get('schema_version') == LOCK_SCHEMA_VERSION and
                      previous.get('material_id') == MATERIAL_ID and
                      previous.get('recipe_sha256') == recipe_sha256 and
                      previous.get('source_dir') == str(source) and
                      previous.get('state') == current_state and
                      previous.get('targets') == targets)
        except (json.JSONDecodeError, OSError):
            reused = False
    if not reused:
        for row, path in zip(rows, files, strict=True):
            _require(_sha(path) == row['sha256'], 'ARM material SHA-256 differs: ' + row['target'])
        _atomic_json(validation, {
            'schema_version': LOCK_SCHEMA_VERSION,
            'material_id': MATERIAL_ID,
            'recipe_sha256': recipe_sha256,
            'source_dir': str(source),
            'targets': targets,
            'state': current_state,
        })
    return tuple(MaterialFile(source=source / row['target'], target=row['target'],
                              payload_path='aarch64/' + row['target'],
                              bytes=row['bytes'], sha256=row['sha256']) for row in rows), reused


def image_content_id(material: ArmMaterial, base_digest: str, initializer_digest: str) -> str:
    """Derive a material-image identity from validated payload and implementation inputs."""
    _require(material.enabled and material.content_id and material.files,
             'ARM material is not enabled')
    _require(DIGEST.fullmatch(base_digest) is not None, 'Invalid ARM material base image digest')
    _require(SHA256.fullmatch(initializer_digest) is not None,
             'Invalid ARM material initializer SHA-256')
    return _stable_hash({
        'source_content_id': material.content_id,
        'base_digest': base_digest,
        'initializer_sha256': initializer_digest,
        'layout_version': LAYOUT_VERSION,
    })


def prepare(work_directory: Path | str, environ: Mapping[str, str] | None = None) -> ArmMaterial:
    """Return the validated ARM material descriptor or a disabled sentinel.

    When disabled, this function intentionally does not parse or stat
    ``ARM64_MATERIALS_DIR``.  When enabled, it writes a local source-validation
    cache and a material lock skeleton below ``<work>/cache/materials``.
    """
    env = environ or os.environ
    if not enabled(env):
        return DISABLED
    work = Path(work_directory).expanduser()
    _require(work.is_absolute(), 'work_directory must be absolute for ARM material preparation')
    work = work.resolve()
    rows, recipe_sha256 = _recipe_rows()
    source = _source_dir(env)
    cache_root = work / 'cache/materials' / MATERIAL_ID
    files, reused = _validated_source(cache_root, source, rows, recipe_sha256)
    source_content_id = _stable_hash({
        'material_id': MATERIAL_ID,
        'recipe_sha256': recipe_sha256,
        'layout_version': LAYOUT_VERSION,
        'files': [row.as_dict() for row in files],
    })
    cache_dir = cache_root / ('sha-' + source_content_id)
    lock_path = cache_dir / 'materials-lock.json'
    material = ArmMaterial(enabled=True, content_id=source_content_id, source_dir=source,
                           files=files, cache_dir=cache_dir, lock_path=lock_path,
                           recipe_sha256=recipe_sha256)
    existing = read_image_lock(material)
    lock = {
        'schema_version': LOCK_SCHEMA_VERSION,
        'kind': 'pxeye-arm64-material',
        'material_id': MATERIAL_ID,
        'content_id': source_content_id,
        'layout_version': LAYOUT_VERSION,
        'recipe_sha256': recipe_sha256,
        'files': [row.as_dict() for row in files],
        'source_validation_reused': reused,
    }
    if existing is not None:
        lock['image'] = existing['image']
    _atomic_json(lock_path, lock)
    return material


def read_image_lock(material: ArmMaterial) -> dict | None:
    """Read a complete image record for the given validated material, if any."""
    if not material.enabled or material.lock_path is None or not material.lock_path.is_file():
        return None
    try:
        data = json.loads(material.lock_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if (data.get('schema_version') != LOCK_SCHEMA_VERSION or
            data.get('kind') != 'pxeye-arm64-material' or
            data.get('material_id') != MATERIAL_ID or
            data.get('content_id') != material.content_id):
        return None
    image = data.get('image')
    if not isinstance(image, dict):
        return None
    reference, digest = image.get('reference'), image.get('digest')
    if not isinstance(reference, str) or not reference or DIGEST.fullmatch(str(digest)) is None:
        return None
    return data


def write_image_lock(material: ArmMaterial, *, reference: str, digest: str,
                     image_content: str, base_digest: str,
                     initializer_sha256: str) -> dict:
    """Persist the Registry result after the caller has built and inspected it."""
    _require(material.enabled and material.lock_path is not None,
             'ARM material is not enabled')
    _require(isinstance(reference, str) and reference and '\n' not in reference and '\r' not in reference,
             'Invalid ARM material Registry reference')
    _require(DIGEST.fullmatch(digest) is not None, 'Invalid ARM material Registry digest')
    _require(SHA256.fullmatch(image_content) is not None, 'Invalid ARM material image content ID')
    _require(DIGEST.fullmatch(base_digest) is not None, 'Invalid ARM material base image digest')
    _require(SHA256.fullmatch(initializer_sha256) is not None,
             'Invalid ARM material initializer SHA-256')
    _require(SHA256.fullmatch(str(material.recipe_sha256)) is not None,
             'ARM material lacks a validated recipe SHA-256')
    data = {
        'schema_version': LOCK_SCHEMA_VERSION,
        'kind': 'pxeye-arm64-material',
        'material_id': MATERIAL_ID,
        'content_id': material.content_id,
        'layout_version': LAYOUT_VERSION,
        'recipe_sha256': material.recipe_sha256,
        'files': [row.as_dict() for row in material.files],
        'image': {
            'reference': reference,
            'digest': digest,
            'content_id': image_content,
            'base_digest': base_digest,
            'initializer_sha256': initializer_sha256,
        },
    }
    _atomic_json(material.lock_path, data)
    return data
