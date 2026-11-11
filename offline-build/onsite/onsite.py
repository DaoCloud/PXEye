#!/usr/bin/env python3
"""Import a verified relok8s delivery and prepare/install its frozen Helm recipe."""
import argparse
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
        json.dump(value, stream, indent=2, ensure_ascii=False); stream.write('\n')
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


def unpack(args):
    archive, checksums, output = args.archive.resolve(), args.checksums.resolve(), args.output.resolve()
    require(not output.exists(), 'Unpack output exists; choose a new directory')
    expected = []
    for line in checksums.read_text().splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?(.+)', line)
        if match and match[2] == archive.name:
            expected.append(match[1].lower())
    require(len(expected) == 1, 'Expected exactly one checksum for ' + archive.name)
    print('VERIFY_ARCHIVE_SHA256', flush=True)
    require(sha(archive) == expected[0], 'Archive checksum mismatch')
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
        write_json(temporary / 'unpack-result.json', {'archive_sha256': expected[0], 'root': bundle.name})
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
        require(c.get('schema_version') == 1, 'Unsupported onsite config schema')
        for key in ('context', 'namespace', 'release_prefix', 'site_name', 'bundle', 'work_directory'):
            require(c.get(key), 'Missing site configuration: ' + key)
        require(NAME.fullmatch(c['namespace']) and NAME.fullmatch(c['release_prefix']), 'Invalid namespace/release prefix')
        require(len(c['release_prefix']) <= 35, 'Release prefix too long for generated resource names')
        require(c.get('mode') in ('new', 'restore'), 'Mode must be new or restore')
        self.bundle, self.work = Path(c['bundle']).resolve(), Path(c['work_directory']).resolve()
        require(not self.work.is_relative_to(self.bundle) and not self.bundle.is_relative_to(self.work), 'Work directory must be outside bundle')
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.private = self.work / 'private'; self.private.mkdir(exist_ok=True, mode=0o700); self.private.chmod(0o700)
        self.lock = (self.work / '.lock').open('a'); fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_id = hashlib.sha256((c['context'] + '/' + c['namespace'] + '/' + c['release_prefix']).encode()).hexdigest()[:24]
        self.site_lock = (Path(tempfile.gettempdir()) / ('pxeye-onsite-' + lock_id + '.lock')).open('a')
        fcntl.flock(self.site_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.descriptor = json.loads((self.bundle / 'bundle.json').read_text())
        require(self.descriptor.get('architecture') == 'linux/amd64', 'Only amd64 control-plane bundles are supported')
        require(self.descriptor.get('kind') == 'pxeye-nico-helm', 'Use the Helm/relok8s delivery, not a legacy OCI bundle')
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
        identity_config.pop('data_backup_directory', None)  # recovery evidence may be supplied after import
        identity_config['implementation_sha256'] = {name: sha(HOME / name) for name in ('onsite.py', 'registry_bridge.py', 'relocation.py')}
        identity_config['phase_value_hashes'] = {key: sha(value) for key, value in c.get('phase_values', {}).items()}
        fingerprint = hashlib.sha256(json.dumps(identity_config, sort_keys=True).encode()).hexdigest()
        self.state_path = self.work / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'config_sha256': fingerprint, 'bundle_inventory_sha256': identity, 'steps': {}}
        # Exact predecessor identities may retain completed imports. All site,
        # archive and bridge inputs must still match; no arbitrary state reset.
        if self.state['config_sha256'] != fingerprint and self.state['bundle_inventory_sha256'] == identity:
            for previous_source, with_relocation in (('4315ad8762820d95b3054ae5e241ef7e4b366d0f556029d274bfb19c31bce0e4', True), ('19e0d0fc117c305257967152f3c330813883ddc202c567ce1dbc6037f8df235d', True), ('5dacea47145f7fca625ff001d1ff4496e9d6b32ca4ed2b9d8c58537c22e538b7', True), ('1c4a17c382cf1743a62b6ff260aca98f581bff7252bb5dc9e86b3286dc793701', False), ('d0cdd13aab92e73b9eed0437b5f632fcdc2efcb90385d9c325a21e70c5c6c421', False)):
                predecessor = copy.deepcopy(identity_config)
                if not with_relocation:
                    predecessor['implementation_sha256'].pop('relocation.py')
                predecessor['implementation_sha256']['onsite.py'] = previous_source
                old_fingerprint = hashlib.sha256(json.dumps(predecessor, sort_keys=True).encode()).hexdigest()
                if self.state['config_sha256'] == old_fingerprint:
                    self.state.setdefault('implementation_updates', []).append({
                        'from': old_fingerprint, 'to': fingerprint, 'reason': 'onsite-compatibility-fix'})
                    self.state['config_sha256'] = fingerprint
                    print('REUSE_STATE: compatible onsite update; completed imports retained', flush=True)
                    break
        require(self.state['config_sha256'] == fingerprint and self.state['bundle_inventory_sha256'] == identity,
                'Config/bundle changed; use a new work_directory')
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
        log.write_text(result.stdout + '\nSTDERR:\n' + result.stderr); log.chmod(0o600)
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
        return self.config['release_prefix'] + {'core': '', 'pxeye': '-pxeye', 'materials': '-materials'}.get(phase, '-' + phase)

    def old_values(self, phase):
        if self.config['mode'] != 'restore' or phase in ('pxeye', 'materials'):
            return {}
        value = self.helm_run(['get', 'values', self.release(phase), '-n', self.config['namespace'], '--all', '-o', 'json'],
                              phase + '-old-values', private=True)
        return json.loads(value.stdout) or {}

    def image_defaults(self, defaults, values):
        """Retain site settings while replacing every locked image field from the migrated Chart."""
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

    def service_ips(self):
        values = dict(self.config.get('service_ips') or {})
        for key, suffix in (('dns', 'dns'), ('pxe', 'pxe'), ('ntp', 'ntp-client')):
            if not values.get(key) and self.config['mode'] == 'restore':
                result = self.kubectl(['-n', self.config['namespace'], 'get', 'service', self.config['release_prefix'] + '-nico-' + suffix, '-o', 'json'], 'service-' + key)
                values[key] = json.loads(result.stdout)['spec']['clusterIP']
            require(values.get(key), 'Missing service_ips.' + key)
            try:
                address = ipaddress.ip_address(values[key])
            except (ValueError, TypeError):
                raise ValueError('Invalid service_ips.' + key + ': expected a client-facing IPv4 address, not a headless Service or empty value') from None
            require(address.version == 4, 'service_ips.' + key + ' must be IPv4')
        require(len(set(values.values())) == 3, 'Service IPs must be distinct')
        return values

    def configure_core(self, values, ips):
        api = values['nico-api']; text = api['siteConfig']['nicoApiSiteConfig']
        network = self.config.get('host_network')
        if network:
            require(re.fullmatch(r'[a-zA-Z0-9_-]+', network['name']), 'Invalid HostInband network name')
            prefix = ipaddress.ip_network(network['prefix'], strict=True)
            require(prefix.version == 4 and ipaddress.ip_address(network['gateway']) in prefix, 'Host gateway must be inside IPv4 prefix')
            require(576 <= int(network.get('mtu', 1500)) <= 9216, 'Invalid MTU')
            parsed = tomllib.loads(text)
            nets = parsed.get('networks', {})
            selected = [(name, value) for name, value in nets.items() if value.get('type') == 'hostinband']
            require(len(selected) == 1, 'Automatic network substitution requires exactly one HostInband network')
            old_name, old = selected[0]
            text = text.replace('[networks.' + old_name + ']', '[networks.' + network['name'] + ']')
            for key in ('prefix', 'gateway'):
                text = text.replace(key + ' = "' + old[key] + '"', key + ' = ' + json.dumps(network[key]))
            text = re.sub(r'(?m)^mtu\s*=\s*\d+\s*$', 'mtu = ' + str(network.get('mtu', 1500)), text)
        else:
            require(self.config['mode'] == 'restore', 'New installation requires host_network')
        # Preserve on-site policy and credentials; only change the site display name explicitly.
        text = re.sub(r'(?m)^sitename\s*=.*$', lambda _: 'sitename = ' + json.dumps(self.config['site_name']), text)
        tomllib.loads(text)
        api['siteConfig']['nicoApiSiteConfig'] = text
        values['nico-dns'].setdefault('service', {})['clusterIP'] = ips['dns']
        values['nico-pxe'].setdefault('service', {})['clusterIP'] = ips['pxe']
        values['nico-ntp'].setdefault('clientService', {})['clusterIP'] = ips['ntp']
        require(not self.config.get('enable_hardware_actions', False), 'Hardware automation is outside this installer scope')
        parsed = tomllib.loads(text)
        require(not parsed.get('site_explorer', {}).get('enabled', False) and not parsed.get('firmware_global', {}).get('autoupdate', False),
                'Existing site enables discovery/firmware automation; disable it in reviewed Core values before restoring')

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
        ips = self.service_ips()
        settings = {'release_prefix': self.config['release_prefix'], 'namespace': self.config['namespace'],
                    'site_name': self.config['site_name'], 'dns_ip': ips['dns'], 'pxe_ip': ips['pxe'], 'ntp_ip': ips['ntp']}
        plan = copy.deepcopy(json.loads((self.bundle / 'profiles/install-plan.json').read_text()))
        plan['schema_version'] = 1
        phases = []
        for phase in plan['phases']:
            phase.pop('material_chart', None)
            if phase['id'] == 'core' and self.config.get('publish_materials', False):
                phases.append({'id': 'materials', 'name': '材料发布', 'chart_id': 'materials',
                               'release': self.release('materials'), 'timeout_seconds': 1800})
            phases.append(phase)
        plan['phases'] = phases
        for phase in phases:
            key = phase.pop('chart_id'); item = charts[key]
            chart = self.pull_chart(item, stage / 'pulled' / phase['id'])
            destination = recipe / 'charts' / (key + '.tgz')
            if not destination.exists(): shutil.copyfile(chart, destination)
            defaults = yaml.safe_load(self.helm_run(['show', 'values', str(chart)], phase['id'] + '-defaults').stdout) or {}
            values = self.image_defaults(defaults, merge(defaults, self.old_values(phase['id'])))
            # Escape the site name as TOML, rather than doing raw substitution inside TOML text.
            if phase['id'] == 'core':
                config = values['nico-api']['siteConfig']['nicoApiSiteConfig']
                config = config.replace('"@{site_name}"', json.dumps(self.config['site_name']))
                values['nico-api']['siteConfig']['nicoApiSiteConfig'] = config
            values = substitute(values, settings)
            values = merge(values, phase.pop('values_inline', {}))
            if self.config.get('storage_class'):
                values['storageClass'] = self.config['storage_class']
            overrides = self.config.get('phase_values', {}).get(phase['id'])
            if overrides:
                values = merge(values, yaml.safe_load(Path(overrides).read_text()) or {})
            if phase['id'] == 'core': self.configure_core(values, ips)
            require(not TOKEN.search(json.dumps(values)), 'Unresolved values variables in ' + phase['id'])
            target = recipe / 'values' / (phase['id'] + '.yaml')
            target.write_text(yaml.safe_dump(values, sort_keys=False, allow_unicode=True)); target.chmod(0o600)
            phase['chart'] = str(destination.relative_to(recipe)); phase['values'] = [str(target.relative_to(recipe))]
            phase['release'] = self.release(phase['id'])
            rendered = self.helm_run(['template', phase['release'], str(chart), '-n', self.config['namespace'], '-f', str(target)],
                                     phase['id'] + '-render', private=True).stdout
            self.check_images(rendered, catalog)
        plan = substitute(plan, settings)
        plan['version'] = str(catalog['bundle_version'])
        plan['name'] = 'NICo offline onsite recipe'
        plan['files'] = {str(path.relative_to(recipe)): sha(path) for directory in ('charts', 'values') for path in (recipe / directory).rglob('*') if path.is_file()}
        write_json(recipe / 'catalog.json', catalog)
        plan['files']['catalog.json'] = sha(recipe / 'catalog.json')
        write_json(recipe / 'deployment.json', plan)
        recipe.rename(existing)
        self.state['recipe_manifest_sha256'] = sha(existing / 'deployment.json'); self.save()
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

    def install(self, phase, resume_failed=False):
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
                self.check_health(root, item)
                print('ALREADY_INSTALLED', key); continue
            earlier = phases[:phases.index(item)]
            require(all(self.state['steps'].get('installed-' + p['id']) for p in earlier), 'Run previous phases first, or use --phase all')
            self.check_ownership(root, item)
            self.snapshot(key, resume_failed)
            args = ['upgrade', '--install', item['release'], str(root / item['chart']), '-n', self.config['namespace'],
                    '--create-namespace', '--wait', '--wait-for-jobs', '--timeout', str(item.get('timeout_seconds', 900)) + 's']
            for value in item['values']: args += ['-f', str(root / value)]
            self.helm_run(args, key + '-install', private=True, timeout=item.get('timeout_seconds', 900) + 60)
            self.check_pvcs(key)
            self.check_health(root, item)
            self.state['steps']['installed-' + key] = {'release': item['release'], 'at': datetime.now(timezone.utc).isoformat()}; self.save()
        print('HELM_PHASES_COMPLETE; strict Core mTLS, boot HTTP and physical-network acceptance remain explicit follow-up checks')

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

    def snapshot(self, phase, resume_failed=False):
        directory = self.private / ('before-' + phase)
        if (directory / 'complete.json').exists():
            require(resume_failed, 'Snapshot exists; inspect Helm/Jobs, then explicitly use --phase NAME --resume-failed')
            status = self.helm_run(['status', self.release(phase), '-n', self.config['namespace'], '-o', 'json'], phase + '-resume-status', check=False, private=True)
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
        result = self.helm_run(['get', 'all', self.release(phase), '-n', self.config['namespace']], phase + '-helm-before', check=False, private=True)
        require(result.returncode == 0 or 'release: not found' in result.stderr.lower(), 'Cannot capture Helm release state; inspect before install')
        (directory / 'helm.txt').write_text(result.stdout); (directory / 'helm.txt').chmod(0o600)
        write_json(directory / 'complete.json', {'metadata_only': True, 'helm_exit_code': result.returncode})

    def cold_backup(self, engine, node):
        """Export only the two stopped backend PVCs from a confirmed Kind node."""
        self.preflight()
        require(self.config['mode'] == 'restore', 'Cold backup is only for restoring existing backends')
        nodes = json.loads(self.kubectl(['get', 'nodes', '-o', 'json'], 'backup-nodes').stdout)
        require(node in {item['metadata']['name'] for item in nodes['items']}, 'Kind node is not in the selected cluster')
        names = [self.config['release_prefix'] + '-nico-' + key for key in ('postgres', 'vault')]

        def stopped():
            resources = json.loads(self.kubectl(['-n', self.config['namespace'], 'get', 'pods,deployments,statefulsets,daemonsets', '-o', 'json'], 'backup-writer-check', private=True).stdout)
            for item in resources['items']:
                spec = item['spec'] if item['kind'] == 'Pod' else item['spec']['template']['spec']
                claims = {v['persistentVolumeClaim']['claimName'] for v in spec.get('volumes', []) if 'persistentVolumeClaim' in v}
                require(not claims.intersection(names) and item['metadata']['name'] not in names,
                        'Cold backup requires backend Pods/controllers stopped; never stop them automatically')
        stopped()
        directory = self.private / ('data-backup-' + str(time.time_ns())); directory.mkdir(mode=0o700)
        records = []
        for name in names:
            pvc = json.loads(self.kubectl(['-n', self.config['namespace'], 'get', 'pvc', name, '-o', 'json'], 'backup-' + name + '-pvc', private=True).stdout)
            pv = json.loads(self.kubectl(['get', 'pv', pvc['spec']['volumeName'], '-o', 'json'], 'backup-' + name + '-pv', private=True).stdout)
            path = pv['spec'].get('hostPath', {}).get('path') or pv['spec'].get('local', {}).get('path')
            require(path and Path(path).is_absolute(), 'Cold backup helper only supports Kind hostPath/local PVs')
            affinities = pv['spec'].get('nodeAffinity', {}).get('required', {}).get('nodeSelectorTerms', [])
            affinity_names = {value for term in affinities for rule in term.get('matchExpressions', [])
                              if rule['key'] == 'kubernetes.io/hostname' and rule['operator'] == 'In' for value in rule['values']}
            require(affinity_names == {node}, 'PV node affinity must identify exactly the selected Kind node')
            archive = directory / (name + '.tar')
            command = [engine, 'exec', node, 'tar', '-C', path, '-cf', '-', '.']
            print('RUN', shlex.join(command), '> private backup archive', flush=True)
            started = time.monotonic()
            with archive.open('xb') as output:
                result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=7200)
            (directory / (name + '.stderr')).write_bytes(result.stderr)
            require(result.returncode == 0, 'Cold PVC archive failed; incomplete evidence retained at ' + str(directory))
            records.append({'pvc': name, 'uid': pvc['metadata']['uid'], 'pv': pvc['spec']['volumeName'],
                            'node': node, 'archive': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha(archive),
                            'seconds': round(time.monotonic() - started, 3)})
        stopped()
        write_json(directory / 'backup.json', {'complete': True, 'mode': 'stopped-kind-volumes', 'volumes': records,
                                               'restore_tested': False})
        self.config['data_backup_directory'] = str(directory)
        write_json(self.config_path, self.config)
        print('COLD_BACKUP_COMPLETE', directory, '; archive SHA recorded, restoration not tested')

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

    def bootstrap(self):
        self.preflight()
        catalog = json.loads((self.work / 'catalog.json').read_text())
        require(catalog.get('ready'), 'Import bundle first')
        item = next(row for row in catalog['charts'] if row['id'] == 'pxeye')
        directory = self.work / 'bootstrap'; directory.mkdir(exist_ok=True)
        chart = self.pull_chart(item, directory)
        values = {'storageClass': self.config.get('storage_class') or '',
                  'nico': {'enabled': True, 'allowClusterResources': True}}
        values = merge(values, self.config.get('pxeye_values', {}))
        path = directory / 'values.yaml'; path.write_text(yaml.safe_dump(values)); path.chmod(0o600)
        release = self.config.get('pxeye_release') or self.config['namespace'] + '-pxeye'
        require(NAME.fullmatch(release), 'Invalid PXEye release')
        phase = {'id': 'pxeye', 'release': release, 'chart': str(chart.relative_to(self.work)),
                 'values': [str(path.relative_to(self.work))]}
        rendered = self.helm_run(['template', release, str(chart), '-n', self.config['namespace'], '-f', str(path)], 'pxeye-render', private=True).stdout
        self.check_images(rendered, catalog)
        self.check_ownership(self.work, phase)
        self.helm_run(['upgrade', '--install', release, str(chart), '-n', self.config['namespace'], '--create-namespace',
                       '--wait', '--timeout', '900s', '-f', str(path)], 'pxeye-bootstrap', private=True, timeout=960)
        print('PXEYE_HELM_READY; existing non-Helm PXEye is never automatically adopted')


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
        require(result.returncode == 0, 'Registry discovery cannot read target namespace workloads')
        return json.loads(result.stdout) if result.stdout.strip() else {}

    # No subnet scan or public image-Registry enumeration. Use the existing PXEye
    # image authority and private-IP/loopback image authorities in this namespace.
    objects = read(['-n', args.namespace, 'get', 'pods,deployments', '-o', 'json'])
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
    require(candidates, 'No Registry candidate found; use --registry-url to specify the site endpoint')
    require(len(candidates) <= 16, 'Too many Registry candidates; use --registry-url to select the site endpoint')
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
            '; check probe results or select explicitly with --registry-url')
    selected = next(iter(found))
    print('REGISTRY_DETECTED', selected, flush=True)
    return selected, {'sources': {key: sorted(value) for key, value in candidates.items()}, 'probes': probes}


