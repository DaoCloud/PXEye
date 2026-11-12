#!/usr/bin/env python3
"""One-command offline delivery: export images, prepare Charts, package and verify."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os
import hashlib
import platform

import yaml

HOME = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HOME / 'material-prepare'))
import containerd_export
sys.path.insert(0, str(HOME))
import build_config
import arm_materials
sys.path.insert(0, str(HOME / 'helm-bundle'))
import assembly


def load_packager():
    spec = importlib.util.spec_from_file_location('offline_delivery_packager', HOME / 'helm-bundle/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pxeye_image():
    """The parent Chart owns the explicit PXEye image reference."""
    values = yaml.safe_load((HOME.parent / 'charts/pxeye/values.yaml').read_text())
    image = values.get('image') if isinstance(values, dict) else None
    if not isinstance(image, str) or not image:
        raise ValueError('Set charts/pxeye/values.yaml image to the complete PXEye registry reference')
    return image


def chart_images(path, package_value, packager, ui=None, material_records=None):
    """Render the locked parent Chart and write its exact containerd requirements."""
    work = package_value['work_directory']
    charts = packager.chart_sources.prepare(work, package_value['sources'].get('charts'), packager.b, helm=package_value['tools']['helm'])
    ui = ui or pxeye_image()
    with tempfile.TemporaryDirectory(prefix='.parent-discovery-', dir=work) as temporary:
        temporary = Path(temporary)
        root = packager.stage_charts(
            temporary / 'bundle', temporary, {'__ui__': ui, ui: ui}, {}, ui, [],
            charts / 'deployment/charts', package_value['tools']['helm'],
            material_records=material_records,
        )['pxeye']
        settings = {'release_prefix': 'nico', 'namespace': 'nico-system', 'site_name': 'Build validation',
                    'dns_ip': '10.96.40.10', 'pxe_ip': '10.96.40.11', 'ntp_ip': '10.96.40.12'}
        values = packager.b.substitute((root / 'values.yaml').read_text(), settings)
        value_path = temporary / 'values.yaml'; value_path.write_text(values)
        result = packager.command([package_value['tools']['helm'], 'template', 'pxeye', root, '--namespace', 'nico-system', '-f', value_path],
                                  temporary / 'render.log')
        images = set()
        def walk(value):
            if isinstance(value, dict):
                if isinstance(value.get('image'), str): images.add(value['image'])
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(list(yaml.safe_load_all(result.stdout)))
    if not images:
        raise ValueError('Parent Chart render did not produce image references')
    target = work / 'generated' / 'resolved-images.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join(image + '\n' for image in sorted(images)))
    print('CHART_IMAGE_CLOSURE', len(images), target, flush=True)
    return target


def seeded_roles(package_value):
    source, descriptor, rows, roles, _ = assembly.inputs(package_value)
    return source, roles


def require_seed_matches(source, generated):
    expected = {line.strip() for line in generated.read_text().splitlines() if line.strip()}
    actual = {line.strip() for line in (source / 'manifests/images.txt').read_text().splitlines() if line.strip()}
    if expected != actual:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise ValueError('Cached image closure differs from the parent Chart; run delivery.py --seed-cache before building. Missing: ' +
                         ', '.join(missing) + '; extra: ' + ', '.join(extra))


def cache_reference(reference, registry):
    """Replace only the registry hostname; PXEye itself is published as pxeye."""
    parts = reference.split('/')
    repository = '/'.join(parts[1:]) if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost') else reference
    if 'mmzhou-os-install-console' in repository:
        tag = reference.rsplit(':', 1)[-1] if ':' in reference.rsplit('/', 1)[-1] else 'latest'
        return registry + '/pxeye:' + tag
    return registry + '/' + repository


def registry_settings():
    """Return the configured cache Registry address and its TLS mode."""
    registry = os.environ.get('REGISTRY', '').strip().removeprefix('http://').removeprefix('https://').rstrip('/')
    if not registry or '/' in registry:
        raise ValueError('Set REGISTRY to a registry host[:port], for example REGISTRY=127.0.0.1:1027')
    insecure = os.environ.get('REGISTRY_INSECURE', 'true').lower() in ('1', 'true', 'yes')
    return registry, insecure


def image_repository(reference):
    """Return a Docker repository without a mutable tag or digest."""
    value = reference.split('@', 1)[0]
    prefix, slash, tail = value.rpartition('/')
    if ':' in tail:
        tail = tail.rsplit(':', 1)[0]
    return (prefix + slash if slash else '') + tail


def registry_digest(docker, runner_image, reference, insecure):
    """Read a Registry manifest digest using the pinned PXEye tool image.

    The build host is intentionally not required to have skopeo installed.
    PXEye contains skopeo, and Docker has already obtained ``runner_image``
    from the same configured Registry before this helper is used.
    """
    command = [docker, 'run', '--rm', '--network', 'host', '--user', '0:0', '--entrypoint', 'skopeo', runner_image,
               'inspect', '--tls-verify=' + ('false' if insecure else 'true'), '--format', '{{.Digest}}',
               'docker://' + reference]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Cannot read Registry digest for ' + reference + ': ' + result.stderr[-1000:].strip())
    digest = result.stdout.strip()
    if arm_materials.DIGEST.fullmatch(digest) is None:
        raise ValueError('Registry returned an invalid image digest for ' + reference + ': ' + digest)
    return digest


def material_record(material, *, reference, digest, image_content, base_digest, initializer_sha256,
                    definition_sha256):
    """Return the final delivery record without polluting image identity.

    ``source`` and ``runtime`` describe provenance and consumption in the
    delivery manifest only.  The image tag remains solely a function of the
    immutable payload, recipe, base manifest, initializer and image definition.
    """
    return material.as_manifest() | {
        'image': reference,
        'digest': digest,
        'image_content_id': image_content,
        'base_digest': base_digest,
        'initializer_sha256': initializer_sha256,
        'image_definition_sha256': definition_sha256,
        'source': {'directory': str(material.source_dir), 'layout': 'direct-aarch64-file-set'},
        'runtime': {
            'init_container': 'boot-artifacts-aarch64',
            'destination': '/forge-boot-artifacts/blobs/internal/aarch64',
            'http_path': '/public/blobs/internal/aarch64/',
            'chart_value': 'nicoCore.nico-pxe.bootArtifactContainers',
            'consumer': 'nico-pxe',
        },
    }


def require_clean_arm_material_sources():
    """Reject an ARM image publish from uncommitted material implementation.

    ``make bundles`` reaches ARM construction before the existing package
    builder's clean-source gate.  Put the equivalent guard here, before Docker
    receives the payload, so a dirty checkout cannot create a Registry side
    effect and then fail later during packaging.  Unrelated product work is
    intentionally outside this narrow delivery-source list.
    """
    sources = (
        'Makefile',
        'charts/pxeye',
        'deploy/offline-core',
        'offline-build/delivery.py',
        'offline-build/arm_materials.py',
        'offline-build/arm-material-init.py',
        'offline-build/material-prepare/recipe-e703.json',
        'offline-build/helm-bundle/assembly.py',
        'offline-build/helm-bundle/build.py',
        'offline-build/helm-bundle/charts.py',
    )
    result = subprocess.run(
        ['git', '-C', str(HOME.parent), 'status', '--porcelain', '--untracked-files=all', '--', *sources],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError('Cannot verify ARM material build sources are committed: ' + result.stderr[-1000:].strip())
    if result.stdout.strip():
        raise ValueError('Commit ARM material sources before constructing or publishing the material image')


def require_local_linux_amd64():
    """Fail before any Docker mutation when this bundle cannot be built here."""
    machine = platform.machine().lower()
    if sys.platform != 'linux' or machine not in ('x86_64', 'amd64'):
        raise ValueError('ARM material image construction requires a Linux amd64 builder')


def material_dockerfile(base_reference, base_digest):
    """Return the complete, identity-bearing Dockerfile for ARM boot material."""
    return (
        'FROM ' + image_repository(base_reference) + '@' + base_digest + '\n'
        'COPY payload /payload\n'
        'COPY arm-material-init.py /usr/local/bin/arm-material-init\n'
        'USER 0:0\n'
        'ENTRYPOINT ["python3", "/usr/local/bin/arm-material-init"]\n')


def docker_platform(docker, reference):
    """Read a local image platform without depending on Docker's default target."""
    result = subprocess.run([docker, 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', reference],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Cannot inspect local ARM material base image ' + reference + ': ' + result.stderr[-1000:].strip())
    return result.stdout.strip().lower()


def arm_material_record(package_value, registry, insecure, *, allow_build=True):
    """Build or reuse the optional immutable ARM boot-material image.

    This is the one deliberate build/push operation performed by ``bundles``.
    Its reference is content-addressed by the validated payload, initializer and
    immutable PXEye base manifest.  All normal workload images still arrive
    from the pre-populated Registry through the ordinary cache-images flow.
    """
    if allow_build and arm_materials.enabled():
        require_local_linux_amd64()
        require_clean_arm_material_sources()
    material = arm_materials.prepare(package_value['work_directory'])
    if not material.enabled:
        return []

    initializer = HOME / 'arm-material-init.py'
    if not initializer.is_file() or initializer.is_symlink():
        raise ValueError('Missing or unsafe ARM material initializer: ' + str(initializer))
    initializer_sha256 = hashlib.sha256(initializer.read_bytes()).hexdigest()

    lock = arm_materials.read_image_lock(material)
    if not allow_build:
        if lock is None:
            raise ValueError('ARM material plan requires a complete materials-lock.json; run make bundles once without --plan')
        image = lock['image']
        base_digest = image.get('base_digest')
        if arm_materials.DIGEST.fullmatch(str(base_digest)) is None:
            raise ValueError('ARM material plan lock lacks a valid base image digest; run make bundles again')
        definition = material_dockerfile(cache_reference(pxeye_image(), registry), base_digest)
        definition_sha256 = hashlib.sha256(definition.encode()).hexdigest()
        image_content = arm_materials.image_content_id(material, base_digest, initializer_sha256,
                                                       definition_sha256)
        reference = registry + '/pxeye/materials/boot-aarch64:sha-' + image_content
        if (image.get('reference') != reference or image.get('content_id') != image_content or
                image.get('initializer_sha256') != initializer_sha256 or
                image.get('definition_sha256') != definition_sha256 or
                arm_materials.DIGEST.fullmatch(str(image.get('digest'))) is None):
            raise ValueError('ARM material plan lock does not match current inputs; run make bundles without --plan')
        print('REUSE_ARM64_MATERIAL_PLAN', reference, image['digest'], flush=True)
        return [material_record(material, reference=reference, digest=image['digest'], image_content=image_content,
                                base_digest=base_digest, initializer_sha256=initializer_sha256,
                                definition_sha256=definition_sha256)]

    docker = package_value['tools']['docker']
    # The parent Chart can name PXEye through another registry host.  Its
    # cache-images target is always the configured build Registry, which is the
    # only safe base for a no-network material image build.
    base_reference = cache_reference(pxeye_image(), registry)
    print('PREPARE_ARM64_MATERIAL_BASE', base_reference, flush=True)
    pull = subprocess.run([docker, 'pull', '--platform', 'linux/amd64', base_reference], capture_output=True, text=True)
    if pull.returncode:
        protocol = 'HTTP' if insecure else 'HTTPS'
        raise ValueError('Cannot obtain ARM material base image ' + base_reference +
                         '. Publish PXEye with make images first and make Docker trust the ' + protocol +
                         ' Registry: ' + pull.stderr[-1000:].strip())
    base_digest = registry_digest(docker, base_reference, base_reference, insecure)
    if docker_platform(docker, base_reference) != 'linux/amd64':
        raise ValueError('ARM material base image is not linux/amd64: ' + base_reference)
    definition = material_dockerfile(base_reference, base_digest)
    definition_sha256 = hashlib.sha256(definition.encode()).hexdigest()
    image_content = arm_materials.image_content_id(material, base_digest, initializer_sha256,
                                                   definition_sha256)
    reference = registry + '/pxeye/materials/boot-aarch64:sha-' + image_content

    if lock is not None:
        image = lock['image']
        if (image.get('reference') == reference and image.get('content_id') == image_content and
                image.get('base_digest') == base_digest and image.get('initializer_sha256') == initializer_sha256 and
                image.get('definition_sha256') == definition_sha256):
            try:
                actual = registry_digest(docker, base_reference, reference, insecure)
            except ValueError:
                actual = None
            if actual == image.get('digest'):
                print('REUSE_ARM64_MATERIAL_IMAGE', reference, actual, flush=True)
                return [material_record(material, reference=reference, digest=actual, image_content=image_content,
                                        base_digest=base_digest, initializer_sha256=initializer_sha256,
                                        definition_sha256=definition_sha256)]

    # Never build from the network: the precise base has already been pulled
    # from REGISTRY and the Docker build runs without a network namespace.
    material.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.image-', dir=material.cache_dir) as temporary:
        context = Path(temporary)
        payload = context / 'payload/aarch64'
        payload.mkdir(parents=True)
        for item in material.files:
            target = payload / item.target
            shutil.copyfile(item.source, target)
            target.chmod(0o644)
        manifest = material.as_manifest() | {'image_content_id': image_content,
                                              'base_digest': base_digest,
                                              'initializer_sha256': initializer_sha256,
                                              'image_definition_sha256': definition_sha256}
        (context / 'payload/manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        shutil.copyfile(initializer, context / 'arm-material-init.py')
        (context / 'arm-material-init.py').chmod(0o644)
        (context / 'Dockerfile').write_text(definition)
        print('BUILD_ARM64_MATERIAL_IMAGE', reference, flush=True)
        build = subprocess.run([docker, 'build', '--platform', 'linux/amd64', '--pull=false', '--network=none',
                                '--label', 'io.pxeye.offline-material=' + image_content,
                                '--tag', reference, str(context)], capture_output=True, text=True)
        if build.returncode:
            raise ValueError('ARM material image build failed for ' + reference + ': ' + build.stderr[-2000:].strip())

    # Keep the content-addressed Docker tag as a local build cache.  It is safe
    # to retain because the tag is derived from immutable input content, and it
    # avoids repeating the multi-gigabyte material build after an interrupted
    # packaging run.
    print('PUSH_ARM64_MATERIAL_IMAGE', reference, flush=True)
    push = subprocess.run([docker, 'push', reference], capture_output=True, text=True)
    if push.returncode:
        raise ValueError('ARM material image push failed for ' + reference + ': ' + push.stderr[-2000:].strip())
    digest = registry_digest(docker, base_reference, reference, insecure)

    arm_materials.write_image_lock(material, reference=reference, digest=digest,
                                   image_content=image_content, base_digest=base_digest,
                                   initializer_sha256=initializer_sha256,
                                   definition_sha256=definition_sha256)
    print('ARM64_MATERIAL_READY', reference, digest, flush=True)
    return [material_record(material, reference=reference, digest=digest, image_content=image_content,
                            base_digest=base_digest, initializer_sha256=initializer_sha256,
                            definition_sha256=definition_sha256)]


def cache_images(path):
    """Populate REGISTRY from Chart-derived image references; no handwritten image list."""
    registry, insecure = registry_settings()
    raw = build_config.read(path)
    options = containerd_export.DEFAULTS | raw.get('image_export', {})
    packager = load_packager(); package_value = assembly.configuration(path)
    print('DELIVERY_STAGE [cache-images-chart-closure]', flush=True)
    # The material must exist before the first parent Chart render; otherwise
    # the generated closure would omit the initContainer image. PXEye itself is
    # deliberately published by the preceding ``make images`` step.
    material_records = arm_material_record(package_value, registry, insecure)
    image_list = chart_images(path, package_value, packager, material_records=material_records)
    known = set(subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'list', '-q'], capture_output=True, text=True, check=True).stdout.splitlines())
    material_images = {record['image'] for record in material_records}
    for source in [line.strip() for line in image_list.read_text().splitlines() if line.strip()]:
        if source in material_images:
            # arm_material_record has just built, pushed and digest-checked it.
            print('REUSE_ARM64_MATERIAL_CACHE', source, flush=True)
            continue
        if source not in known:
            print('PULL_SOURCE_IMAGE', source, flush=True)
            pull = [options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'pull', '--platform', 'linux/amd64']
            if insecure and cache_reference(source, registry) == source:
                pull.append('--plain-http')
            subprocess.run(pull + [source], check=True)
        target = cache_reference(source, registry)
        print('PUSH_CACHE_IMAGE', source, '->', target, flush=True)
        if source != target:
            subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'tag', source, target], check=True)
        command = [options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'push', '--platform', 'linux/amd64']
        if insecure: command.append('--plain-http')
        subprocess.run(command + [target], check=True)
    print('CACHE_IMAGES_COMPLETE', registry, flush=True)


