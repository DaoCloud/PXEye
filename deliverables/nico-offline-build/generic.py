"""Build immutable materials, then render a site using the shared recipe functions."""
import argparse
import ast
from datetime import datetime, timezone
import errno
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse

import build as b

PROFILE = 'e703126e4-core-single-node'


def toolkit_source(row):
    path = b.REPO / row['source']
    return path if path.is_file() else b.BUILD_HOME / row['target']


def validation_site(package):
    """Transient render inputs, never a deployment configuration."""
    return {
        'bundle_id': package['bundle_id'], 'site_name': 'Build validation only',
        'namespace': 'nico-system', 'release_prefix': 'nico',
        'registry': 'registry.example.invalid:5000', 'repository_prefix': 'nico-offline',
        'context': 'kind-validation', 'kind_node': 'validation-control-plane',
        'service_cidr': '10.96.0.0/12',
        'service_ips': {'dns': '10.96.40.10', 'pxe': '10.96.40.11', 'ntp': '10.96.40.12'},
        'host_network': {'name': 'host_boot', 'prefix': '192.0.2.0/24', 'gateway': '192.0.2.1', 'mtu': 1500},
        'bundle_host_path': '/home/kind/nico-bundles', 'node_port': 31808,
        **{purpose: {**package[purpose], 'source_image': 'archive.local/pxeye:' + package[purpose]['tag']} for purpose in ('ui', 'bootstrap')},
    }


def settings_for(config, version, extra):
    return {
        'namespace': config['namespace'], 'release_prefix': config['release_prefix'],
        'site_name': config['site_name'], 'version': version,
        'dns_ip': config['service_ips']['dns'], 'ntp_ip': config['service_ips']['ntp'],
        'pxe_ip': config['service_ips']['pxe'], 'bootstrap_image': extra[1]['image'],
    }


def targets_for(extra, config):
    return [{**row, 'image': config['registry'] + '/nico/pxeye:' + row['tag']} for row in extra]


def recipe_tools(bundle, config, version):
    for name in ('import-oci-bundle.py',):
        shutil.copyfile(b.REPO / 'tools' / name, bundle / 'tools' / name)
    for name in ('verify-bundle.py', 'import-pxeye-images.py', 'prepare-auth.py'):
        shutil.copyfile(b.REPO / 'tools/offline-field' / name, bundle / 'tools' / name)
    params = {'BUNDLE_ID': config['bundle_id'], 'VERSION': version,
              'RELEASE': config['release_prefix'], 'NAMESPACE': config['namespace'],
              'SITE_NAME': repr(config['site_name'])}
    for name in ('deployment-client', 'verify-core'):
        text = (b.REPO / 'tools/offline-field' / (name + '.py.in')).read_text()
        for key, value in params.items():
            text = text.replace('@@' + key + '@@', value)
        b.require('@@' not in text, 'Unresolved helper token')
        ast.parse(text)
        b.write(bundle / 'tools' / (name + '.py'), text)


def archive_delivery(stage, bundle, bundle_id, version, revision):
    print('ARCHIVE', flush=True)
    archive = stage / 'bundle.tar.gz'
    b.pack_tree(bundle, archive, bundle_id)
    print('HASH_ARCHIVE', flush=True)
    digest = b.sha(archive)
    print('VERIFY_ARCHIVE_CONTENTS', flush=True)
    rows = json.loads((bundle / 'manifests/file-inventory.json').read_text())['files']
    packed = {r['path']: r for r in rows}
    inv = bundle / 'manifests/file-inventory.json'
    packed['manifests/file-inventory.json'] = {'sha256': b.sha(inv), 'bytes': inv.stat().st_size}
    seen = set()
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if member.isdir():
                continue
            name = b.safe_name(member.name)
            b.require(member.isfile() and name.startswith(bundle_id + '/'), 'Unexpected archive member')
            relative = name[len(bundle_id) + 1:]
            b.require(relative in packed and relative not in seen and member.size == packed[relative]['bytes'], 'Archive inventory mismatch: ' + relative)
            seen.add(relative)
            h = hashlib.sha256()
            with tar.extractfile(member) as stream:
                for block in iter(lambda: stream.read(8 * 1024**2), b''):
                    h.update(block)
            b.require(h.hexdigest() == packed[relative]['sha256'], 'Archive checksum mismatch: ' + relative)
    b.require(seen == set(packed), 'Missing archive members')
    b.write(stage / 'SHA256SUMS', digest + '  bundle.tar.gz\n')
    b.dump(stage / 'build-result.json', {
        'bundle_id': bundle_id, 'version': version, 'source_revision': revision,
        'kind': 'nico-materials', 'recipe_ready': False, 'image_count': 25,
        'archive_sha256': digest, 'archive_bytes': archive.stat().st_size,
    })


