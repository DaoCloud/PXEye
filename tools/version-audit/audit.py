#!/usr/bin/env python3
"""Export committed packaging inputs and live artifacts, then compare their content."""
from __future__ import annotations

import argparse
from collections import defaultdict
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


DIGEST = re.compile(r"sha256:[0-9a-f]{64}$")
ROOT = "/forge-boot-artifacts/blobs/internal"
FILE_TEST = ("-name '*.efi' -o -name '*.squashfs' -o -name '*.iso' "
             "-o -name '*.bfb' -o -name '*.deb' -o -name 'vmlinuz*' "
             "-o -name 'initrd*' -o -name 'BUILD-INFO.json' -o -name 'ROOTFS-PACKAGES.json' "
             "-o -name 'mmzhou-build-info.json' -o -name 'kernel' -o -name 'linux'")
ACCEPT = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"


def run(args, *, cwd=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
                            text=True, timeout=600)
    if result.returncode:
        # Do not echo arbitrary subprocess stderr: it can contain credentials.
        raise ValueError(f"{args[0]} failed (exit {result.returncode}); check tool access and inputs")
    return result.stdout


def sha(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(8 * 1024**2), b""):
        h.update(block)
    return h.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def snapshot(kind):
    return {"schema_version": 1, "kind": kind,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "images": [], "files": [], "notes": [], "errors": []}


def role(reference):
    name = reference.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
    return {"mmzhou-os-install-console": "pxeye"}.get(name, name)


def file_key(name):
    name = name.removeprefix("./").lstrip("/")
    for prefix in ("payload/", "forge-boot-artifacts/blobs/internal/"):
        name = name.removeprefix(prefix)
    return name


def selected_file(name):
    p = Path(name)
    return (p.suffix in (".efi", ".squashfs", ".iso", ".bfb", ".deb")
            or p.name.startswith(("vmlinuz", "initrd"))
            or p.name in ("BUILD-INFO.json", "ROOTFS-PACKAGES.json", "mmzhou-build-info.json", "kernel", "linux"))