def containerd_args(options):
    """Return the immutable ctr connection prefix used by this build."""
    return [options['ctr'], '--address', options['containerd_address'],
            '--namespace', options['containerd_namespace']]


def ensure_registry_content(options, source, target, insecure):
    """Pull a Chart image and repair a stale containerd image record if needed.

    ``ctr images pull`` may accept an already-tagged image whose content was
    garbage-collected or copied incompletely. The direct OCI exporter needs the
    complete graph below the configured content store, not merely an image
    record. Verify that graph after every pull; only then use ``content fetch``
    for the requested platform as a bounded repair. This never removes an image
    tag or touches Kubernetes workloads.
    """
    base = containerd_args(options)
    pull = base + ['images', 'pull', '--platform', 'linux/amd64']
    if insecure:
        pull.append('--plain-http')
    subprocess.run(pull + [target], check=True)
    if target != source:
        subprocess.run(base + ['images', 'tag', target, source], check=True)
    try:
        containerd_export.resolve_images(options, [source])
        return
    except (ValueError, KeyError, OSError) as pull_error:
        # A stale tag is a local cache condition, not evidence that the remote
        # Registry lacks the image. Fetch the exact target content once, then
        # re-run the same strict graph validation before proceeding.
        print('REFETCH_REGISTRY_CONTENT', target, 'AS', source, flush=True)
        fetch = base + ['content', 'fetch', '--platform', 'linux/amd64']
        if insecure:
            fetch.append('--plain-http')
        result = subprocess.run(fetch + [target], capture_output=True, text=True)
        if result.returncode:
            raise ValueError('Cannot repair incomplete containerd content for ' + target + ': ' +
                             result.stderr[-1000:].strip()) from pull_error
        if target != source:
            subprocess.run(base + ['images', 'tag', target, source], check=True)
        try:
            containerd_export.resolve_images(options, [source])
        except (ValueError, KeyError, OSError) as error:
            raise ValueError('Registry image remains incomplete in containerd after content fetch: ' +
                             source + ': ' + str(error)) from error


