#!/usr/bin/env python3
"""Inspect final Grace payloads without executing GPU workloads."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_record(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(block)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def elf(data, name, pages=False):
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('Not AArch64 ELF: ' + name)
    if pages:
        offset = struct.unpack_from('<Q', data, 32)[0]
        size, count = struct.unpack_from('<HH', data, 54)
        for index in range(count):
            header = offset + index * size
            if struct.unpack_from('<I', data, header)[0] == 1:
                position, address = struct.unpack_from('<QQ', data, header + 8)
                if (address - position) % 65536:
                    raise ValueError('ELF incompatible with 64K pages: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('version', 'core', 'libredfish'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    source = Path('/code')
    payload = source / 'pxe/static/blobs/internal/aarch64'
    image = payload / 'scout.squashfs'

    def cat(name):
        return subprocess.check_output(['unsquashfs', '-cat', str(image), name])

    for name in ('ipxe.efi', 'golan.efi', 'scout.efi'):
        with (payload / name).open('rb') as stream:
            data = stream.read(4096)
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if data[:2] != b'MZ' or data[offset:offset + 4] != b'PE\0\0' or struct.unpack_from('<H', data, offset + 4)[0] != 0xaa64:
            raise ValueError('Not ARM64 EFI: ' + name)
    hashes = {}
    for name in ('forge-scout', 'mlx-firmware-supervisor'):
        data = cat('opt/forge/' + name)
        elf(data, name, pages=True)
        expected = source / 'target/aarch64-unknown-linux-gnu/release' / name
        if sha(data) != file_record(expected)['sha256']:
            raise ValueError('Rootfs binary differs from this build: ' + name)
        hashes[name] = sha(data)
    if sha(cat('opt/forge/forge_root.pem')) != file_record(Path('/inputs/scout-ca.crt'))['sha256']:
        raise ValueError('Rootfs CA differs from the selected public CA')
    if cat('etc/scout-image-version').decode().strip() != args.version:
        raise ValueError('Rootfs version differs from this build')
    packages = []
    for stanza in cat('var/lib/dpkg/status').decode().split('\n\n'):
        fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                      if ': ' in line and not line.startswith(' '))
        status = fields.get('Status', '')
        if status.endswith('ok installed'):
            packages.append({key: fields.get(key) for key in ('Package', 'Version', 'Architecture')})
        elif status and status not in ('deinstall ok config-files', 'purge ok not-installed'):
            raise ValueError('Unfinished package: ' + str(fields.get('Package')))
    listing = subprocess.check_output(['unsquashfs', '-ll', str(image)], text=True)
    modules = []
    for name in ('nvidia.ko.zst', 'mlx5_ib.ko.zst'):
        paths = {line.split('squashfs-root/', 1)[1] for line in listing.splitlines()
                 if 'squashfs-root/' in line and line.endswith('/' + name)
                 and line.split('squashfs-root/', 1)[1].startswith(
                     ('usr/lib/modules/', 'lib/modules/'))}
        if len(paths) != 1:
            raise ValueError('Expected exactly one kernel module: ' + name)
        path = paths.pop()
        kernel = path.split('/modules/', 1)[1].split('/', 1)[0]
        data = subprocess.check_output(['zstd', '-dc'], input=cat(path))
        elf(data, path)
        if b'vermagic=' + kernel.encode() + b' ' not in data:
            raise ValueError('Kernel module ABI mismatch: ' + path)
        modules.append({'path': path, 'kernel': kernel, 'sha256': sha(data)})
    names = ('BUILD-INFO.json', 'ROOTFS-PACKAGES.json', 'golan.efi', 'ipxe.efi', 'scout.efi', 'scout.squashfs')
    (payload / 'ROOTFS-PACKAGES.json').write_text(json.dumps(packages, indent=2) + '\n')
    info = {'schema_version': 1, 'built_at': datetime.now(timezone.utc).isoformat(),
            'architecture': 'aarch64', 'core_commit': args.core, 'libredfish_commit': args.libredfish,
            'scout_version': args.version, 'verified_binaries': hashes, 'modules': modules,
            'configured_packages': len(packages), 'real_grace_boot_performed': False,
            'gpu_tests_performed': False, 'efi_signed': False,
            'files': {name: file_record(payload / name) for name in names[2:]}}
    (payload / 'BUILD-INFO.json').write_text(json.dumps(info, indent=2) + '\n')
    recipe = {'schema_version': 1, 'source': {'core_commit': args.core, 'libredfish_commit': args.libredfish},
              'materials': [dict(group='aarch64', target=name, path='boot/aarch64/' + name,
                                 **file_record(payload / name)) for name in names]}
    (payload / 'MATERIAL-RECIPE.json').write_text(json.dumps(recipe, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