def build_revision(raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        return None
    return next((value[k] for k in ('source_commit', 'source_revision', 'git_commit')
                 if isinstance(value.get(k), str) and re.fullmatch('[0-9a-f]{7,40}', value[k])), None)


def canonical(reference):
    parts = reference.split('/')
    if len(parts) == 1:
        return 'docker.io/library/' + reference
    if not ('.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost'):
        return 'docker.io/' + reference
    return reference


class Content:
    """Use local OCI blobs first; public/cache Registry access is metadata-only.

    Image layers are read only from local containerd storage, never downloaded
    implicitly. Missing content remains explicitly unknown.
    """

    def __init__(self, args):
        self.args = args
        self.refs = {}
        self.memo = {}
        try:
            lines = run([args.ctr, '--namespace', args.containerd_namespace,
                         'images', 'list']).splitlines()[1:]
            for line in lines:
                parts = line.split()
                if len(parts) >= 3 and DIGEST.fullmatch(parts[2]):
                    self.refs[parts[0]] = parts[2]
                    self.refs[canonical(parts[0])] = parts[2]
        except (ValueError, OSError):
            pass

    def local(self, digest):
        if not DIGEST.fullmatch(digest):
            raise ValueError("Invalid OCI digest")
        return Path(self.args.content_dir) / digest.split(":", 1)[1]

    def reference(self, ref):
        if not self.args.registry:
            return ref
        # Same hostname replacement used by offline-build/delivery.py.
        parts = ref.split('/')
        repository = '/'.join(parts[1:]) if len(parts) > 1 and (
            '.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost') else ref
        if 'mmzhou-os-install-console' in repository:
            repository = 'pxeye:' + ref.rsplit(':', 1)[-1]
        return self.args.registry.rstrip('/') + '/' + repository

    def blob(self, digest, ref, *, config=False):
        path = self.local(digest)
        if path.is_file():
            data = path.read_bytes()
        else:
            ref = self.reference(ref)
            repo = ref.split('@', 1)[0]
            if ':' in repo.rsplit('/', 1)[-1]:
                repo = repo.rsplit(':', 1)[0]
            host, sep, repo = repo.partition('/')
            if not sep or not ('.' in host or ':' in host or host == 'localhost'):
                raise ValueError("Image absent from local content; supply --registry for a reachable cache")
            scheme = 'http' if self.args.registry_http else 'https'
            endpoint = 'blobs' if config else 'manifests'
            req = urllib.request.Request(f'{scheme}://{host}/v2/{repo}/{endpoint}/{digest}',
                                         headers={'Accept': ACCEPT})
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read(8 * 1024**2 + 1)
            if len(data) > 8 * 1024**2:
                raise ValueError("OCI metadata exceeds limit")
        if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("OCI metadata digest mismatch")
        return json.loads(data)

    def resolve(self, reference, digest=None):
        ref = self.reference(reference)
        if not digest and '@' in ref:
            digest = ref.rsplit('@', 1)[-1]
        # make bundles consumes the Registry, not a possibly stale local tag.
        if not digest and not self.args.registry:
            digest = self.refs.get(canonical(ref)) or self.refs.get(canonical(reference))
        if not digest:
            repo, _, tag = ref.rpartition(':')
            if '/' not in repo:
                raise ValueError("No local image record; use --registry or preload the image")
            host, repo = repo.split('/', 1)
            scheme = 'http' if self.args.registry_http else 'https'
            req = urllib.request.Request(f'{scheme}://{host}/v2/{repo}/manifests/{tag}',
                                         headers={'Accept': ACCEPT})
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read(8 * 1024**2 + 1)
            if len(data) > 8 * 1024**2:
                raise ValueError("OCI metadata exceeds limit")
            digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            manifest = json.loads(data)
        else:
            manifest = self.blob(digest, reference)
        if 'manifests' in manifest:
            candidates = [m for m in manifest['manifests'] if
                          m.get('platform', {}).get('os') == 'linux' and
                          m.get('platform', {}).get('architecture') == self.args.architecture]
            if len(candidates) != 1:
                raise ValueError("Missing or ambiguous OCI platform")
            digest = candidates[0]['digest']
            manifest = self.blob(digest, reference)
        if not manifest.get('config') or 'layers' not in manifest:
            raise ValueError("Not an OCI image manifest (possibly a config-only runtime imageID)")
        return digest, manifest

    def image(self, reference, runtime_id=None):
        result = {"role": role(reference), "reference": reference, "digest": None}
        try:
            candidate = runtime_id.rsplit('@', 1)[-1] if runtime_id else None
            if candidate:
                candidate = candidate.removeprefix('docker-pullable://').removeprefix('containerd://')
            if runtime_id and (not candidate or not DIGEST.fullmatch(candidate)):
                raise ValueError("Runtime did not report a usable content ID")
            try:
                digest, manifest = self.resolve(reference, candidate)
            except (ValueError, OSError) as error:
                if not candidate:
                    raise
                # Some CRI implementations expose config IDs, not manifests.
                # Match a local image only after verifying its config digest.
                digest, manifest = self.resolve(reference)
                if manifest['config']['digest'] != candidate:
                    raise ValueError("Cannot bind runtime imageID to a manifest") from error
            result['digest'] = digest
            result['config_digest'] = manifest['config']['digest']
            self.memo[digest] = manifest
            try:
                config = self.blob(manifest['config']['digest'], reference, config=True)
                labels = config.get('config', {}).get('Labels') or {}
                result['version'] = labels.get('org.opencontainers.image.version')
                result['revision'] = labels.get('org.opencontainers.image.revision')
            except (ValueError, OSError):
                result['provenance_note'] = 'OCI labels unavailable; manifest digest verified'
        except (ValueError, OSError) as error:
            result['error'] = str(error)
        return result

    def files(self, image):
        digest = image.get('digest')
        if digest not in self.memo:
            raise ValueError("Cannot inspect files without a resolved image manifest")
        files = {}
        for layer in self.memo[digest]['layers']:
            path = self.local(layer['digest'])
            if not path.is_file():
                raise ValueError("Image layers absent locally; preload image on the audit host")
            with path.open('rb') as stream:
                if 'sha256:' + sha(stream) != layer['digest']:
                    raise ValueError("Local OCI layer digest mismatch")
            with tarfile.open(path, 'r|*') as archive:
                for member in archive:
                    name = file_key(member.name)
                    if not name.startswith(('x86_64/', 'aarch64/', 'apt/')):
                        continue
                    parent, _, base = name.rpartition('/')
                    if base.startswith('.wh.'):
                        target = parent + '/' + base[4:]
                        prefix = parent + '/' if base == '.wh..wh..opq' else target + '/'
                        files = {k: v for k, v in files.items() if k != target and not k.startswith(prefix)}
                    elif selected_file(name):
                        if member.isfile():
                            with archive.extractfile(member) as stream:
                                metadata = stream.read() if Path(name).name == 'BUILD-INFO.json' and member.size <= 1024**2 else None
                                files[name] = {"path": name, "sha256": hashlib.sha256(metadata).hexdigest() if metadata is not None else sha(stream),
                                               "bytes": member.size, "source_image": image['reference']}
                                if metadata is not None:
                                    try:
                                        files[name]['declared_revision'] = build_revision(metadata)
                                    except ValueError:
                                        files[name]['provenance_note'] = 'Build metadata is not valid JSON'
                        elif member.issym() or member.islnk():
                            files[name] = {"path": name, "sha256": None,
                                           "error": "Link target not resolved; requires file verification"}
        if not files:
            raise ValueError('No supported Boot files found in image layers')
        return list(files.values())


RENDER = '''
import contextlib, importlib.util, json, pathlib, sys
root, work, helm, arm = sys.argv[1:]
sys.path.insert(0, root + '/offline-build')
import delivery
p = delivery.load_packager()
work = pathlib.Path(work)
options = {'work_directory': work, 'sources': {'charts': pathlib.Path(root) / 'offline-build/helm-bundle/chart-sources.json'}, 'tools': {'helm': helm}}
materials = [{'id': 'boot-aarch64', 'image': 'audit.invalid/boot-aarch64:generated'}] if arm == '1' else []
with contextlib.redirect_stdout(sys.stderr):
    path = delivery.chart_images(None, options, p, material_records=materials)
print(json.dumps(path.read_text().splitlines()))
'''


def package(args):
    report = snapshot('package')
    repo = Path(run(['git', '-C', args.repo, 'rev-parse', '--show-toplevel']).strip())
    commit = run(['git', '-C', repo, 'rev-parse', '--verify', '--end-of-options',
                  args.revision + '^{commit}']).strip()
    report.update(source_revision=commit, source='committed Git snapshot',
                  architecture=args.architecture, arm64_enabled=args.include_arm64)
    print(f'读取已提交配置 {commit[:12]}；不读取工作区修改。', file=sys.stderr)
    content = Content(args)
    with tempfile.TemporaryDirectory(prefix='pxeye-version-audit-') as tmp:
        root = Path(tmp) / 'repo'; root.mkdir()
        data = subprocess.run(['git', '-C', str(repo), 'archive', commit],
                              capture_output=True, check=True, timeout=60).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(root, filter='data')
        work = Path(tmp) / 'work'; work.mkdir()
        if args.chart_cache:
            target = work / 'cache/charts'; target.mkdir(parents=True)
            sources = json.loads((root / 'offline-build/helm-bundle/chart-sources.json').read_text())
            for row in sources.values():
                source = Path(args.chart_cache) / (row['sha256'] + '.tar.gz')
                if source.is_file():
                    with source.open('rb') as stream:
                        if sha(stream) != row['sha256']:
                            raise ValueError('Chart cache checksum mismatch: ' + source.name)
                    shutil.copyfile(source, target / source.name)
        references = json.loads(run([sys.executable, '-c', RENDER, root, work,
                                     args.helm, '1' if args.include_arm64 else '0']))
        for ref in references:
            if ref == 'audit.invalid/boot-aarch64:generated':
                continue
            print('检查镜像 ' + ref, file=sys.stderr)
            image = content.image(ref)
            report['images'].append(image)
            if 'boot-artifacts' in role(ref):
                try:
                    report['files'].extend(content.files(image))
                except (ValueError, OSError, tarfile.TarError) as error:
                    report['errors'].append('Boot镜像文件未确认: ' + str(error))
        if args.include_arm64:
            recipe = json.loads((root / 'offline-build/material-prepare/recipe-e703.json').read_text())
            for row in recipe['materials']:
                if row['group'] == 'aarch64':
                    report['files'].append({'path': 'aarch64/' + row['target'],
                                            'sha256': row['sha256'], 'bytes': row['bytes'],
                                            'source': 'committed ARM recipe; build validates payload'})
            report['notes'].append('ARM材料文件按已提交配方核对；材料镜像digest由构建时生成，本次不构建。')
        else:
            report['notes'].append('ARM材料未启用（与make bundles默认一致）；可加--include-arm64。')
    report['notes'].append('ISO由外部提供，不属于当前仓库默认离线包；环境额外文件会单独列出。')
    return report


def runtime(args):
    report = snapshot('runtime')
    report['context'] = args.context
    report['namespaces'] = args.namespace or ['nico-system', 'mmzhou']
    report['architecture'] = args.architecture
    report['file_scope'] = ROOT if not args.boot_root else args.boot_root
    content = Content(args)
    kube = [args.kubectl, '--context', args.context, '--request-timeout=30s']
    found = False
    file_sources = set()
    for namespace in report['namespaces']:
        pods = json.loads(run(kube + ['-n', namespace, 'get', 'pods', '-o', 'json']))
        for pod in pods['items']:
            meta, spec, status = pod['metadata'], pod['spec'], pod.get('status', {})
            if (not re.search(args.name_pattern, meta['name']) or meta.get('deletionTimestamp')
                    or status.get('phase') in ('Succeeded', 'Failed')):
                continue
            found = True
            statuses = {c['name']: c for c in status.get('containerStatuses', []) + status.get('initContainerStatuses', [])}
            for field in ('containers', 'initContainers'):
                for c in spec.get(field, []):
                    live = statuses.get(c['name'], {})
                    image = content.image(c['image'], live.get('imageID')) if live.get('imageID') else {
                        'role': role(c['image']), 'reference': c['image'], 'digest': None,
                        'error': 'Container has no runtime imageID; configured reference only'}
                    image.update(consumer=f"{namespace}/{meta['name']}/{c['name']}",
                                 pod_uid=meta['uid'], node=spec.get('nodeName'),
                                 runtime_image_id=live.get('imageID'), init=field == 'initContainers')
                    report['images'].append(image)
                    if role(c['image']) != 'nico-pxe' or field != 'containers':
                        continue
                    source = (namespace, meta['name'], c['name'])
                    file_sources.add(source)
    if not found:
        report['errors'].append('所选namespace/name-pattern没有活动Pod；未采集任何环境镜像。')
    if not file_sources:
        report['errors'].append('未找到活动nico-pxe容器，未采集发布文件。')
    for namespace, pod, container in sorted(file_sources):
        base = kube + ['-n', namespace, 'exec', pod, '-c', container, '--']
        root = args.boot_root or ROOT
        print(f'计算发布文件SHA256 {namespace}/{pod}:{root}', file=sys.stderr)
        command = f'find "$1" -type f \\( {FILE_TEST} \\) -exec sha256sum {{}} +'
        try:
            output = run(base + ['sh', '-c', command, 'audit', root])
            if not output.strip():
                raise ValueError('No supported published files found')
            for line in output.splitlines():
                match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
                if not match or not match[2].startswith(root.rstrip('/') + '/'):
                    raise ValueError('Unexpected sha256sum output')
                name = match[2][len(root.rstrip('/')) + 1:]
                report['files'].append({'path': name, 'sha256': match[1],
                                        'consumer': f'{namespace}/{pod}/{container}',
                                        'published_path': match[2]})
                if Path(name).name == 'BUILD-INFO.json':
                    try:
                        # Metadata is evidence only; equality still uses actual file hashes.
                        raw = run(base + ['head', '-c', '1048576', match[2]])
                        report['files'][-1]['declared_revision'] = build_revision(raw)
                    except (ValueError, OSError):
                        report['files'][-1]['provenance_note'] = 'Build metadata unreadable; file SHA verified'
        except (ValueError, OSError) as error:
            report['errors'].append(f'{namespace}/{pod}文件采集失败: {error}')
    report['notes'].append('文件只读核对PXE发布目录中的EFI/squashfs/ISO/BFB/deb/kernel/initrd及构建元数据；不读取凭据或user-data。')
    return report


def compare(args):
    expected, actual = (json.loads(p.read_text()) for p in (args.package, args.runtime))
    if (expected.get('kind'), actual.get('kind')) != ('package', 'runtime') or any(
            x.get('schema_version') != 1 for x in (expected, actual)):
        raise ValueError('Use schema-1 package/runtime snapshots')
    result = snapshot('comparison')
    result.update(package_revision=expected.get('source_revision'), context=actual.get('context'))
    result['rows'] = []
    for section, key, value in [('images', 'role', 'digest'), ('files', 'path', 'sha256')]:
        left, right = defaultdict(list), defaultdict(list)
        for row in expected[section]: left[row[key]].append(row)
        for row in actual[section]: right[row[key]].append(row)
        for name in sorted(left.keys() | right.keys()):
            a, b = left[name], right[name]
            av, bv = sorted({r[value] for r in a if r.get(value)}), sorted({r[value] for r in b if r.get(value)})
            if not a: status = '仅环境'
            elif not b: status = '仅打包'
            elif len(av) > 1 or len(bv) > 1: status = '不一致'
            elif any(not r.get(value) for r in a + b): status = '无法确认'
            else: status = '一致' if av == bv else '不一致'
            result['rows'].append({'type': section, 'name': name, 'status': status,
                                   'package': a, 'runtime': b})
    result['errors'] = ['打包清单: ' + e for e in expected['errors']] + ['环境清单: ' + e for e in actual['errors']]
    result['notes'] = expected['notes'] + actual['notes']
    if not expected['images'] or not actual['images']:
        result['errors'].append('镜像清单为空，不能判定环境与打包版本一致。')
    print(f"打包基准 {expected.get('source_revision', '')[:12]}  |  环境 {actual.get('context')}")
    for section, label in [('images', '镜像'), ('files', '文件')]:
        rows = [r for r in result['rows'] if r['type'] == section]
        print(f'\n{label}（{len(rows)}项）')
        displayed = defaultdict(int)
        for row in rows:
            displayed[row['status']] += 1
            if section == 'files' and displayed[row['status']] > 12:
                continue
            def describe(items):
                return ', '.join(sorted({(r.get('reference', '') + ' ' + (r.get('digest') or r.get('sha256') or '?')[:19]).strip() for r in items})) or '—'
            print(f"  {row['status']:4}  {row['name']}  | 包: {describe(row['package'])} | 环境: {describe(row['runtime'])}")
        counts = {s: sum(r['status'] == s for r in rows) for s in ('一致', '不一致', '仅打包', '仅环境', '无法确认')}
        print('  ' + ' · '.join(f'{k} {v}' for k, v in counts.items()))
        if section == 'files' and any(v > 12 for v in counts.values()):
            print('  每种结果最多展示12个文件；其余逐项结果见JSON。')
    for error in result['errors']: print('  无法确认: ' + error)
    print('\n完整逐项结果（包括一致和仅环境文件）: ' + str(args.output))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples (run on a Linux build/control host):
  python3 audit.py package --repo /path/to/PXEye --registry 127.0.0.1:1027 --registry-http --output package.json
  python3 audit.py runtime --context kubernetes-admin@kubernetes --output runtime.json
  python3 audit.py compare --package package.json --runtime runtime.json --output comparison.json

Exit: 0 complete/matching; 2 differences or incomplete verification; 1 command failure.
No images are built/pulled, no workloads/configuration are changed. package may download pinned Helm sources.
''')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('package', 'runtime', 'compare'):
        p = sub.add_parser(name, help={'package': 'Export committed packaging inputs', 'runtime': 'Export active Pods and published files', 'compare': 'Compare two exported snapshots'}[name])
        p.add_argument('--output', type=Path, required=True)
        if name == 'compare':
            p.add_argument('--package', type=Path, required=True)
            p.add_argument('--runtime', type=Path, required=True)
            continue
        p.add_argument('--architecture', choices=('amd64', 'arm64'), default='amd64', help='Container platform; independent of the installed host architecture')
        p.add_argument('--ctr', default='ctr')
        p.add_argument('--containerd-namespace', default='k8s.io')
        p.add_argument('--content-dir', default='/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256')
        p.add_argument('--registry', default='', help='Cache hostname:port, same remapping as make bundles')
        p.add_argument('--registry-http', action='store_true', help='Use HTTP for Registry metadata; default verifies HTTPS')
        if name == 'package':
            p.add_argument('--repo', default=str(Path(__file__).resolve().parents[2]))
            p.add_argument('--revision', default='HEAD', help='Committed packaging revision (default HEAD); ignores dirty files')
            p.add_argument('--helm', default='helm')
            p.add_argument('--chart-cache', help='Directory containing checksum-named Chart .tar.gz files; verified before reuse')
            p.add_argument('--include-arm64', action='store_true', help='Match make bundles INCLUDE_ARM64_MATERIALS=1')
        else:
            p.add_argument('--context', required=True)
            p.add_argument('--namespace', action='append', help='Repeatable; default nico-system and mmzhou')
            p.add_argument('--name-pattern', default='nico|pxeye|os-install-console|cert-manager', help='Pod name regex scope')
            p.add_argument('--kubectl', default='kubectl')
            p.add_argument('--boot-root', help='PXE container published-file root')
    args = parser.parse_args()
    try:
        if args.command == 'compare':
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = compare(args)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.with_suffix('.txt').write_text(output.getvalue())
            print(output.getvalue(), end='')
        else:
            result = globals()[args.command](args)
        save(args.output, result)
        if args.command == 'compare':
            return 2 if result['errors'] or any(r['status'] != '一致' for r in result['rows']) else 0
        print(f"已导出 {len(result['images'])} 条镜像引用 / {len(result['files'])} 条文件记录 → {args.output}")
        for note in result['notes']: print('说明: ' + note)
        incomplete = (result['errors'] or any(not r.get('digest') for r in result['images'])
                      or any(not r.get('sha256') for r in result['files']))
        for error in result['errors']: print('无法确认: ' + error)
        return 2 if incomplete else 0
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        print('失败: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
