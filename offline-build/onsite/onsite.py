#!/usr/bin/env python3
"""Import a verified relok8s delivery and prepare/install its frozen Helm recipe."""
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
import yaml
from registry_bridge import RegistryBridge
from relocation import prepare_intermediate, restore_root_fields

HOME = Path(__file__).resolve().parent
VERIFY_PATH = HOME.parent / 'helm-bundle/verify.py'
if not VERIFY_PATH.is_file():
    VERIFY_PATH = HOME.parent / 'verify.py'  # installed at bundle/tools/onsite
spec = importlib.util.spec_from_file_location('helm_delivery_verify', VERIFY_PATH)
verifier = importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
TOKEN = re.compile(r'@\{([a-z_]+)\}')
NAME = re.compile(r'[a-z][a-z0-9-]{0,47}[a-z0-9]|[a-z]')
PXEYE_ONLY_COMPONENTS = {
    'pxeye': {'enabled': True},
    'certManager': {'enabled': False},
    'platform': {'enabled': False},
    'vaultBootstrap': {'enabled': False},
    'core': {'enabled': False},
    'materials': {'enabled': False},
}
NAMESPACE = 'nico-system'
RELEASE = 'nico'
PXEYE_NODE_PORT = 31808


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def safe_extract(archive, target, *, limit=None):
    """Regular files/directories only; no links, duplicate files or traversal."""
    target = Path(target); target.mkdir(parents=True, exist_ok=True)
    seen, size = set(), 0
    with tarfile.open(archive, 'r:*') as tar:
        for member in tar:
            path = Path(member.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.name,
                    'Unsafe archive path')
            require(member.isfile() or member.isdir(), 'Archive links/special files are unsupported')
            name = path.as_posix()
            require(name not in seen, 'Duplicate archive member: ' + name); seen.add(name)
            size += member.size
            require(limit is None or size <= limit, 'Archive expansion exceeds available space or configured limit')
            destination = target / path
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, destination.open('xb') as output:
                    shutil.copyfileobj(source, output, 8 * 1024**2)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)


def archive_identity(archive):
    info = Path(archive).stat()
    return {'name': Path(archive).name, 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns}


def unpack(args):
    archive, output = args.archive.resolve(), args.output.resolve()
    require(archive.is_file() and not archive.is_symlink(), 'Archive is missing or unsafe: ' + str(archive))
    require(not output.exists(), 'Unpack output exists; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    budget = shutil.disk_usage(output.parent).free - 1024**3
    require(budget > archive.stat().st_size, 'Insufficient space to unpack')
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '.unpacking-', dir=output.parent))
    try:
        safe_extract(archive, temporary, limit=budget)
        descriptors = list(temporary.glob('*/bundle.json'))
        require(len(descriptors) == 1, 'Expected one bundle root')
        bundle = descriptors[0].parent
        require(set(temporary.iterdir()) == {bundle}, 'Unexpected extra archive roots')
        require(json.loads(descriptors[0].read_text()).get('kind') == 'pxeye-nico-helm', 'Wrong bundle format')
        verifier.verify(bundle)
        write_json(temporary / 'unpack-result.json', {'archive': archive_identity(archive), 'root': bundle.name})
        temporary.rename(output)
        print('UNPACK_COMPLETE', output / bundle.name)
    except BaseException:
        print('UNPACK_FAILED; evidence retained at', temporary, file=sys.stderr)
        raise


def merge(base, updates):
    result = copy.deepcopy(base)
    for key, value in updates.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def substitute(item, values):
    if isinstance(item, str):
        return TOKEN.sub(lambda match: str(values.get(match[1], match[0])), item)
    if isinstance(item, dict):
        return {key: substitute(value, values) for key, value in item.items()}
    if isinstance(item, list):
        return [substitute(value, values) for value in item]
    return item


def pack(root, output):
    with tarfile.open(output, 'w:gz') as tar:
        tar.add(root, arcname=root.name, recursive=True)


def expand_dependencies(root):
    """Normalize vendored subcharts so transport URLs can be rewritten recursively."""
    folder = root / 'charts'
    if not folder.is_dir(): return
    for archive in list(folder.glob('*.tgz')):
        temporary = Path(tempfile.mkdtemp(prefix='.expand-', dir=root))
        safe_extract(archive, temporary, limit=256 * 1024**2)
        candidates = list(temporary.glob('*/Chart.yaml'))
        require(len(candidates) == 1, 'Invalid vendored subchart archive')
        child = candidates[0].parent
        destination = folder / child.name
        require(not destination.exists(), 'Duplicate vendored subchart')
        child.rename(destination); shutil.rmtree(temporary); archive.unlink()
    for child in folder.iterdir():
        if child.is_dir() and (child / 'Chart.yaml').is_file(): expand_dependencies(child)


def restore_conditions(original, relocated):
    # relok8s 0.5.4 strips dependency metadata. Keep condition/tags/aliases so
    # disabled upstream components do not accidentally become enabled.
    for path in original.rglob('Chart.yaml'):
        target = relocated / path.relative_to(original)
        require(target.is_file(), 'Relocation lost a vendored Chart')
        source = yaml.safe_load(path.read_text()); output = yaml.safe_load(target.read_text())
        if 'dependencies' in source: output['dependencies'] = source['dependencies']
        target.write_text(yaml.safe_dump(output, sort_keys=False))


