"""Read-only export of an explicit local containerd image list."""
import fcntl
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import prepared as contract
import sources

HOME = Path(__file__).resolve().parent
REPO = HOME.parents[1]
sys.path.insert(0, str(HOME.parent))
import build_config
sys.path.insert(0, str(HOME.parent / 'onsite'))
from progress import Progress, transcript, install_signal_handlers

DEFAULTS = {
    'containerd_content': '/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256',
    'containerd_address': '/run/containerd/containerd.sock',
    'containerd_namespace': 'k8s.io',
    'ctr': 'ctr',
}


def configuration(path, image_list=None):
    raw = build_config.read(path)
    contract.require('work_directory' in raw, 'Missing work_directory in build-config.json')
    overrides = raw.get('image_export', raw.get('sources', {}))
    contract.require(isinstance(overrides, dict) and set(overrides) <= set(DEFAULTS) | {'image_list'}, 'Unknown source settings')
    options = DEFAULTS | overrides
    contract.require(all(isinstance(v, str) and v and not any(c in v for c in '\n\r\0') for v in options.values()),
                     'Source settings must be nonempty strings')
    contract.require(isinstance(raw['work_directory'], str), 'work_directory must be a path')
    work = Path(raw['work_directory']).expanduser()
    contract.require(work.is_absolute(), 'work_directory must be absolute or start with ~/')
    work = work.resolve()
    contract.require(not work.is_relative_to(REPO) or work.is_relative_to(REPO / 'outputs_'),
                     'Use the repository outputs_ directory or a location outside the Git checkout')
    selected_list = image_list or options.get('image_list')
    contract.require(selected_list, 'No image list supplied; use the unified delivery entry or provide image_export.image_list for the legacy exporter')
    for key in ('containerd_content', 'containerd_address'):
        value = Path(options[key]).expanduser()
        if not value.is_absolute():
            value = path.parent / value
        options[key] = str(value.resolve())
    image_list = Path(selected_list).expanduser()
    if not image_list.is_absolute(): image_list = path.parent / image_list
    image_list = image_list.resolve()
    options['image_list'] = str(image_list)
    content = Path(options['containerd_content'])
    # Export staging and logs are fixed children of work; original sources stay separate.
    for target in (work / 'offline-images', work / '.offline-images.building', work / 'logs'):
        contract.require(not target.is_symlink() and not image_list.is_relative_to(target) and
                         not content.is_relative_to(target) and not target.is_relative_to(content),
                         'Source and generated directories overlap')
    refs = []
    for line in image_list.read_text().splitlines():
        ref = line.partition('#')[0].strip()
        if not ref:
            continue
        contract.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_:@-]*', ref) and
                         (':' in ref.rsplit('/', 1)[-1] or '@sha256:' in ref),
                         'Use one explicitly tagged or digest-pinned image per line: ' + ref)
        contract.require(ref not in refs, 'Duplicate listed image: ' + ref)
        refs.append(ref)
    contract.require(refs, 'The image list is empty')
    return work, options, refs


def image_roles(rows, options):
    """Record explicit list annotations, or the unique PXEye product identity."""
    refs = {row['image'] for row in rows}
    roles = {}
    for line in Path(options['image_list']).read_text().splitlines():
        reference, _, comment = line.partition('#')
        if comment.strip().startswith('roles='):
            for role in comment.strip()[6:].split(','):
                role = role.strip()
                contract.require(role in ('ui', 'bootstrap') and role not in roles and reference.strip() in refs,
                                 'Invalid or duplicate image role annotation: ' + line)
                roles[role] = reference.strip()
    candidates = []
    for row in rows:
        config = metadata(Path(options['containerd_content']), row['config'])
        labels = (config.get('config') or {}).get('Labels') or {}
        if labels.get('org.opencontainers.image.title') == 'PXEye':
            candidates.append(row['image'])
    if 'ui' not in roles and len(candidates) == 1:
        roles['ui'] = candidates[0]
    if 'ui' in roles:
        roles.setdefault('bootstrap', roles['ui'])
    return roles


