#!/usr/bin/env python3
"""Prepare pinned Charts and build a relok8s delivery from exported images or prepared materials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error
import uuid

import yaml

HOME = Path(__file__).resolve().parent
REPO = HOME.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HOME))
import charts
import chart_sources
sys.path.insert(0, str(HOME.parent / 'onsite'))
from relocation import prepare_intermediate
from progress import Progress, atomic_json, transcript, install_signal_handlers
from verify import verify
sys.path.insert(0, str(HOME.parent / 'material-prepare'))
import prepared

spec = importlib.util.spec_from_file_location('materials_builder', HOME.parent / 'build.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
LOCK = json.loads((HOME / 'toolchain-lock.json').read_text())


def command(argv, log=None, timeout=3600, check=True, **kwargs):
    # Commands contain only public image references and paths, never credentials.
    print('RUN', ' '.join(map(str, argv)), flush=True)
    result = subprocess.run(list(map(str, argv)), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, **kwargs)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as stream:
            stream.write('\nATTEMPT ' + datetime.now(timezone.utc).isoformat() + '\n' + result.stdout +
                         ('\nSTDERR:\n' + result.stderr if result.stderr else '') + '\nEXIT_CODE=' + str(result.returncode) + '\n')
    if check and result.returncode:
        raise ValueError(f'{argv[0]} exited {result.returncode}; ' + (f'log: {log}' if log else (result.stdout + result.stderr)[-2000:]))
    return result


def read_config(path):
    config = json.loads(path.read_text())
    required = {'schema_version', 'materials_bundle', 'output_root', 'bundle_id', 'include', 'tools'}
    b.require(required <= set(config) <= required | {'chart_sources'}
              and config['schema_version'] == 1, 'Use the supplied Helm build configuration schema 1')
    b.require(set(config['include']) == {'aarch64', 'bfb', 'apt'} and all(type(v) is bool for v in config['include'].values()), 'Invalid material switches')
    b.require(set(config['tools']) == {'docker', 'helm', 'relok8s'}, 'Invalid tool configuration')
    b.require(re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}', config['bundle_id']), 'Invalid bundle_id')
    for key in ('materials_bundle', 'output_root'):
        value = Path(config[key])
        b.require(value.is_absolute() and not any(c in str(value) for c in ',\n\r'), 'Use absolute paths without commas/newlines: ' + key)
        config[key] = value.resolve()
    source, output = config['materials_bundle'], config['output_root']
    b.require(source.is_dir() and not source.is_symlink(), 'materials_bundle must be an extracted materials or prepared directory')
    b.require(not output.is_relative_to(source) and not source.is_relative_to(output), 'Output must be outside input materials')
    b.require(not output.is_relative_to(REPO), 'Keep artifacts outside the Git checkout')
    if (source / 'prepared.json').is_file():
        descriptor = json.loads((source / 'prepared.json').read_text())
        b.require(descriptor.get('kind') in ('nico-prepared', 'nico-package-input') and descriptor.get('complete'), 'Incomplete prepared input')
        b.require(descriptor['include'] == config['include'], 'Material switches must match prepared input; run preparation with the intended switches')
        return config
    descriptor = json.loads((source / 'bundle.json').read_text())
    report = json.loads((source / 'manifests/build-report.json').read_text())
    b.require(descriptor.get('kind') == 'nico-materials' and report.get('profile') == 'e703126e4-core-single-node', 'Use the verified generic e703 materials bundle, not a site deployment or raw upstream bundle')
    return config


def input_plan(config):
    source = config['materials_bundle']
    if (source / 'prepared.json').is_file():
        rows = json.loads((source / 'manifests/files.json').read_text())['files']
        records = json.loads((source / 'manifests/images-lock.json').read_text())
        descriptor = json.loads((source / 'prepared.json').read_text())
        base = [r for r in records if r['kind'] == 'core']
        if descriptor.get('kind') == 'nico-package-input' and 'image_roles' in descriptor:
            by_reference = {r['image']: r for r in records}
            extra = [dict(by_reference[ref], source_image=ref, purpose=role)
                     for role, ref in descriptor['image_roles'].items()]
        else:
            extra = [dict(r, source_image=r['image'], purpose=r['kind']) for r in records if r['kind'] in ('ui', 'bootstrap')]
        b.require(len(extra) == 2, 'Expected one UI and one bootstrap image')
        prefixes = {'aarch64': 'boot/aarch64/', 'bfb': 'http/nico/dpu/', 'apt': 'boot/apt/'}
        groups = {name: [r for r in rows if r['path'].startswith(prefixes[name])]
                  for name in descriptor.get('raw_material_groups', [])}
        b.require(all(groups.values()), 'Package input lacks selected raw material files')
        print('BUILD_PLAN', json.dumps({'prepared_images': len(records), 'new_material_images': list(groups), 'package_builds_images': bool(groups), 'charts': ['pxeye', 'cert-manager', 'platform', 'core', 'materials']}), flush=True)
        return rows, base, extra, groups
    rows = json.loads((source / 'manifests/file-inventory.json').read_text())['files']
    paths = {r['path']: r for r in rows}
    base = json.loads((source / 'manifests/images-lock.json').read_text())
    extra = json.loads((source / 'manifests/deployment-images-lock.json').read_text())
    b.require(len(base) == 23 and len({r['image'] for r in base}) == 23, 'Expected 23 distinct locked Core images')
    b.require(len(extra) == 2 and {r['purpose'] for r in extra} == {'ui', 'bootstrap'}, 'Both PXEye images are required')
    groups = {}
    prefixes = {'aarch64': 'boot/aarch64/', 'bfb': 'http/nico/dpu/', 'apt': 'boot/apt/'}
    for name, prefix in prefixes.items():
        if config['include'][name]:
            groups[name] = [r for r in rows if r['path'].startswith(prefix)]
            b.require(groups[name], 'Missing selected material group: ' + name)
    required = {'images/nico-amd64.oci.tar', 'tools/helm'} | {r['archive'] for r in extra}
    required |= {'deployment/charts/' + name for name in ('nico-0.1.1.tgz', 'cert-manager-v1.17.1.tgz', 'pxeye-nico-platform-0.1.0.tgz')}
    required |= {r['path'] for group in groups.values() for r in group}
    for name in required:
        row = paths.get(name)
        path = source / b.safe_name(name)
        b.require(row and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source), 'Missing or unsafe input: ' + name)
        b.require(path.stat().st_size == row['bytes'], 'Input size differs: ' + name)
    print('BUILD_PLAN', json.dumps({'base_images': len(base), 'extra_images': len(extra),
          'new_material_images': list(groups), 'charts': ['pxeye', 'cert-manager', 'platform', 'core', 'materials'],
          'required_files': sorted(required)}, ensure_ascii=False), flush=True)
    return rows, base, extra, groups


def download(url, destination):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as incoming, destination.open('wb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024**2)
            return
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)


def hinted_images(root):
    values = yaml.safe_load((root / 'values.yaml').read_text())
    hints = yaml.safe_load((root / '.relok8s-images.yaml').read_text())
    def field(match):
        item = values
        for part in match[1].strip().lstrip('.').split('.'):
            item = item[part]
        return str(item)
    return {re.sub(r'{{\s*(.*?)\s*}}', field, hint) for hint in hints}


def relok_tool(config, cache):
    item = LOCK['relok8s']
    supplied = config['tools']['relok8s']
    if supplied:
        path = Path(supplied).resolve()
        b.require(path.is_file() and os.access(path, os.X_OK), 'Configured relok8s is not executable')
    else:
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / 'relok8s'
        marker = cache / 'relok8s.json'
        if path.exists():
            b.require(marker.is_file() and json.loads(marker.read_text())['sha256'] == b.sha(path), 'Cached relok8s differs; inspect it before removing this cache')
        else:
            with tempfile.TemporaryDirectory(dir=cache) as temporary:
                work = Path(temporary)
                archive = work / item['asset']
                print('PREPARE_TOOL relok8s', item['version'], flush=True)
                download(item['release_url'] + '/' + item['asset'], archive)
                b.require(b.sha(archive) == item['archive_sha256'], 'relok8s release archive checksum mismatch')
                with tarfile.open(archive, 'r:gz') as tar:
                    member = tar.getmember('relok8s')
                    b.require(member.isfile() and member.size < 256 * 1024**2, 'Invalid relok8s binary entry')
                    binary = work / 'relok8s'
                    with tar.extractfile(member) as incoming, binary.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                binary.chmod(0o755)
                binary.rename(path)
                b.dump(marker, {'version': item['version'], 'sha256': b.sha(path), 'release_archive_sha256': item['archive_sha256']})
    version = command([path, 'version']).stdout.strip()
    b.require(version == 'relok8s version: ' + item['version'], 'relok8s version must be ' + item['version'])
    return path


def docker_archive(source, reference, destination, tag):
    """Bridge one verified OCI image to Docker's standard load format."""
    with tarfile.open(source, 'r:') as src, tarfile.open(destination, 'w:') as dest:
        index = json.load(src.extractfile('index.json'))
        desc = next(d for d in index['manifests'] if d.get('annotations', {}).get('org.opencontainers.image.ref.name') == reference)
        manifest = json.load(src.extractfile('blobs/sha256/' + desc['digest'][7:]))
        config_bytes = src.extractfile('blobs/sha256/' + manifest['config']['digest'][7:]).read()
        config = json.loads(config_bytes)
        def add_bytes(name, data):
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            dest.addfile(info, io.BytesIO(data))
        config_name = manifest['config']['digest'][7:] + '.json'
        add_bytes(config_name, config_bytes)
        layers = []
        for i, layer in enumerate(manifest['layers']):
            name = config['rootfs']['diff_ids'][i][7:] + '/layer.tar'
            layers.append(name)
            with src.extractfile('blobs/sha256/' + layer['digest'][7:]) as raw:
                stream = gzip.GzipFile(fileobj=raw) if layer['mediaType'].endswith('+gzip') or layer['mediaType'].endswith('.gzip') else raw
                b.require('zstd' not in layer['mediaType'], 'zstd bootstrap layers need a supported Docker load input')
                with tempfile.TemporaryFile() as expanded:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(8 * 1024**2), b''):
                        expanded.write(block); digest.update(block)
                    b.require('sha256:' + digest.hexdigest() == config['rootfs']['diff_ids'][i], 'Invalid bootstrap diff_id')
                    size = expanded.tell(); expanded.seek(0)
                    info = tarfile.TarInfo(name); info.size = size; info.mode = 0o644
                    dest.addfile(info, expanded)
        add_bytes('manifest.json', json.dumps([{'Config': config_name, 'RepoTags': [tag], 'Layers': layers}]).encode())


