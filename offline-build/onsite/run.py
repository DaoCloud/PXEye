#!/usr/bin/env python3
"""One configuration, one command: unpack, import, freeze, install and resume."""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
import onsite
from progress import Progress, atomic_json, transcript, install_signal_handlers

HOME = Path(__file__).resolve().parent


def require_path(value, label):
    path = Path(value)
    onsite.require(path.is_absolute() and not path.is_symlink(), 'Use an absolute, non-symlink path for ' + label)
    return path.resolve()


def extract(config, target):
    archive, checksums = (require_path(config[k], k) for k in ('archive', 'checksums'))
    if not target.exists():
        onsite.unpack(SimpleNamespace(archive=archive, checksums=checksums, output=target))
    else:
        result = json.loads((target / 'unpack-result.json').read_text())
        matches = [line.split()[0].lower() for line in checksums.read_text().splitlines()
                   if len(line.split()) == 2 and line.split()[1].lstrip('*') == archive.name]
        onsite.require(matches == [result['archive_sha256']] and onsite.sha(archive) == matches[0],
                       'Archive/checksum differs from completed extraction; use a new extraction/work directory')
    result = json.loads((target / 'unpack-result.json').read_text())
    relative = Path(result['root'])
    onsite.require(len(relative.parts) == 1 and relative.name not in ('.', '..') and not relative.is_absolute(), 'Invalid bundle root')
    bundle = target / relative
    onsite.verifier.verify(bundle)
    return bundle


def site_config(config, bundle, work):
    path = work / 'site-config.json'
    if path.exists():
        print('REUSE_SITE_CONFIG', path, flush=True)
        return path
    supplied = copy.deepcopy(config['site'])
    supplied['context'] = supplied.get('context') or onsite.select_restore_context(path)
    supplied.setdefault('namespace', 'nico-system')
    onsite.require(supplied.get('mode') in ('new', 'restore'), 'site.mode must be new or restore')
    if not supplied.get('release_prefix'):
        if supplied['mode'] == 'restore':
            command = [str(bundle / 'tools/helm'), '--kube-context', supplied['context'], '-n', supplied['namespace'], 'list', '--all', '-o', 'json']
            print('SELECT_EXISTING_CORE_RELEASE', flush=True)
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            onsite.require(result.returncode == 0, 'Cannot read existing Helm releases')
            releases = [row['name'] for row in json.loads(result.stdout) if row['chart'].startswith('nico-')]
            onsite.require(len(releases) == 1, 'Expected one Core release; set site.release_prefix explicitly')
            supplied['release_prefix'] = releases[0]
        else:
            supplied['release_prefix'] = 'nico'
    registry = supplied.setdefault('registry', {})
    if not registry.get('url'):
        args = SimpleNamespace(context=supplied['context'], namespace=supplied['namespace'],
            ca_file=registry.get('ca_file'), skip_tls_verify=registry.get('skip_tls_verify', False))
        url, discovery = onsite.detect_registry(args)
        registry.update(url=url, discovery=discovery)
    base = json.loads((HOME / 'site-config.example.json').read_text())
    document = onsite.merge(base, supplied)
    document.update(schema_version=1, bundle=str(bundle), work_directory=str(work / 'deployment'))
    if document['mode'] == 'new':
        onsite.require(all((document.get('service_ips') or {}).get(k) for k in ('dns', 'pxe', 'ntp'))
                       and document.get('host_network'), 'New site requires site.service_ips and site.host_network in the configuration file')
    atomic_json(path, document)
    return path


def run(path):
    config = json.loads(path.read_text())
    onsite.require(config.get('schema_version') == 1, 'Use run-config.example.json schema 1')
    onsite.require(type(config.get('bootstrap_pxeye')) is bool, 'bootstrap_pxeye must be true or false')
    work, target = (require_path(config[k], k) for k in ('work_directory', 'extract_directory'))
    onsite.require(not work.is_relative_to(target) and not target.is_relative_to(work), 'Extraction and work directories must be separate')
    for key in ('archive', 'checksums'):
        value = require_path(config[key], key)
        onsite.require(not value.is_relative_to(work) and not value.is_relative_to(target), 'Input must be outside work/extraction directories')
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (work / '.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = {'config': config, 'checksums_sha256': onsite.sha(config['checksums']),
                    'implementation': {name: onsite.sha(HOME / name) for name in
                        ('run.py', 'onsite.py', 'progress.py', 'registry_bridge.py', 'relocation.py', 'site-config.example.json')}}
        identity['phase_values'] = {key: onsite.sha(value) for key, value in config['site'].get('phase_values', {}).items()}
        progress = Progress(work, identity)
        with transcript(work):
            try:
                with progress.stage('01-unpack', 'Verify and unpack offline delivery'):
                    bundle = extract(config, target)
                with progress.stage('02-site', 'Resolve cluster, Registry and site configuration') as checkpoint:
                    resolved = work / 'site-config.json'
                    # Freeze generated settings; never accept edits behind the config identity.
                    if checkpoint.get('sha256'):
                        onsite.require(onsite.sha(resolved) == checkpoint['sha256'], 'Resolved site-config changed; use a new work directory')
                    resolved = site_config(config, bundle, work)
                    checkpoint['sha256'] = onsite.sha(resolved)
                environment = work / 'environment.sh'
                import shlex
                environment.write_text('export KIT=' + shlex.quote(str(HOME)) + '\nexport CONFIG=' + shlex.quote(str(resolved)) +
                                       '\nexport BUNDLE=' + shlex.quote(str(bundle)) + '\nexport WORK=' + shlex.quote(str(work / 'deployment')) + '\n')
                environment.chmod(0o600)
                engine = onsite.Onsite(resolved)
                with progress.stage('03-preflight', 'Check bundle, target cluster and tools'):
                    engine.preflight()
                with progress.stage('04-import', 'Import images and publish Helm OCI Charts'):
                    engine.import_bundle()
                with progress.stage('05-recipe', 'Freeze and validate installation recipe'):
                    if (engine.work / 'recipe').exists():
                        engine.validate_recipe()
                        print('REUSE_RECIPE', engine.work / 'recipe', flush=True)
                    else:
                        engine.prepare_recipe()
                if config['bootstrap_pxeye']:
                    with progress.stage('06-pxeye', 'Install or verify PXEye'):
                        engine.bootstrap(resume=True)
                else:
                    print('SKIP [06-pxeye] bootstrap_pxeye=false; preserve existing PXEye', flush=True)
                for phase in engine.validate_recipe()['phases']:
                    with progress.stage('07-install-' + phase['id'], 'Install or verify ' + phase['id']):
                        engine.install(phase['id'], automatic=True)
                progress.complete()
                print('ONSITE_COMPLETE', work, '; Helm readiness passed; physical provisioning remains a separate acceptance', flush=True)
            except BaseException as error:
                progress.fail(error)
                raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    install_signal_handlers()
    run(args.config.resolve())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
