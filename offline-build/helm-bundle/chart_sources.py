"""Download pinned upstream Charts and prepare inspectable, compatible Chart trees."""
import hashlib
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

import yaml

HOME = Path(__file__).resolve().parent


def settings(overrides=None):
    defaults = json.loads((HOME / 'chart-sources.json').read_text())
    if isinstance(overrides, Path):
        supplied = json.loads(overrides.read_text())
        if not isinstance(supplied, dict) or set(supplied) != set(defaults):
            raise ValueError('Chart source file must define core and cert-manager')
        for key, row in supplied.items():
            if not isinstance(row, dict) or set(row) != set(defaults[key]):
                raise ValueError('Use the complete Chart source example fields: ' + key)
            if any(row[field] != defaults[key][field] for field in ('name', 'version')):
                raise ValueError('Chart version must match the pinned image/compatibility profile: ' + key)
        defaults = supplied
        overrides = None
    overrides = overrides or {}
    if set(overrides) - set(defaults):
        raise ValueError('Only core and cert-manager download sources are supported')
    for key, supplied in overrides.items():
        if set(supplied) - {'url', 'sha256', 'subdirectory'}:
            raise ValueError('Override url, sha256 and subdirectory; Chart versions are pinned by the profile')
        defaults[key].update(supplied)
    for row in defaults.values():
        url = urllib.parse.urlsplit(row['url'])
        if url.scheme not in ('https', 'http', 'file', 'oci') or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use a public HTTP(S)/OCI Chart URL or local file URI, without credentials or query parameters')
        if len(row['sha256']) != 64 or any(c not in '0123456789abcdef' for c in row['sha256']):
            raise ValueError('Every downloaded Chart requires SHA256')
        sub = Path(row['subdirectory'])
        if sub.is_absolute() or '..' in sub.parts or not sub.parts:
            raise ValueError('Use a safe archive-relative Chart subdirectory')
    return defaults


def extract(archive, subdirectory, target):
    """Extract only the selected Chart subtree, including its packaged dependencies."""
    prefix = Path(subdirectory)
    seen = set(); total = 0
    with tarfile.open(archive, 'r:*') as incoming:
        members = incoming.getmembers()
        indexed = {m.name.rstrip('/'): m for m in members}
        if len(indexed) != len(members): raise ValueError('Duplicate Chart archive member')
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe Chart archive path')
            if not name.is_relative_to(prefix):
                continue
            relative = name.relative_to(prefix)
            if not relative.parts:
                if not member.isdir(): raise ValueError('Expected Chart directory')
                continue
            if relative.as_posix() in seen or not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError('Duplicate or unsupported entry in Chart archive')
            content = member
            links = set()
            while content.issym():
                if content.name in links: raise ValueError('Cyclic Chart symlink')
                links.add(content.name)
                resolved = Path(posixpath.normpath(posixpath.join(posixpath.dirname(content.name), content.linkname)))
                if not resolved.is_relative_to(prefix): raise ValueError('Chart symlink leaves selected subtree')
                content = indexed.get(resolved.as_posix())
                if content is None: raise ValueError('Chart symlink target is missing')
            if not (content.isdir() or content.isfile()) or (member.issym() and not content.isfile()):
                raise ValueError('Chart links must resolve to regular files')
            seen.add(relative.as_posix()); total += content.size
            if total > 256 * 1024**2: raise ValueError('Chart subtree exceeds 256 MiB')
            destination = target / relative
            if member.isdir(): destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with incoming.extractfile(content) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(0o755 if content.mode & 0o111 else 0o644)
    metadata = target / 'Chart.yaml'
    if not metadata.is_file(): raise ValueError('Downloaded archive lacks Chart.yaml at ' + subdirectory)
    return yaml.safe_load(metadata.read_text())