def archive_image(layout, reference, destination):
    """Bridge only one prepared image into an OCI tar without duplicating all blobs."""
    index = json.loads((layout / 'index.json').read_text())
    desc = next(d for d in index['manifests'] if d.get('annotations', {}).get('org.opencontainers.image.ref.name') == reference)
    manifest_path = layout / 'blobs/sha256' / desc['digest'][7:]
    manifest = json.loads(manifest_path.read_text())
    with tarfile.open(destination, 'w:') as tar:
        data = json.dumps({'schemaVersion': 2, 'manifests': [desc]}).encode()
        entry = tarfile.TarInfo('index.json'); entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
        tar.add(layout / 'oci-layout', arcname='oci-layout')
        for blob in [desc, manifest['config']] + manifest['layers']:
            name = 'blobs/sha256/' + blob['digest'][7:]
            tar.add(layout / name, arcname=name)


def unpack_oci(source, target):
    """Extract a previously hash-verified layout once, without archive ownership."""
    target.mkdir(parents=True)
    with tarfile.open(source, 'r:') as archive:
        for member in archive:
            name = b.safe_name(member.name)
            b.require(member.isfile() or member.isdir(), 'OCI links/devices are not allowed')
            if member.isdir():
                continue
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as incoming, path.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 8 * 1024**2)
    return target