def build_generic(args, document):
    b.require(set(document) == {'schema_version', 'build', 'package', 'files'}, 'Schema 3 contains build/package/files; site parameters belong to configure.py')
    package = document['package']
    b.require(set(package) == {'bundle_id', 'ui', 'bootstrap'}, 'Invalid package fields')
    for purpose in ('ui', 'bootstrap'):
        b.require(set(package[purpose]) == {'archive', 'tag', 'digest'}, 'Package images declare archive/tag/digest; OCI source names are read from the archive')
    b.require(set(document['build']) == {'source_bundle', 'output_root'}, 'Invalid build paths')
    b.require(all(Path(v).is_absolute() for v in document['build'].values()), 'Use absolute build paths')
    config = b.parse_config(args.config.resolve(), validation_site(package))
    plan = b.load_plan(document, config)
    b.verify_repository_inputs(plan)
    source = (args.source_bundle or Path(document['build']['source_bundle'])).resolve()
    if args.plan:
        print('MODE materials-only;现场参数不参与构建')
        b.print_plan(plan, config, source)
        return
    if args.check_inputs:
        b.verify_declared_inputs(plan, config, source)
        print('INPUTS_READY', 'files=' + str(len(plan['inputs'])), 'full_content_hashes_are_verified_during_build', flush=True)
        return
    b.require(args.helm, 'Helm 3 is required for build-time render validation')
    version = args.version or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    b.require(re.fullmatch(r'[A-Za-z0-9._-]{1,100}', version), 'Unsafe build version')
    revision = args.source_revision
    if not revision:
        marker = b.BUILD_HOME / 'source-revision.txt'
        revision = marker.read_text().strip() if marker.is_file() else b.run(['git', '-C', str(b.REPO), 'rev-parse', 'HEAD']).strip()
    b.require(re.fullmatch('[0-9a-f]{40}', revision), 'Use a full committed source revision')
    output = (args.output or Path(document['build']['output_root']) / version).resolve()
    b.require(not output.exists() and not output.is_relative_to(source) and not source.is_relative_to(output), 'Output must be new and outside source')
    b.require(not output.is_relative_to(b.REPO) and not b.REPO.is_relative_to(output), 'Keep artifacts outside the source checkout')
    output.parent.mkdir(parents=True, exist_ok=True)
    size = sum(row['bytes'] for row in plan['inputs'])
    b.require(shutil.disk_usage(output.parent).free > size * 2 + 2 * 1024**3, 'Insufficient build space')
    with (output.parent / ('.' + output.name + '.lock')).open('a') as lock:
        b.fcntl.flock(lock, b.fcntl.LOCK_EX | b.fcntl.LOCK_NB)
        b.require(not output.exists(), 'Output already exists')
        b.verify_declared_inputs(plan, config, source)
        stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.building-', dir=output.parent))
        try:
            bundle = stage / 'bundle'
            for name in ('images', 'manifests', 'tools', 'docs', 'config', 'deployment/charts', 'deployment/patches'):
                (bundle / name).mkdir(parents=True, exist_ok=True)
            print('VERIFY_INPUT_OCI', flush=True)
            records = json.loads((source / 'manifests/images-lock.json').read_text())
            b.require({r['image']: r['amd64_manifest'] for r in records} == plan['base_image_manifests'], 'Base lock differs from file plan')
            base_images = b.oci_check(source / 'images/nico-amd64.oci.tar', records)
            b.require(b.sha(source / 'images/nico-amd64.oci.tar') == b.OCI_SHA, 'Base OCI mismatch')
            extra = []
            for purpose in ('ui', 'bootstrap'):
                image = config[purpose]
                with tarfile.open(image['archive'], 'r:') as archive:
                    with archive.extractfile('index.json') as stream:
                        index = json.load(stream)
                references = [r.get('annotations', {}).get('org.opencontainers.image.ref.name') for r in index['manifests'] if r.get('digest') == image['digest']]
                b.require(len(references) == 1 and references[0], 'Extra OCI must have one named manifest matching the configured digest')
                image['source_image'] = references[0]
                verified = b.oci_check(Path(image['archive']), reference=image['source_image'])[0]
                b.require(verified['digest'] == image['digest'], 'Extra image manifest mismatch')
                extra.append({k: image[k] for k in ('source_image', 'tag', 'digest')} | {
                    'archive': 'images/pxeye-' + image['tag'] + '.oci.tar', 'purpose': purpose})
            print('COPY_VERIFIED_MATERIALS', len(plan['inputs']), flush=True)
            for row in plan['inputs']:
                if row['role'] == 'nico_chart':
                    continue
                original = source / row['source'] if row['root'] == 'bundle' else Path(config[row['role']]['archive'])
                b.require(original.stat().st_size == row['bytes'] and b.sha(original) == row['sha256'], 'Input checksum mismatch: ' + row['source'])
                target = bundle / row['target']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
            with tempfile.TemporaryDirectory(dir=stage) as temporary:
                b.patch_core(source, bundle / 'deployment', Path(temporary))
            for row in plan['toolkit']:
                target = bundle / 'deployment-kit' / row['target']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(toolkit_source(row), target)
            for name in plan['repository']:
                target = bundle / 'deployment-kit' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(b.REPO / name, target)
            b.write(bundle / 'deployment-kit/source-revision.txt', revision + '\n')
            shutil.copyfile(b.BUILD_HOME / 'site-config.example.json', bundle / 'config/site-config.example.json')
            for name, lang in (('CONFIGURE.md', 'CONFIGURE.md'), ('CONFIGURE.zh-CN.md', 'CONFIGURE.zh-CN.md')):
                shutil.copyfile(b.BUILD_HOME / lang, bundle / 'docs' / name)
            shutil.copyfile(b.REPO / 'tools/offline-field/verify-bundle.py', bundle / 'tools/verify-bundle.py')
            b.dump(bundle / 'manifests/deployment-images-lock.json', extra)
            b.dump(bundle / 'manifests/materials-input-lock.json', [r for r in plan['inputs'] if r['role'] == 'material'])
            b.dump(bundle / 'manifests/build-file-plan.json', {'inputs': plan['inputs'], 'generated': plan['generated'], 'source_revision': revision})
            # This render only proves that the locked templates compose. These
            # documentation-only addresses never become a deployable recipe.
            with tempfile.TemporaryDirectory(dir=stage) as temporary:
                scratch = Path(temporary)
                rendered = scratch / 'render';rendered.mkdir()
                (rendered / 'manifests').mkdir()
                shutil.copyfile(bundle / 'manifests/images-lock.json', rendered / 'manifests/images-lock.json')
                bound = targets_for(extra, config)
                manifest = b.prepare_recipe(rendered, config, version, settings_for(config, version, bound), scratch, source, bundle / 'deployment')
                locked = {config['registry'] + '/' + config['repository_prefix'] + '/' + r['image'] for r in records} | {r['image'] for r in bound}
                report = b.validate_render(rendered, manifest, config, args.helm, scratch, locked)
            b.dump(bundle / 'manifests/build-report.json', {
                'profile': PROFILE, 'source_revision': revision, 'base_archive_sha256': b.OCI_SHA,
                'base_images': base_images, 'extra_images': extra,
                'validation_render': report, 'validation_only': True,
                'builder_sha256': b.sha(b.BUILD_HOME / 'build.py'),
                'source_assets': {name: b.sha(b.REPO / name) for name in plan['repository']},
                'toolkit_assets': {row['target']: b.sha(toolkit_source(row)) for row in plan['toolkit']},
                'configuration_sha256': b.sha(args.config),
            })
            b.dump(bundle / 'bundle.json', {'schema_version': 2, 'id': package['bundle_id'],
                'name': 'NICo reusable offline materials', 'kind': 'nico-materials', 'profile': PROFILE,
                'version': version, 'architecture': 'linux/amd64', 'recipe_ready': False,
                'image_archive': 'images/nico-amd64.oci.tar', 'image_lock': 'manifests/images-lock.json'})
            b.inventory(bundle)
            expected = {r['target'] for r in plan['inputs']} | set(plan['generated'])
            actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
            b.require(actual == expected, 'Output differs from file plan: missing=' + str(sorted(expected - actual)) + '; extra=' + str(sorted(actual - expected)))
            b.verify(bundle)
            archive_delivery(stage, bundle, package['bundle_id'], version, revision)
            stage.rename(output)
            print('BUILD_COMPLETE', output, flush=True)
        except BaseException:
            print('BUILD_FAILED; staging retained at', stage, flush=True)
            raise


