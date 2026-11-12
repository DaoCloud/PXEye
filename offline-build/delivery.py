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


def pxeye_image(path):
    """Find the one locally-built PXEye image without a user-maintained list."""
    raw = build_config.read(path)
    options = containerd_export.DEFAULTS | raw.get('image_export', {})
    result = subprocess.run([options['ctr'], '--address', options['containerd_address'], '--namespace',
                             options['containerd_namespace'], 'images', 'list'], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('Cannot read local containerd image list: ' + result.stderr[-2000:])
    refs = [line.split()[0] for line in result.stdout.splitlines() if len(line.split()) >= 3 and 'mmzhou-os-install-console' in line.split()[0]]
    if not refs:
        raise ValueError('No local PXEye image reference contains mmzhou-os-install-console')
    rows = containerd_export.resolve_images(options, refs)
    candidates = []
    for row in rows:
        labels = (containerd_export.metadata(Path(options['containerd_content']), row['config']).get('config') or {}).get('Labels') or {}
        if labels.get('org.opencontainers.image.title') == 'PXEye': candidates.append(row['image'])
    if len(candidates) != 1:
        raise ValueError('Expected exactly one local PXEye image identified by org.opencontainers.image.title=PXEye; found: ' + ', '.join(candidates))
    return candidates[0]


def chart_images(path, package_value, packager, ui=None):
    """Render the locked parent Chart and write its exact containerd requirements."""
    work = package_value['work_directory']
    charts = packager.chart_sources.prepare(work, package_value['sources'].get('charts'), packager.b, helm=package_value['tools']['helm'])
    ui = ui or pxeye_image(path)
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
    source, roles = seeded_roles(package_value)
    print('DELIVERY_STAGE [chart-image-closure]', flush=True)
    image_list = chart_images(path, package_value, packager, ui=roles['ui'])
    require_seed_matches(source, image_list)
    if plan:
        print('DELIVERY_STAGE [package-plan]', flush=True)
        assembly.plan(package_value)
        print('DELIVERY_PLAN_OK', path, flush=True)
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
    parser.add_argument('--seed-cache', action='store_true', help='One-time or version-change action: derive the parent closure and export it from local containerd')
    args = parser.parse_args()
    if args.write_config:
        if args.config or args.plan or args.version:
            raise SystemExit('--write-config cannot be combined with build options')
        build_config.initialize(args.write_config, 'image_export', args.work_directory)
        build_config.initialize(args.write_config, 'helm_bundle', args.work_directory)
        return
    if not args.config:
        raise SystemExit('Pass --config or --write-config')
    run(args.config, args.plan, args.version, args.seed_cache)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from None