def registry_input(path, package_value, packager, material_records=None):
    """Materialize the Chart closure from REGISTRY into an isolated OCI input.

    containerd is only an export transport here: every image is first pulled from
    REGISTRY and retagged to its Chart reference before the existing OCI exporter
    reads it.  No old offline-images directory or handwritten image list is used.
    """
    registry, insecure = registry_settings()
    material_records = list(material_records or [])
    image_list = chart_images(path, package_value, packager, material_records=material_records)
    references = [line.strip() for line in image_list.read_text().splitlines() if line.strip()]
    identity = hashlib.sha256(json.dumps({'registry': registry, 'images': references,
                                          'materials': material_records}, sort_keys=True).encode()).hexdigest()[:24]
    work = package_value['work_directory'] / 'cache' / 'registry-exports' / identity
    config = work / 'build-config.json'
    raw = build_config.read(path)
    chart_source = str(package_value['sources']['charts'])
    # Registry input is build-private.  Do not reuse the Kubernetes image
    # namespace: an old image record there can make `ctr images pull` report a
    # cache hit even after content GC, and deleting that record would affect
    # running workloads.  This deterministic namespace retains the exact
    # graph for this closure and is distinct for changed inputs.
    image_export = dict(raw.get('image_export', {}))
    image_export['containerd_namespace'] = 'pxeye-offline-' + identity
    generated = {'work_directory': str(work), 'image_export': image_export,
                 'helm_bundle': raw['helm_bundle'] | {'chart_sources': chart_source}}
    work.mkdir(parents=True, exist_ok=True)
    # Registry inputs are isolated from old OCI exports, but upstream Chart
    # archives remain a shared download cache.  Copy only absent complete files;
    # chart_sources.py treats their checksum-named paths as immutable cache hits.
    parent_cache = package_value['work_directory'] / 'cache/charts'
    child_cache = work / 'cache/charts'
    if parent_cache.is_dir():
        child_cache.mkdir(parents=True, exist_ok=True)
        for archive in parent_cache.glob('*.tar.gz'):
            target_archive = child_cache / archive.name
            if not target_archive.exists():
                shutil.copy2(archive, target_archive)
    config.write_text(json.dumps(generated, indent=2) + '\n')
    options = containerd_export.DEFAULTS | generated['image_export']
    for source in references:
        target = cache_reference(source, registry)
        print('PULL_REGISTRY_IMAGE', target, 'AS', source, flush=True)
        ensure_registry_content(options, source, target, insecure)
    print('DELIVERY_STAGE [registry-oci-export]', flush=True)
    containerd_export.run(config, image_list=image_list)
    return config, assembly.configuration(config)


