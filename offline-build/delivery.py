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
import re
import hashlib

import yaml

HOME = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HOME / 'material-prepare'))
import containerd_export
sys.path.insert(0, str(HOME))
import build_config
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


def chart_images(path, package_value, packager, ui=None):
    """Render the locked parent Chart and write its exact containerd requirements."""
    work = package_value['work_directory']
    charts = packager.chart_sources.prepare(work, package_value['sources'].get('charts'), packager.b, helm=package_value['tools']['helm'])
    ui = ui or pxeye_image()
    with tempfile.TemporaryDirectory(prefix='.parent-discovery-', dir=work) as temporary:
        temporary = Path(temporary)
        root = packager.stage_charts(temporary / 'bundle', temporary, {'__ui__': ui, ui: ui}, {}, ui, [],
                                     charts / 'deployment/charts', package_value['tools']['helm'])['pxeye']
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


def cache_images(path):
    """Populate REGISTRY from Chart-derived image references; no handwritten image list."""
    registry = os.environ.get('REGISTRY', '').strip().removeprefix('http://').removeprefix('https://').rstrip('/')
    if not registry or '/' in registry:
        raise ValueError('Set REGISTRY to a registry host[:port], for example REGISTRY=127.0.0.1:1027')
    insecure = os.environ.get('REGISTRY_INSECURE', 'true').lower() in ('1', 'true', 'yes')
    raw = build_config.read(path)
    options = containerd_export.DEFAULTS | raw.get('image_export', {})
    packager = load_packager(); package_value = assembly.configuration(path)
    print('DELIVERY_STAGE [cache-images-chart-closure]', flush=True)
    image_list = chart_images(path, package_value, packager)
    known = set(subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'list', '-q'], capture_output=True, text=True, check=True).stdout.splitlines())
    for source in [line.strip() for line in image_list.read_text().splitlines() if line.strip()]:
        if source not in known:
            print('PULL_SOURCE_IMAGE', source, flush=True)
            subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'pull', '--platform', 'linux/amd64', source], check=True)
        target = cache_reference(source, registry)
        print('PUSH_CACHE_IMAGE', source, '->', target, flush=True)
        subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'tag', source, target], check=True)
        command = [options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'push', '--platform', 'linux/amd64']
        if insecure: command.append('--plain-http')
        subprocess.run(command + [target], check=True)
    print('CACHE_IMAGES_COMPLETE', registry, flush=True)


def registry_input(path, package_value, packager):
    """Materialize the Chart closure from REGISTRY into an isolated OCI input.

    containerd is only an export transport here: every image is first pulled from
    REGISTRY and retagged to its Chart reference before the existing OCI exporter
    reads it.  No old offline-images directory or handwritten image list is used.
    """
    registry = os.environ.get('REGISTRY', '').strip().removeprefix('http://').removeprefix('https://').rstrip('/')
    if not registry or '/' in registry:
        raise ValueError('Set REGISTRY to a registry host[:port], for example REGISTRY=127.0.0.1:1027')
    insecure = os.environ.get('REGISTRY_INSECURE', 'true').lower() in ('1', 'true', 'yes')
    image_list = chart_images(path, package_value, packager)
    references = [line.strip() for line in image_list.read_text().splitlines() if line.strip()]
    identity = hashlib.sha256(json.dumps({'registry': registry, 'images': references}, sort_keys=True).encode()).hexdigest()[:24]
    work = package_value['work_directory'] / 'cache' / 'registry-exports' / identity
    config = work / 'build-config.json'
    raw = build_config.read(path)
    chart_source = str(package_value['sources']['charts'])
    generated = {'work_directory': str(work), 'image_export': raw.get('image_export', {}),
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
        pull = [options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'pull']
        if insecure: pull.append('--plain-http')
        subprocess.run(pull + ['--platform', 'linux/amd64', target], check=True)
        subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace', options['containerd_namespace'], 'images', 'tag', target, source], check=True)
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
    if seed_cache:
        print('DELIVERY_STAGE [cache-seed-image-closure]', flush=True)
        image_list = chart_images(path, package_value, packager)
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
    registry_config, package_value = registry_input(path, package_value, packager)
    if plan:
        print('DELIVERY_STAGE [package-plan]', flush=True)
        assembly.plan(package_value)
        print('DELIVERY_PLAN_OK', registry_config, flush=True)
        return
    work = package_value['work_directory']
    work.mkdir(parents=True, exist_ok=True)
    print('DELIVERY_STAGE [package]', flush=True)
    config = assembly.prepare(package_value, packager)
    packager.run_build(config, argparse.Namespace(version=version, check_inputs=False))
    print('DELIVERY_COMPLETE', work / 'output', flush=True)


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
