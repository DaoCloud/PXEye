#!/usr/bin/env python3
"""Export listed local containerd images into a fixed work-directory structure."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
HOME = Path(__file__).resolve().parent
REPO = HOME.parents[1]
sys.path.insert(0, str(HOME))
import prepared as contract
import sources
sys.path.insert(0, str(HOME.parent / 'helm-bundle'))
h = b = None


def load_legacy_tools():
    global h, b
    if h is None:
        spec = importlib.util.spec_from_file_location('helm_packager', HOME.parent / 'helm-bundle/build.py')
        h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(h)
        b = h.b


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_config(path):
    load_legacy_tools()
    c = json.loads(path.read_text())
    version = c.get('schema_version')
    keys = {'schema_version', 'recipe', 'input_root', 'output_root', 'cache_directory', 'package_output_root', 'include', 'tools'}
    b.require(version in (1, 2) and set(c) == keys | ({'archives'} if version == 1 else {'sources'}), 'Use materials configuration schema 2 (source generation) or legacy schema 1 (existing archives)')
    c['recipe'] = (path.parent / c['recipe']).resolve() if not Path(c['recipe']).is_absolute() else Path(c['recipe'])
    if not c['recipe'].exists() and c['recipe'].name == 'recipe-e703.json': c['recipe'] = HOME / 'recipe-e703.json'
    recipe = json.loads(c['recipe'].read_text())
    b.require(recipe.get('schema_version') == 1 and recipe.get('platform') == 'linux/amd64', 'Unsupported material recipe')
    b.require(set(c['include']) == {'aarch64', 'apt', 'bfb'} and all(type(v) is bool for v in c['include'].values()), 'Invalid material switches')
    b.require(set(c['tools']) == {'docker', 'helm', 'relok8s'}, 'Invalid tools')
    for key in ('input_root', 'output_root', 'cache_directory', 'package_output_root'):
        value = Path(c[key]); b.require(value.is_absolute() and not any(x in str(value) for x in ',\n\r'), 'Use absolute paths without commas or newlines: ' + key)
        c[key] = value.resolve()
    b.require(version == 2 or c['input_root'].is_dir(), 'Missing input_root')
    b.require(not c['input_root'].is_relative_to(REPO), 'Keep generated inputs outside source')
    for key in ('output_root', 'cache_directory', 'package_output_root'):
        b.require(not c[key].is_relative_to(REPO) and not c[key].is_relative_to(c['input_root']) and not c['input_root'].is_relative_to(c[key]), 'Keep outputs/cache outside source and input: ' + key)
    b.require(not c['output_root'].is_relative_to(c['cache_directory']) and not c['cache_directory'].is_relative_to(c['output_root']), 'Separate prepared and cache directories')
    b.require(len({r['id'] for r in recipe['images']}) == len(recipe['images']), 'Duplicate image IDs')
    for row in recipe['images']:
        b.require(re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}', row['id']), 'Invalid image ID')
        b.require(row['method'] in ('archive', 'registry'), 'This profile supports archive or digest-pinned registry image sources; material images are built by this script')
        b.require(b.DIGEST.fullmatch(row['digest']), 'Every input image requires an immutable amd64 manifest digest')
        b.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./:_-]*:[A-Za-z0-9][A-Za-z0-9._-]*', row['reference']), 'Image reference must include an explicit tag')
    b.require({r['kind'] for r in recipe['images']} >= {'core', 'ui', 'bootstrap'}, 'Recipe requires Core, UI and bootstrap images')
    return c, recipe


def input_path(c, value):
    p = Path(value)
    p = p if p.is_absolute() else contract.relative(c['input_root'], value)
    b.require(p.is_file() and not p.is_symlink(), 'Missing regular input file: ' + str(p))
    return p


def preflight(c, recipe, full=True):
    print('PREPARE_PLAN', json.dumps({'profile': recipe['profile'], 'images': [{'id': r['id'], 'method': r['method'], 'purpose': r['purpose'], 'reference': r['reference'], 'digest': r['digest']} for r in recipe['images']], 'build_material_images': [k for k, v in c['include'].items() if v], 'scope': recipe['scope']}, ensure_ascii=False), flush=True)
    paths = []
    used = {r['archive'] for r in recipe['images'] if r['method'] == 'archive'}
    for key in sorted(used):
        row = recipe['archives'][key];paths.append((input_path(c, c['archives'][key]), row))
    selected = [r for r in recipe['materials'] if c['include'][r['group']]]
    for key, enabled in c['include'].items(): b.require(not enabled or any(r['group'] == key for r in selected), 'Selected material group is empty: ' + key)
    for row in selected: paths.append((input_path(c, row['path']), row))
    for name, digest in recipe['raw_charts'].items(): paths.append((input_path(c, 'charts/' + name), {'sha256': digest}))
    # Detect every missing file before reading any large archive or starting Docker.
    for path, row in paths:
        b.require('bytes' not in row or path.stat().st_size == row['bytes'], 'Input size differs: ' + str(path))
    if full:
        for path, row in paths:
            print('VERIFY_INPUT', path, flush=True)
            b.require(b.sha(path) == row['sha256'], 'Input checksum differs: ' + str(path))
    for tool in ('docker', 'helm'): b.require(shutil.which(c['tools'][tool]), 'Missing tool: ' + tool)
    return selected, sum(p.stat().st_size for p, _ in paths)


def select_image(layout, row):
    index = json.loads((layout / 'index.json').read_text())
    def flatten(desc):
        data = json.loads((layout / 'blobs/sha256' / desc['digest'][7:]).read_text())
        if 'manifests' in data:
            options = [r for r in data['manifests'] if r.get('platform', {}).get('architecture') == 'amd64' and r.get('platform', {}).get('os') == 'linux']
            b.require(len(options) == 1, 'Ambiguous amd64 image index')
            return flatten(options[0])
        return desc
    named = [d for d in index['manifests'] if d.get('annotations', {}).get('org.opencontainers.image.ref.name') == row['reference']]
    options = [flatten(d) for d in (named or index['manifests'])]
    options = [d for d in options if d['digest'] == row['digest']]
    b.require(len(options) == 1, 'Locked image not found uniquely in archive: ' + row['reference'])
    desc = copy.deepcopy(options[0]);desc['annotations'] = {'org.opencontainers.image.ref.name': row['reference']}
    return desc


def add_image(layout, destination, desc):
    (destination / 'blobs/sha256').mkdir(parents=True, exist_ok=True)
    manifest = json.loads((layout / 'blobs/sha256' / desc['digest'][7:]).read_text())
    for record in [desc, manifest['config']] + manifest['layers']:
        name = record['digest'][7:]; target = destination / 'blobs/sha256' / name
        if not target.exists(): shutil.copyfile(layout / 'blobs/sha256' / name, target)
    p = destination / 'index.json'
    index = json.loads(p.read_text()) if p.exists() else {'schemaVersion': 2, 'manifests': []}
    index['manifests'].append(desc); b.dump(p, index); b.dump(destination / 'oci-layout', {'imageLayoutVersion': '1.0.0'})


def verify_payload(layout, reference, manifest):
    _, record = contract.image(layout, reference)
    expected = {'payload/' + r['path']: r for r in manifest['files']}
    expected['payload/manifest.json'] = {'sha256': hashlib.sha256((json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode()).hexdigest()}
    found = {}
    for layer in record['layers']:
        path = layout / 'blobs/sha256' / layer['digest'][7:]
        with tarfile.open(path, 'r:*') as archive:
            for member in archive:
                name = member.name.removeprefix('./')
                b.require(not name.startswith('payload/.wh.'), 'Payload whiteout is not allowed')
                if name in expected:
                    b.require(member.isfile(), 'Payload entry is not a regular file: ' + name)
                    digest = hashlib.sha256()
                    with archive.extractfile(member) as stream:
                        for block in iter(lambda: stream.read(8 * 1024**2), b''): digest.update(block)
                    found[name] = digest.hexdigest()
    b.require(all(found.get(k) == v['sha256'] for k, v in expected.items()), 'Material image payload differs: ' + manifest['id'])


def build(c, recipe, plan=False):
    run_started = time.monotonic()
    run_started_at = datetime.now(timezone.utc).isoformat()
    tracked = ['offline-build/material-prepare', 'offline-build/helm-bundle', 'offline-build/build.py', 'offline-build/onsite', 'deploy/offline-core', 'deploy/nico-platform', 'deploy/bootstrap-kubernetes.yaml', 'deploy/nico-cluster-permissions.yaml']
    if not plan:
        b.require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'amd64'), 'Run preparation on Linux x86_64')
        b.require(not h.command(['git', '-C', REPO, 'status', '--porcelain', '--untracked-files=all', '--'] + tracked).stdout, 'Commit build sources before preparation')
    if c['schema_version'] == 2:
        c, recipe = sources.generate(c, recipe, plan=plan)
        if plan:
            print('SOURCE_PLAN_OK; no files exported, copied or built', flush=True)
            return
    print('STAGE 3/5 Verify raw inputs and prepare locked images', flush=True)
    selected, size = preflight(c, recipe, full=not plan)
    verification_seconds = time.monotonic() - run_started
    if plan: return
    b.require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'amd64'), 'Run preparation on Linux x86_64')
    docker = c['tools']['docker']
    h.command([docker, 'version', '--format', '{{.Server.Version}}'], timeout=30)
    context = json.loads(h.command([docker, 'context', 'inspect']).stdout)[0]
    endpoint = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    b.require((endpoint or context['Endpoints']['docker']['Host']).startswith('unix://'), 'Use a local Docker Unix socket')
    helm_version = h.command([c['tools']['helm'], 'version', '--short']).stdout.strip()
    b.require(helm_version.startswith('v3.'), 'Helm 3 is required')
    revision = h.command(['git', '-C', REPO, 'rev-parse', 'HEAD']).stdout.strip()
    source_hashes = {str(p.relative_to(REPO)): b.sha(p) for name in tracked for p in ([REPO / name] if (REPO / name).is_file() else sorted((REPO / name).rglob('*'))) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    helm_path = Path(shutil.which(c['tools']['helm']))
    fingerprint = identity({'recipe': recipe, 'include': c['include'], 'implementation': source_hashes, 'helm_sha256': b.sha(helm_path)})
    c['output_root'].mkdir(parents=True, exist_ok=True);c['cache_directory'].mkdir(parents=True, exist_ok=True)
    output = c['output_root'] / fingerprint[:24]
    with (c['output_root'] / '.prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists():
            contract.verify(output);write_result(c, output, fingerprint, 'REUSE');return
        b.require(shutil.disk_usage(output.parent).free > size * 3 + 2 * 1024**3, 'Need three times selected input size plus 2 GiB free')
        stage = Path(tempfile.mkdtemp(prefix='.' + fingerprint[:16] + '.building-', dir=output.parent))
        started = run_started;timings = [{'id': 'verify-inputs', 'action': 'VERIFY', 'seconds': round(verification_seconds, 3)}]
        try:
            layout = stage / 'images/layout';records = [];layouts = {};checked = set()
            for row in recipe['images']:
                if row['method'] != 'archive': continue
                key = row['archive']
                if key not in layouts: layouts[key] = h.unpack_oci(input_path(c, c['archives'][key]), stage / ('.input-' + key))
                before = time.monotonic();desc = select_image(layouts[key], row)
                add_image(layouts[key], layout, desc);contract.image(layout, row['reference'], row['digest'], checked)
                records.append({'image': row['reference'], 'digest': row['digest'], 'kind': row['kind'], 'purpose': row['purpose'], 'method': 'archive', 'archive_sha256': recipe['archives'][key]['sha256']})
                timings.append({'id': row['id'], 'action': 'IMPORT', 'seconds': round(time.monotonic() - before, 3)})
                print('IMPORT', row['id'], row['digest'], flush=True)
            bootstrap = next(r for r in records if r['kind'] == 'bootstrap')
            # Bootstrap is explicitly archive-sourced so registry credentials/tools
            # never need to be acquired from the live cluster.
            b.require(next(r for r in recipe['images'] if r['kind'] == 'bootstrap')['method'] == 'archive', 'Bootstrap tools must be archive-sourced')
            materials = []
            with h.BuildRegistry(docker, stage / '.work', uuid.uuid4().hex[:12]) as registry:
                archive = registry.work / 'tools.tar'
                loaded = registry.work / 'docker-tools.tar'
                h.archive_image(layout, bootstrap['image'], archive)
                h.docker_archive(archive, bootstrap['image'], loaded, registry.tool_image)
                h.command([docker, 'load', '--input', loaded], registry.work / 'tools-load.log')
                registry.owned_tags.append(registry.tool_image);archive.unlink();loaded.unlink()
                def skopeo(args, dest, log):
                    dest.mkdir(parents=True, exist_ok=True)
                    return h.command([docker, 'run', '--rm', '--network', 'host', '--user', '0:0', '--entrypoint', 'skopeo', '--mount', f'type=bind,src={dest},dst=/output', registry.tool_image] + args, registry.work / log)
                for row in recipe['images']:
                    if row['method'] != 'registry':continue
                    b.require(row['kind'] != 'bootstrap', 'Bootstrap must use archive')
                    source = row.get('registry_reference', row['reference'].rsplit(':', 1)[0])
                    b.require('@' not in source, 'registry_reference must be a repository; digest is a separate lock field')
                    temp = registry.work / ('fetch-' + row['id']);before = time.monotonic()
                    skopeo(['copy', '--retry-times', '3', '--preserve-digests', 'docker://' + source + '@' + row['digest'], 'oci:/output:image'], temp, row['id'] + '-fetch.log')
                    desc = json.loads((temp / 'index.json').read_text())['manifests'][0];desc['annotations'] = {'org.opencontainers.image.ref.name': row['reference']}
                    add_image(temp, layout, desc);contract.image(layout, row['reference'], row['digest'])
                    records.append({'image': row['reference'], 'digest': row['digest'], 'kind': row['kind'], 'purpose': row['purpose'], 'method': 'registry'})
                    timings.append({'id': row['id'], 'action': 'FETCH', 'seconds': round(time.monotonic() - before, 3)})
                print('STAGE 4/5 Build or reuse material images', flush=True)
                for name, enabled in c['include'].items():
                    if not enabled:continue
                    group = [r for r in selected if r['group'] == name]
                    key = identity({'files': group, 'publisher': b.sha(HOME.parent / 'helm-bundle/material-publish.py'), 'base': bootstrap['digest'], 'platform': 'linux/amd64', 'recipe': 'COPY payload /payload; COPY publish.py /publish.py; ENTRYPOINT python3 /publish.py'})
                    cached = c['cache_directory'] / 'materials' / key
                    ref = 'prepared.local/nico-material-' + name + ':' + key[:24]
                    expected_files = [{'path': r['target'], 'bytes': r['bytes'], 'sha256': r['sha256']} for r in group]
                    before = time.monotonic();action = 'REUSE'
                    if not cached.exists():
                        print('BUILD_MATERIAL', name, ref, flush=True);action = 'BUILD'
                        context = registry.work / ('material-' + name);payload = context / 'payload';payload.mkdir(parents=True)
                        files = []
                        for row in group:
                            target = contract.relative(payload, row['target']);target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(input_path(c, row['path']), target);target.chmod(0o644)
                            files.append({'path': row['target'], 'bytes': row['bytes'], 'sha256': row['sha256']})
                        manifest = {'id': name, 'version': key[:24], 'container_platform': 'linux/amd64', 'target_architecture': 'aarch64' if name == 'aarch64' else 'mixed', 'image_payload': '/payload', 'published_path': '/materials/' + name + '/' + key[:24], 'files': files}
                        b.dump(payload / 'manifest.json', manifest)
                        shutil.copyfile(HOME.parent / 'helm-bundle/material-publish.py', context / 'publish.py')
                        for folder in [payload] + [p for p in payload.rglob('*') if p.is_dir()]:folder.chmod(0o755)
                        b.write(context / 'Dockerfile', 'FROM ' + registry.tool_image + '\nCOPY payload /payload\nCOPY publish.py /publish.py\nENTRYPOINT ["python3", "/publish.py"]\n')
                        build_ref = registry.address + '/build/nico-material-' + name + ':' + key[:24]
                        h.command([docker, 'build', '--pull=false', '--network=none', '--platform=linux/amd64', '--tag', build_ref, context], registry.work / (name + '-build.log'))
                        registry.owned_tags.append(build_ref)
                        h.command([docker, 'push', build_ref], registry.work / (name + '-push.log'))
                        temp = registry.work / ('export-' + name)
                        skopeo(['copy', '--preserve-digests', '--src-tls-verify=false', 'docker://' + build_ref, 'oci:/output:image'], temp, name + '-export.log')
                        desc = json.loads((temp / 'index.json').read_text())['manifests'][0];desc['annotations'] = {'org.opencontainers.image.ref.name': ref};b.dump(temp / 'index.json', {'schemaVersion': 2, 'manifests': [desc]})
                        verify_payload(temp, ref, manifest)
                        b.dump(temp / 'material.json', manifest)
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        with (cached.parent / '.cache.lock').open('a') as cache_lock:
                            fcntl.flock(cache_lock, fcntl.LOCK_EX)
                            if not cached.exists():
                                cache_stage = Path(tempfile.mkdtemp(prefix='.' + key[:16] + '.building-', dir=cached.parent))
                                shutil.copytree(temp, cache_stage, dirs_exist_ok=True)
                                cache_stage.rename(cached)
                    manifest = json.loads((cached / 'material.json').read_text());desc = json.loads((cached / 'index.json').read_text())['manifests'][0]
                    b.require(manifest['id'] == name and manifest['version'] == key[:24] and manifest['files'] == expected_files and manifest['image_payload'] == '/payload' and manifest['published_path'] == '/materials/' + name + '/' + key[:24], 'Cached material identity differs: ' + name)
                    contract.image(cached, ref, desc['digest']);verify_payload(cached, ref, manifest)
                    add_image(cached, layout, desc)
                    materials.append(manifest | {'image': ref, 'image_digest': desc['digest'], 'input_fingerprint': key})
                    records.append({'image': ref, 'digest': desc['digest'], 'kind': 'material', 'purpose': name, 'method': 'build', 'input_fingerprint': key})
                    timings.append({'id': name, 'action': action, 'seconds': round(time.monotonic() - before, 3)})
                    print(action + '_MATERIAL_READY', name, desc['digest'], flush=True)
            print('STAGE 5/5 Prepare Charts, verify and publish prepared output', flush=True)
            # Create compatible Charts directly from pinned raw inputs and repository patches.
            charts = stage / 'deployment';(charts / 'charts').mkdir(parents=True);(charts / 'patches').mkdir()
            scratch = stage / '.patch';scratch.mkdir()
            b.patch_core(c['input_root'], charts, scratch)
            (stage / 'tools').mkdir();shutil.copyfile(shutil.which(c['tools']['helm']), stage / 'tools/helm');(stage / 'tools/helm').chmod(0o755)
            b.dump(stage / 'manifests/images-lock.json', records);b.dump(stage / 'manifests/materials.json', materials)
            b.dump(stage / 'reports/timings.json', timings)
            b.dump(stage / 'reports/sources.json', {'recipe': recipe, 'original_sources': c.get('sources'), 'raw_input_directory': str(c['input_root']), 'implementation_sha256': source_hashes, 'source_revision': revision, 'helm_version': helm_version, 'started_at': run_started_at, 'finished_at': datetime.now(timezone.utc).isoformat(), 'seconds': round(time.monotonic() - started, 3), 'material_payloads_verified': True})
            b.dump(stage / 'prepared.json', {'schema_version': 1, 'kind': 'nico-prepared', 'complete': True, 'profile': recipe['profile'], 'architecture': 'linux/amd64', 'fingerprint': fingerprint, 'source_revision': revision, 'include': c['include'], 'scope': recipe['scope']})
            # Staging only: no old outputs, caches or global Docker resources are removed.
            logs = stage / 'logs';logs.mkdir()
            for p in (stage / '.work').glob('*.log'): shutil.copyfile(p, logs / p.name)
            for name in list(layouts):shutil.rmtree(stage / ('.input-' + name))
            shutil.rmtree(stage / '.work');shutil.rmtree(scratch)
            contract.inventory(stage);contract.verify(stage)
            stage.rename(output);write_result(c, output, fingerprint, 'BUILD')
        except BaseException:
            print('MATERIAL_PREPARE_FAILED; staging retained at', stage, flush=True)
            raise


def write_result(c, output, fingerprint, action):
    config = {'schema_version': 1, 'materials_bundle': str(output), 'output_root': str(c['package_output_root']), 'bundle_id': 'pxeye-nico-offline', 'include': c['include'], 'tools': c['tools']}
    # Per-prepared input configuration; never a single mutable global pointer.
    path = output.parent / (output.name + '.helm-build.json')
    if path.exists():b.require(json.loads(path.read_text()) == config, 'Generated packaging config differs: ' + str(path))
    else:b.dump(path, config)
    b.dump(output.parent / (output.name + '.result.json'), {'prepared': str(output), 'fingerprint': fingerprint, 'action': action, 'helm_config': str(path)})
    print('MATERIAL_PREPARE_COMPLETE', output, flush=True)
    print('HELM_BUILD_CONFIG', path, flush=True)
    print('NEXT_COMMAND', shlex.join(['python3', str(HOME.parent / 'helm-bundle/build.py'), '--config', str(path)]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--plan', action='store_true', help='Check image references, metadata and content presence without exporting or building')
    args = parser.parse_args()
    path = args.config.expanduser().resolve()
    raw = json.loads(path.read_text())
    if 'work_directory' in raw:
        import containerd_export
        containerd_export.run(path, plan=args.plan)
    else:
        c, recipe = read_config(path)
        build(c, recipe, args.plan)


if __name__ == '__main__':
    try:main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:raise SystemExit(str(error)) from None