def metadata(root, digest):
    path = sources.blob_path(root, {'digest': digest})
    contract.require(contract.sha(path) == digest[7:], 'Source metadata checksum differs: ' + digest)
    return json.loads(path.read_text())


def resolve_images(options, refs):
    argv = [options['ctr'], '--address', options['containerd_address'],
            '--namespace', options['containerd_namespace'], 'images', 'list']
    print('READ', shlex.join(argv), flush=True)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    contract.require(result.returncode == 0, 'Cannot read local containerd image list: ' + result.stderr[-2000:])
    targets = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and re.fullmatch(r'sha256:[0-9a-f]{64}', fields[2]):
            targets[fields[0]] = fields[2]
    root = Path(options['containerd_content'])
    rows, failures = [], []
    for ref in refs:
        try:
            original = targets.get(ref)
            if original is None and '@sha256:' in ref:
                original = 'sha256:' + ref.rsplit('@sha256:', 1)[1]
            contract.require(original, 'Image reference absent from selected containerd namespace')
            digest = original
            visited = set()
            while True:
                contract.require(digest not in visited and len(visited) < 8, 'Invalid nested image index')
                visited.add(digest)
                data = metadata(root, digest)
                if 'manifests' not in data:
                    break
                matches = [r for r in data['manifests'] if r.get('platform', {}).get('os') == 'linux'
                           and r.get('platform', {}).get('architecture') == 'amd64']
                contract.require(len(matches) == 1, 'Expected exactly one linux/amd64 image')
                digest = matches[0]['digest']
            row = {'id': ref, 'image': ref, 'reference': ref, 'digest': digest,
                   'source_descriptor': original, 'amd64_manifest': digest,
                   'config': data['config']['digest'], 'layers': len(data['layers'])}
            _, graph = sources.graph(root, row)
            metadata(root, graph[1]['digest'])
            rows.append(row)
            print('SELECT', ref, digest, flush=True)
        except (ValueError, KeyError, OSError) as error:
            failures.append(ref + ': ' + str(error))
    contract.require(not failures, 'Local image export prerequisites failed:\n' + '\n'.join(failures))
    return rows


def verify_output(output, identity):
    descriptor = json.loads((output / 'export.json').read_text())
    contract.require(descriptor.get('kind') == 'containerd-image-export' and descriptor.get('complete') is True
                     and descriptor['identity'] == identity, 'Export belongs to different inputs; use another work_directory')
    files = descriptor['files']
    expected = {r['path'] for r in files} | {'export.json', 'SHA256SUMS'}
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    contract.require(actual == expected and not any(p.is_symlink() for p in output.rglob('*')), 'Export inventory differs')
    for row in files:
        path = contract.relative(output, row['path'])
        contract.require(path.is_file() and path.stat().st_size == row['bytes'] and
                         contract.sha(path) == row['sha256'], 'Export checksum differs: ' + row['path'])
    checksum_rows = files + [{'path': 'export.json', 'sha256': contract.sha(output / 'export.json')}]
    expected_sums = ''.join(r['sha256'] + '  ' + r['path'] + '\n' for r in checksum_rows)
    contract.require((output / 'SHA256SUMS').read_text() == expected_sums, 'Export checksum file differs')