def image_view(layout, reference, target):
    """Same dir transport as the existing importer: OCI and Docker v2, no conversion."""
    index = json.loads((layout / 'index.json').read_text())
    desc = next(d for d in index['manifests'] if d.get('annotations', {}).get('org.opencontainers.image.ref.name') == reference)
    target.mkdir()
    raw = (layout / 'blobs/sha256' / desc['digest'][7:]).read_bytes()
    b.write(target / 'version', 'Directory Transport Version: 1.1\n')
    (target / 'manifest.json').write_bytes(raw)
    manifest = json.loads(raw)
    for blob in [manifest['config']] + manifest['layers']:
        b.require(b.DIGEST.fullmatch(blob['digest']), 'Invalid OCI blob digest')
        name = blob['digest'][7:]
        if not (target / name).exists():
            try:
                os.link(layout / 'blobs/sha256' / name, target / name)
            except OSError as error:
                if error.errno != 18: raise
                shutil.copyfile(layout / 'blobs/sha256' / name, target / name)
    return target


class BuildRegistry:
    def __init__(self, docker, work, run_id, resumable=False):
        self.docker, self.work, self.run_id = docker, work, run_id
        self.resumable = resumable
        self.name = 'mmzhou-offline-' + run_id
        self.container = None
        self.tool_image = 'mmzhou-offline-tools:' + run_id
        self.owned_tags = []

    def __enter__(self):
        self.work.mkdir(parents=True, exist_ok=self.resumable)
        try:
            if command([self.docker, 'image', 'inspect', LOCK['registry_image']], check=False).returncode:
                command([self.docker, 'pull', LOCK['registry_image']], self.work / 'registry-pull.log')
            storage = self.work / 'registry-data'; storage.mkdir(exist_ok=self.resumable)
            port_file = self.work / 'registry-port.json'
            port = json.loads(port_file.read_text())['port'] if self.resumable and port_file.exists() else ''
            previous = command([self.docker, 'inspect', self.name], check=False)
            if previous.returncode == 0:
                info = json.loads(previous.stdout)[0]
                b.require(info['Config'].get('Labels', {}).get('io.pxeye.offline-build') == self.run_id,
                          'Registry name belongs to another run')
                b.require(self.resumable and port, 'Existing Registry needs inspection')
                command([self.docker, 'stop', '--time', '5', self.name], check=False)
                remaining = command([self.docker, 'inspect', self.name], check=False)
                if remaining.returncode == 0:
                    b.require(not json.loads(remaining.stdout)[0]['State']['Running'], 'Registry is still running')
                    command([self.docker, 'rm', self.name])
            self.container = command([self.docker, 'run', '--rm', '-d', '--name', self.name,
                '--label', 'io.pxeye.offline-build=' + self.run_id,
                '-p', '127.0.0.1:' + str(port) + ':5000', '--mount', f'type=bind,src={storage},dst=/var/lib/registry', LOCK['registry_image']],
                self.work / 'registry-start.log').stdout.strip()
            endpoint = command([self.docker, 'port', self.container, '5000/tcp']).stdout.strip()
            b.require(re.fullmatch(r'127\.0\.0\.1:[0-9]+', endpoint), 'Registry must listen on loopback only')
            self.address = 'localhost:' + endpoint.rsplit(':', 1)[1]
            if self.resumable:
                atomic_json(port_file, {'port': int(endpoint.rsplit(':', 1)[1])})
            for _ in range(30):
                try:
                    with urllib.request.urlopen('http://' + endpoint + '/v2/', timeout=1) as response:
                        if response.status == 200:
                            return self
                except OSError:
                    time.sleep(0.2)
            raise ValueError('Build registry did not become ready')
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *_):
        failures = []
        if self.container:
            command([self.docker, 'logs', self.container], self.work / 'registry.log', check=False)
            command([self.docker, 'stop', '--time', '5', self.container], self.work / 'registry-stop.log', check=False)
            state = command([self.docker, 'inspect', '--format', '{{.State.Running}}', self.container], check=False)
            if not state.returncode and state.stdout.strip() == 'true':
                failures.append('Registry still running: ' + self.container)
        for tag in self.owned_tags:
            if command([self.docker, 'image', 'rm', tag], check=False).returncode:
                failures.append('Could not remove per-run tag: ' + tag)
        b.require(not failures, '; '.join(failures))

    def skopeo(self, args, log, view=None):
        cmd = [self.docker, 'run', '--rm', '--network', 'host', '--user', '0:0', '--entrypoint', 'skopeo']
        if view:
            cmd += ['--mount', f'type=bind,src={view},dst=/input,readonly']
        return command(cmd + [self.tool_image] + args, self.work / log)

    def seed(self, view, dest, log):
        self.skopeo(['copy', '--retry-times', '3', '--preserve-digests', '--dest-tls-verify=false',
            '--dest-oci-accept-uncompressed-layers', 'dir:/input', 'docker://' + dest], log, view)