def run(path, plan, version, seed_cache=False):
    path = path.expanduser().resolve()
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or 'work_directory' not in value:
        raise ValueError('Use the shared build-config.json with work_directory')
    packager = load_packager()
    package_value = assembly.configuration(path)
    # ARM payloads are intentionally opt-in.  When enabled, validate/build the
    # content-addressed image before rendering so its initContainer is part of
    # the exact image closure exported and relocated into the final delivery.
    if seed_cache and not arm_materials.enabled():
        material_records = []
    else:
        registry, insecure = registry_settings()
        material_records = arm_material_record(package_value, registry, insecure, allow_build=not plan)
    if seed_cache:
        print('DELIVERY_STAGE [cache-seed-image-closure]', flush=True)
        image_list = chart_images(path, package_value, packager, material_records=material_records)
        existing = package_value['work_directory'] / 'offline-images' / 'manifests' / 'images.txt'
        if existing.is_file():
            expected = {line.strip() for line in image_list.read_text().splitlines() if line.strip()}
            actual = {line.strip() for line in existing.read_text().splitlines() if line.strip()}
            if expected == actual:
                print('CACHE_SEED_REUSED', existing.parent.parent, flush=True)
                return
        print('DELIVERY_STAGE [cache-seed-containerd-export]', flush=True)
        containerd_export.run(path, plan=plan, image_list=image_list)
        print('CACHE_SEED_COMPLETE', package_value['work_directory'] / 'offline-images', flush=True)
        return
    print('DELIVERY_STAGE [registry-input]', flush=True)
    original_work = package_value['work_directory']
    registry_config, package_value = registry_input(path, package_value, packager, material_records=material_records)
    if plan:
        print('DELIVERY_STAGE [package-plan]', flush=True)
        assembly.plan(package_value)
        print('DELIVERY_PLAN_OK', registry_config, flush=True)
        return
    work = package_value['work_directory']
    work.mkdir(parents=True, exist_ok=True)
    print('DELIVERY_STAGE [package]', flush=True)
    config = assembly.prepare(package_value, packager, material_records=material_records)
    # Registry closure exports and bundle staging are cache entries.  Final
    # deliverables belong to the stable top-level output directory instead.
    config['output_root'] = original_work / 'output'
    packager.run_build(config, argparse.Namespace(version=version, check_inputs=False))
    print('DELIVERY_COMPLETE', original_work / 'output', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--write-config', type=Path, help='Create or complete the one shared build-config.json and its default source files')
    parser.add_argument('--work-directory', type=Path, help='Used only with --write-config')
    parser.add_argument('--plan', action='store_true', help='Read local images and package inputs without creating outputs')
    parser.add_argument('--version', help='Optional delivery version')
    parser.add_argument('--seed-cache', action='store_true', help='Legacy containerd OCI export action')
    parser.add_argument('--cache-images', action='store_true', help='Render Charts, pull missing source images, and push them to REGISTRY')
    args = parser.parse_args()
    if args.write_config:
        if args.config or args.plan or args.version:
            raise SystemExit('--write-config cannot be combined with build options')
        build_config.initialize(args.write_config, 'image_export', args.work_directory)
        build_config.initialize(args.write_config, 'helm_bundle', args.work_directory)
        return
    if not args.config:
        raise SystemExit('Pass --config or --write-config')
    if args.cache_images:
        if args.plan or args.version or args.seed_cache: raise SystemExit('--cache-images cannot be combined with build options')
        cache_images(args.config)
    else:
        run(args.config, args.plan, args.version, args.seed_cache)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from None
