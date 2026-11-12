#!/usr/bin/env python3
"""Build an immutable, complete NICo Core delivery from local locked inputs.

No Docker socket, Kubernetes credentials, live cluster or network is used. This
builder supports the pinned e703126e4 / nico-0.1.1 material set. Changed upstream
charts must be reviewed before adding another compatibility profile.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import difflib
from datetime import datetime, timezone
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import tarfile
import tempfile

try:
    import yaml
except ImportError:
    raise SystemExit('Python PyYAML is required; use the documented Python environment.') from None

BUILD_HOME = Path(__file__).resolve().parent
REPO = BUILD_HOME if (BUILD_HOME / 'deploy').is_dir() else BUILD_HOME.parent
ASSETS = REPO / 'deploy/offline-core'
RAW = {
    'nico-0.1.1.tgz': '9e38837fcd7305ffd5e060ba18e973794388d3b0f83363b7903a21d3ae94ad67',
    'cert-manager-v1.17.1.tgz': '48707f6e8937290da96065dc7de8b4f5a95d9707798d4b5a0d560f78c12996f7',
}
OCI_SHA = '67a36d111080860e3b4e98ecd48e5c83557d437f3472643cb344c12fab965a5e'
DIGEST = re.compile(r'sha256:([0-9a-f]{64})\Z')
TOKEN = re.compile(r'@\{([a-z_]+)\}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    path.chmod(0o644)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o644)


def substitute(value, settings):
    if isinstance(value, str):
        return TOKEN.sub(lambda m: str(settings.get(m[1], m[0])), value)
    if isinstance(value, dict):
        return {key: substitute(item, settings) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, settings) for item in value]
    return value


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, **kwargs)
    details = result.stdout + result.stderr if str(command[0]) == 'patch' else result.stderr
    require(result.returncode == 0, 'Command failed: ' + str(command[0]) + '\n' + details[:4000])
    return result.stdout


def safe_name(value):
    p = PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts, 'Unsafe archive path: ' + value)
    return str(p)


def extract_chart(archive, target):
    with tarfile.open(archive) as source:
        for member in source:
            name = safe_name(member.name)
            require(member.isfile() or member.isdir(), 'Chart links/devices are not allowed: ' + name)
            dest = target / name
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, dest.open('wb') as out:
                    shutil.copyfileobj(src, out)
                dest.chmod(member.mode & 0o755)


def pack_tree(source, destination, prefix):
    """Fixed ownership/time; do not preserve host identity or follow links."""
    with destination.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=1) as gz:
        with tarfile.open(fileobj=gz, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob('*')):
                require(path.is_file() and not path.is_symlink() or path.is_dir() and not path.is_symlink(), 'Unsafe output file')
                info = archive.gettarinfo(str(path), arcname=prefix + '/' + path.relative_to(source).as_posix())
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644
                if path.is_file():
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)


def oci_check(path, expected=None, reference=None):
    """Verify every blob once, then verify the exact amd64 image closure."""
    with tarfile.open(path, 'r:') as archive:
        members = {}
        for member in archive:
            name = safe_name(member.name)
            require(member.isfile() or member.isdir(), 'OCI links/devices are not allowed')
            if member.isfile():
                require(name not in members, 'Duplicate OCI member: ' + name)
                members[name] = member
        require('index.json' in members and 'oci-layout' in members, 'Missing OCI layout/index')
        verified = {}
        for name, member in members.items():
            if name.startswith('blobs/'):
                require(re.fullmatch(r'blobs/sha256/[0-9a-f]{64}', name), 'Unsupported blob path')
                h = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(8 * 1024**2), b''):
                        h.update(block)
                require(h.hexdigest() == name.rsplit('/', 1)[1], 'Corrupt OCI blob: ' + name)
                verified['sha256:' + h.hexdigest()] = member.size

        def read(name):
            require(name in members, 'Missing OCI member: ' + name)
            return json.load(archive.extractfile(members[name]))

        def blob(desc):
            digest = desc.get('digest', '')
            require(DIGEST.fullmatch(digest) is not None, 'Invalid digest')
            require(verified.get(digest) == desc['size'], 'Missing blob or size mismatch: ' + digest)
            return read('blobs/sha256/' + digest[7:])

        index = read('index.json')
        rows = expected if expected is not None else [{'image': reference}]
        images = []
        for row in rows:
            matches = [d for d in index['manifests'] if d.get('annotations', {}).get('org.opencontainers.image.ref.name') == row['image']]
            require(len(matches) == 1, 'OCI reference absent or ambiguous: ' + str(row['image']))
            desc = matches[0]
            if row.get('amd64_manifest'):
                require(desc['digest'] == row['amd64_manifest'], 'Locked manifest mismatch: ' + row['image'])
            manifest = blob(desc)
            require('config' in manifest and 'layers' in manifest, 'A leaf amd64 manifest is required, not a multi-platform index')
            config = blob(manifest['config'])
            require(config.get('architecture') == 'amd64' and config.get('os') == 'linux', 'Only linux/amd64 control-plane images are supported')
            for layer in manifest['layers']:
                require(verified.get(layer['digest']) == layer['size'], 'Image layer is absent: ' + layer['digest'])
            images.append({'image': row['image'], 'digest': desc['digest'],
                           'config': manifest['config']['digest'], 'layers': len(manifest['layers'])})
        return images


def parse_config(path, value=None):
    c = json.loads(path.read_text()) if value is None else value
    fields = {'bundle_id', 'site_name', 'namespace', 'release_prefix', 'registry', 'repository_prefix',
              'context', 'kind_node', 'service_cidr', 'service_ips', 'host_network', 'bundle_host_path', 'node_port', 'ui', 'bootstrap'}
    require(set(c) == fields, 'Site configuration must contain exactly: ' + ', '.join(sorted(fields)))
    for key in ('namespace', 'release_prefix'):
        require(isinstance(c[key], str) and re.fullmatch(r'[a-z][a-z0-9-]{0,28}[a-z0-9]|[a-z]', c[key]), 'Invalid/overlong ' + key)
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', c['bundle_id']), 'Invalid bundle_id')
    require(isinstance(c['site_name'], str) and 1 <= len(c['site_name']) <= 100, 'Invalid site_name')
    require(re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', c['registry']), 'Registry must be host[:port], without scheme/credentials')
    require(re.fullmatch(r'[a-z0-9][a-z0-9/_-]*', c['repository_prefix']), 'Invalid repository prefix')
    require(30000 <= c['node_port'] <= 32767, 'Invalid NodePort')
    require(re.fullmatch(r'[A-Za-z0-9._@:-]+', c['context']), 'Invalid context')
    require(re.fullmatch(r'[a-z0-9][a-z0-9.-]+', c['kind_node']), 'Invalid Kind node')
    host_path = Path(c['bundle_host_path'])
    require(host_path.is_absolute() and '..' not in host_path.parts and len(host_path.parts) > 2 and re.fullmatch(r'/[A-Za-z0-9/_.-]+', c['bundle_host_path']), 'Use a dedicated absolute bundle host path without shell metacharacters')
    network = ipaddress.ip_network(c['service_cidr'], strict=True)
    require(network.version == 4 and set(c['service_ips']) == {'dns', 'pxe', 'ntp'}, 'Invalid service IP configuration')
    ips = [ipaddress.ip_address(v) for v in c['service_ips'].values()]
    require(len(set(ips)) == 3 and all(i in network and i not in (network.network_address, network.broadcast_address) for i in ips), 'Service IPs must be unique usable addresses inside service_cidr')
    n = c['host_network'];require(set(n) == {'name', 'prefix', 'gateway', 'mtu'}, 'Invalid host_network fields')
    require(re.fullmatch(r'[a-z][a-z0-9_-]{0,48}', n['name']), 'Invalid HostInband name')
    host_net = ipaddress.ip_network(n['prefix'], strict=True);gateway = ipaddress.ip_address(n['gateway'])
    require(host_net.version == 4 and gateway in host_net and gateway not in (host_net.network_address, host_net.broadcast_address), 'Host gateway must be usable and inside the subnet')
    require(1280 <= n['mtu'] <= 9216, 'Invalid MTU')
    for purpose in ('ui', 'bootstrap'):
        image = c[purpose]
        require(set(image) == {'archive', 'source_image', 'tag', 'digest'}, 'Invalid ' + purpose + ' fields')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', image['tag']), 'Invalid image tag')
        require(DIGEST.fullmatch(image['digest']) is not None, 'Invalid expected image digest')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./:_-]*:[A-Za-z0-9][A-Za-z0-9._-]*', image['source_image']), 'Invalid OCI source reference')
        image['archive'] = str((path.parent / image['archive']).resolve())
    require(c['ui']['tag'] != c['bootstrap']['tag'], 'UI and bootstrap archive tags must be distinct')
    version = re.match(r'^(\d+)\.(\d+)\.(\d+)', c['ui']['tag'])
    require(version and tuple(map(int, version.groups())) >= (0, 22, 16), 'UI >=0.22.16 is required for phase/readiness fixes')
    return c


def patch_core(source, output, scratch, expected_charts=None):
    expected_charts = RAW if expected_charts is None else expected_charts
    require(set(expected_charts) == set(RAW), 'Both pinned raw Charts are required')
    for name in expected_charts:
        require(sha(source / 'charts' / name) == expected_charts[name], 'Unsupported raw Chart revision: ' + name)
    extract_chart(source / 'charts/nico-0.1.1.tgz', scratch)
    for name in ('migration-job-lifecycle.patch', 'core-runtime-compatibility.patch'):
        patch = ASSETS / 'patches' / name
        run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', str(patch)], cwd=scratch)
        shutil.copy2(patch, output / 'patches' / patch.name)
    shutil.copy2(ASSETS / 'patches/platform-tls-vault-roles.patch', output / 'patches/platform-tls-vault-roles.patch')
    chart = scratch / 'nico'
    service_patches = []
    def update(file, text):
        before = file.read_text()
        service_patches.append(''.join(difflib.unified_diff(before.splitlines(True), text.splitlines(True), fromfile='a/nico/' + file.relative_to(chart).as_posix(), tofile='b/nico/' + file.relative_to(chart).as_posix())))
        file.write_text(text)
    # Pin the three internal Service IPs to the same explicit values given to
    # Kea. Fresh clusters no longer depend on previously allocated ClusterIPs.
    for component in ('nico-dns', 'nico-pxe'):
        file = chart / 'charts' / component / 'templates/service.yaml'
        text = file.read_text();require(text.count('\nspec:\n') == 1, 'Unexpected service template')
        text = text.replace('\nspec:\n', '\nspec:\n  {{- with .Values.service.clusterIP }}\n  clusterIP: {{ . | quote }}\n  {{- end }}\n', 1)
        update(file, text)
    file = chart / 'charts/nico-ntp/templates/service-client.yaml'
    update(file, file.read_text().replace('\nspec:\n', '\nspec:\n  {{- with .Values.clientService.clusterIP }}\n  clusterIP: {{ . | quote }}\n  {{- end }}\n', 1))
    # Supply the map even when the optional new value is not set by callers.
    values = chart / 'charts/nico-ntp/values.yaml'
    update(values, values.read_text() + '\nclientService: {}\n')
    write(output / 'patches/pin-service-ips.patch', ''.join(service_patches))
    pack_tree(chart, output / 'charts/nico-0.1.1.tgz', 'nico')
    shutil.copy2(source / 'charts/cert-manager-v1.17.1.tgz', output / 'charts/cert-manager-v1.17.1.tgz')
    pack_tree(REPO / 'deploy/nico-platform', output / 'charts/pxeye-nico-platform-0.1.0.tgz', 'pxeye-nico-platform')


def prepare_recipe(bundle, config, version, settings, scratch, source, prepared_charts=None):
    deployment = bundle / 'deployment'
    for folder in ('charts', 'patches', 'values'):
        (deployment / folder).mkdir(parents=True)
    if prepared_charts is None:
        patch_core(source, deployment, scratch)
    else:
        for folder in ('charts', 'patches'):
            for path in sorted((prepared_charts / folder).iterdir()):
                require(path.is_file() and not path.is_symlink(), 'Invalid prepared chart/patch')
                shutil.copyfile(path, deployment / folder / path.name)
    records = json.loads((bundle / 'manifests/images-lock.json').read_text())
    image_map = {r['image']: config['registry'] + '/' + config['repository_prefix'] + '/' + r['image'] for r in records}
    for name in ('cert-manager', 'platform', 'vault', 'core'):
        value = yaml.safe_load((ASSETS / 'values' / (name + '.yaml')).read_text())
        def map_images(item):
            if isinstance(item, dict): return {k: map_images(v) for k, v in item.items()}
            if isinstance(item, list): return [map_images(v) for v in item]
            if isinstance(item, str):
                if item in image_map: return image_map[item]
                # Chart image.repository is stored separately from image.tag.
                repos = {ref.rsplit(':', 1)[0]: dest.rsplit(':', 1)[0] for ref, dest in image_map.items()}
                return substitute(repos.get(item, item), {k: v for k, v in settings.items() if k != 'site_name'})
            return item
        value = map_images(value)
        if name == 'platform' and 'storage_class' in config:
            value['storageClass'] = config['storage_class']
        if name == 'core':
            api = value['nico-api']
            # Keep NICo tokens for all identity/DNS fields, using the same
            # namespace/release inputs as the UI preflight.
            api['auth']['additionalIssuerCns'] = ['@{release_prefix}-nico-admin-issuer']
            import tomllib
            text = api['siteConfig']['nicoApiSiteConfig']
            text = text.replace('sitename = "@{site_name}"', 'sitename = ' + json.dumps(config['site_name'], ensure_ascii=False))
            parsed = tomllib.loads(text)
            old = next(iter(parsed['networks']))
            n = config['host_network']
            text = text.replace('[networks.' + old + ']', '[networks.' + n['name'] + ']')
            old_net = parsed['networks'][old]
            for key, val in (('prefix', n['prefix']), ('gateway', n['gateway'])):
                text = text.replace(key + ' = "' + str(old_net[key]) + '"', key + ' = "' + val + '"')
            text = text.replace('mtu = 1500', 'mtu = ' + str(n['mtu']))
            api['siteConfig']['nicoApiSiteConfig'] = text
            value['nico-dns'].setdefault('service', {})['clusterIP'] = config['service_ips']['dns']
            value['nico-pxe'].setdefault('service', {})['clusterIP'] = config['service_ips']['pxe']
            value['nico-ntp']['clientService'] = {'clusterIP': config['service_ips']['ntp']}
        write(deployment / 'values' / (name + '.yaml'), yaml.safe_dump(value, sort_keys=False, allow_unicode=True))
    manifest = substitute(json.loads((ASSETS / 'deployment.json').read_text()), settings)
    manifest['files'] = {p.relative_to(deployment).as_posix(): sha(p) for folder in ('charts', 'values', 'patches') for p in sorted((deployment / folder).rglob('*')) if p.is_file()}
    dump(deployment / 'deployment.json', manifest)
    return manifest


def prepare_bootstrap(bundle, config, settings, ui):
    namespace = config['namespace'];name = namespace + '-pxeye'
    objects = list(yaml.safe_load_all((REPO / 'deploy/bootstrap-kubernetes.yaml').read_text()))
    for obj in objects:
        old = obj['metadata']['name'];obj['metadata']['name'] = namespace if old == 'mmzhou' else old.replace('mmzhou-pxeye', name)
        if 'namespace' in obj['metadata']: obj['metadata']['namespace'] = namespace
        if obj['kind'] == 'RoleBinding':
            obj['roleRef']['name'] = name + '-nico-installer'
            obj['subjects'] = [{'kind': 'ServiceAccount', 'name': name, 'namespace': namespace}]
        if obj['kind'] == 'Deployment':
            labels = {'app.kubernetes.io/instance': name}
            obj['metadata']['labels'] = labels;obj['spec']['selector']['matchLabels'] = labels
            spec = obj['spec']['template'];spec['metadata']['labels'] = labels;pod = spec['spec']
            pod['serviceAccountName'] = name
            if 'storage_class' in config:
                pod['nodeSelector'] = {'kubernetes.io/hostname': config['kind_node']}
            container = pod['containers'][0];container['image'] = ui['image'] + '@' + ui['digest']
            container['imagePullPolicy'] = 'IfNotPresent'
            container['volumeMounts'].append({'name': 'nico-bundles', 'mountPath': '/nico-bundles', 'readOnly': True})
            for volume in pod['volumes']:
                for key in ('configMap', 'secret', 'persistentVolumeClaim'):
                    if key in volume:
                        for field in ('name', 'secretName', 'claimName'):
                            if field in volume[key]: volume[key][field] = volume[key][field].replace('mmzhou-pxeye', name)
            pod['volumes'].append({'name': 'nico-bundles', 'hostPath': {'path': config['bundle_host_path'], 'type': 'Directory'}})
        if obj['kind'] == 'Service':
            obj['spec']['selector'] = {'app.kubernetes.io/instance': name}
            obj['spec']['ports'][0]['nodePort'] = config['node_port']
        if obj['kind'] == 'PersistentVolumeClaim' and 'storage_class' in config:
            obj['spec']['storageClassName'] = config['storage_class']
    write(bundle / 'deployment/pxeye-bootstrap.yaml', yaml.safe_dump_all(objects, sort_keys=False))
    role = next(o for o in objects if o['kind'] == 'Role')
    binding = next(o for o in objects if o['kind'] == 'RoleBinding')
    write(bundle / 'deployment/nico-target-namespace-rbac.yaml', yaml.safe_dump_all([role, binding], sort_keys=False))
    cluster = list(yaml.safe_load_all((REPO / 'deploy/nico-cluster-permissions.yaml').read_text().replace('mmzhou-pxeye', name).replace('namespace: mmzhou', 'namespace: ' + namespace)))
    write(bundle / 'deployment/nico-cluster-permissions.yaml', yaml.safe_dump_all(cluster, sort_keys=False))
    dump(bundle / 'config/runtime.json', {'site': {'name': config['site_name'], 'namespace': namespace, 'deployment': name},
         'core_url': '', 'nico_deployment': {'enabled': True, 'namespace': namespace, 'allow_cluster_resources': True, 'bundles_directory': '/nico-bundles'}})
    dump(bundle / 'config/deployment-settings.json', {**settings, 'deployment': name, 'node_port': config['node_port'],
         'registry': config['registry'], 'service_cidr': config['service_cidr'], 'service_ips': config['service_ips']})


def validate_render(bundle, manifest, config, helm, scratch, locked):
    settings = {'release_prefix': config['release_prefix'], 'namespace': config['namespace'], 'site_name': config['site_name']}
    objects = [];phases = []
    for phase in manifest['phases']:
        command = [helm, 'template', substitute(phase['release'], settings), str(bundle / 'deployment' / phase['chart']), '--namespace', config['namespace']]
        for i, relative in enumerate(phase['values']):
            values = scratch / (phase['id'] + '-' + str(i) + '.yaml')
            write(values, substitute((bundle / 'deployment' / relative).read_text(), settings))
            command += ['-f', str(values)]
        text = run(command)
        require('@{' not in text and 'REPLACE_WITH_' not in text, 'Unresolved rendered token')
        rows = [o for o in yaml.safe_load_all(text) if o]
        phases.append({'id': phase['id'], 'resources': len(rows)})
        objects += rows
    images = set()
    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get('image'), str): images.add(v['image'])
            for child in v.values(): walk(child)
        elif isinstance(v, list):
            for child in v: walk(child)
    for o in objects:
        walk(o)
        if o['kind'] in ('Deployment', 'StatefulSet'):
            require(o['spec'].get('replicas', 1) == 1, 'Only single replica is supported')
        if o['kind'] == 'Certificate':
            require(len(o['spec'].get('commonName', '').encode()) <= 64, 'Certificate commonName >64 bytes')
        if o['kind'] not in ('ClusterRole', 'ClusterRoleBinding', 'CustomResourceDefinition', 'ClusterIssuer', 'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration'):
            require(o['metadata'].get('namespace', config['namespace']) == config['namespace'], 'Cross-namespace rendered object')
    require(images <= locked, 'Rendered image is not in the locked input: ' + ', '.join(sorted(images - locked)))
    prefix = config['release_prefix'];ns = config['namespace']
    services = {o['metadata']['name']: o for o in objects if o['kind'] == 'Service'}
    for key, suffix in (('dns', 'dns'), ('pxe', 'pxe'), ('ntp', 'ntp-client')):
        require(services[prefix + '-nico-' + suffix]['spec']['clusterIP'] == config['service_ips'][key], 'DHCP/Service IP mismatch')
    # Catch the startupapicheck hook dependency deadlock before packaging.
    startup = [o for o in objects if 'startupapicheck' in o['metadata']['name']]
    require({o['kind'] for o in startup} >= {'Job', 'ServiceAccount', 'Role', 'RoleBinding'}, 'Incomplete startupapicheck dependencies')
    require(all(not o['metadata'].get('annotations', {}).get('helm.sh/hook') for o in startup), 'startupapicheck hook mismatch')
    require(len([o for o in objects if o['kind'] in ('Deployment', 'StatefulSet')]) == 13, 'Unexpected Core workload count')
    core = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == prefix + '-nico-api')
    serialized = yaml.safe_dump(core)
    require(prefix + '-nico-admin-issuer' in serialized and 'admin-root' in serialized, 'Missing admin trust mount')
    for o in objects:
        if o['kind'] == 'Job' and o['metadata']['name'].endswith('-migrate'):
            require(o['spec'].get('activeDeadlineSeconds') == 900, 'Migration deadline missing')
    return {'phases': phases, 'workloads': 13, 'rendered_images': sorted(images), 'namespace': ns}


def inventory(bundle):
    entries = []
    for path in sorted(bundle.rglob('*')):
        require(not path.is_symlink(), 'Output symlinks are not allowed')
        if path.is_file() and path != bundle / 'manifests/file-inventory.json':
            relative = path.relative_to(bundle).as_posix()
            require(not any(p in ('private', '.git', '__pycache__') for p in Path(relative).parts), 'Private/cache path in output')
            require(path.name not in ('auth.json', 'kubeconfig', 'console.sqlite3'), 'Private state in output')
            entries.append({'path': relative, 'bytes': path.stat().st_size, 'sha256': sha(path), 'category': relative.split('/')[0]})
    dump(bundle / 'manifests/file-inventory.json', {'schema_version': 1, 'files': entries})


def verify(bundle):
    inv = json.loads((bundle / 'manifests/file-inventory.json').read_text())
    listed = [r['path'] for r in inv['files']]
    require(len(listed) == len(set(listed)), 'Duplicate inventory paths')
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    require(actual == set(listed) | {'manifests/file-inventory.json'}, 'Unlisted/missing files in delivery')
    for row in inv['files']:
        p = bundle / safe_name(row['path'])
        require(p.resolve().is_relative_to(bundle), 'Inventory escapes bundle')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size == row['bytes'] and sha(p) == row['sha256'], 'Inventory mismatch: ' + row['path'])
    descriptor = json.loads((bundle / 'bundle.json').read_text())
    if descriptor.get('kind') == 'nico-materials':
        require(descriptor.get('recipe_ready') is False and not (bundle / 'deployment/deployment.json').exists(), 'Materials must not be directly deployable')
        print('BUNDLE_VERIFIED', len(inv['files']), 'files; site initialization required', flush=True)
        return
    manifest = json.loads((bundle / 'deployment/deployment.json').read_text())
    for name, digest in manifest['files'].items(): require(sha(bundle / 'deployment' / safe_name(name)) == digest, 'Recipe mismatch: ' + name)
    require(manifest['version'] == json.loads((bundle / 'bundle.json').read_text())['version'], 'Descriptor version mismatch')
    print('BUNDLE_VERIFIED', len(inv['files']), 'files', flush=True)


def load_plan(document, config):
    """The schema is an allow-list, not a directory scan."""
    generic = document.get('schema_version') == 3
    files = document['files']
    require(set(files) == {'inputs', 'generated', 'repository', 'toolkit', 'base_image_manifests'}, 'Invalid files sections')
    require(len(files['base_image_manifests']) == 23 and all(DIGEST.fullmatch(v) for v in files['base_image_manifests'].values()), 'Declare all 23 base image manifests')
    settings = {'ui_tag': config['ui']['tag'], 'bootstrap_tag': config['bootstrap']['tag']}
    files = substitute(files, settings)
    expected_roles = {
        'base_images': ('images/nico-amd64.oci.tar', 'images/nico-amd64.oci.tar'),
        'image_lock': ('manifests/images-lock.json', 'manifests/images-lock.json'),
        'nico_chart': ('charts/nico-0.1.1.tgz', 'deployment/charts/nico-0.1.1.tgz'),
        'cert_manager_chart': ('charts/cert-manager-v1.17.1.tgz', 'deployment/charts/cert-manager-v1.17.1.tgz'),
        'tool_helm': ('tools/helm', 'tools/helm'),
        'tool_cli': ('tools/nico-admin-cli', 'tools/nico-admin-cli'),
        'ui': ('ui.archive', 'images/pxeye-' + config['ui']['tag'] + '.oci.tar'),
        'bootstrap': ('bootstrap.archive', 'images/pxeye-' + config['bootstrap']['tag'] + '.oci.tar'),
    }
    seen_roles = set();targets = []
    for row in files['inputs']:
        require(set(row) == {'role', 'root', 'source', 'target', 'bytes', 'sha256'}, 'Invalid input file fields')
        require(isinstance(row['bytes'], int) and row['bytes'] > 0 and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'Invalid file size/hash')
        require(safe_name(row['target']) == row['target'] and '@{' not in row['target'], 'Invalid output path')
        targets.append(row['target'])
        if row['role'] == 'material':
            require(row['root'] == 'bundle' and row['source'] == row['target'] and safe_name(row['source']).split('/')[0] in ('boot', 'dpu', 'http', 'source'), 'Invalid material path')
        else:
            role = row['role'];require(role in expected_roles and role not in seen_roles, 'Unknown/duplicate input role: ' + role)
            seen_roles.add(role)
            require((row['source'], row['target']) == expected_roles[role], 'Unsupported input/output mapping: ' + role)
            require(row['root'] == (('package' if generic else 'site') if role in ('ui', 'bootstrap') else 'bundle'), 'Invalid source root')
    require(seen_roles == set(expected_roles), 'Missing mandatory input roles')
    for target in files['generated']:
        require(safe_name(target) == target and '@{' not in target, 'Invalid generated output')
        targets.append(target)
    require(len(targets) == len(set(targets)), 'Duplicate output files in configuration')
    mandatory = {'bundle.json', 'manifests/file-inventory.json', 'manifests/build-file-plan.json'}
    mandatory |= {'deployment-kit/configure.py', 'config/site-config.example.json', 'docs/CONFIGURE.zh-CN.md'} if generic else {'deployment/deployment.json', 'config/runtime.json', 'docs/INSTALL.md'}
    require(mandatory <= set(files['generated']), 'Missing mandatory generated files')
    for name in files['repository']:
        require(safe_name(name) == name and '*' not in name, 'List repository files individually')
    require(len(files['repository']) == len(set(files['repository'])), 'Duplicate repository inputs')
    toolkit = [
        {'source': 'offline-build/build.py', 'target': 'build.py'},
        {'source': 'offline-build/README.md', 'target': 'README.md'},
        {'source': 'offline-build/README.zh-CN.md', 'target': 'README.zh-CN.md'},
        {'source': 'offline-build/legacy-build-config.example.json', 'target': 'build-config.example.json'}]
    if generic:
        toolkit += [{'source': 'offline-build/' + name, 'target': name} for name in ('generic.py', 'configure.py', 'site-config.example.json', 'CONFIGURE.md', 'CONFIGURE.zh-CN.md')]
        for name in ('materials-lock.json', 'refresh-lock.py'):
            row = {'source': 'offline-build/' + name, 'target': name}
            if row in files['toolkit']:
                toolkit.append(row)
    require(files['toolkit'] == toolkit, 'Unsupported toolkit files')
    return files


def expand_configuration(document):
    """Keep user paths/options separate from the versioned machine-managed lock."""
    if document.get('schema_version') != 4:
        return document
    require(set(document) == {'schema_version', 'build', 'package', 'include'}, 'Schema 4 contains only build/package/include')
    require(set(document['package']) == {'bundle_id', 'ui_archive', 'bootstrap_archive'}, 'Invalid package fields')
    include = document['include']
    require(set(include) == {'dpu', 'history'} and all(type(v) is bool for v in include.values()), 'include.dpu/history must be booleans')
    lock = json.loads((BUILD_HOME / 'materials-lock.json').read_text())
    require(set(lock) == {'schema_version', 'profile', 'images', 'files'} and lock['schema_version'] == 1, 'Invalid materials lock')
    require(lock['profile'] == 'e703126e4-core-single-node' and set(lock['images']) == {'ui', 'bootstrap'}, 'Unsupported material profile')
    files = lock['files']
    def selected(row):
        if row['role'] != 'material':
            return True
        if row['source'].startswith('source/'):
            return include['history']
        if row['source'].startswith(('dpu/', 'http/nico/dpu/')):
            return include['dpu']
        return True
    files['inputs'] = [row for row in files['inputs'] if selected(row)]
    package = {'bundle_id': document['package']['bundle_id']}
    for purpose in ('ui', 'bootstrap'):
        require(set(lock['images'][purpose]) == {'tag', 'digest'}, 'Invalid locked image metadata')
        package[purpose] = {'archive': document['package'][purpose + '_archive'], **lock['images'][purpose]}
    return {'schema_version': 3, 'build': document['build'], 'package': package, 'files': files}


def print_plan(plan, config, source):
    for name, digest in plan['base_image_manifests'].items():
        print('contained-image\t' + name + '\t' + digest)
    for row in plan['inputs']:
        origin = str(Path(source) / row['source']) if row['root'] == 'bundle' else config[row['role']]['archive']
        action = 'patch+package' if row['role'] == 'nico_chart' else 'copy'
        print(action + '\t' + origin + '\t=> bundle/' + row['target'])
    for target in plan['generated']:
        print('generate\t=> bundle/' + target)
    total = sum(r['bytes'] for r in plan['inputs'])
    print('PLAN_COMPLETE', 'inputs=' + str(len(plan['inputs'])), 'generated=' + str(len(plan['generated'])),
          'bundle_files=' + str(len(plan['inputs']) + len(plan['generated'])), 'input_bytes=' + str(total))


def verify_declared_inputs(plan, config, source):
    print('VERIFY_DECLARED_INPUTS', flush=True)
    for row in plan['inputs']:
        path = source / row['source'] if row['root'] == 'bundle' else Path(config[row['role']]['archive'])
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes'], 'Input missing/size mismatch: ' + str(path))
        if row['root'] == 'bundle':require(path.resolve().is_relative_to(source), 'Input escapes source-bundle')
        if row['role'] in ('image_lock', 'ui', 'bootstrap'):
            require(sha(path) == row['sha256'], 'Input checksum mismatch: ' + str(path))
        if row['role'] == 'base_images':require(row['sha256'] == OCI_SHA, 'Unsupported base OCI lock')
        if row['role'] in ('nico_chart', 'cert_manager_chart'):require(row['sha256'] == RAW[Path(row['source']).name], 'Unsupported raw Chart lock')
    verify_repository_inputs(plan)


def verify_repository_inputs(plan):
    actual_resources = {p.relative_to(REPO).as_posix() for folder in (ASSETS, REPO / 'deploy/nico-platform', REPO / 'tools/offline-field') for p in folder.rglob('*') if p.is_file()}
    actual_resources |= {'deploy/bootstrap-kubernetes.yaml', 'deploy/nico-cluster-permissions.yaml', 'tools/import-oci-bundle.py'}
    if 'tools/offline-field/INSTALL.site.md.in' not in plan['repository']:
        actual_resources.discard('tools/offline-field/INSTALL.site.md.in')
    require(actual_resources == set(plan['repository']), 'Repository resources differ from declared file list')
    for name in plan['repository']:
        path = REPO / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(REPO), 'Repository input missing: ' + name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-bundle', type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--version')
    p.add_argument('--source-revision')
    p.add_argument('--helm', default=shutil.which('helm'))
    p.add_argument('--verify', type=Path)
    p.add_argument('--plan', action='store_true', help='List every input and output without reading large inputs or building')
    p.add_argument('--check-inputs', action='store_true', help='Check selected input sizes, required hashes and dependencies without building')
    p.add_argument('--write-config', type=Path, help='Create a new small configuration from path arguments')
    p.add_argument('--output-root', type=Path)
    p.add_argument('--ui-archive', type=Path)
    p.add_argument('--bootstrap-archive', type=Path)
    p.add_argument('--include-history', action='store_true')
    p.add_argument('--without-dpu', action='store_true')
    a = p.parse_args()
    if a.write_config:
        require(not a.write_config.exists(), 'Configuration already exists; choose a new path')
        require(all((a.source_bundle, a.output_root, a.ui_archive, a.bootstrap_archive)), 'Provide --source-bundle/--output-root/--ui-archive/--bootstrap-archive')
        template = BUILD_HOME / 'legacy-build-config.example.json'
        if not template.is_file():
            template = BUILD_HOME / 'build-config.example.json'  # Existing exported legacy kits.
        document = json.loads(template.read_text())
        require(document['schema_version'] == 4, 'Use the current small configuration template')
        document['build'] = {'source_bundle': str(a.source_bundle.resolve()), 'output_root': str(a.output_root.resolve())}
        document['package'].update(ui_archive=str(a.ui_archive.resolve()), bootstrap_archive=str(a.bootstrap_archive.resolve()))
        document['include'] = {'dpu': not a.without_dpu, 'history': a.include_history}
        dump(a.write_config, document)
        print('BUILD_CONFIG_CREATED', a.write_config)
        return
    if a.verify:
        verify(a.verify.resolve());return
    require(a.config, '--config is required')
    document = expand_configuration(json.loads(a.config.read_text()))
    if document.get('schema_version') == 3:
        from generic import build_generic
        build_generic(a, document)
        return
    print('LEGACY_SITE_BOUND_CONFIG: schema 3 builds reusable materials without site parameters.', flush=True)
    explicit = document.get('schema_version') == 2
    if explicit:
        require(set(document) == {'schema_version', 'build', 'site', 'files'}, 'Invalid build configuration fields')
        require(set(document['build']) == {'source_bundle', 'output_root'}, 'Invalid build paths')
        require(all(Path(document['build'][k]).is_absolute() for k in ('source_bundle', 'output_root')), 'Use absolute source_bundle and output_root paths')
        config = parse_config(a.config.resolve(), document['site'])
        a.source_bundle = a.source_bundle or Path(document['build']['source_bundle'])
        a.version = a.version or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        a.output = a.output or Path(document['build']['output_root']) / a.version
        plan = load_plan(document, config)
        if a.plan:
            verify_repository_inputs(plan)
            print_plan(plan, config, a.source_bundle)
            return
        payload = [{'path': r['source'], 'bytes': r['bytes'], 'sha256': r['sha256']} for r in plan['inputs'] if r['role'] == 'material']
        source_inventory = {'files': [{'path': r['source'], 'bytes': r['bytes'], 'sha256': r['sha256']} for r in plan['inputs'] if r['root'] == 'bundle']}
    else:
        require(not a.plan, '--plan requires the explicit schema_version=2 build configuration')
        print('LEGACY_CONFIG: use offline-build/legacy-build-config.example.json for an explicit file list', file=sys.stderr)
        config = parse_config(a.config.resolve());plan = None
        require(a.source_bundle, 'Legacy config requires --source-bundle')
        source_inventory = json.loads((a.source_bundle / 'manifests/file-inventory.json').read_text())
        payload = [row for row in source_inventory['files'] if safe_name(row['path']).split('/')[0] in ('boot', 'dpu', 'http', 'source')]
    if not a.source_revision:
        marker = BUILD_HOME / 'source-revision.txt'
        a.source_revision = marker.read_text().strip() if marker.is_file() else run(['git', '-C', str(REPO), 'rev-parse', 'HEAD']).strip()
    require(all((a.source_bundle, a.output, a.version, a.helm)), 'Build requires source-bundle/output/version/helm')
    require(re.fullmatch(r'[0-9a-f]{40}', a.source_revision), 'Use the full committed source revision')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', a.version), 'Invalid version')
    source = a.source_bundle.resolve();output = a.output.resolve()
    require(not output.exists() and not output.is_relative_to(source) and not source.is_relative_to(output), 'Output must be new and outside source-bundle')
    require(not REPO.is_relative_to(output) and not output.is_relative_to(REPO), 'Keep artifacts outside the source checkout')
    inputs = [source / 'images/nico-amd64.oci.tar', source / 'manifests/images-lock.json'] + [source / 'charts' / n for n in RAW] + [Path(config[k]['archive']) for k in ('ui', 'bootstrap')]
    require(all(x.is_file() and not x.is_symlink() for x in inputs), 'A required input file is absent or symlinked')
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / ('.' + output.name + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not output.exists(), 'Output already exists')
        size = sum(row['bytes'] for row in plan['inputs']) if plan else sum(x.stat().st_size for x in inputs) + sum(row['bytes'] for row in payload)
        require(shutil.disk_usage(output.parent).free > size * 2 + 2 * 1024**3, 'Insufficient space for independent copy, archive and safety margin')
        stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.building-', dir=output.parent))
        try:
            bundle = stage / 'bundle';bundle.mkdir()
            for folder in ('images', 'manifests', 'tools', 'docs', 'config'): (bundle / folder).mkdir()
            if plan:
                verify_declared_inputs(plan, config, source)
                dump(bundle / 'manifests/build-file-plan.json', {'inputs': plan['inputs'], 'generated': plan['generated'], 'base_image_manifests': plan['base_image_manifests'], 'source_revision': a.source_revision})
            print('VERIFY_INPUT_OCI', flush=True)
            require(sha(inputs[0]) == OCI_SHA, 'Unsupported/corrupt base image archive')
            records = json.loads(inputs[1].read_text());require(len(records) == 23 and len({r['image'] for r in records}) == 23, 'Expected 23 unique locked images')
            if plan:
                require({r['image']: r['amd64_manifest'] for r in records} == plan['base_image_manifests'], 'Base images differ from configured list')
            base_images = oci_check(inputs[0], records)
            shutil.copyfile(inputs[0], bundle / 'images/nico-amd64.oci.tar')
            shutil.copyfile(inputs[1], bundle / 'manifests/images-lock.json')
            extra = []
            for purpose in ('ui', 'bootstrap'):
                c = config[purpose];image = oci_check(Path(c['archive']), reference=c['source_image'])[0]
                require(image['digest'] == c['digest'], purpose + ' manifest does not match expected digest')
                target = config['registry'] + '/nico/pxeye:' + c['tag']
                filename = 'images/pxeye-' + c['tag'] + '.oci.tar'
                shutil.copyfile(c['archive'], bundle / filename)
                extra.append({'image': target, 'source_image': c['source_image'], 'digest': image['digest'], 'archive': filename, 'purpose': purpose})
            dump(bundle / 'manifests/deployment-images-lock.json', extra)
            print('COPY_VERIFIED_MATERIALS', len(payload), flush=True)
            for row in payload:
                original = source / row['path']
                require(original.resolve().is_relative_to(source) and not original.is_symlink() and original.is_file(), 'Invalid source payload path')
                require(original.stat().st_size == row['bytes'] and sha(original) == row['sha256'], 'Source material checksum mismatch: ' + row['path'])
                target = bundle / row['path'];target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
            dump(bundle / 'manifests/materials-input-lock.json', payload)
            settings = {'namespace': config['namespace'], 'release_prefix': config['release_prefix'], 'site_name': config['site_name'], 'version': a.version,
                'dns_ip': config['service_ips']['dns'], 'ntp_ip': config['service_ips']['ntp'], 'pxe_ip': config['service_ips']['pxe'], 'bootstrap_image': extra[1]['image']}
            with tempfile.TemporaryDirectory(dir=stage) as temporary:
                scratch = Path(temporary)
                manifest = prepare_recipe(bundle, config, a.version, settings, scratch, source)
                prepare_bootstrap(bundle, config, settings, extra[0])
                for tool in ('helm', 'nico-admin-cli'):
                    original = source / 'tools' / tool;require(original.is_file(), 'Missing tool: ' + tool)
                    row = next((r for r in source_inventory['files'] if r['path'] == 'tools/' + tool), None)
                    require(row and not original.is_symlink() and sha(original) == row['sha256'], 'Tool checksum mismatch: ' + tool)
                    shutil.copy2(original, bundle / 'tools' / tool)
                shutil.copyfile(REPO / 'tools/import-oci-bundle.py', bundle / 'tools/import-oci-bundle.py')
                for name in ('deployment-client', 'verify-core'):
                    text = (REPO / 'tools/offline-field' / (name + '.py.in')).read_text()
                    for key, val in {'BUNDLE_ID': config['bundle_id'], 'VERSION': a.version, 'RELEASE': config['release_prefix'], 'NAMESPACE': config['namespace'], 'SITE_NAME': repr(config['site_name'])}.items(): text = text.replace('@@' + key + '@@', val)
                    ast.parse(text);write(bundle / 'tools' / (name + '.py'), text)
                shutil.copyfile(REPO / 'tools/offline-field/verify-bundle.py', bundle / 'tools/verify-bundle.py')
                shutil.copyfile(REPO / 'tools/offline-field/import-pxeye-images.py', bundle / 'tools/import-pxeye-images.py')
                shutil.copyfile(REPO / 'tools/offline-field/prepare-auth.py', bundle / 'tools/prepare-auth.py')
                locked = {config['registry'] + '/' + config['repository_prefix'] + '/' + r['image'] for r in records} | {r['image'] for r in extra}
                report = validate_render(bundle, manifest, config, a.helm, scratch, locked)
            report.update({'source_revision': a.source_revision, 'base_archive_sha256': OCI_SHA, 'base_images': base_images,
                'extra_images': extra, 'profile': 'e703126e4-core-single-node', 'cold_install_tested': False,
                'source_assets': {name: sha(REPO / name) for name in plan['repository']} if plan else {p.relative_to(REPO).as_posix(): sha(p) for directory in (ASSETS, REPO / 'deploy/nico-platform', REPO / 'tools/offline-field') for p in sorted(directory.rglob('*')) if p.is_file()}, 'builder_sha256': sha(Path(__file__)), 'build_configuration_sha256': sha(a.config)})
            dump(bundle / 'manifests/build-report.json', report)
            dump(bundle / 'bundle.json', {'schema_version': 1, 'id': config['bundle_id'], 'name': 'NICo Core single-node offline delivery',
                'version': a.version, 'architecture': 'linux/amd64', 'recipe_directory': 'deployment', 'image_archive': 'images/nico-amd64.oci.tar', 'image_lock': 'manifests/images-lock.json', 'recipe_ready': True})
            install_docs(bundle, config, a.version)
            inventory(bundle)
            if plan:
                expected = {r['target'] for r in plan['inputs']} | set(plan['generated'])
                actual = {f.relative_to(bundle).as_posix() for f in bundle.rglob('*') if f.is_file()}
                require(actual == expected, 'Output differs from config: missing=' + str(sorted(expected - actual)) + '; extra=' + str(sorted(actual - expected)))
            verify(bundle)
            print('ARCHIVE', flush=True)
            archive = stage / 'bundle.tar.gz';pack_tree(bundle, archive, config['bundle_id'])
            print('HASH_ARCHIVE', flush=True)
            archive_digest = sha(archive)
            print('VERIFY_ARCHIVE_CONTENTS', flush=True)
            # Read back the packed bytes and compare every regular member to the
            # complete inventory, including the inventory file itself.
            packed = {r['path']: r for r in json.loads((bundle / 'manifests/file-inventory.json').read_text())['files']}
            packed['manifests/file-inventory.json'] = {'sha256': sha(bundle / 'manifests/file-inventory.json'), 'bytes': (bundle / 'manifests/file-inventory.json').stat().st_size}
            seen = set()
            with tarfile.open(archive, 'r|gz') as tar:
                for member in tar:
                    if member.isdir(): continue
                    name = safe_name(member.name)
                    require(member.isfile() and name.startswith(config['bundle_id'] + '/'), 'Unexpected archive member')
                    relative = name[len(config['bundle_id']) + 1:]
                    require(relative in packed and relative not in seen and member.size == packed[relative]['bytes'], 'Archive inventory mismatch: ' + relative)
                    seen.add(relative);h = hashlib.sha256()
                    with tar.extractfile(member) as stream:
                        for block in iter(lambda: stream.read(8 * 1024**2), b''): h.update(block)
                    require(h.hexdigest() == packed[relative]['sha256'], 'Archive payload mismatch: ' + relative)
            require(seen == set(packed), 'Archive is missing files')
            write(stage / 'SHA256SUMS', archive_digest + '  bundle.tar.gz\n')
            dump(stage / 'build-result.json', {'bundle_id': config['bundle_id'], 'version': a.version, 'source_revision': a.source_revision,
                'archive_sha256': archive_digest, 'archive_bytes': archive.stat().st_size, 'workloads': report['workloads'], 'image_count': 23 + len(extra)})
            stage.rename(output)
            print('BUILD_COMPLETE', str(output), flush=True)
        except BaseException:
            print('BUILD_FAILED; staging retained at ' + str(stage), file=sys.stderr)
            raise


def install_docs(bundle, config, version):
    text = (REPO / 'tools/offline-field/INSTALL.md.in').read_text()
    params = {'BUNDLE_ID': config['bundle_id'], 'VERSION': version, 'NAMESPACE': config['namespace'],
        'RELEASE': config['release_prefix'], 'PXEYE': config['namespace'] + '-pxeye', 'REGISTRY': config['registry'],
        'REPO_PREFIX': config['repository_prefix'], 'CONTEXT': config['context'], 'NODE': config['kind_node'], 'HOST_PATH': config['bundle_host_path'], 'NODE_PORT': str(config['node_port'])}
    for key, val in params.items(): text = text.replace('@@' + key + '@@', val)
    require('@@' not in text, 'Unresolved installation documentation token')
    write(bundle / 'docs/INSTALL.md', text)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from None