def run(path, plan=False, image_list=None):
    work, options, refs = configuration(path, image_list=image_list)
    if plan:
        rows = resolve_images(options, refs)
        print('IMAGE_EXPORT_PLAN', json.dumps({'images': len(rows), 'image_roles': image_roles(rows, options), 'output': str(work / 'offline-images')}), flush=True)
        return
    contract.require(sys.platform == 'linux', 'Run image export on the local Linux containerd host')
    work.mkdir(parents=True, exist_ok=True)
    install_signal_handlers()
    with (work / '.image-export.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logs = work / 'logs/image-export'
        logs.mkdir(parents=True, exist_ok=True)
        implementation = {p.name: contract.sha(p) for p in [Path(__file__), HOME / 'sources.py', HOME / 'prepared.py', HOME / 'build.py']}
        implementation['build_config.py'] = contract.sha(HOME.parent / 'build_config.py')
        identity = sources.fingerprint({'sources': options, 'images': refs, 'image_list_sha256': contract.sha(options['image_list']), 'implementation': implementation})
        with transcript(logs):
            had_progress = (logs / 'progress.json').exists()
            progress = Progress(logs, identity)
            try:
                with progress.stage('resolve', 'Read listed containerd images and validate amd64 content'):
                    rows = resolve_images(options, refs)
                    roles = image_roles(rows, options)
                    previous = progress.state.get('images')
                    contract.require(previous is None or previous == rows,
                                     'Listed image tags changed; use another work_directory to export the new versions')
                    progress.state['images'] = rows; progress.save()
                output = work / 'offline-images'
                if output.exists():
                    with progress.stage('verify', 'Verify completed image export'):
                        verify_output(output, identity)
                    progress.complete()
                    print('IMAGE_EXPORT_REUSED', output, flush=True)
                    return
                stage = work / '.offline-images.building'
                contract.require(not stage.exists() or had_progress, 'Unowned export staging directory; inspect before retrying')
                stage.mkdir(exist_ok=True)
                allowed = {'images/nico-amd64.oci.tar', 'images/nico-amd64.oci.tar.part',
                           'manifests/images-lock.json', 'manifests/images.txt', 'export.json', 'SHA256SUMS'}
                contract.require(not any(p.is_symlink() or (p.is_file() and p.relative_to(stage).as_posix() not in allowed)
                                         for p in stage.rglob('*')), 'Unexpected file in export staging directory')
                archive = stage / 'images/nico-amd64.oci.tar'
                archive.parent.mkdir(parents=True, exist_ok=True)
                with progress.stage('export', 'Export image manifests, configurations and shared layers') as record:
                    if archive.exists():
                        contract.require(record.get('sha256') and contract.sha(archive) == record['sha256'],
                                         'Unrecorded or changed image archive; inspect before retrying')
                        print('REUSE_ARCHIVE', archive, flush=True)
                    else:
                        root = Path(options['containerd_content'])
                        graph = {}
                        for row in rows:
                            _, items = sources.graph(root, row)
                            graph.update({r['digest']: r['size'] for r in items})
                        contract.require(shutil.disk_usage(work).free > sum(graph.values()) + 1024**3,
                                         'Insufficient space for image export plus 1 GiB reserve')
                        temporary = archive.with_suffix('.tar.part')
                        sources.export_archive(root, rows, temporary)
                        record['sha256'] = contract.sha(temporary)
                        progress.save(); temporary.replace(archive)
                    record['bytes'] = archive.stat().st_size
                with progress.stage('publish', 'Write image inventory, provenance and checksums'):
                    # Preserve the historical exporter interface exactly; additional
                    # runtime/progress data belongs in sidecars, not this lock file.
                    legacy_rows = [{key: row[key] for key in ('image', 'source_descriptor', 'amd64_manifest',
                                                             'config', 'layers')} for row in rows]
                    contract.dump(stage / 'manifests/images-lock.json', legacy_rows)
                    (stage / 'manifests/images.txt').write_text(''.join(ref + '\n' for ref in refs))
                    files = [{'path': p.relative_to(stage).as_posix(), 'bytes': p.stat().st_size,
                              'sha256': contract.sha(p)} for p in sorted(stage.rglob('*'))
                             if p.is_file() and p.name not in ('export.json', 'SHA256SUMS')]
                    contract.dump(stage / 'export.json', {'kind': 'containerd-image-export', 'schema_version': 1,
                                  'complete': True, 'identity': identity, 'sources': options,
                                  'images': len(rows), 'image_roles': roles, 'files': files})
                    checksum_rows = files + [{'path': 'export.json', 'sha256': contract.sha(stage / 'export.json')}]
                    (stage / 'SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + r['path'] + '\n' for r in checksum_rows))
                    verify_output(stage, identity)
                    stage.rename(output)
                progress.complete()
                print('IMAGE_EXPORT_COMPLETE', output, flush=True)
            except BaseException as error:
                progress.fail(error)
                raise
