#!/usr/bin/env python3
"""Synchronize committed code to an existing SSH checkout with an incremental bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]

# Python -c leaves stdin available for the binary bundle. No remote shell
# interpolation is used for Git arguments or paths inside this helper.
REMOTE = r'''
import fcntl, hashlib, json, os, pathlib, subprocess, sys, tempfile
action, directory = sys.argv[1:3]
root = pathlib.Path(directory).resolve()
def git(*args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('git ' + args[0] + ' failed: ' + result.stderr[-2000:])
    return result.stdout.strip()
def check():
    if git('rev-parse', '--show-toplevel') != str(root):
        raise ValueError('Target must be the repository root')
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Remote checkout has uncommitted changes; nothing overwritten')
    return git('rev-parse', 'HEAD')
try:
    if action == 'probe':
        head = check()
        origin = git('remote', 'get-url', 'origin')
        print(json.dumps({'head': head, 'origin_hash': hashlib.sha256(origin.encode()).hexdigest()}))
    elif action == 'apply':
        before, target, expected_hash = sys.argv[3:6]
        cache = pathlib.Path(git('rev-parse', '--git-path', 'pxeye-code-sync'))
        if not cache.is_absolute(): cache = root / cache
        if cache.is_symlink(): raise ValueError('Sync staging must not be a symlink')
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if check() != before: raise ValueError('Remote HEAD changed during sync; retry after inspection')
            with tempfile.NamedTemporaryFile(dir=cache, suffix='.bundle', delete=False) as stream:
                bundle = pathlib.Path(stream.name)
                digest = hashlib.sha256()
                for block in iter(lambda: sys.stdin.buffer.read(1024 * 1024), b''):
                    stream.write(block); digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError('Transferred bundle checksum differs: ' + str(bundle))
            git('bundle', 'verify', str(bundle))
            git('fetch', '--no-tags', str(bundle), target)
            if git('rev-parse', 'FETCH_HEAD') != target:
                raise ValueError('Fetched commit differs from requested commit')
            if check() != before: raise ValueError('Remote checkout changed during transfer')
            git('merge', '--ff-only', target)
            if check() != target: raise ValueError('Remote commit verification failed')
            bundle.unlink()
            print(json.dumps({'head': target, 'clean': True}))
    else:
        raise ValueError('Unknown sync action')
except Exception as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def git_path(name):
    path = Path(git('rev-parse', '--git-path', name))
    return path if path.is_absolute() else REPO / path


def create_bundle(path, target, base, run_id):
    # Git bundle requires a named positive ref. Freeze it so another local
    # commit cannot change the revision while the bundle is being created.
    reference = 'refs/pxeye-code-sync/' + run_id
    git('update-ref', reference, target, '')
    try:
        return subprocess.run(['git', '-C', str(REPO), 'bundle', 'create', str(path), reference, '^' + base],
                              capture_output=True, text=True, timeout=300)
    finally:
        git('update-ref', '-d', reference, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=git_path('pxeye-code-sync/config.json'))
    parser.add_argument('--ref', default='HEAD', help='Committed revision to synchronize (default: HEAD)')
    parser.add_argument('--check', action='store_true', help='Read-only remote check; do not transfer or update')
    args = parser.parse_args()
    path = args.config.expanduser().resolve()
    require(path.is_file(), 'Create the local sync configuration first: ' + str(path))
    config = json.loads(path.read_text())
    require(set(config) == {'host', 'port', 'directory'}, 'Configuration requires host, port and directory')
    require(isinstance(config['host'], str) and re.fullmatch(r'(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.-]+', config['host'])
            and not config['host'].startswith('-'), 'Invalid SSH host')
    require(type(config['port']) is int and 1 <= config['port'] <= 65535, 'Invalid SSH port')
    require(isinstance(config['directory'], str) and config['directory'].startswith('/')
            and not any(c in config['directory'] for c in '\n\r\0'), 'Use an absolute remote repository directory')
    target = git('rev-parse', '--verify', args.ref + '^{commit}')
    origin_hash = hashlib.sha256(git('remote', 'get-url', 'origin').encode()).hexdigest()
    logs = git_path('pxeye-code-sync/logs'); logs.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    log_path = logs / (run_id + '.log')
    with log_path.open('x') as log:
        log_path.chmod(0o600)
        def report(message):
            print(message, flush=True); log.write(message + '\n'); log.flush()
        def remote(action, *extra, stdin=None):
            command = shlex.join(['python3', '-c', REMOTE, action, config['directory'], *extra])
            result = subprocess.run(['ssh', '-p', str(config['port']), '-o', 'BatchMode=yes',
                                     '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                                     config['host'], command], stdin=stdin, capture_output=True, text=True, timeout=300)
            log.write(result.stdout + result.stderr + '\nEXIT_CODE=' + str(result.returncode) + '\n'); log.flush()
            require(result.returncode == 0, 'Remote ' + action + ' failed: ' + result.stderr.strip())
            return json.loads(result.stdout)
        try:
            report('[1/4] Check committed source and remote checkout')
            dirty = git('status', '--porcelain', '--untracked-files=normal')
            if dirty: report('LOCAL_UNCOMMITTED_CHANGES_EXCLUDED')
            state = remote('probe')
            require(state['origin_hash'] == origin_hash, 'Local and remote origin differ; inspect target repository')
            base = state['head']
            require(re.fullmatch(r'[0-9a-f]{40,64}', base), 'Invalid remote commit')
            if base == target:
                report('SYNC_UP_TO_DATE ' + target)
                return
            ancestry = subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', base, target],
                                      capture_output=True, text=True)
            require(ancestry.returncode == 0, 'Remote HEAD is unknown or not an ancestor; fetch/review history before syncing')
            if args.check:
                report('SYNC_CHECK_OK ' + base[:12] + ' -> ' + target[:12])
                return
            with tempfile.TemporaryDirectory(prefix='pxeye-code-sync-') as name:
                bundle = Path(name) / 'commits.bundle'
                report('[2/4] Create incremental bundle ' + base[:12] + ' -> ' + target[:12])
                result = create_bundle(bundle, target, base, run_id)
                log.write(result.stdout + result.stderr); log.flush()
                require(result.returncode == 0, 'Cannot create incremental Git bundle: ' + result.stderr.strip())
                digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
                report('[3/4] Transfer ' + str(bundle.stat().st_size) + ' bytes and fast-forward remote')
                with bundle.open('rb') as stream:
                    updated = remote('apply', base, target, digest, stdin=stream)
                report('[4/4] Verify remote commit and clean working tree')
                require(updated == {'head': target, 'clean': True}, 'Unexpected remote verification result')
                report('SYNC_COMPLETE ' + config['host'] + ':' + config['directory'] + ' ' + target)
        except BaseException as error:
            report('SYNC_FAILED ' + str(error))
            raise
        finally:
            print('LOG', log_path, flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