def stage_charts(bundle, source, mapping, material_images, bootstrap, core_references, chart_directory=None):
    trees = bundle.parent / '.charts'
    trees.mkdir()
    prepared = {}
    for filename, key in [('cert-manager-v1.17.1.tgz', 'cert-manager'), ('nico-0.1.1.tgz', 'core'), ('pxeye-nico-platform-0.1.0.tgz', 'platform')]:
        dest = trees / key; dest.mkdir()
        b.extract_chart((Path(chart_directory) if chart_directory else source / 'deployment/charts') / filename, dest)
        roots = [p for p in dest.iterdir() if p.is_dir() and (p / 'Chart.yaml').is_file()]
        b.require(len(roots) == 1, 'Chart root absent or ambiguous: ' + filename)
        prepared[key] = roots[0]
    prepared['pxeye'] = trees / 'pxeye'
    charts.pxeye(prepared['pxeye'], REPO, next(v for k, v in mapping.items() if k == '__ui__'))
    prepared['materials'] = trees / 'materials'
    charts.materials(prepared['materials'], material_images, bootstrap)
    for key in ('cert-manager', 'core', 'platform'):
        root = prepared[key]
        values = yaml.safe_load((root / 'values.yaml').read_text()) or {}
        profile = yaml.safe_load((REPO / 'deploy/offline-core/values' / (key + '.yaml')).read_text())
        values = charts.merge(values, profile)
        if key == 'platform':
            values['bootstrapImage'] = bootstrap
            values['coreServiceAccount'] = '@{release_prefix}-nico-api'
        if key == 'core':
            # Explicit locked runtime dependencies belong to the real Core Chart,
            # not to a dummy Deployment created only for image collection.
            if not (source / 'prepared.json').is_file():
                values['offlineDependencies'] = {'image' + str(i): r for i, r in enumerate(core_references)}
            else:
                values.pop('offlineDependencies', None)
        hints = charts.bind_images(values, mapping | {v: v for v in mapping.values()})
        # Match the dependency default's collection type to the root override.
        # Without this Helm silently discards defaults with a coalesce warning.
        if key == 'core':
            child_path = root / 'charts/nico-pxe/values.yaml'
            child = yaml.safe_load(child_path.read_text())
            child['bootArtifactContainers'] = values['nico-pxe']['bootArtifactContainers']
            b.write(child_path, yaml.safe_dump(child, sort_keys=False))
        b.write(root / 'values.yaml', yaml.safe_dump(values, sort_keys=False))
        b.write(root / '.relok8s-images.yaml', yaml.safe_dump(hints))
    for key in ('pxeye', 'materials'):
        root = prepared[key]
        values = yaml.safe_load((root / 'values.yaml').read_text())
        identity = {v: v for v in mapping.values()} | {v: v for v in material_images.values()}
        hints = charts.bind_images(values, identity)
        b.write(root / 'values.yaml', yaml.safe_dump(values, sort_keys=False))
        b.write(root / '.relok8s-images.yaml', yaml.safe_dump(hints))
    return prepared


def validate_charts(roots, helm, mapping, material_images, directory):
    known = set(mapping.values()) | set(material_images.values())
    settings = {'release_prefix': 'nico', 'namespace': 'nico-system', 'site_name': 'Build validation',
                'dns_ip': '10.96.40.10', 'pxe_ip': '10.96.40.11', 'ntp_ip': '10.96.40.12'}
    report = []
    for key, root in roots.items():
        expected = hinted_images(root)
        modes = ['infrastructure', 'vault-bootstrap'] if key == 'platform' else ['default']
        for mode in modes:
            values = b.substitute((root / 'values.yaml').read_text(), settings)
            path = directory / (key + '-' + mode + '.yaml'); path.write_text(values)
            args = [helm, 'template', 'nico' if key in ('core', 'platform') else key, root,
                    '--namespace', 'nico-system', '-f', path]
            if key == 'platform':
                args += ['--set', 'mode=' + mode]
            objects = list(yaml.safe_load_all(command(args, directory / (key + '-' + mode + '.log')).stdout))
            images = set()
            def walk(value):
                if isinstance(value, dict):
                    if isinstance(value.get('image'), str):
                        images.add(value['image'])
                    for child in value.values(): walk(child)
                elif isinstance(value, list):
                    for child in value: walk(child)
            walk(objects)
            b.require(images <= known, 'Rendered image is outside the archive closure: ' + ', '.join(sorted(images - known)))
            b.require(images <= expected, 'Rendered image is absent from this Chart hints: ' + ', '.join(sorted(images - expected)))
            if key == 'core':
                native_boot = [v for k, v in mapping.items() if 'boot-artifacts-x86' in k]
                b.require(native_boot and set(native_boot) <= images, 'Native x86_64 boot-artifacts initContainer was lost during Chart composition')
            b.require('@{' not in yaml.safe_dump(objects), 'Unresolved validation token in ' + key)
            report.append({'chart': key, 'mode': mode, 'resources': len(objects), 'images': sorted(images)})
    return report


def check_intermediate(path, expected):
    with tarfile.open(path, 'r:') as outer:
        required = {'hints.yaml', 'original-chart/Chart.yaml', 'original-chart/values.yaml', 'images.tar'}
        b.require(required <= set(outer.getnames()), 'relok8s output lacks required members')
        with outer.extractfile('images.tar') as images, tarfile.open(fileobj=images, mode='r:') as inner:
            manifests = json.load(inner.extractfile('manifest.json'))
            names = {name for row in manifests for name in row['RepoTags']}
            b.require(names == expected, 'relok8s archived images differ from hints: ' + str(sorted(names ^ expected)))
    return len(names)