def read_site(path, extra):
    document = json.loads(path.read_text())
    b.require(set(document) == {'schema_version', 'site', 'registry_access', 'storage_class'} and document['schema_version'] == 1, 'Invalid site configuration sections')
    def missing(value, prefix=''):
        result = []
        if isinstance(value, dict):
            for key, child in value.items():
                result += missing(child, prefix + '.' + key if prefix else key)
        elif value is None or value == '':
            result.append(prefix)
        return result
    b.require(not missing(document), 'Set the onsite fields before initialization: ' + ', '.join(missing(document)))
    site = dict(document['site'])
    b.require('ui' not in site and 'bootstrap' not in site, 'Site configuration must not change locked images')
    for row in extra:
        site[row['purpose']] = {k: row[k] for k in ('source_image', 'tag', 'digest')} | {'archive': row['archive']}
    site = b.parse_config(path, site)
    b.require(re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}', document['storage_class']), 'Invalid StorageClass')
    site['storage_class'] = document['storage_class']
    access = document['registry_access']
    b.require(set(access) == {'push_url', 'pull_url', 'insecure'} and type(access['insecure']) is bool, 'Invalid registry_access')
    for key in ('push_url', 'pull_url'):
        u = urllib.parse.urlsplit(access[key])
        b.require(u.scheme in ('http', 'https') and re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', u.netloc) and not u.path and not u.query and not u.fragment and u.username is None and (u.port is None or 1 <= u.port <= 65535), 'Use an explicit http(s)://host:port without credentials/path: ' + key)
    # This profile's importer has no registry authentication input. Do not
    # accept credentials in JSON or silently bypass an auth challenge.
    return site, access


def site_docs(bundle, config, access, version):
    text = (b.REPO / 'tools/offline-field/INSTALL.site.md.in').read_text()
    params = {'BUNDLE_ID': config['bundle_id'], 'VERSION': version,
        'NAMESPACE': config['namespace'], 'RELEASE': config['release_prefix'],
        'PXEYE': config['namespace'] + '-pxeye', 'REGISTRY': config['registry'],
        'REPO_PREFIX': config['repository_prefix'], 'CONTEXT': config['context'],
        'NODE': config['kind_node'], 'HOST_PATH': config['bundle_host_path'],
        'NODE_PORT': str(config['node_port']), 'STORAGE_CLASS': config['storage_class'],
        'PUSH_URL': access['push_url'], 'PULL_URL': access['pull_url'],
        'INSECURE': '--insecure' if access['insecure'] else '',
        'CURL_TLS': '-k' if access['insecure'] else '',
        'SKIP_VERIFY': 'true' if access['insecure'] else 'false',
        'SKIP_VERIFY_PY': 'True' if access['insecure'] else 'False'}
    for key, value in params.items():
        text = text.replace('@@' + key + '@@', value)
    b.require('@@' not in text, 'Unresolved onsite documentation token')
    b.write(bundle / 'docs/INSTALL.md', text)


def configure_main():
    parser = argparse.ArgumentParser(description='Render a new site tree; hard-link immutable materials without copying or recompressing them.')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--site-config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--helm', default=shutil.which('helm'))
    args = parser.parse_args()
    source = args.bundle.resolve();output = args.output.resolve()
    b.require(source.is_dir() and not output.exists(), 'Use an existing materials bundle and a new site output directory')
    b.require(not output.is_relative_to(source) and not source.is_relative_to(output), 'Keep site output outside source materials')
    b.require(not output.is_relative_to(b.REPO), 'Keep site outputs outside the Git/toolkit directory')
    descriptor = json.loads((source / 'bundle.json').read_text())
    report = json.loads((source / 'manifests/build-report.json').read_text())
    b.require(report.get('profile') == PROFILE, 'Only the verified e703 Core builder layout is supported; do not use raw or unknown field bundles')
    b.require(descriptor.get('architecture') == 'linux/amd64', 'Only linux/amd64 controller images are supported')
    extra = json.loads((source / 'manifests/deployment-images-lock.json').read_text())
    b.require(len(extra) == 2 and {r['purpose'] for r in extra} == {'ui', 'bootstrap'}, 'Both locked PXEye archives are required')
    extra = sorted(extra, key=lambda row: row['purpose'] != 'ui')
    for row in extra:
        row.setdefault('tag', row.get('image', '').rsplit(':', 1)[-1])
        b.require(row['archive'] == 'images/pxeye-' + row['tag'] + '.oci.tar', 'Unexpected extra archive path')
    config, access = read_site(args.site_config.resolve(), extra)
    b.require(output.name == config['bundle_id'] and config['bundle_id'] != descriptor['id'], 'Output basename must equal site.bundle_id and differ from the materials id')
    helm = args.helm or str(source / 'tools/helm')
    b.require(Path(helm).is_file() or shutil.which(helm), 'Helm 3 is required on the machine performing initialization')
    print('VERIFY_SOURCE_MATERIALS (hashes may take time; no files are copied)', flush=True)
    b.verify(source)
    source_inventory = json.loads((source / 'manifests/file-inventory.json').read_text())
    indexed = {row['path']: row for row in source_inventory['files']}
    b.require(indexed.get('images/nico-amd64.oci.tar', {}).get('sha256') == b.OCI_SHA, 'Unsupported base OCI')
    records = json.loads((source / 'manifests/images-lock.json').read_text())
    b.require(len(records) == 23 and len({r['image'] for r in records}) == 23, 'Expected 23 distinct base images')
    output.parent.mkdir(parents=True, exist_ok=True)
    b.require(output.parent.stat().st_dev == source.stat().st_dev, 'Use the same filesystem for materials and site output; hard links must not fall back to large copies')
    version = str(descriptor['version']) + '-site-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with (output.parent / ('.' + output.name + '.lock')).open('a') as lock:
        b.fcntl.flock(lock, b.fcntl.LOCK_EX | b.fcntl.LOCK_NB)
        b.require(not output.exists(), 'Site output already exists; choose a new id/output')
        stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.configuring-', dir=output.parent))
        try:
            for folder in ('images', 'tools', 'manifests', 'config', 'docs'):
                (stage / folder).mkdir()
            linked = []
            for relative, row in indexed.items():
                if relative.split('/')[0] not in ('images', 'boot', 'dpu', 'http', 'source') and relative not in ('tools/helm', 'tools/nico-admin-cli'):
                    continue
                target = stage / b.safe_name(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                b.require((source / relative).stat().st_mode & 0o004, 'Immutable material must be readable by the non-root PXEye Pod: ' + relative)
                try:
                    b.os.link(source / relative, target)
                except OSError as error:
                    if error.errno == errno.EXDEV:
                        raise ValueError('Materials and output must use the same filesystem; no large-copy fallback') from None
                    raise
                linked.append(relative)
            b.require({'images/nico-amd64.oci.tar', 'tools/helm', 'tools/nico-admin-cli'} | {r['archive'] for r in extra} <= set(linked), 'Required material missing from inventory')
            shutil.copyfile(source / 'manifests/images-lock.json', stage / 'manifests/images-lock.json')
            bound = targets_for(extra, config)
            b.dump(stage / 'manifests/deployment-images-lock.json', bound)
            with tempfile.TemporaryDirectory(dir=stage) as temporary:
                scratch = Path(temporary)
                manifest = b.prepare_recipe(stage, config, version, settings_for(config, version, bound), scratch, source, source / 'deployment')
                b.prepare_bootstrap(stage, config, settings_for(config, version, bound), bound[0])
                recipe_tools(stage, config, version)
                locked = {config['registry'] + '/' + config['repository_prefix'] + '/' + r['image'] for r in records} | {r['image'] for r in bound}
                rendered = b.validate_render(stage, manifest, config, helm, scratch, locked)
            site_docs(stage, config, access, version)
            b.dump(stage / 'config/site-config.json', json.loads(args.site_config.read_text()))
            b.dump(stage / 'manifests/build-report.json', {
                'profile': PROFILE, 'source_version': descriptor['version'],
                'source_inventory_sha256': b.sha(source / 'manifests/file-inventory.json'),
                'site_configuration_sha256': b.sha(args.site_config), 'render': rendered,
                'material_reuse': 'hardlink', 'hardlinked_files': linked,
            })
            b.dump(stage / 'bundle.json', {'schema_version': 2, 'id': config['bundle_id'],
                'name': config['site_name'], 'version': version, 'architecture': 'linux/amd64',
                'recipe_directory': 'deployment', 'recipe_ready': True,
                'image_archive': 'images/nico-amd64.oci.tar', 'image_lock': 'manifests/images-lock.json'})
            # mkdtemp creates0700. The final tree is mounted into a UID1000
            # Pod, so normalize only the newly created directories/files,
            # never chmod a material inode shared with the source bundle.
            stage.chmod(0o755)
            for path in stage.rglob('*'):
                if path.is_dir():
                    path.chmod(0o755)
                elif path.relative_to(stage).as_posix() not in linked:
                    path.chmod(0o644 | (path.stat().st_mode & 0o111))
            b.inventory(stage)
            b.verify(stage)
            stage.rename(output)
            print('SITE_CONFIGURED', output, 'reused_files=' + str(len(linked)), 'large_bytes_copied=0 archive_recompressed=false', flush=True)
        except BaseException:
            print('CONFIGURE_FAILED; staging retained at', stage, flush=True)
            raise
