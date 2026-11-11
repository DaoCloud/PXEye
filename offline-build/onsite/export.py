#!/usr/bin/env python3
"""Export the onsite helper kit for an already-built Helm bundle (no large-file rebuild)."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile

HOME = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    archive = root.with_name(root.name + '.tar.gz')
    if root.exists() or archive.exists():
        raise SystemExit('Output directory/archive exists; choose a new output')
    target = root / 'tools/onsite'; target.mkdir(parents=True)
    for name in ('onsite.py', 'registry_bridge.py', 'site-config.example.json', 'README.zh-CN.md', 'README.md', 'prepare_bundle.py', 'prepare-site.sh'):
        shutil.copyfile(HOME / name, target / name)
    wrapper = HOME / 'prepare-bundle.sh'
    if not wrapper.is_file(): wrapper = HOME.parent / 'prepare-bundle.sh'
    shutil.copyfile(wrapper, root / 'tools/prepare-bundle.sh')
    (root / 'tools/prepare-bundle.sh').chmod(0o755)
    verify = HOME.parent / 'helm-bundle/verify.py'
    if not verify.is_file(): verify = HOME.parent / 'verify.py'
    shutil.copyfile(verify, root / 'tools/verify.py')
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
