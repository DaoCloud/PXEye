#!/usr/bin/env python3
"""Export the onsite helper kit for an already-built Helm bundle (no large-file rebuild)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from urllib.request import urlopen

HOME = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toolchain(target):
    """Resolve fixed Linux tools on the build host; field hosts never download."""
    lock = json.loads((HOME / 'toolchain.json').read_text())
    cache = Path(os.environ.get('ONSITE_TOOLS_CACHE', str(HOME.parents[1] / 'outputs_/cache/onsite-tools/linux-amd64'))).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True)
    for row in lock['tools']:
        name = row['name']
        asset = cache / (name + '.tar.gz' if row.get('member') else name)
        if not asset.is_file() or digest(asset) != row['sha256']:
            temporary = asset.with_name(asset.name + '.part')
            for attempt in range(3):
                try:
                    with urlopen(row['url'], timeout=30) as source, temporary.open('wb') as output:
                        shutil.copyfileobj(source, output, 1024**2)
                    if digest(temporary) != row['sha256']:
                        raise ValueError('Tool checksum mismatch: ' + name)
                    temporary.replace(asset)
                    break
                except (OSError, ValueError):
                    temporary.unlink(missing_ok=True)
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
        destination = target / name
        if row.get('member'):
            with tarfile.open(asset, 'r:gz') as archive:
                member = archive.getmember(row['member'])
                if not member.isfile():
                    raise ValueError('Tool member is not a regular file: ' + name)
                with archive.extractfile(member) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
            if digest(destination) != row['binary_sha256']:
                raise ValueError('Extracted tool checksum mismatch: ' + name)
        else:
            shutil.copyfile(asset, destination)
        destination.chmod(0o755)
        print('ONSITE_TOOL_READY', name, row['version'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    archive = root.with_name(root.name + '.tar.gz')
    if root.exists() or archive.exists():
        raise SystemExit('Output directory/archive exists; choose a new output')
    target = root / 'tools/onsite'; target.mkdir(parents=True)
    for name in ('install.sh', 'toolchain.json', 'README.zh-CN.md', 'README.md'):
        shutil.copyfile(HOME / name, target / name)
    shutil.copytree(HOME / 'lib', target / 'lib')
    toolchain(root / 'tools/bin')
    launcher = root / 'install.sh'
    launcher.write_text('#!/usr/bin/env bash\nset -euo pipefail\nROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)\nexec bash "$ROOT/tools/onsite/install.sh" "$@"\n')
    launcher.chmod(0o755)
    revision = subprocess.run(['git', '-C', str(HOME.parents[1]), 'rev-parse', 'HEAD'], text=True, capture_output=True)
    if revision.returncode == 0:
        (root / 'source-revision.txt').write_text(revision.stdout)
    sums = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix())
    (root / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(root, arcname=root.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n')
    print('ONSITE_KIT_EXPORTED', archive)


if __name__ == '__main__':
    main()