class Onsite:
    def __init__(self, path):
        self.config_path = Path(path).resolve()
        self.config = json.loads(self.config_path.read_text())
        c = self.config
        require(c.get('schema_version') == 3, 'Unsupported onsite config schema')
        for key in ('context', 'namespace', 'site_name', 'bundle', 'work_directory'):
            require(c.get(key), 'Missing site configuration: ' + key)
        require(NAME.fullmatch(c['namespace']), 'Invalid namespace')
        require(c['namespace'] == NAMESPACE,
                'This installer always creates nico-system with the nico parent release')
        legacy = {'mode', 'release_prefix', 'pxeye_release', 'cert_manager', 'service_ips', 'host_network',
                  'data_backup_directory', 'storage_class', 'pxeye_values', 'phase_values'}
        require(not legacy.intersection(c), 'Legacy site configuration is not accepted by the one-command installer')
        self.bundle, self.work = Path(c['bundle']).resolve(), Path(c['work_directory']).resolve()
        require(not self.work.is_relative_to(self.bundle) and not self.bundle.is_relative_to(self.work), 'Work directory must be outside bundle')
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.private = self.work / 'private'; self.private.mkdir(exist_ok=True, mode=0o700); self.private.chmod(0o700)
        self.lock = (self.work / '.lock').open('a'); fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_id = hashlib.sha256((c['context'] + '/' + c['namespace'] + '/' + RELEASE).encode()).hexdigest()[:24]
        self.site_lock = (Path(tempfile.gettempdir()) / ('pxeye-onsite-' + lock_id + '.lock')).open('a')
        fcntl.flock(self.site_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.descriptor = json.loads((self.bundle / 'bundle.json').read_text())
        require(self.descriptor.get('architecture') == 'linux/amd64', 'Only amd64 control-plane bundles are supported')
        require(self.descriptor.get('kind') == 'pxeye-nico-helm', 'Use the Helm/relok8s delivery, not a legacy OCI bundle')
        require(self.descriptor.get('initial_provisioning_network_state') == 'unconfigured',
                'This delivery predates the control-plane-only installer; rebuild the offline bundle with the current source')
        registry = c.get('registry', {})
        up = urlsplit(registry.get('url') or '')
        require(up.scheme in ('http', 'https') and up.hostname and not up.username and not up.password and not up.path and not up.query and not up.fragment,
                'Registry URL must be http(s)://host[:port], without trailing slash or credentials')
        self.registry = up.netloc
        for key in ('ca_file', 'docker_config_directory'):
            if registry.get(key):
                require(Path(registry[key]).is_absolute() and Path(registry[key]).exists(), 'Missing absolute registry path: ' + key)
        prefix = registry.get('repository_prefix', 'nico-offline')
        require(re.fullmatch(r'[a-z0-9]+(?:[._/-][a-z0-9]+)*', prefix), 'Invalid Registry repository prefix')
        identity = hashlib.sha256((self.bundle / 'manifests/file-inventory.json').read_bytes()).hexdigest()
        self.scope = prefix + '/bundle-' + identity[:20]
        self.helm = str(self.bundle / 'tools/helm'); self.relok = str(self.bundle / 'tools/relok8s')
        self.env = dict(os.environ)
        if registry.get('docker_config_directory'):
            self.env['DOCKER_CONFIG'] = registry['docker_config_directory']
            self.env['HELM_REGISTRY_CONFIG'] = str(Path(registry['docker_config_directory']) / 'config.json')
        if registry.get('ca_file'):
            self.env['SSL_CERT_FILE'] = registry['ca_file']
        identity_config = copy.deepcopy(c)
        identity_config['implementation_sha256'] = {name: sha(HOME / name) for name in ('onsite.py', 'registry_bridge.py', 'relocation.py')}
        fingerprint = hashlib.sha256(json.dumps(identity_config, sort_keys=True).encode()).hexdigest()
        self.state_path = self.work / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'config_sha256': fingerprint, 'bundle_inventory_sha256': identity, 'steps': {}}
        require(self.state['config_sha256'] == fingerprint and self.state['bundle_inventory_sha256'] == identity,
                'Config/bundle changed; use a new work_directory')
        self.cert_manager_mode = self.state.get('cert_manager_mode')
        require(self.cert_manager_mode in (None, 'install', 'reuse'), 'Invalid saved cert-manager decision')
        self.save()

    def save(self):
        write_json(self.state_path, self.state)

    def run(self, args, label, *, check=True, env=None, private=False, timeout=3600):
        label = re.sub(r'[^A-Za-z0-9._-]', '_', label)
        directory = self.private if private else self.work / 'logs'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        start = time.monotonic()
        print(datetime.now(timezone.utc).isoformat(), 'RUN', shlex.join(list(map(str, args))), flush=True)
        try:
            result = subprocess.run(list(map(str, args)), env=env or self.env, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def text(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
            result = subprocess.CompletedProcess(args, 124, text(error.stdout), text(error.stderr) + '\nCommand timed out')
        log = directory / (label + '.log')
        with log.open('a') as stream:
            stream.write('\nATTEMPT ' + datetime.now(timezone.utc).isoformat() + '\n' + result.stdout + '\nSTDERR:\n' + result.stderr + '\nEXIT_CODE=' + str(result.returncode) + '\n')
        log.chmod(0o600)
        with (self.work / 'timings.jsonl').open('a') as stream:
            stream.write(json.dumps({'step': label, 'seconds': round(time.monotonic() - start, 3), 'exit_code': result.returncode}) + '\n')
        require(not check or result.returncode == 0, f'{label} failed (exit {result.returncode}); see {log}')
        return result

    def kubectl(self, args, label, **kwargs):
        return self.run(['kubectl', '--context', self.config['context']] + args, label, **kwargs)

    def helm_run(self, args, label, **kwargs):
        return self.run([self.helm, '--kube-context', self.config['context']] + args, label, **kwargs)

    def tls_flags(self):
        registry = self.config['registry']; result = []
        if registry['url'].startswith('http://'):
            result.append('--plain-http')
        if registry.get('skip_tls_verify'):
            result.append('--insecure-skip-tls-verify')
        if registry.get('ca_file'):
            result += ['--ca-file', registry['ca_file']]
        return result

    def cert_manager_inventory(self):
        """Return the complete, cluster-scoped cert-manager health picture."""
        crd_names = ('certificates.cert-manager.io', 'issuers.cert-manager.io', 'clusterissuers.cert-manager.io')
        crds = {}
        for name in crd_names:
            result = self.kubectl(['get', 'crd', name, '--ignore-not-found', '-o', 'json'],
                                  'cert-manager-crd-' + name, private=True)
            if not result.stdout.strip():
                crds[name] = {'present': False, 'healthy': False}
                continue
            row = json.loads(result.stdout)
            conditions = {item.get('type'): item.get('status') for item in (row.get('status') or {}).get('conditions', [])}
            crds[name] = {
                'present': True,
                'healthy': conditions.get('Established') == 'True' and conditions.get('NamesAccepted') == 'True',
            }
        required = ('cert-manager-controller', 'cert-manager-webhook', 'cert-manager-cainjector')
        components = {name: {'present': False, 'healthy': False, 'deployments': []} for name in required}
        deployments = json.loads(self.kubectl(['get', 'deployments', '-A', '-o', 'json'],
                                              'cert-manager-deployments', private=True).stdout)
        for deployment in deployments.get('items', []):
            metadata, spec, status = (deployment.get('metadata') or {}, deployment.get('spec') or {}, deployment.get('status') or {})
            name = str(metadata.get('name') or '')
            containers = ((spec.get('template') or {}).get('spec') or {}).get('containers') or []
            text = ' '.join([name] + [str(container.get('image') or '') for container in containers])
            desired = int(spec.get('replicas') if spec.get('replicas') is not None else 1)
            generation = metadata.get('generation')
            current = status.get('observedGeneration') == generation
            ready = int(status.get('readyReplicas') or 0)
            available = int(status.get('availableReplicas') or 0)
            healthy = current and desired >= 1 and ready >= desired and available >= desired
            for component in required:
                if component not in text:
                    continue
                row = components[component]
                row['present'] = True
                row['healthy'] = row['healthy'] or healthy
                row['deployments'].append({
                    'namespace': metadata.get('namespace'), 'name': name, 'desired': desired,
                    'ready': ready, 'available': available, 'current': current,
                })
        return {'crds': crds, 'components': components}

    def resolve_cert_manager_mode(self):
        inventory = self.cert_manager_inventory()
        crds = inventory['crds'].values()
        components = inventory['components'].values()
        absent = not any(item['present'] for item in crds) and not any(item['present'] for item in components)
        healthy = all(item['healthy'] for item in crds) and all(item['healthy'] for item in components)
        if absent:
            detected = 'install'
        elif healthy:
            detected = 'reuse'
        else:
            raise ValueError('cert-manager is partially installed or not healthy; resolve it before installation: ' +
                             json.dumps(inventory, sort_keys=True))
        saved = self.state.get('cert_manager_mode')
        if saved:
            if saved == 'reuse':
                require(detected == 'reuse', 'Previously reused cert-manager is no longer healthy; stop and inspect it')
            else:
                require(detected == 'install' or self.state['steps'].get('installed-cert-manager'),
                        'cert-manager appeared after this installation chose to install it; stop rather than adopting it')
            self.cert_manager_mode = saved
            print('REUSE_CERT_MANAGER_DECISION', saved, flush=True)
            return
        self.cert_manager_mode = detected
        self.state['cert_manager_mode'] = detected
        self.save()
        print(('REUSE_SHARED_CERT_MANAGER' if detected == 'reuse' else 'INSTALL_BUNDLED_CERT_MANAGER'), flush=True)

    def check_pxeye_node_port(self, release, values):
        """Fail before Helm writes when a standalone PXEye NodePort is occupied."""
        service = values.get('service', {})
        require(isinstance(service, dict), 'Generated PXEye Service settings must contain an object')
        if service.get('type', 'NodePort') != 'NodePort':
            return
        port = service.get('nodePort', PXEYE_NODE_PORT)
        require(type(port) is int and 1 <= port <= 65535,
                'Generated PXEye NodePort must be an integer from 1 to 65535')
        rows = json.loads(self.kubectl(['get', 'services', '-A', '-o', 'json'], 'pxeye-nodeport-check',
                                       private=True).stdout)
        for item in rows.get('items', []):
            metadata = item.get('metadata') or {}
            for endpoint in (item.get('spec') or {}).get('ports') or []:
                if endpoint.get('nodePort') != port:
                    continue
                if metadata.get('namespace') == self.config['namespace'] and metadata.get('name') == release:
                    continue
                raise ValueError('PXEye NodePort ' + str(port) + ' is already used by ' +
                                 str(metadata.get('namespace')) + '/' + str(metadata.get('name')) +
                                 '; the one-command installer reserves NodePort 31808, so release that Service or use a clean target cluster')
        # This only proves Kubernetes has not assigned the NodePort to another
        # Service.  It does not prove a containerized node publishes that port
        # to its host or any external network.
        print('PXEYE_NODEPORT_UNALLOCATED_IN_CLUSTER', port, flush=True)

    def preflight(self):
        # Avoid rereading every GiB for each phase when the verified input tree is unchanged.
        stamps = {}
        for path in self.bundle.rglob('*'):
            require(not path.is_symlink(), 'Bundle now contains a symlink')
            if path.is_file():
                info = path.stat()
                stamps[str(path.relative_to(self.bundle))] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev]
        if self.state.get('verified_file_stats') != stamps:
            verifier.verify(self.bundle)
            self.state['verified_file_stats'] = stamps; self.save()
        else:
            print('REUSE_INPUT_VERIFICATION; input file metadata unchanged', flush=True)
        nodes = json.loads(self.kubectl(['get', 'nodes', '-o', 'json'], 'nodes').stdout)
        require(any(node['status']['nodeInfo']['architecture'] == 'amd64' and
                    any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']) for node in nodes['items']),
                'An amd64 Ready node is required')
        endpoint = self.kubectl(['config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}'], 'cluster-endpoint').stdout
        old = self.state.get('cluster_endpoint')
        require(not old or old == endpoint, 'Context now points at another API server')
        self.state['cluster_endpoint'] = endpoint; self.save()
        self.helm_run(['version', '--short'], 'helm-version')
        self.run([self.relok, 'version'], 'relok8s-version')
        # relok8s accesses the target through a loopback bridge and otherwise
        # reports upstream TLS failures as a generic local 502.  Check the
        # configured Registry directly before any import work begins.
        RegistryBridge(self.config['registry'], self.private / 'registry-preflight').probe_upstream()
        print('REGISTRY_V2_OK', self.registry, flush=True)
        releases = json.loads(self.helm_run(
            ['list', '--all', '-n', self.config['namespace'], '-o', 'json'],
            'namespace-release-layout', private=True).stdout)
        allowed = set()
        bootstrap = self.state['steps'].get('bootstrapped-pxeye')
        if isinstance(bootstrap, dict) and isinstance(bootstrap.get('release'), str):
            allowed.add(bootstrap['release'])
        bootstrap_intent = self.state.get('pxeye_install_intent')
        if isinstance(bootstrap_intent, dict) and isinstance(bootstrap_intent.get('release'), str):
            allowed.add(bootstrap_intent['release'])
        if self.state.get('install_intents') or any(key.startswith('installed-') for key in self.state['steps']):
            allowed.add(self.release('core'))
        unexpected = sorted(item.get('name') for item in releases
                            if isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'] not in allowed)
        require(not unexpected,
                'Fresh installation requires an empty nico-system namespace or only releases created by this run; unexpected: ' +
                ', '.join(unexpected))
        self.resolve_cert_manager_mode()
        self.check_namespace_resources(allowed)
        print('PREFLIGHT_OK', self.config['context'], self.config['namespace'])

    def import_bundle(self):
        self.preflight()
        # Never leave a previously ready catalog visible while updating inputs.
        catalog_path = self.work / 'catalog.json'
        entries = []
        with RegistryBridge(self.config['registry'], self.private / 'relok-auth') as bridge:
            env = self.env | {'DOCKER_CONFIG': str(bridge.private)}
            for item in self.descriptor['charts']:
                key = item['id']; require(NAME.fullmatch(key), 'Invalid chart id')
                record = self.state['steps'].get('import-' + key)
                if record:
                    chart = self.work / record['local_chart']
                    require(chart.is_file() and sha(chart) == record['sha256'], 'Cached relocated Chart changed: ' + key)
                    self.pull_chart(record, self.work / 'verified-oci' / key)
                    entries.append(record); print('REUSE_CHART', key, flush=True); continue
                target = self.work / 'relocation' / key; target.mkdir(parents=True, exist_ok=True)
                relocation = self.bundle / item['relocation']
                require(relocation.resolve().is_relative_to(self.bundle), 'Unsafe relocation path')
                attempt = Path(tempfile.mkdtemp(prefix='attempt-', dir=target))
                relocation = prepare_intermediate(relocation, attempt / 'compatible.tar')
                self.run([self.relok, 'chart', 'move', relocation, '--registry', bridge.address,
                          '--repo-prefix', self.scope + '/images', '--out', str(attempt / '*.tgz'), '--yes'],
                         key + '-relocate', env=env, timeout=14400)
                files = list(attempt.glob('*.tgz')); require(len(files) == 1, 'Relok8s did not produce exactly one Chart')
                tree = attempt / 'tree'; safe_extract(files[0], tree, limit=256 * 1024**2)
                roots = list(tree.glob('*/Chart.yaml')); require(len(roots) == 1, 'Relocated Chart root is ambiguous')
                root = roots[0].parent
                restore_root_fields(root)
                expand_dependencies(root)
                original_tree = attempt / 'original'
                safe_extract(self.bundle / item['chart'], original_tree, limit=256 * 1024**2)
                original_roots = list(original_tree.glob('*/Chart.yaml'))
                require(len(original_roots) == 1, 'Original Chart root is ambiguous')
                original = original_roots[0].parent
                expand_dependencies(original)
                restore_conditions(original, root)
                # The bridge is only a transport endpoint, never a deployment endpoint.
                for path in root.rglob('*'):
                    if path.is_file() and path.suffix in ('.yaml', '.yml', '.tpl', '.txt', '.json'):
                        path.write_text(path.read_text().replace(bridge.address, self.registry))
                chart = target / 'chart.tgz'; pack(root, chart)
                digest = sha(chart)
                metadata = yaml.safe_load((root / 'Chart.yaml').read_text())
                # Content-addressed repository prevents tag replacement across retries or versions.
                repository = self.registry + '/' + self.scope + '/charts/' + digest
                pushed = self.helm_run(['push', str(chart), 'oci://' + repository] + self.tls_flags(), key + '-chart-push')
                match = re.findall(r'Digest:\s*(sha256:[0-9a-f]{64})', pushed.stdout + pushed.stderr)
                require(len(set(match)) == 1, 'Helm push did not report one OCI digest')
                record = {'id': key, 'name': metadata['name'], 'version': str(metadata['version']),
                          'oci': 'oci://' + repository + '/' + metadata['name'], 'oci_digest': match[0],
                          'sha256': digest, 'local_chart': str(chart.relative_to(self.work))}
                self.pull_chart(record, self.work / 'verified-oci' / key)
                self.state['steps']['import-' + key] = record; self.save(); entries.append(record)
        catalog = {'schema_version': 1, 'kind': 'pxeye-nico-onsite', 'ready': True,
                   'bundle_id': self.descriptor['id'], 'bundle_version': self.descriptor['version'],
                   'bundle_inventory_sha256': self.state['bundle_inventory_sha256'],
                   'registry': self.registry, 'charts': entries}
        catalog = self.refresh_catalog_images(catalog)
        print('IMPORT_COMPLETE', catalog_path)

    def refresh_catalog_images(self, catalog):
        """Use relok8s' canonical manifest digests, retaining source-lock provenance."""
        rows = json.loads((self.bundle / 'manifests/images-lock.json').read_text())
        logs = []
        for chart in catalog['charts']:
            require(self.state['steps'].get('import-' + chart['id']), 'Missing completed Chart transfer')
            logs.extend((self.work / 'logs' / (chart['id'] + '-relocate.log')).read_text().splitlines())
        images = []
        for row in rows:
            source = row['build_reference']
            marker = ':' + source + ') => '
            digests = set()
            name = source.rsplit('/', 1)[-1]
            repository = name.rsplit(':', 1)[0]
            for line in logs:
                if marker not in line:
                    continue
                match = re.match(r'(\S+) \((sha256:[0-9a-f]{64})\)', line.split(marker, 1)[1])
                require(match, 'Unrecognized relok8s transfer evidence for ' + source)
                reference, digest = match.groups()
                path = reference.partition('/')[2]
                require(path in (self.scope + '/images/' + name, self.scope + '/images/' + repository + '@' + digest),
                        'Unexpected relocated image path for ' + source)
                digests.add(digest)
            require(len(digests) == 1, 'Missing or conflicting relok8s transfer digests for ' + source)
            images.append({'source': row.get('source', source),
                           'image': self.registry + '/' + self.scope + '/images/' + name,
                           'source_digest': row['digest'], 'digest': next(iter(digests)),
                           'kind': row['kind'], 'verification': 'relok8s-canonicalized-transfer'})
        if catalog.get('images') != images:
            print('REFRESH_IMAGE_DIGESTS', len(images), '; original source digests retained', flush=True)
        catalog['images'] = images
        write_json(self.work / 'catalog.json', catalog)
        return catalog

    def pull_chart(self, record, directory):
        directory.mkdir(parents=True, exist_ok=True)
        attempt = Path(tempfile.mkdtemp(prefix='pull-', dir=directory))
        result = self.helm_run(['pull', record['oci'], '--version', record['version'], '--destination', str(attempt)] + self.tls_flags(),
                               record['id'] + '-chart-pull')
        digests = re.findall(r'Digest:\s*(sha256:[0-9a-f]{64})', result.stdout + result.stderr)
        require(record['oci_digest'] in digests, 'OCI Chart digest changed')
        files = list(attempt.glob('*.tgz'))
        require(len(files) == 1 and sha(files[0]) == record['sha256'], 'Pulled Chart archive checksum mismatch')
        return files[0]

    def release(self, phase):
        return RELEASE + {'core': '', 'pxeye': '-pxeye', 'materials': '-materials'}.get(phase, '-' + phase)

    def imported_defaults(self, defaults, catalog):
        """Resolve image fields relok8s missed through exact input-lock identities."""
        rows = json.loads((self.bundle / 'manifests/images-lock.json').read_text())
        transferred = {row['source']: row for row in catalog['images']}
        locked = {}
        for row in rows:
            target = transferred[row.get('source', row['build_reference'])]
            locked[row['build_reference']] = target

        def walk(value):
            if isinstance(value, dict):
                value = {key: walk(item) for key, item in value.items()}
                repository, tag = value.get('repository'), value.get('tag')
                target = locked.get(repository + ':' + str(tag)) if isinstance(repository, str) else None
                if target:
                    tagged = target['image'].split('@')[0]
                    value['repository'] = tagged.rsplit(':', 1)[0]
                    value['tag'] = tagged.rsplit(':', 1)[1]
                    value['digest'] = target['digest']
                    if 'registry' in value: value['registry'] = ''
                return value
            if isinstance(value, list): return [walk(item) for item in value]
            if isinstance(value, str) and value in locked:
                target = locked[value]
                repository = target['image'].rsplit(':', 1)[0]
                return repository + '@' + target['digest']
            return value
        return walk(defaults)

    def image_defaults(self, defaults, values):
        """Replace every locked image field with its relocated image identity."""
        # Legacy releases used arrays for boot artifacts; the offline Chart
        # uses index-keyed maps so relok8s can relocate each image.
        if (isinstance(defaults, dict) and defaults and isinstance(values, list)
                and all(isinstance(key, str) and key.isdecimal() for key in defaults)):
            values = {str(index): value for index, value in enumerate(values)}
        if isinstance(defaults, dict) and isinstance(values, dict):
            if isinstance(defaults.get('repository'), str) and defaults['repository'].startswith(self.registry + '/'):
                for key in ('repository', 'tag', 'digest', 'registry'):
                    values.pop(key, None)
                    if key in defaults: values[key] = defaults[key]
            for key, value in defaults.items():
                values[key] = self.image_defaults(value, values.get(key, value))
        elif isinstance(defaults, str) and defaults.startswith(self.registry + '/'):
            return defaults
        elif isinstance(defaults, list):
            # Image-bearing bootArtifactContainers are normalized to maps by the builder.
            return values
        return values

    def configure_core(self, values):
        api = values['nico-api']; text = api['siteConfig']['nicoApiSiteConfig']
        # A first installation has no physical provisioning-network facts. Do
        # not ship a documentation subnet or translate Kubernetes ClusterIPs
        # into DHCP options. Those values are applied later by site settings.
        text = re.sub(r'(?m)^sitename\s*=.*$', lambda _: 'sitename = ' + json.dumps(self.config['site_name']), text)
        parsed = tomllib.loads(text)
        networks = parsed.get('networks') or {}
        require(not any(value.get('type') == 'hostinband' for value in networks.values()),
                'Initial delivery must not define a HostInband provisioning network')
        api['siteConfig']['nicoApiSiteConfig'] = text
        dhcp = values.setdefault('nico-dhcp', {})
        require(dhcp.get('replicas') == 0,
                'Initial delivery must keep nico-dhcp scaled to zero until physical boot settings are configured')
        for component in ('nico-dhcp', 'nico-dns', 'nico-pxe', 'nico-ntp'):
            values.setdefault(component, {}).setdefault('externalService', {})['enabled'] = False
        require(not parsed.get('site_explorer', {}).get('enabled', False) and not parsed.get('firmware_global', {}).get('autoupdate', False),
                'Initial delivery must not enable discovery or firmware automation')

    def prepare_recipe(self):
        self.preflight()
        catalog = json.loads((self.work / 'catalog.json').read_text())
        require(catalog.get('ready') and catalog['bundle_inventory_sha256'] == self.state['bundle_inventory_sha256'], 'Import this bundle first')
        existing = self.work / 'recipe'
        require(not existing.exists(), 'Recipe already exists; use its frozen files or remove only this generated recipe after review')
        catalog = self.refresh_catalog_images(catalog)
        stage = Path(tempfile.mkdtemp(prefix='.recipe-', dir=self.work)); recipe = stage / 'nico-recipe'; recipe.mkdir()
        (recipe / 'charts').mkdir(); (recipe / 'values').mkdir()
        charts = {item['id']: item for item in catalog['charts']}
        settings = {'release_prefix': RELEASE, 'namespace': self.config['namespace'],
                    'site_name': self.config['site_name']}
        plan = copy.deepcopy(json.loads((self.bundle / 'profiles/install-plan.json').read_text()))
        plan['schema_version'] = 1
        phases = []
        for phase in plan['phases']:
            if self.cert_manager_mode == 'reuse' and phase['id'] == 'cert-manager':
                print('SKIP_CERT_MANAGER_PHASE reuse-shared-controller', flush=True)
                continue
            phase.pop('material_chart', None)
            phases.append(phase)
        plan['phases'] = phases
        for phase in phases:
            key = phase.pop('chart_id'); item = charts[key]
            chart = self.pull_chart(item, stage / 'pulled' / phase['id'])
            destination = recipe / 'charts' / (key + '.tgz')
            if not destination.exists(): shutil.copyfile(chart, destination)
            defaults = yaml.safe_load(self.helm_run(['show', 'values', str(chart)], phase['id'] + '-defaults').stdout) or {}
            defaults = self.imported_defaults(defaults, catalog)
            values = self.image_defaults(defaults, copy.deepcopy(defaults))
            # Escape the site name as TOML, rather than doing raw substitution inside TOML text.
            if phase['id'] == 'core':
                config = values['nicoCore']['nico-api']['siteConfig']['nicoApiSiteConfig']
                config = config.replace('"@{site_name}"', json.dumps(self.config['site_name']))
                values['nicoCore']['nico-api']['siteConfig']['nicoApiSiteConfig'] = config
            values = substitute(values, settings)
            values = merge(values, phase.pop('values_inline', {}))
            if self.cert_manager_mode == 'reuse':
                components = values.setdefault('components', {})
                require(isinstance(components, dict), 'Parent Chart components must contain an object')
                cert_manager = components.setdefault('certManager', {})
                require(isinstance(cert_manager, dict), 'Parent Chart components.certManager must contain an object')
                cert_manager['enabled'] = False
            if phase['id'] == 'core': self.configure_core(values['nicoCore'])
            require(not TOKEN.search(json.dumps(values)), 'Unresolved values variables in ' + phase['id'])
            target = recipe / 'values' / (phase['id'] + '.yaml')
            target.write_text(yaml.safe_dump(values, sort_keys=False, allow_unicode=True)); target.chmod(0o600)
            phase['chart'] = str(destination.relative_to(recipe)); phase['values'] = [str(target.relative_to(recipe))]
            phase['release'] = self.release('core')
            rendered = self.helm_run(['template', phase['release'], str(chart), '-n', self.config['namespace'], '-f', str(target)],
                                     phase['id'] + '-render', private=True).stdout
            self.check_images(rendered, catalog)
        plan = substitute(plan, settings)
        plan['version'] = str(catalog['bundle_version'])
        plan['name'] = 'NICo offline onsite recipe'
        plan['cert_manager_mode'] = self.cert_manager_mode
        plan['files'] = {str(path.relative_to(recipe)): sha(path) for directory in ('charts', 'values') for path in (recipe / directory).rglob('*') if path.is_file()}
        write_json(recipe / 'catalog.json', catalog)
        plan['files']['catalog.json'] = sha(recipe / 'catalog.json')
        write_json(recipe / 'deployment.json', plan)
        self.state['recipe_manifest_sha256'] = sha(recipe / 'deployment.json'); self.save()
        recipe.rename(existing)
        shutil.rmtree(stage)
        print('RECIPE_READY', existing)
        self.ui_package()

    def ui_package(self):
        root = self.work / 'recipe'
        manifest = self.validate_recipe()
        for phase in manifest['phases']: self.check_ownership(root, phase)
        archive = self.work / 'ui-recipe.tar.gz'; pack(root, archive); archive.chmod(0o600)
        write_json(self.work / 'recipe-result.json', {'archive_sha256': sha(archive), 'archive': str(archive),
                                                     'notice': 'May include private Helm values; transfer securely; do not commit'})
        print('UI_UPLOAD', archive, '; use frozen site defaults; do not run UI and CLI installation concurrently')

    def validate_recipe(self):
        root = self.work / 'recipe'
        require(self.state.get('recipe_manifest_sha256') == sha(root / 'deployment.json'), 'Frozen deployment manifest changed')
        manifest = json.loads((root / 'deployment.json').read_text())
        for name, digest in manifest['files'].items():
            require((root / name).resolve().is_relative_to(root) and sha(root / name) == digest, 'Frozen recipe changed: ' + name)
        return manifest

    def install(self, phase, resume_failed=False, automatic=False):
        self.preflight()
        root = self.work / 'recipe'; manifest = self.validate_recipe()
        phases = manifest['phases']
        require(not resume_failed or phase != 'all', 'Use --resume-failed only with one explicitly reviewed --phase')
        selected = phases if phase == 'all' else [item for item in phases if item['id'] == phase]
        require(selected, 'Unknown phase: ' + phase)
        for item in selected:
            key = item['id']
            # A completed phase is rechecked, not blindly replayed (especially Vault/migrations).
            if self.state['steps'].get('installed-' + key) and not resume_failed:
                status = self.helm_run(['status', item['release'], '-n', self.config['namespace'], '-o', 'json'], key + '-status', private=True)
                require(json.loads(status.stdout)['info']['status'] == 'deployed', 'Previously completed Helm phase is no longer deployed: ' + key)
                if automatic: self.check_pvcs(key)
                self.check_health(root, item)
                print('ALREADY_INSTALLED', key); continue
            earlier = phases[:phases.index(item)]
            require(all(self.state['steps'].get('installed-' + p['id']) for p in earlier), 'Run previous phases first, or use --phase all')
            self.check_ownership(root, item)
            if automatic and (self.private / ('before-' + key) / 'complete.json').exists():
                self.check_pvcs(key)  # Keep the original PVC baseline across every retry.
                result = self.helm_run(['status', item['release'], '-n', self.config['namespace'], '-o', 'json'],
                                       key + '-resume-status', check=False, private=True)
                require(result.returncode == 0 or 'release: not found' in result.stderr.lower(), 'Cannot establish Helm state; stop before retry')
                status = json.loads(result.stdout)['info']['status'] if result.returncode == 0 else 'not-found'
                require(status in ('deployed', 'failed', 'not-found'), 'Helm is pending or requires operator review: ' + status)
                if status == 'deployed':
                    # Helm may have succeeded before the process was interrupted. Verify
                    # the exact intent instead of rerunning migrations/bootstrap hooks.
                    intent = self.state.get('install_intents', {}).get(key)
                    require(intent == self.install_intent(root, item), 'No matching install intent; inspect deployed release before continuing')
                    self.verify_deployed(root, item)
                    self.state['steps']['installed-' + key] = {'release': item['release'], 'at': datetime.now(timezone.utc).isoformat(), 'recovered': True}
                    self.save(); print('RECOVERED_INSTALLED', key, flush=True); continue
                print('RESUME_FAILED_PHASE', key, status, flush=True)
                # The original complete snapshot remains authoritative.
            else:
                # The ordered parent-Chart phases all use one Helm release.
                # Snapshot/recovery must therefore query the selected item's
                # release, not derive the obsolete per-phase release name.
                self.snapshot(key, item['release'], resume_failed)
            self.state.setdefault('install_intents', {})[key] = self.install_intent(root, item)
            self.save()
            args = ['upgrade', '--install', item['release'], str(root / item['chart']), '-n', self.config['namespace'],
                    '--create-namespace', '--wait', '--wait-for-jobs', '--timeout', str(item.get('timeout_seconds', 900)) + 's']
            for value in item['values']: args += ['-f', str(root / value)]
            self.helm_run(args, key + '-install', private=True, timeout=item.get('timeout_seconds', 900) + 60)
            self.check_pvcs(key)
            self.check_health(root, item)
            self.state['steps']['installed-' + key] = {'release': item['release'], 'at': datetime.now(timezone.utc).isoformat()}; self.save()
        print('HELM_PHASES_COMPLETE; strict Core mTLS, boot HTTP and physical-network acceptance remain explicit follow-up checks')

    def verify_deployed(self, root, item):
        key = item['id']
        current = self.helm_run(['get', 'values', item['release'], '-n', self.config['namespace'], '-o', 'json'],
                                key + '-resume-values', private=True)
        wanted = {}
        for value in item['values']:
            wanted = merge(wanted, yaml.safe_load((root / value).read_text()) or {})
        require((json.loads(current.stdout) or {}) == wanted, 'Deployed Helm values differ from frozen intent')
        with tarfile.open(root / item['chart']) as archive:
            names = [name for name in archive.getnames() if name.count('/') == 1 and name.endswith('/Chart.yaml')]
            require(len(names) == 1, 'Expected one root Chart metadata file')
            metadata = yaml.safe_load(archive.extractfile(names[0]).read())
        releases = json.loads(self.helm_run(['list', '--all', '-n', self.config['namespace'], '-o', 'json'], key + '-resume-releases', private=True).stdout)
        matches = [r for r in releases if r['name'] == item['release']]
        require(len(matches) == 1 and matches[0]['chart'] == metadata['name'] + '-' + str(metadata['version']), 'Deployed Chart differs from frozen intent')
        self.check_health(root, item)

    def install_intent(self, root, item):
        return {'release': item['release'], 'chart_sha256': sha(root / item['chart']),
                'values': {value: sha(root / value) for value in item['values']}}

    def check_images(self, rendered, catalog):
        allowed = {row['image'] for row in catalog['images']}
        for row in catalog['images']:
            tagged = row['image'].split('@')[0]
            # A digest reference drops the tag, but retains a registry's port.
            repository = tagged.rsplit(':', 1)[0] if ':' in tagged.rsplit('/', 1)[-1] else tagged
            allowed.add(repository + '@' + row['digest'])
            allowed.add(tagged + '@' + row['digest'])

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('containers', 'initContainers', 'ephemeralContainers') and isinstance(item, list):
                        for container in item:
                            require(container['image'] in allowed, 'Rendered image is outside imported lock: ' + container['image'])
                    walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        for obj in yaml.safe_load_all(rendered): walk(obj)

    def namespace_exists(self):
        return bool(self.kubectl(['get', 'namespace', self.config['namespace'], '--ignore-not-found', '-o', 'name'], 'namespace').stdout.strip())

    @staticmethod
    def namespace_system_resource(item):
        """Return true only for the namespace-scoped objects Kubernetes creates itself."""
        metadata = item.get('metadata') or {}
        annotations = metadata.get('annotations') or {}
        if item.get('kind') == 'ServiceAccount' and metadata.get('name') == 'default':
            return True
        if item.get('kind') == 'ConfigMap' and metadata.get('name') == 'kube-root-ca.crt':
            return True
        return (
            item.get('kind') == 'Secret'
            and item.get('type') == 'kubernetes.io/service-account-token'
            and annotations.get('kubernetes.io/service-account.name') == 'default'
        )

    def namespace_resource_belongs_to(self, item, releases):
        """Recognize Helm resources for exactly the releases this run owns."""
        metadata = item.get('metadata') or {}
        annotations = metadata.get('annotations') or {}
        if (
            annotations.get('meta.helm.sh/release-name') in releases
            and annotations.get('meta.helm.sh/release-namespace') == self.config['namespace']
        ):
            return True
        labels = metadata.get('labels') or {}
        return (
            item.get('kind') == 'Secret'
            and item.get('type') == 'helm.sh/release.v1'
            and labels.get('owner') == 'helm'
            and labels.get('name') in releases
        )

    def namespace_runtime_resources(self, rows, releases):
        """Resolve controller outputs from this run's actual parent resources."""
        namespace = self.config['namespace']
        owned = {item['metadata']['uid'] for item in rows
                 if self.namespace_resource_belongs_to(item, releases)}
        hook_rows = [item for item in rows if item['metadata'].get('annotations', {}).get('helm.sh/hook')
                     and item['metadata']['uid'] not in owned]
        if hook_rows:
            hooks = set()
            for release in sorted(releases):
                result = self.helm_run(['get', 'hooks', release, '-n', namespace],
                                       'namespace-hooks-' + release, private=True, check=False)
                require(result.returncode == 0 or 'release: not found' in result.stderr.lower(),
                        'Cannot establish Helm hook ownership for ' + release)
                for obj in yaml.safe_load_all(result.stdout):
                    if obj and obj.get('metadata', {}).get('annotations', {}).get('helm.sh/hook'):
                        meta = obj['metadata']
                        hooks.add((obj['kind'], meta.get('namespace', namespace), meta['name']))
            for item in hook_rows:
                meta = item['metadata']
                if (item['kind'], meta.get('namespace', namespace), meta['name']) in hooks:
                    owned.add(meta['uid'])

        def flag(args, name):
            for index, value in enumerate(args):
                if value.startswith(name + '='):
                    return value[len(name) + 1:]
                if value == name and index + 1 < len(args):
                    return args[index + 1]
            return None

        secrets = {item['metadata']['name']: item for item in rows if item['kind'] == 'Secret'}
        for item in rows:
            if item['metadata']['uid'] not in owned:
                continue
            if item['kind'] == 'Certificate':
                secret = secrets.get(item.get('spec', {}).get('secretName'))
                if secret and secret['metadata'].get('annotations', {}).get('cert-manager.io/certificate-name') == item['metadata']['name']:
                    owned.add(secret['metadata']['uid'])
            elif item['kind'] == 'Deployment':
                for container in item.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
                    args = container.get('args') or []
                    ca_name = flag(args, '--dynamic-serving-ca-secret-name')
                    ca_namespace = flag(args, '--dynamic-serving-ca-secret-namespace')
                    if ca_namespace == '$(POD_NAMESPACE)':
                        env = next((env for env in container.get('env', []) if env.get('name') == 'POD_NAMESPACE'), {})
                        if env.get('valueFrom', {}).get('fieldRef', {}).get('fieldPath') == 'metadata.namespace':
                            ca_namespace = item['metadata']['namespace']
                    secret = secrets.get(ca_name)
                    if secret and ca_namespace == namespace:
                        meta = secret['metadata']
                        if (meta.get('labels', {}).get('app.kubernetes.io/managed-by') == 'cert-manager'
                                and meta.get('annotations', {}).get('cert-manager.io/allow-direct-injection') == 'true'):
                            owned.add(meta['uid'])
            elif item['kind'] == 'Job' and self.state.get('install_intents', {}).get('vault'):
                for container in item.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
                    command = ' '.join(container.get('command') or [])
                    if 'pxeye-bootstrap-vault' not in command:
                        continue
                    prefix = next((env.get('value') for env in container.get('env', []) if env.get('name') == 'NICO_PREFIX'), None)
                    if not isinstance(prefix, str) or not NAME.fullmatch(prefix):
                        continue
                    for name in (prefix + '-nico-vault-recovery', prefix + '-nico-vault-token', prefix + '-ssh-host-key'):
                        secret = secrets.get(name)
                        if (secret and secret.get('type') == 'Opaque'
                                and secret['metadata'].get('labels', {}).get('app.kubernetes.io/instance') == prefix + '-vault-bootstrap'):
                            owned.add(secret['metadata']['uid'])

        # CertificateRequests, temporary private-key Secrets and CronJob Jobs
        # carry real parent UIDs even when they have no Helm annotations.
        owners = {item['metadata']['uid']: (item['kind'], item['metadata']['name']) for item in rows}
        while True:
            before = len(owned)
            for item in rows:
                for parent in item['metadata'].get('ownerReferences', []):
                    if parent.get('uid') in owned and owners.get(parent['uid']) == (parent.get('kind'), parent.get('name')):
                        owned.add(item['metadata']['uid'])
            if len(owned) == before:
                return owned

    def check_namespace_resources(self, releases):
        """Reject non-system leftovers instead of letting Helm adopt old site data."""
        if not self.namespace_exists():
            return
        resource_types = (
            'services,configmaps,secrets,persistentvolumeclaims,serviceaccounts,'
            'roles,rolebindings,deployments,statefulsets,daemonsets,jobs,cronjobs,'
            'networkpolicies,poddisruptionbudgets'
        )
        result = self.kubectl(
            ['-n', self.config['namespace'], 'get', resource_types, '-o', 'json'],
            'namespace-resource-layout', private=True,
        )
        rows = list(json.loads(result.stdout).get('items') or [])
        # Shared or successfully installed cert-manager makes these resource
        # kinds available. Their controller outputs also need ownership checks.
        if self.cert_manager_mode == 'reuse' or self.state['steps'].get('installed-cert-manager'):
            result = self.kubectl(
                ['-n', self.config['namespace'], 'get', 'certificates,certificaterequests,issuers', '-o', 'json'],
                'namespace-cert-manager-layout', private=True,
            )
            rows.extend(json.loads(result.stdout).get('items') or [])
        runtime_resources = self.namespace_runtime_resources(rows, releases)
        unexpected = []
        for item in rows:
            if self.namespace_system_resource(item) or item['metadata']['uid'] in runtime_resources:
                continue
            metadata = item.get('metadata') or {}
            unexpected.append(str(item.get('kind') or 'Resource') + '/' + str(metadata.get('name') or '?'))
        require(
            not unexpected,
            'Fresh installation refuses residual resources in nico-system; remove or migrate them before retrying: ' +
            ', '.join(sorted(unexpected)),
        )
        print('NAMESPACE_LAYOUT_OK', self.config['namespace'], flush=True)

    def check_ownership(self, root, phase):
        args = ['template', phase['release'], str(root / phase['chart']), '-n', self.config['namespace']]
        for path in phase['values']: args += ['-f', str(root / path)]
        rendered = self.helm_run(args, phase['id'] + '-ownership-render', private=True).stdout
        exists = self.namespace_exists()
        for obj in yaml.safe_load_all(rendered):
            if not obj or obj['kind'] == 'Namespace': continue
            meta = obj.get('metadata', {}); name = meta.get('name')
            if not name: continue
            namespace = meta.get('namespace')
            cluster = obj['kind'] in {'ClusterRole', 'ClusterRoleBinding', 'CustomResourceDefinition', 'ClusterIssuer', 'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration'}
            require(cluster or namespace in (None, self.config['namespace']), 'Chart targets another namespace')
            if not cluster and not exists: continue
            args = ['get', obj['kind'], name, '--ignore-not-found', '-o', 'json']
            if not cluster: args += ['-n', self.config['namespace']]
            result = self.kubectl(args, phase['id'] + '-owner-' + obj['kind'] + '-' + name, private=True)
            if not result.stdout.strip(): continue
            annotations = json.loads(result.stdout)['metadata'].get('annotations', {})
            # Hook resources are managed by Helm's hook deletion policy, not release ownership.
            if meta.get('annotations', {}).get('helm.sh/hook'):
                owner = annotations.get('meta.helm.sh/release-name')
                require(owner in (None, phase['release']), 'Hook is owned by another release')
                hooks = self.helm_run(['get', 'hooks', phase['release'], '-n', self.config['namespace']], phase['id'] + '-existing-hooks', private=True)
                require(any(hook and hook.get('kind') == obj['kind'] and hook.get('metadata', {}).get('name') == name
                            for hook in yaml.safe_load_all(hooks.stdout)), 'Existing hook is absent from the selected Helm release')
                continue
            require(annotations.get('meta.helm.sh/release-name') == phase['release'] and
                    annotations.get('meta.helm.sh/release-namespace') == self.config['namespace'],
                    'Existing object belongs to another owner: ' + obj['kind'] + '/' + name)

    def snapshot(self, phase, release, resume_failed=False):
        directory = self.private / ('before-' + phase)
        if (directory / 'complete.json').exists():
            require(resume_failed, 'Snapshot exists; inspect Helm/Jobs, then explicitly use --phase NAME --resume-failed')
            status = self.helm_run(['status', release, '-n', self.config['namespace'], '-o', 'json'], phase + '-resume-status', check=False, private=True)
            require(status.returncode == 0 or 'release: not found' in status.stderr.lower(), 'Could not establish Helm state; inspect before retry')
            if status.returncode == 0:
                require(not json.loads(status.stdout)['info']['status'].startswith('pending-'), 'Helm operation is still pending; inspect instead of replaying')
            directory.rename(self.private / ('before-' + phase + '-' + str(time.time_ns())))
        directory.mkdir(exist_ok=True, mode=0o700)
        pvcs = {'items': []}
        if self.namespace_exists():
            result = self.kubectl(['-n', self.config['namespace'], 'get', 'pvc', '-o', 'json'], phase + '-pvc-before', private=True)
            pvcs = json.loads(result.stdout)
        write_json(directory / 'pvcs.json', pvcs)
        result = self.helm_run(['get', 'all', release, '-n', self.config['namespace']], phase + '-helm-before', check=False, private=True)
        require(result.returncode == 0 or 'release: not found' in result.stderr.lower(), 'Cannot capture Helm release state; inspect before install')
        (directory / 'helm.txt').write_text(result.stdout); (directory / 'helm.txt').chmod(0o600)
        write_json(directory / 'complete.json', {'metadata_only': True, 'helm_exit_code': result.returncode})

    def check_health(self, root, phase):
        args = ['template', phase['release'], str(root / phase['chart']), '-n', self.config['namespace']]
        for value in phase['values']: args += ['-f', str(root / value)]
        rendered = self.helm_run(args, phase['id'] + '-health-render', private=True).stdout
        for obj in yaml.safe_load_all(rendered):
            if not obj or obj.get('metadata', {}).get('annotations', {}).get('helm.sh/hook'): continue
            kind, name = obj['kind'], obj.get('metadata', {}).get('name')
            timeout = str(phase.get('timeout_seconds', 900)) + 's'
            if kind in ('Deployment', 'StatefulSet', 'DaemonSet'):
                self.kubectl(['-n', self.config['namespace'], 'rollout', 'status', kind.lower() + '/' + name, '--timeout', timeout],
                             phase['id'] + '-ready-' + name, private=True, timeout=phase.get('timeout_seconds', 900) + 60)
            elif kind == 'Certificate':
                self.kubectl(['-n', self.config['namespace'], 'wait', '--for=condition=Ready', 'certificate/' + name, '--timeout', timeout],
                             phase['id'] + '-cert-' + name, private=True, timeout=phase.get('timeout_seconds', 900) + 60)

    def check_pvcs(self, phase):
        previous = json.loads((self.private / ('before-' + phase) / 'pvcs.json').read_text())
        current = json.loads(self.kubectl(['-n', self.config['namespace'], 'get', 'pvc', '-o', 'json'], phase + '-pvc-after', private=True).stdout)
        mapping = {item['metadata']['name']: item for item in current['items']}
        for old in previous['items']:
            item = mapping.get(old['metadata']['name'])
            require(item and item['metadata']['uid'] == old['metadata']['uid'] and
                    item['spec'].get('volumeName') == old['spec'].get('volumeName'),
                    'Existing PVC identity/binding changed; stop and inspect')

    def bootstrap(self, resume=False):
        self.preflight()
        catalog = json.loads((self.work / 'catalog.json').read_text())
        require(catalog.get('ready'), 'Import bundle first')
        item = next(row for row in catalog['charts'] if row['id'] == 'pxeye')
        directory = self.work / 'bootstrap'; directory.mkdir(exist_ok=True)
        chart = self.pull_chart(item, directory)
        core_release = self.release('core')
        namespace = self.config['namespace']
        values = {'nico': {'enabled': True, 'allowClusterResources': True},
                  'siteBootstrap': {
                      'enabled': True,
                      'siteName': self.config['site_name'],
                      'coreUrl': 'https://' + core_release + '-nico-api.' + namespace + '.svc.cluster.local:1079',
                      'namespace': namespace,
                      'clientSecret': core_release + '-nico-admin-client',
                      'clientCertKey': 'tls.crt',
                      'clientPrivateKey': 'tls.key',
                      'caSecret': core_release + '-nico-site-ca',
                      'caKey': 'tls.crt',
                      'pxeInternalUrl': 'http://' + core_release + '-nico-pxe.' + namespace + '.svc:8080',
                  },
                  # Bootstrap owns the PXEye UI only.  The offline parent
                  # package has all NICo components enabled by default so its
                  # later, ordered phases can turn them on; inheriting those
                  # defaults here would bypass that ordering.
                  'components': copy.deepcopy(PXEYE_ONLY_COMPONENTS)}
        # Components are intentionally not a user override for this path;
        # one-click NICo installation continues through the frozen phases.
        values['components'] = copy.deepcopy(PXEYE_ONLY_COMPONENTS)
        # The one-command path has no editable deployment settings.  Keep the
        # PXEye access contract and its in-cluster Core handoff deterministic.
        values.setdefault('service', {}).update({'type': 'NodePort', 'nodePort': PXEYE_NODE_PORT})
        values['siteBootstrap'] = {
            'enabled': True,
            'siteName': self.config['site_name'],
            'coreUrl': 'https://' + core_release + '-nico-api.' + namespace + '.svc.cluster.local:1079',
            'namespace': namespace,
            'clientSecret': core_release + '-nico-admin-client',
            'clientCertKey': 'tls.crt',
            'clientPrivateKey': 'tls.key',
            'caSecret': core_release + '-nico-site-ca',
            'caKey': 'tls.crt',
            'pxeInternalUrl': 'http://' + core_release + '-nico-pxe.' + namespace + '.svc:8080',
        }
        path = directory / 'values.yaml'; path.write_text(yaml.safe_dump(values)); path.chmod(0o600)
        release = self.config['namespace'] + '-pxeye'
        require(NAME.fullmatch(release), 'Invalid PXEye release')
        require(release != self.release('core'),
                'PXEye and Core parent releases must differ')
        self.check_pxeye_node_port(release, values)
        phase = {'id': 'pxeye', 'release': release, 'chart': str(chart.relative_to(self.work)),
                 'values': [str(path.relative_to(self.work))]}
        rendered = self.helm_run(['template', release, str(chart), '-n', self.config['namespace'], '-f', str(path)], 'pxeye-render', private=True).stdout
        self.check_images(rendered, catalog)
        self.check_ownership(self.work, phase)
        if resume and self.state['steps'].get('bootstrapped-pxeye'):
            status = self.helm_run(['status', release, '-n', self.config['namespace'], '-o', 'json'], 'pxeye-status', private=True)
            require(json.loads(status.stdout)['info']['status'] == 'deployed', 'PXEye release is no longer deployed')
            self.check_health(self.work, phase)
            print('ALREADY_INSTALLED pxeye', flush=True); return
        if resume:
            status = self.helm_run(['status', release, '-n', self.config['namespace'], '-o', 'json'], 'pxeye-resume-status', check=False, private=True)
            require(status.returncode == 0 or 'release: not found' in status.stderr.lower(), 'Cannot establish PXEye release state')
            if status.returncode == 0:
                actual = json.loads(status.stdout)['info']['status']
                require(actual in ('deployed', 'failed'), 'PXEye Helm operation is pending; inspect before retry')
                if actual == 'deployed' and self.state.get('pxeye_install_intent') == self.install_intent(self.work, phase):
                    self.verify_deployed(self.work, phase)
                    self.state['steps']['bootstrapped-pxeye'] = {'release': release, 'at': datetime.now(timezone.utc).isoformat(), 'recovered': True}
                    self.save(); print('RECOVERED_INSTALLED pxeye', flush=True); return
        self.state['pxeye_install_intent'] = self.install_intent(self.work, phase); self.save()
        self.helm_run(['upgrade', '--install', release, str(chart), '-n', self.config['namespace'], '--create-namespace',
                       '--wait', '--timeout', '900s', '-f', str(path)], 'pxeye-bootstrap', private=True, timeout=960)
        self.state['steps']['bootstrapped-pxeye'] = {'release': release, 'at': datetime.now(timezone.utc).isoformat()}; self.save()
        print('PXEYE_HELM_READY; existing non-Helm PXEye is never automatically adopted')

    def check_pxeye_core_connection(self):
        """Require the PXEye process to finish its in-cluster mTLS handoff."""
        release = self.config['namespace'] + '-pxeye'
        program = (
            'import json, sys; from urllib.request import urlopen; '
            'state = json.load(urlopen("http://127.0.0.1:8080/healthz", timeout=5)); '
            'sys.exit(0 if state.get("core", {}).get("ready") else 1)'
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = self.kubectl(
                ['-n', self.config['namespace'], 'exec', 'deployment/' + release, '--', 'python3', '-c', program],
                'pxeye-core-connection', check=False, private=True, timeout=30)
            if result.returncode == 0:
                self.state['steps']['pxeye-core-connected'] = {
                    'release': release, 'at': datetime.now(timezone.utc).isoformat()}
                self.save()
                print('PXEYE_CORE_CONNECTED', flush=True)
                return
            time.sleep(5)
        raise ValueError('PXEye did not complete its in-cluster Core connection within five minutes; see ' +
                         str(self.private / 'pxeye-core-connection.log'))


def detect_registry(args):
    """Discover a site endpoint from explicit cluster evidence, then probe Registry V2."""
    candidates = {}

    def add(authority, source):
        if not authority or '/' in authority or '@' in authority:
            return
        parsed = urlsplit('//' + authority)
        try:
            valid = parsed.hostname and parsed.port != 0 and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if valid:
            candidates.setdefault(authority.lower(), set()).add(source)

    def read(arguments, optional=False):
        result = subprocess.run(['kubectl', '--context', args.context, '--request-timeout=15s'] + arguments,
                                text=True, capture_output=True, timeout=20)
        if optional and result.returncode:
            print('REGISTRY_DISCOVERY_HINT_UNAVAILABLE: optional local-registry-hosting ConfigMap', flush=True)
            return {}
        require(result.returncode == 0, 'Registry discovery cannot read cluster workload evidence')
        return json.loads(result.stdout) if result.stdout.strip() else {}

    # No subnet scan or public image-Registry enumeration. A new nico-system
    # namespace is empty, so inspect existing workload image authorities across
    # the cluster as the explicit local evidence of the fireseed Registry.
    override = os.environ.get('NICO_REGISTRY_URL')
    if override:
        parsed = urlsplit(override)
        require(parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and
                not parsed.path.rstrip('/') and not parsed.query and not parsed.fragment,
                'NICO_REGISTRY_URL must be http(s)://host[:port] without a path')
        add(parsed.netloc, 'NICO_REGISTRY_URL')
    else:
        objects = read(['get', 'pods,deployments', '-A', '-o', 'json'])
        for item in objects.get('items', []):
            spec = item['spec'] if item['kind'] == 'Pod' else item['spec']['template']['spec']
            for container in spec.get('containers', []) + spec.get('initContainers', []):
                image = container.get('image', '')
                if '/' not in image:
                    continue
                authority = image.split('/', 1)[0]
                if not ('.' in authority or ':' in authority or authority == 'localhost'):
                    continue
                host = urlsplit('//' + authority).hostname
                try:
                    address = ipaddress.ip_address(host)
                    local = address.is_private and not address.is_unspecified and not address.is_multicast
                except ValueError:
                    local = host == 'localhost' or bool(host and host.endswith('.localhost'))
                public = host in {'docker.io', 'index.docker.io', 'registry-1.docker.io', 'ghcr.io',
                                  'quay.io', 'nvcr.io', 'registry.k8s.io', 'gcr.io'}
                if not public and (local or container.get('name') == 'pxeye'):
                    add(authority, 'workload-image')
        hint = read(['-n', 'kube-public', 'get', 'configmap', 'local-registry-hosting',
                     '--ignore-not-found', '-o', 'json'], optional=True)
        if hint:
            data = yaml.safe_load(hint.get('data', {}).get('localRegistryHosting.v1', '')) or {}
            if isinstance(data, dict):
                add(data.get('host'), 'local-registry-hosting')
    require(candidates, 'No Registry candidate found; make the site Registry visible to a workload or set NICO_REGISTRY_URL')
    require(len(candidates) <= 16, 'Too many Registry candidates; set NICO_REGISTRY_URL to select the site endpoint')
    context = ssl.create_default_context(cafile=str(args.ca_file) if args.ca_file else None)
    if args.skip_tls_verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    found, probes = set(), []
    for authority in sorted(candidates):
        # Prefer TLS. Certificate failure never silently falls back to HTTP.
        for scheme in ('https', 'http'):
            url = scheme + '://' + authority
            parsed = urlsplit(url)
            connection = None
            certificate_error = False
            try:
                options = {'context': context} if scheme == 'https' else {}
                cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
                connection = cls(parsed.hostname, parsed.port, timeout=4, **options)
                connection.request('GET', '/v2/', headers={'Accept': 'application/json'})
                response = connection.getresponse()
                api = response.getheader('Docker-Distribution-Api-Version', '').lower()
                valid = response.status in (200, 401) and api == 'registry/2.0'
                probes.append({'url': url, 'status': response.status, 'registry_v2': valid})
                if valid:
                    host = '[' + parsed.hostname + ']' if ':' in parsed.hostname else parsed.hostname
                    port = parsed.port
                    canonical = scheme + '://' + host + (':' + str(port) if port and port != {'https': 443, 'http': 80}[scheme] else '')
                    found.add(canonical)
                    break
            except ssl.SSLCertVerificationError:
                certificate_error = True
                probes.append({'url': url, 'error': 'TLS certificate verification failed'})
            except (OSError, http.client.HTTPException, ValueError) as error:
                probes.append({'url': url, 'error': type(error).__name__})
            finally:
                if connection:
                    connection.close()
            if certificate_error:
                break
    for probe in probes:
        print('REGISTRY_PROBE', json.dumps(probe, sort_keys=True), flush=True)
    require(len(found) == 1, 'Expected one reachable Registry V2 endpoint, found ' + str(len(found)) +
            '; check probe results or set NICO_REGISTRY_URL')
    selected = next(iter(found))
    print('REGISTRY_DETECTED', selected, flush=True)
    return selected, {'sources': {key: sorted(value) for key, value in candidates.items()}, 'probes': probes}


def select_install_context():
    result = subprocess.run(['kubectl', 'config', 'get-contexts', '-o', 'name'],
                            capture_output=True, text=True, timeout=15)
    require(result.returncode == 0, 'Cannot read local kubeconfig contexts')
    contexts = [name for name in result.stdout.splitlines() if name.startswith('kind-')]
    current = subprocess.run(['kubectl', 'config', 'current-context'], capture_output=True, text=True, timeout=15)
    require(current.returncode == 0, 'Cannot read the current kubeconfig context')
    selected = current.stdout.strip()
    if selected in contexts:
        return selected
    require(len(contexts) == 1,
            'Expected exactly one Kind context; select the intended cluster with kubectl config use-context before running')
    return contexts[0]