def build(config, args, progress=None):
    _, base, extra, groups = input_plan(config)
    b.require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'amd64'), 'Build on Linux x86_64, such as the .50 builder')
    for key in ('docker', 'helm'):
        b.require(shutil.which(config['tools'][key]), 'Required build tool absent: ' + key)
    docker = config['tools']['docker']
    command([docker, 'version', '--format', '{{.Server.Version}}'], timeout=30)
    context = json.loads(command([docker, 'context', 'inspect'], timeout=30).stdout)[0]
    endpoint = context['Endpoints']['docker']['Host']
    if not os.environ.get('DOCKER_CONTEXT'):
        endpoint = os.environ.get('DOCKER_HOST') or endpoint
    b.require(endpoint.startswith('unix://'), 'Use a local Unix Docker endpoint; build Registry loopback cannot use a remote Docker context')
    command([config['tools']['helm'], 'version', '--short'], timeout=30)
    version = args.version or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    b.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', version), 'Unsafe build version')
    config['output_root'].mkdir(parents=True, exist_ok=True)
    output = config['output_root'] / version
    b.require(not output.exists(), 'Output already exists; choose a new version')
    source = config['materials_bundle']
    size = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
    b.require(shutil.disk_usage(output.parent).free > size * 4 + 2 * 1024**3, 'Need at least four times the extracted materials size plus 2 GiB free space')
    docker_root = Path(command([docker, 'info', '--format', '{{.DockerRootDir}}'], timeout=30).stdout.strip())
    b.require(docker_root.is_dir() and shutil.disk_usage(docker_root).free > size * 2 + 2 * 1024**3,
              'Need at least twice the input size plus 2 GiB free in local Docker storage')
    is_prepared = (source / 'prepared.json').is_file()
    with progress.stage('01-inputs', 'Verify input hashes and toolchain'):
        if is_prepared:
            prepared.verify(source, kinds=('nico-prepared', 'nico-package-input'))
        else:
            b.verify(source)
            b.require(b.sha(source / 'images/nico-amd64.oci.tar') == b.OCI_SHA, 'Unsupported Core archive')
    if args.check_inputs:
        print('HELM_INPUTS_READY; relok8s and pinned registry image will be prepared during build', flush=True)
        return
    revision = command(['git', '-C', REPO, 'rev-parse', 'HEAD']).stdout.strip()
    tracked = ['offline-build/material-prepare', 'offline-build/onsite', 'offline-build/helm-bundle', 'offline-build/build.py', 'deploy/bootstrap-kubernetes.yaml',
               'deploy/nico-platform', 'deploy/offline-core', 'deploy/nico-cluster-permissions.yaml', 'charts/pxeye', 'offline-build/build_config.py', 'offline-build/build-config.example.json']
    dirty = command(['git', '-C', REPO, 'status', '--porcelain', '--untracked-files=all', '--'] + tracked).stdout
    b.require(not dirty, 'Commit build sources before constructing images; unrelated changes are preserved')
    with (output.parent / ('.' + version + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        b.require(not output.exists(), 'Output already exists')
        stage = progress.directory
        try:
            bundle = stage / 'bundle'
            for folder in ('charts', 'relocation', 'manifests', 'profiles', 'tools', 'docs'):
                (bundle / folder).mkdir(parents=True, exist_ok=True)
            with progress.stage('02-tools', 'Prepare locked packaging tools'):
                relok = relok_tool(config, output.parent / '.tool-cache')
            rows = base if is_prepared else b.oci_check(source / 'images/nico-amd64.oci.tar', base)
            for row in ([] if is_prepared else extra):
                verified = b.oci_check(source / row['archive'], reference=row['source_image'])[0]
                b.require(verified['digest'] == row['digest'], 'PXEye archive digest mismatch')
            run_id = hashlib.sha256(str(stage).encode()).hexdigest()[:12]
            material_records = []
            packages = []
            with BuildRegistry(config['tools']['docker'], stage / '.work', run_id, resumable=True) as registry:
                bootstrap = next(row for row in extra if row['purpose'] == 'bootstrap')
                loaded = registry.work / 'build-tools.tar'
                if is_prepared:
                    tool_archive = registry.work / 'bootstrap.oci.tar'
                    archive_image(source / 'images/layout', bootstrap['source_image'], tool_archive)
                    docker_archive(tool_archive, bootstrap['source_image'], loaded, registry.tool_image)
                    tool_archive.unlink()
                else:
                    docker_archive(source / bootstrap['archive'], bootstrap['source_image'], loaded, registry.tool_image)
                command([registry.docker, 'load', '--input', loaded], registry.work / 'tools-load.log')
                registry.owned_tags.append(registry.tool_image)
                loaded.unlink()
                mapping = {}
                image_records = []
                layouts = {}
                prepared_materials = json.loads((source / 'manifests/materials.json').read_text()) if is_prepared else []
                material_rows = [r for r in json.loads((source / 'manifests/images-lock.json').read_text()) if r['kind'] == 'material'] if is_prepared else []
                staged_images = unique_images(base + extra + material_rows)
                for i, row in enumerate(staged_images):
                    reference = row.get('source_image') or row['image']
                    destination = registry.address + '/build/' + reference.rsplit('/', 1)[-1]
                    b.require(destination not in mapping.values(), 'Input image basenames collide: ' + reference)
                    if is_prepared:
                        layout = source / 'images/layout'
                    else:
                        archive = source / row.get('archive', 'images/nico-amd64.oci.tar')
                        if archive not in layouts:
                            target = registry.work / ('oci-' + str(len(layouts)))
                            if target.exists(): shutil.rmtree(target)
                            layouts[archive] = unpack_oci(archive, target)
                        layout = layouts[archive]
                    with progress.stage(f'02-image-{i:02}', 'Stage image ' + reference):
                        view_path = registry.work / f'view-{i:02}'
                        if view_path.exists(): shutil.rmtree(view_path)
                        view = image_view(layout, reference, view_path)
                        digest = row.get('amd64_manifest') or row['digest']
                        if registry_has(registry, destination, digest):
                            print('REUSE_IMAGE', reference, flush=True)
                        else:
                            registry.seed(view, destination, f'image-{i:02}.log')
                    mapping[reference] = destination
                    image_records.append({'source': reference, 'build_reference': destination,
                        'digest': row.get('amd64_manifest') or row['digest'], 'kind': row.get('kind', row.get('purpose', 'core'))})
                mapping['__ui__'] = mapping[next(r['source_image'] for r in extra if r['purpose'] == 'ui')]
                bootstrap_ref = mapping[bootstrap['source_image']]
                material_images = {r['id']: mapping[r['image']] for r in prepared_materials}
                material_records.extend(r | {'build_reference': mapping[r['image']]} for r in prepared_materials)
                for name, group in groups.items():
                    context = registry.work / ('material-' + name)
                    if context.exists(): shutil.rmtree(context)
                    payload = context / 'payload'; payload.mkdir(parents=True)
                    records = []
                    prefix = {'aarch64': 'boot/aarch64/', 'apt': 'boot/apt/', 'bfb': 'http/nico/dpu/'}[name]
                    for row in group:
                        relative = row['path'][len(prefix):]
                        target = payload / b.safe_name(relative); target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source / row['path'], target); target.chmod(0o644)
                        records.append({'path': relative, 'bytes': row['bytes'], 'sha256': row['sha256']})
                    manifest = {'id': name, 'version': version, 'container_platform': 'linux/amd64',
                        'target_architecture': 'aarch64' if name == 'aarch64' else 'mixed',
                        'image_payload': '/payload', 'published_path': '/materials/' + name + '/' + version, 'files': records}
                    b.dump(payload / 'manifest.json', manifest)
                    shutil.copyfile(HOME / 'material-publish.py', context / 'publish.py')
                    (context / 'publish.py').chmod(0o644)
                    for folder in [payload] + [p for p in payload.rglob('*') if p.is_dir()]:
                        folder.chmod(0o755)
                    b.write(context / 'Dockerfile', 'FROM ' + registry.tool_image + '\nCOPY payload /payload\nCOPY publish.py /publish.py\nENTRYPOINT ["python3", "/publish.py"]\n')
                    ref = registry.address + '/build/nico-material-' + name + ':' + version
                    command([registry.docker, 'build', '--pull=false', '--network=none', '--label',
                        'io.pxeye.offline-build=' + run_id, '--tag', ref, context], registry.work / (name + '-build.log'))
                    registry.owned_tags.append(ref)
                    command([registry.docker, 'push', ref], registry.work / (name + '-push.log'))
                    digest = registry.skopeo(['inspect', '--tls-verify=false', '--format', '{{.Digest}}', 'docker://' + ref], name + '-digest.log').stdout.strip()
                    material_images[name] = ref
                    material_records.append(manifest | {'build_reference': ref, 'image_digest': digest})
                    image_records.append({'build_reference': ref, 'digest': digest, 'kind': 'material'})
                if (stage / '.charts').exists(): shutil.rmtree(stage / '.charts')
                with progress.stage('03-charts', 'Compose and render Charts'):
                    roots = stage_charts(bundle, source, mapping, material_images, bootstrap_ref, [r['image'] for r in base], config.get('chart_directory'))
                    render_dir = stage / 'render'; render_dir.mkdir(exist_ok=True)
                    render = validate_charts(roots, config['tools']['helm'], mapping, material_images, render_dir)
                image_usage = [{'image': r['build_reference'], 'source': r.get('source'), 'used_by': [v['chart'] + '/' + v['mode'] for v in render if r['build_reference'] in v['images']]} for r in image_records]
                if is_prepared:
                    b.require(all(r['used_by'] for r in image_usage), 'Prepared images include entries unused by the selected Charts')
                for key, root in roots.items():
                    metadata = yaml.safe_load((root / 'Chart.yaml').read_text())
                    chart_path = bundle / 'charts' / (key + '.tgz')
                    b.pack_tree(root, chart_path, metadata['name'])
                    relocation = bundle / 'relocation' / (key + '.tar')
                    with progress.stage('04-relocate-' + key, 'Package Chart ' + key) as checkpoint:
                        expected = hinted_images(root)
                        chart_hash = b.sha(chart_path)
                        reuse = (checkpoint.get('chart_sha256') == chart_hash and relocation.is_file()
                                 and checkpoint.get('relocation_sha256') == b.sha(relocation))
                        if reuse:
                            print('REUSE_RELOCATION', key, flush=True)
                        else:
                            partial = relocation.with_suffix('.partial.tar')
                            partial.unlink(missing_ok=True)
                            command([relok, 'chart', 'move', chart_path, '--to-intermediate-bundle', partial, '--yes'],
                                    stage / (key + '-relok8s.log'), env={**os.environ, 'TMPDIR': str(registry.work)})
                            compatible = prepare_intermediate(partial, relocation.with_suffix('.compatible.tar'))
                            compatible.replace(relocation)
                            partial.unlink(missing_ok=True)
                        count = check_intermediate(relocation, expected)
                        checkpoint.update(chart_sha256=chart_hash, relocation_sha256=b.sha(relocation))
                    packages.append({'id': key, 'name': metadata['name'], 'version': metadata['version'],
                        'chart': chart_path.relative_to(bundle).as_posix(), 'relocation': relocation.relative_to(bundle).as_posix(),
                        'images': sorted(expected), 'image_count': count})
            # Only transport artifacts are delivered; transient Registry data,
            # Docker contexts and source OCI archives are not duplicated.
            shutil.copyfile(relok, bundle / 'tools/relok8s')
            shutil.copyfile(source / 'tools/helm', bundle / 'tools/helm')
            for tool in ('relok8s', 'helm'):
                (bundle / 'tools' / tool).chmod(0o755)
            shutil.copyfile(HOME / 'verify.py', bundle / 'tools/verify.py')
            shutil.copytree(REPO / 'offline-build/onsite', bundle / 'tools/onsite', dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copyfile(REPO / 'offline-build/onsite/prepare-bundle.sh', bundle / 'tools/prepare-bundle.sh')
            (bundle / 'tools/prepare-bundle.sh').chmod(0o755)
            for name in ('README.md', 'README.zh-CN.md'):
                shutil.copyfile(HOME / name, bundle / 'docs' / name)
            shutil.copyfile(HOME / 'toolchain-lock.json', bundle / 'manifests/toolchain-lock.json')
            shutil.copyfile(HOME / 'relok8s-LICENSE', bundle / 'docs/relok8s-LICENSE')
            b.dump(bundle / 'manifests/images-lock.json', image_records)
            b.dump(bundle / 'manifests/materials.json', material_records)
            plan = json.loads((REPO / 'deploy/offline-core/deployment.json').read_text())
            plan['phases'][1]['material_chart'] = 'materials'
            for phase in plan['phases']:
                phase['chart_id'] = 'platform' if phase['id'] == 'vault' else phase['id']
                phase.pop('chart', None)
                phase.pop('values', None)
                phase['values_inline'] = {'mode': 'vault-bootstrap'} if phase['id'] == 'vault' else {}
            plan['schema_version'] = 2
            plan['description'] += '；OCI阶段目录需新版安装入口支持。'
            b.dump(bundle / 'profiles/install-plan.json', plan)
            b.write(bundle / 'profiles/site-values.example.yaml', yaml.safe_dump({
                'registry': None, 'namespace': 'nico-system', 'release_prefix': 'nico', 'storage_class': None,
                'service_ips': {'dns': None, 'pxe': None, 'ntp': None},
                'host_network': {'name': None, 'prefix': None, 'gateway': None, 'mtu': 1500},
            }, sort_keys=False))
            b.dump(bundle / 'bundle.json', {'schema_version': 1, 'kind': 'pxeye-nico-helm', 'id': config['bundle_id'],
                'version': version, 'source_revision': revision, 'architecture': 'linux/amd64', 'charts': packages,
                'requires_site_configuration': True, 'multi_phase_oci_ui_ready': False})
            chart_provenance = Path(config.get('chart_directory', source / 'deployment/charts')).parent / 'upstream-sources.json'
            b.dump(bundle / 'manifests/build-report.json', {'source_revision': revision, 'input_bundle': json.loads((source / ('prepared.json' if is_prepared else 'bundle.json')).read_text()),
                'upstream_chart_sources': json.loads(chart_provenance.read_text()) if chart_provenance.is_file() else None,
                'input_inventory_sha256': b.sha(source / ('manifests/files.json' if is_prepared else 'manifests/file-inventory.json')),
                'package_builds_images': bool(groups), 'base_images': rows,
                'native_x86_boot_artifacts': {'source': 'existing locked image', 'internal_files_verified': False},
                'validation_render': render, 'image_usage': image_usage, 'tool_hashes': {n: b.sha(bundle / 'tools' / n) for n in ('helm', 'relok8s')},
                'cold_install_tested': False, 'multi_phase_oci_ui_ready': False})
            b.inventory(bundle)
            verify(bundle)
            with progress.stage('05-archive', 'Compress delivery archive') as checkpoint:
                inventory_hash = b.sha(bundle / 'manifests/file-inventory.json')
                archive = stage / 'bundle.tar.gz'
                if (archive.is_file() and checkpoint.get('inventory_sha256') == inventory_hash
                        and checkpoint.get('archive_sha256') == b.sha(archive)):
                    print('REUSE_ARCHIVE', archive, flush=True)
                else:
                    partial = stage / 'bundle.partial.tar.gz'
                    b.pack_tree(bundle, partial, config['bundle_id'])
                    partial.replace(archive)
                checkpoint.update(inventory_sha256=inventory_hash, archive_sha256=b.sha(archive))
            digest = b.sha(stage / 'bundle.tar.gz')
            b.write(stage / 'SHA256SUMS', digest + '  bundle.tar.gz\n')
            # Read back every archive member; directory verification alone does
            # not prove that the compressed delivery contains the same bytes.
            with progress.stage('06-verify', 'Read back every archived file'):
                expected = {r['path']: r for r in json.loads((bundle / 'manifests/file-inventory.json').read_text())['files']}
                expected['manifests/file-inventory.json'] = {'sha256': b.sha(bundle / 'manifests/file-inventory.json'), 'bytes': (bundle / 'manifests/file-inventory.json').stat().st_size}
                seen = set()
                with tarfile.open(stage / 'bundle.tar.gz', 'r|gz') as tar:
                    for member in tar:
                        if member.isdir(): continue
                        name = b.safe_name(member.name)
                        b.require(member.isfile() and name.startswith(config['bundle_id'] + '/'), 'Unexpected delivery archive member')
                        relative = name[len(config['bundle_id']) + 1:]
                        b.require(relative in expected and relative not in seen and member.size == expected[relative]['bytes'], 'Archive inventory mismatch')
                        seen.add(relative); h = hashlib.sha256()
                        with tar.extractfile(member) as stream:
                            for block in iter(lambda: stream.read(8 * 1024**2), b''): h.update(block)
                        b.require(h.hexdigest() == expected[relative]['sha256'], 'Archive content checksum mismatch: ' + relative)
                b.require(seen == set(expected), 'Delivery archive is incomplete')
            logs = stage / 'logs'; logs.mkdir(exist_ok=True)
            for path in (stage / '.work').glob('*.log'):
                shutil.copyfile(path, logs / path.name)
            with progress.stage('07-onsite-tools', 'Export the small onsite runner kit'):
                kit = stage / 'onsite-tools'
                # Only this staging directory's generated helper kit is refreshed.
                if kit.exists(): shutil.rmtree(kit)
                for path in (stage / 'onsite-tools.tar.gz', stage / 'onsite-tools.tar.gz.sha256'):
                    path.unlink(missing_ok=True)
                command([sys.executable, REPO / 'offline-build/onsite/export.py', '--output', kit], logs / 'onsite-tools.log')
                kit_digest = b.sha(stage / 'onsite-tools.tar.gz')
                b.write(stage / 'SHA256SUMS', digest + '  bundle.tar.gz\n' + kit_digest + '  onsite-tools.tar.gz\n')
            b.dump(stage / 'build-result.json', {'version': version, 'source_revision': revision,
                'archive_bytes': (stage / 'bundle.tar.gz').stat().st_size, 'archive_sha256': digest,
                'distinct_images': len(image_records), 'charts': len(packages), 'cold_install_tested': False,
                'onsite_tools_archive_sha256': kit_digest})
            progress.complete()
            stage.rename(output)
            shutil.rmtree(output / '.work')
            shutil.rmtree(output / '.charts')
            print('HELM_BUILD_COMPLETE', output, flush=True)
            print('DELIVERY_FILES', output / 'bundle.tar.gz', output / 'onsite-tools.tar.gz', output / 'SHA256SUMS', flush=True)
        except BaseException:
            print('HELM_BUILD_FAILED; staging retained at', stage, flush=True)
            raise


def unique_images(rows):
    """One image may serve multiple roles; stage its locked content only once."""
    images = {}
    for row in rows:
        reference = row.get('source_image') or row['image']
        if reference in images:
            previous = images[reference]
            b.require((previous.get('amd64_manifest') or previous['digest']) ==
                      (row.get('amd64_manifest') or row['digest']), 'Conflicting digests for ' + reference)
        else:
            images[reference] = row
    return list(images.values())


def registry_has(registry, reference, digest):
    path, tag = reference.partition('/')[2].rsplit(':', 1)
    request = urllib.request.Request('http://' + registry.address + '/v2/' + path + '/manifests/' + tag,
        method='HEAD', headers={'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.headers.get('Docker-Content-Digest') == digest
    except urllib.error.HTTPError as error:
        if error.code == 404: return False
        raise


def run_build(config, args):
    output = config['output_root']; output.mkdir(parents=True, exist_ok=True)
    identity = {'config': {k: str(v) if isinstance(v, Path) else v for k, v in config.items()},
                'implementation': command(['git', '-C', REPO, 'rev-parse', 'HEAD']).stdout.strip(),
                'input_inventory_sha256': b.sha(config['materials_bundle'] / ('manifests/files.json' if (config['materials_bundle'] / 'prepared.json').exists() else 'manifests/file-inventory.json'))}
    # Persist a default version per configuration. New deliveries use --version.
    key = hashlib.sha256(json.dumps(identity['config'], sort_keys=True).encode()).hexdigest()[:24]
    pointer = output / ('.active-' + key + '.json')
    with (output / ('.active-' + key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not args.version:
            if pointer.exists(): args.version = json.loads(pointer.read_text())['version']
            else: args.version = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        b.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', args.version), 'Unsafe build version')
        identity['version'] = args.version
        directory = output / ('.' + args.version + '.building')
        final = output / args.version
        if final.exists():
            record = json.loads((final / 'progress.json').read_text())
            b.require(record['identity'] == identity and record['status'] == 'completed', 'Output exists with different inputs or incomplete state')
            with transcript(final):
                verify(final / 'bundle')
                result = json.loads((final / 'build-result.json').read_text())
                b.require(b.sha(final / 'bundle.tar.gz') == result['archive_sha256'], 'Completed archive changed')
                b.require(b.sha(final / 'onsite-tools.tar.gz') == result['onsite_tools_archive_sha256'], 'Completed onsite kit changed')
                print('HELM_BUILD_REUSED', final, flush=True)
                print('DELIVERY_FILES', final / 'bundle.tar.gz', final / 'onsite-tools.tar.gz', final / 'SHA256SUMS', flush=True)
            return
        progress = Progress(directory, identity)
        if not args.check_inputs: atomic_json(pointer, {'version': args.version})
        with transcript(directory):
            try:
                build(config, args, progress)
            except BaseException as error:
                progress.fail(error)
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--write-config', type=Path)
    parser.add_argument('--materials-bundle', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--work-directory', type=Path)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--check-inputs', action='store_true')
    parser.add_argument('--prepare-charts', action='store_true', help='Download, verify and unpack Charts only; no Docker or cluster operations')
    parser.add_argument('--version')
    args = parser.parse_args()
    install_signal_handlers()
    if args.write_config:
        b.require(not args.materials_bundle and not args.output_root, 'Use the shared build-config.json and its stage sections')
        sys.path.insert(0, str(HOME.parent))
        import build_config
        build_config.initialize(args.write_config, 'helm_bundle', args.work_directory)
        return
    b.require(args.config, 'Pass --config or --write-config')
    path = args.config.expanduser().resolve()
    raw = json.loads(path.read_text())
    if 'work_directory' in raw:
        import assembly
        value = assembly.configuration(path)
        if args.plan:
            assembly.plan(value)
            return
        work = value['work_directory']; work.mkdir(parents=True, exist_ok=True)
        with (work / '.package-prepare.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logs = work / 'logs/chart-preparation'; logs.mkdir(parents=True, exist_ok=True)
            with transcript(logs):
                if args.prepare_charts:
                    chart_sources.prepare(work, value['sources'].get('charts'), b, helm=value['tools']['helm'])
                    return
                config = assembly.prepare(value, sys.modules[__name__])
    else:
        config = read_config(path)
        if args.prepare_charts or config.get('chart_sources'):
            if args.plan:
                chart_sources.settings(config.get('chart_sources'))
            else:
                downloaded = chart_sources.prepare(config['output_root'], config.get('chart_sources'), b, helm=config['tools']['helm'])
                config['chart_directory'] = str(downloaded / 'deployment/charts')
                if args.prepare_charts: return
    if args.plan:
        input_plan(config)
        return
    run_build(config, args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, tarfile.TarError, yaml.YAMLError) as error:
        raise SystemExit(str(error)) from None