def prepare(work, overrides, b, helm='helm'):
    configured = settings(overrides)
    local = [b.REPO / 'deploy/nico-platform', b.REPO / 'charts/pxeye', b.ASSETS / 'patches']
    implementation = {str(p.relative_to(b.REPO)): b.sha(p) for root in local
                      for p in sorted(root.rglob('*')) if p.is_file()}
    implementation.update({str(p.relative_to(b.REPO)): b.sha(p) for p in
                           [Path(__file__), HOME.parent / 'build.py']})
    identity = hashlib.sha256(json.dumps({'sources': configured, 'implementation': implementation}, sort_keys=True).encode()).hexdigest()
    root = Path(work) / 'charts' / identity[:24]
    if root.exists():
        record = json.loads((root / 'sources.json').read_text())
        b.require(record['identity'] == identity, 'Chart cache identity differs')
        expected = {r['path'] for r in record['files']} | {'sources.json'}
        paths = list(root.rglob('*'))
        b.require(not any(p.is_symlink() for p in paths) and
                  {p.relative_to(root).as_posix() for p in paths if p.is_file()} == expected, 'Chart cache membership differs')
        for row in record['files']:
            path = root / row['path']
            b.require(path.is_file() and b.sha(path) == row['sha256'], 'Chart cache changed: ' + str(path))
        print('REUSE_CHARTS', root, flush=True)
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.charts-', dir=root.parent))
    cache = Path(work) / 'cache/charts'; cache.mkdir(parents=True, exist_ok=True)
    try:
        raw = stage / 'raw'; (raw / 'charts').mkdir(parents=True)
        expected = {}
        for key, row in configured.items():
            archive = cache / (row['sha256'] + '.tar.gz')
            if not archive.exists():
                temporary = archive.with_suffix('.part')
                print('DOWNLOAD_CHART', key, row['url'], flush=True)
                try:
                    if row['url'].startswith('oci://'):
                        with tempfile.TemporaryDirectory(dir=cache) as directory:
                            result = subprocess.run([helm, 'pull', row['url'], '--version', row['version'], '--destination', directory],
                                                    capture_output=True, text=True, timeout=300)
                            b.require(result.returncode == 0, 'Helm Chart download failed: ' + result.stderr[-2000:])
                            packages = list(Path(directory).glob('*.tgz'))
                            b.require(len(packages) == 1, 'Expected one downloaded Helm Chart')
                            shutil.copyfile(packages[0], temporary)
                    else:
                        with urllib.request.urlopen(row['url'], timeout=60) as source, temporary.open('wb') as output:
                            total = 0
                            for block in iter(lambda: source.read(1024**2), b''):
                                total += len(block)
                                b.require(total <= 512 * 1024**2, 'Chart source archive exceeds 512 MiB')
                                output.write(block)
                    b.require(b.sha(temporary) == row['sha256'], 'Downloaded Chart checksum differs: ' + key)
                    temporary.replace(archive)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                # The cache is a local, immutable build-input cache.  Its name
                # is the checksum verified when first stored; subsequent runs
                # must not block on a slow source or rehash large archives.
                print('REUSE_DOWNLOADED_CHART', key, archive, flush=True)
            tree = stage / 'upstream' / key
            tree.mkdir(parents=True)
            metadata = extract(archive, row['subdirectory'], tree)
            b.require(metadata['name'] == row['name'] and str(metadata['version']) == row['version'], 'Downloaded Chart name/version differs: ' + key)
            filename = row['name'] + '-' + row['version'] + '.tgz'
            b.pack_tree(tree, raw / 'charts' / filename, row['name'])
            expected[filename] = b.sha(raw / 'charts' / filename)
        deployment = stage / 'deployment'
        (deployment / 'charts').mkdir(parents=True); (deployment / 'patches').mkdir()
        scratch = stage / '.patch'; scratch.mkdir()
        b.patch_core(raw, deployment, scratch, expected_charts=expected)
        b.dump(deployment / 'upstream-sources.json', configured)
        shutil.rmtree(scratch)
        for filename, key in [('nico-0.1.1.tgz', 'core'), ('cert-manager-v1.17.1.tgz', 'cert-manager'), ('pxeye-nico-platform-0.1.0.tgz', 'platform')]:
            with tarfile.open(deployment / 'charts' / filename) as archive:
                prefix = next(m.name.split('/')[0] for m in archive if m.isfile())
            extract(deployment / 'charts' / filename, prefix, stage / 'trees' / key)
        shutil.copytree(b.REPO / 'charts/pxeye', stage / 'trees/pxeye')
        files = [{'path': p.relative_to(stage).as_posix(), 'sha256': b.sha(p)} for p in sorted(stage.rglob('*')) if p.is_file()]
        b.dump(stage / 'sources.json', {'identity': identity, 'sources': configured, 'files': files})
        stage.rename(root)
        print('CHARTS_READY', root, flush=True)
        return root
    except BaseException:
        print('CHART_PREPARATION_FAILED; staging retained at', stage, flush=True)
        raise
