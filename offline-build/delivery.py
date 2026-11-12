#!/usr/bin/env python3
"""One-command offline delivery: export images, prepare Charts, package and verify."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

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


def run(path, plan, version):
    path = path.expanduser().resolve()
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or 'work_directory' not in value:
        raise ValueError('Use the shared build-config.json with work_directory')
    print('DELIVERY_STAGE [image-export]', flush=True)
    containerd_export.run(path, plan=plan)
    packager = load_packager()
    package_value = assembly.configuration(path)
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
    args = parser.parse_args()
    if args.write_config:
        if args.config or args.plan or args.version:
            raise SystemExit('--write-config cannot be combined with build options')
        build_config.initialize(args.write_config, 'image_export', args.work_directory)
        build_config.initialize(args.write_config, 'helm_bundle', args.work_directory)
        return
    if not args.config:
        raise SystemExit('Pass --config or --write-config')
    run(args.config, args.plan, args.version)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from None