def select_restore_context(config_path):
    if config_path.exists():
        context = json.loads(config_path.read_text()).get('context')
        require(context, 'Existing config has no context; inspect it before continuing')
        return context
    result = subprocess.run(['kubectl', 'config', 'get-contexts', '-o', 'name'],
                            capture_output=True, text=True, timeout=15)
    require(result.returncode == 0, 'Cannot read local kubeconfig contexts')
    contexts = [name for name in result.stdout.splitlines() if name.startswith('kind-')]
    require(len(contexts) == 1, 'Expected one Kind context; select explicitly with --context')
    return contexts[0]


def finish_site_preflight(args):
    Onsite(args.output).preflight()
    if args.activation_file:
        args.activation_file.write_text('export CONTEXT=' + shlex.quote(args.context) + '\n' +
                                        'export NICO_NAMESPACE=' + shlex.quote(args.namespace) + '\n')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    unpack_parser = sub.add_parser('unpack', help='Verify and safely unpack a delivered archive')
    for name in ('archive', 'checksums', 'output'): unpack_parser.add_argument('--' + name, type=Path, required=True)
    for action in ('write-config', 'prepare-site'):
        automatic = action == 'prepare-site'
        config = sub.add_parser(action, help='Create restore configuration and preflight' if automatic else 'Create a site config, never overwrite')
        for option, variable, kind in [('output', 'CONFIG', Path), ('context', 'CONTEXT', str),
                                       ('bundle', 'BUNDLE', Path), ('work-directory', 'WORK', Path)]:
            config.add_argument('--' + option, type=kind, required=not automatic,
                                default=os.environ.get(variable) if automatic else None)
        config.add_argument('--namespace', default=os.environ.get('NICO_NAMESPACE', 'nico-system') if automatic else 'nico-system')
        config.add_argument('--release-prefix', default=None if automatic else 'nico')
        if automatic:
            config.add_argument('--activation-file', type=Path, help=argparse.SUPPRESS)
        else:
            config.add_argument('--restore', action='store_true')
        config.add_argument('--registry-url', help='Explicit Registry endpoint; omit to discover from the selected cluster')
        config.add_argument('--ca-file', type=Path)
        config.add_argument('--skip-tls-verify', action='store_true')
        config.add_argument('--docker-config-directory', type=Path)
    backup = sub.add_parser('backup', help='Cold-copy stopped Postgres/Vault PVCs from a confirmed Kind node')
    backup.add_argument('--config', type=Path, required=True)
    backup.add_argument('--engine', choices=('podman', 'docker'), required=True)
    backup.add_argument('--node', required=True)
    for name in ('preflight', 'import', 'recipe', 'ui-package', 'bootstrap', 'install'):
        command = sub.add_parser(name); command.add_argument('--config', type=Path, required=True)
        if name == 'install':
            command.add_argument('--phase', default='all')
            command.add_argument('--resume-failed', action='store_true')
    args = parser.parse_args()
    if args.action == 'unpack': return unpack(args)
    if args.action in ('write-config', 'prepare-site'):
        automatic = args.action == 'prepare-site'
        if automatic:
            for field, variable in [('output', 'CONFIG'), ('bundle', 'BUNDLE'), ('work_directory', 'WORK')]:
                require(getattr(args, field), 'Missing ' + variable + '; activate environment.sh first')
            if not args.context:
                args.context = select_restore_context(args.output)
                print('CONTEXT_SELECTED', args.context, flush=True)
            args.restore = True
            if not args.release_prefix:
                result = subprocess.run([str(args.bundle / 'tools/helm'), '--kube-context', args.context,
                                         '-n', args.namespace, 'list', '--all', '-o', 'json'],
                                        capture_output=True, text=True, timeout=60)
                require(result.returncode == 0, 'Cannot read existing Helm releases in selected context/namespace')
                releases = [row['name'] for row in json.loads(result.stdout) if row['chart'].startswith('nico-')]
                require(len(releases) == 1, 'Expected one existing NICo Core release; use --release-prefix to select explicitly')
                args.release_prefix = releases[0]
            if args.output.exists():
                existing = json.loads(args.output.read_text())
                expected = {'context': args.context, 'namespace': args.namespace, 'release_prefix': args.release_prefix,
                            'bundle': str(args.bundle.resolve()), 'work_directory': str(args.work_directory.resolve()),
                            'mode': 'restore'}
                require(all(existing.get(key) == value for key, value in expected.items()),
                        'Existing config targets different inputs; inspect it or choose a new CONFIG/WORK')
                registry = existing.get('registry', {})
                require(registry.get('skip_tls_verify', False) == args.skip_tls_verify,
                        'Existing Registry TLS policy differs; use matching options or a new CONFIG/WORK')
                for key, supplied in [('url', args.registry_url), ('ca_file', args.ca_file),
                                      ('docker_config_directory', args.docker_config_directory)]:
                    if supplied is not None:
                        value = str(supplied.resolve()) if isinstance(supplied, Path) else supplied
                        require(registry.get(key) == value, 'Existing Registry option differs: ' + key)
                print('REUSE_SITE_CONFIG', args.output, flush=True)
                finish_site_preflight(args)
                return
        require(not args.output.exists(), 'Configuration exists; not overwriting')
        document = json.loads((HOME / 'site-config.example.json').read_text())
        document.update(context=args.context, namespace=args.namespace, release_prefix=args.release_prefix,
                        bundle=str(args.bundle.resolve()), work_directory=str(args.work_directory.resolve()),
                        mode='restore' if args.restore else 'new')
        registry_url, discovery = (args.registry_url, None) if args.registry_url else detect_registry(args)
        document['registry'].update(url=registry_url, skip_tls_verify=args.skip_tls_verify,
                                    ca_file=str(args.ca_file.resolve()) if args.ca_file else None,
                                    docker_config_directory=str(args.docker_config_directory.resolve()) if args.docker_config_directory else None)
        if discovery:
            document['registry']['discovery'] = discovery
        write_json(args.output, document)
        print('SITE_CONFIG_CREATED', args.output, flush=True)
        if automatic:
            finish_site_preflight(args)
        return
    onsite = Onsite(args.config)
    if args.action == 'backup': onsite.cold_backup(args.engine, args.node)
    elif args.action == 'preflight': onsite.preflight()
    elif args.action == 'import': onsite.import_bundle()
    elif args.action == 'recipe': onsite.prepare_recipe()
    elif args.action == 'ui-package': onsite.preflight(); onsite.ui_package()
    elif args.action == 'bootstrap': onsite.bootstrap()
    elif args.action == 'install': onsite.install(args.phase, args.resume_failed)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, tarfile.TarError, yaml.YAMLError) as error:
        raise SystemExit(str(error)) from None
