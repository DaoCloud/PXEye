#!/usr/bin/env python3
"""Build maintained NICo forks from frozen main heads; no runtime operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
import time
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    'pxeye': 'https://github.com/DaoCloud/PXEye.git',
    'core': 'https://github.com/SSmallMonster/infra-controller.git',
    'libredfish': 'https://github.com/SSmallMonster/libredfish.git',
}
PLATFORM = 'linux/amd64'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_toml(path):
    return tomllib.loads(path.read_text())


class Build:
    def __init__(self, args):
        self.args = args
        self.repo = args.repo.resolve()
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        self.root = args.output.resolve() / self.run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.lock_path = self.root / 'build-lock.json'
        self.state = {
            'schema_version': 1, 'run_id': self.run_id, 'target': args.target,
            'status': 'running', 'platform': PLATFORM, 'sources': {},
            'images': {}, 'files': {}, 'builders': {}, 'timings': [], 'commands': [],
            'scope': 'x86_64 Core/PXEye and optional x86_64 Scout/Boot; no ARM64 or DPU build',
        }
        self.save()
        self.core = self.root / 'sources/core'
        self.pxeye = self.root / 'sources/pxeye'
        self.builder = ''
        self.core_image = ''
        self.docker_context = None
        self.public_ca = None
        print(f'BUILD_LOCK={self.lock_path}', flush=True)

    def save(self):
        temporary = self.lock_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2) + '\n')
        temporary.replace(self.lock_path)

    @contextmanager
    def stage(self, name):
        started = time.monotonic()
        row = {'stage': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running'}
        self.state['timings'].append(row)
        self.save()
        try:
            yield
        except BaseException:
            row['status'] = 'failed'
            raise
        else:
            row['status'] = 'completed'
        finally:
            row.update(seconds=round(time.monotonic() - started, 3),
                       ended_at=datetime.now(timezone.utc).isoformat())
            self.save()
            print(f'STAGE_TIME {name}: {row["seconds"]}s ({row["status"]})', flush=True)

    def run(self, *argv, cwd=None, quiet=False):
        started = time.monotonic()
        argv = [str(value) for value in argv]
        line = f'+ [{cwd or self.repo}] {shlex.join(argv)}\n'
        print(line, end='', flush=True)
        with (self.root / 'build.log').open('a') as log:
            log.write(line)
            log.flush()
            process = subprocess.Popen(
                argv, cwd=cwd or self.repo, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors='replace',
                env=(os.environ | {'DOCKER_CONTEXT': self.docker_context,
                                   'BUILDX_BUILDER': self.docker_context})
                    if self.docker_context else None,
            )
            result = []
            for chunk in process.stdout:
                log.write(chunk)
                if not quiet:
                    print(chunk, end='', flush=True)
                else:
                    result.append(chunk)
            code = process.wait()
            seconds = round(time.monotonic() - started, 3)
            self.state['commands'].append({'argv': argv, 'cwd': str(cwd or self.repo),
                                           'seconds': seconds, 'exit_code': code})
            self.save()
            log.write(f'EXIT_CODE={code} SECONDS={seconds}\n')
            if code:
                raise RuntimeError(f'Command failed ({code}): {shlex.join(argv)}')
        return ''.join(result).strip()

    def file(self, name, path):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'Missing or empty build artifact: {path}')
        self.state['files'][name] = {
            'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path),
        }
        self.save()

    def sources(self):
        if self.run('git', 'status', '--porcelain', '--untracked-files=normal', quiet=True):
            raise RuntimeError('Commit PXEye changes and use a clean tree before building.')
        # Resolve all heads before fetching any source or invoking a compiler.
        for name, url in SOURCES.items():
            head = self.run('git', 'ls-remote', '--exit-code', url, 'refs/heads/main', quiet=True)
            commit = head.split()[0]
            if not re.fullmatch(r'[0-9a-f]{40}', commit):
                raise RuntimeError(f'Invalid main revision from {url}')
            self.state['sources'][name] = {'url': url, 'branch': 'main', 'commit': commit}
        self.save()
        local = self.run('git', 'rev-parse', 'HEAD', quiet=True)
        if local != self.state['sources']['pxeye']['commit']:
            raise RuntimeError(
                'PXEye HEAD must equal DaoCloud/PXEye main. Merge/push changes and update '
                'this checkout first; local feature commits are not release inputs.'
            )
        for name, source in self.state['sources'].items():
            directory = self.root / 'sources' / name
            directory.mkdir(parents=True)
            self.run('git', 'init', directory)
            self.run('git', 'remote', 'add', 'origin', source['url'], cwd=directory)
            self.run('git', 'fetch', '--depth=1', 'origin', source['commit'], cwd=directory)
            self.run('git', 'checkout', '--detach', source['commit'], cwd=directory)
        self.dependencies()
        print('SOURCE_SET: all three maintained main revisions frozen; libredfish pin matches.')

    def dependencies(self):
        self.run('git', 'diff', '--exit-code', 'HEAD', '--', 'Cargo.toml', 'Cargo.lock',
                 cwd=self.core, quiet=True)
        expected = self.state['sources']['libredfish']['commit']
        manifest = read_toml(self.core / 'Cargo.toml')
        dependency = manifest.get('workspace', {}).get('dependencies', {}).get('libredfish', {})
        if not isinstance(dependency, dict):
            raise RuntimeError('Core workspace must declare a pinned Git libredfish dependency.')
        patches = manifest.get('patch', {})
        # Follow the same source override as Cargo rather than building an unrelated checkout.
        patch = patches.get(dependency.get('git', ''), {}).get('libredfish', {})
        selected = patch or dependency
        expected_url = SOURCES['libredfish']
        if selected.get('git', '').removesuffix('.git') != expected_url.removesuffix('.git') or selected.get('rev') != expected or 'path' in selected:
            raise RuntimeError(
                f'Core main must pin {expected_url} at rev={expected} in Cargo.toml '
                '(direct dependency or upstream Git-source patch). Integrate fork fixes into '
                'main and update Cargo.lock; no feature-branch/path fallback is allowed.'
            )
        packages = [item for item in read_toml(self.core / 'Cargo.lock')['package']
                    if item['name'] == 'libredfish']
        wanted = f'git+{selected["git"]}?rev={expected}#{expected}'
        if len(packages) != 1 or packages[0].get('source') != wanted:
            raise RuntimeError('Core Cargo.lock does not resolve the selected libredfish main commit.')
        self.state['libredfish_dependency'] = packages[0]['source']
        self.file('core/Cargo.lock', self.core / 'Cargo.lock')
        self.file('core/Cargo.toml', self.core / 'Cargo.toml')

    def check_docker(self):
        if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
            raise RuntimeError('Run source builds on a Linux x86_64 builder with local Docker.')
        self.docker_context = self.run('docker', 'context', 'show', quiet=True)
        endpoint = self.run('docker', 'context', 'inspect', '--format',
                            '{{.Endpoints.docker.Host}}', self.docker_context, quiet=True)
        if not endpoint.startswith('unix://'):
            raise RuntimeError('Source builds require a local Unix-socket Docker context for bind mounts.')
        actual = self.run('docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}', quiet=True)
        if actual != PLATFORM:
            raise RuntimeError(f'Requires a local {PLATFORM} Docker daemon, got {actual}')
        self.state['docker_context'] = self.docker_context
        self.save()

    def image(self, name, recipe, context, arguments=()):
        core_rev = self.state['sources']['core']['commit']
        reference = f'pxeye-build/{name}:{core_rev[:12]}-{self.run_id}'
        self.file('recipes/' + name, recipe)
        if name in ('core-builder', 'pxe-builder'):
            text = recipe.read_text()
            text = re.sub(r'(?m)^(FROM[^\n]*\n)',
                          lambda match: match.group(0) + f'ENV CARGO_BUILD_JOBS={self.args.jobs}\n', text, count=1)
            recipe = self.root / ('Dockerfile.' + name + '.bounded')
            recipe.write_text(text)
            self.state['cargo_build_jobs'] = self.args.jobs
            self.file('recipes/' + name + '/bounded', recipe)
        if self.args.image_mirror:
            text = recipe.read_text()
            mappings = []
            def mirrored(match):
                original = match.group(2)
                if '$' in original or original == 'scratch' or original.startswith('pxeye-build/'):
                    return match.group(0)
                parts = original.split('/')
                if len(parts) == 1:
                    path = 'docker.io/library/' + original
                elif parts[0] in ('docker.io', 'index.docker.io'):
                    path = 'docker.io/' + '/'.join(parts[1:])
                elif '.' not in parts[0] and ':' not in parts[0]:
                    path = 'docker.io/' + original
                else:
                    return match.group(0)
                replacement = self.args.image_mirror.rstrip('/') + '/' + path
                mappings.append({'source': original, 'mirror': replacement})
                return match.group(1) + replacement
            text = re.sub(r'(?m)^(FROM\s+)(\S+)', mirrored, text)
            if mappings:
                recipe = self.root / ('Dockerfile.' + name + '.mirrored')
                recipe.write_text(text)
                self.state.setdefault('base_image_mirrors', {})[name] = mappings
                self.file('recipes/' + name + '/mirrored', recipe)
        self.run(
            'docker', 'build', '--platform', PLATFORM, '-f', recipe, '-t', reference,
            '--label', f'org.opencontainers.image.revision={core_rev}',
            '--label', f'org.opencontainers.image.source={SOURCES["core"]}',
            '--label', f'org.opencontainers.image.version=main-{core_rev[:12]}',
            '--label', f'io.pxeye.libredfish.revision={self.state["sources"]["libredfish"]["commit"]}',
            *arguments, context,
        )
        image_id = self.run('docker', 'image', 'inspect', '--format', '{{.Id}}', reference, quiet=True)
        self.state['builders'][name] = {'reference': reference, 'image_id': image_id}
        self.save()
        return reference

    def build_builder(self):
        if not self.builder:
            kea = (self.core / 'dev/docker/kea.version').read_text().strip()
            self.builder = self.image(
                'core-builder', self.core / 'dev/docker/Dockerfile.build-container-x86_64',
                self.core, ['--build-arg', f'KEA_VERSION={kea}'],
            )
        return self.builder

    def library(self):
        self.run('docker', 'run', '--rm', '--platform', PLATFORM,
                 '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
                 '-e', 'GIT_CONFIG_VALUE_0=/code',
                 '-v', f'{self.core}:/code', '-w', '/code', self.build_builder(),
                 'cargo', 'build', '--locked', '--release', '--package', 'libredfish', '--lib')
        self.dependencies()
        self.state['library_build'] = 'passed in Core locked workspace; not a deployment image'
        self.save()

    def build_core(self):
        if self.core_image:
            return self.core_image
        builder = self.build_builder()
        kea = (self.core / 'dev/docker/kea.version').read_text().strip()
        runtime = self.image(
            'core-runtime', self.core / 'dev/docker/Dockerfile.runtime-container-x86_64',
            self.core, ['--build-arg', f'KEA_VERSION={kea}'],
        )
        commit = self.state['sources']['core']['commit']
        timestamp = self.run('git', 'show', '-s', '--format=%cI', 'HEAD', cwd=self.core, quiet=True)
        version = f'0.0.0-main-{commit[:12]}'
        arguments = []
        for key, value in {
            'CONTAINER_BUILD_X86_64': builder, 'CONTAINER_RUNTIME_X86_64': runtime,
            'CI_COMMIT_SHORT_SHA': commit[:12], 'CI_COMMIT_TIMESTAMP': timestamp,
            'VERSION': version, 'CARBIDE_BUILD_HELM_VERSION': version,
        }.items():
            arguments += ['--build-arg', f'{key}={value}']
        self.core_image = self.image(
            'nico-core', self.core / 'dev/docker/Dockerfile.release-container-x86_64',
            self.core, arguments,
        )
        self.publish('core', self.core_image, f'main-{commit[:12]}-{self.run_id}')
        self.dependencies()
        return self.core_image

    def scout(self, builder=None):
        self.run('docker', 'run', '--rm', '--platform', PLATFORM,
                 '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
                 '-e', 'GIT_CONFIG_VALUE_0=/code',
                 '-e', f'VERSION=0.0.0-main-{self.state["sources"]["core"]["commit"][:12]}',
                 '-v', f'{self.core}:/code', '-w', '/code', builder or self.build_builder(),
                 'cargo', 'build', '--locked', '--release', '--target=x86_64-unknown-linux-gnu',
                 '-p', 'carbide-scout', '-p', 'carbide-libmlx',
                 '--bin', 'forge-scout', '--bin', 'mlx-firmware-supervisor')
        self.file('scout/forge-scout', self.core / 'target/x86_64-unknown-linux-gnu/release/forge-scout')
        self.file('scout/mlx-firmware-supervisor',
                  self.core / 'target/x86_64-unknown-linux-gnu/release/mlx-firmware-supervisor')
        self.dependencies()

    def prepare_ca(self):
        ca = self.args.scout_ca.resolve()
        content = ca.read_text()
        if 'PRIVATE KEY' in content or '-----BEGIN CERTIFICATE-----' not in content:
            raise RuntimeError('SCOUT_CA_FILE must contain public CA certificates only.')
        public_ca = self.root / 'scout-ca.crt'
        shutil.copyfile(ca, public_ca)
        self.file('inputs/scout-ca.crt', public_ca)
        self.run('openssl', 'x509', '-in', public_ca, '-noout', '-checkend', '0')
        self.public_ca = public_ca

    def boot(self):
        public_ca = self.public_ca
        self.run('git', 'submodule', 'update', '--init', '--depth=1', '--',
                 'pxe/mkosi', 'pxe/ipxe/upstream', cwd=self.core)
        self.state['boot_submodules'] = self.run(
            'git', 'submodule', 'status', '--', 'pxe/mkosi', 'pxe/ipxe/upstream',
            cwd=self.core, quiet=True,
        ).splitlines()
        builder = self.image(
            'pxe-builder', self.core / 'dev/docker/Dockerfile.pxe-build-container',
            self.core / 'dev/docker',
        )
        # Use the upstream production-CA assembly, never its developer-CA shortcut.
        self.scout(builder)
        self.run(
            'docker', 'run', '--rm', '--privileged', '--platform', PLATFORM,
            '-v', f'{self.core}:/code', '-v', f'{public_ca}:/inputs/scout-ca.crt:ro',
            '-w', '/code', '-e', f'VERSION=0.0.0-main-{self.state["sources"]["core"]["commit"][:12]}',
            builder, 'sh', '-ec',
            'git config --global --add safe.directory /code; '
            'git config --global --add safe.directory /code/pxe/ipxe/upstream; '
            'cargo make --cwd pxe build-boot-artifacts-x86-host-ci; '
            'cargo make --cwd pxe --env FORGE_CA_PATH=/inputs/scout-ca.crt '
            'create-ephemeral-image-x86-host-ci',
        )
        self.dependencies()
        payload = self.core / 'pxe/static/blobs/internal'
        # Packaging may rebuild the binaries. Record the final bytes, then compare
        # them with the executables and CA actually embedded in the SquashFS.
        contents = {
            'forge-scout': self.core / 'target/x86_64-unknown-linux-gnu/release/forge-scout',
            'mlx-firmware-supervisor': self.core / 'target/x86_64-unknown-linux-gnu/release/mlx-firmware-supervisor',
            'forge_root.pem': public_ca,
        }
        self.state['verified_boot_contents'] = {}
        for name, path in contents.items():
            actual = self.run(
                'docker', 'run', '--rm', '--platform', PLATFORM,
                '-v', f'{payload}:/payload:ro', builder,
                'bash', '-ec', 'set -o pipefail; unsquashfs -cat '
                '/payload/x86_64/scout.squashfs "$1" | sha256sum',
                '_', f'opt/forge/{name}', quiet=True,
            ).split()[0]
            if actual != sha256(path):
                raise RuntimeError(f'Scout SquashFS contains an unexpected {name}.')
            self.state['verified_boot_contents'][name] = actual
            if name != 'forge_root.pem':
                self.file('scout/' + name, path)
        for filename in ('scout.efi', 'scout.squashfs', 'ipxe.efi', 'golan.efi'):
            self.file(f'boot/x86_64/{filename}', payload / 'x86_64' / filename)
        for directory in ('x86_64', 'apt'):
            for path in sorted((payload / directory).rglob('*')):
                if path.is_file():
                    self.file('boot/' + str(path.relative_to(payload)), path)
        recipe = self.root / 'Dockerfile.boot'
        recipe.write_text(
            f'FROM {self.build_core()}\nWORKDIR /\n'
            'COPY x86_64/ /x86_64/\nCOPY apt/ /apt/\n'
            'CMD ["sh", "-ec", "cp -r /x86_64 /apt /forge-boot-artifacts/blobs/internal/"]\n'
        )
        image = self.image('boot-artifacts-x86_64', recipe, payload)
        self.publish('boot-artifacts-x86_64', image,
                     f'main-{self.state["sources"]["core"]["commit"][:12]}-{self.run_id}')

    def publish(self, name, image, tag):
        if not self.args.registry:
            self.state['images'][name] = {'reference': image, 'published': False}
        else:
            reference = f'{self.args.registry.rstrip("/")}/{name}:{tag}'
            self.run('docker', 'tag', image, reference)
            self.run('docker', 'push', reference)
            digests = json.loads(self.run('docker', 'image', 'inspect', '--format',
                                          '{{json .RepoDigests}}', reference, quiet=True))
            matches = [item for item in digests or [] if item.startswith(reference.rsplit(':', 1)[0] + '@sha256:')]
            if len(matches) != 1:
                raise RuntimeError(f'Cannot resolve pushed digest for {reference}')
            self.state['images'][name] = {
                'reference': reference, 'immutable_reference': matches[0], 'published': True,
            }
            print(f'PUBLISHED_{name.upper().replace("-", "_")}_IMAGE={matches[0]}')
        self.save()

    def build_pxeye(self):
        self.build_core()
        binary_dir = self.pxeye / 'bin'
        binary_dir.mkdir(exist_ok=True)
        container = self.run('docker', 'create', self.core_image, '/bin/true', quiet=True)
        try:
            self.run('docker', 'cp', f'{container}:/opt/carbide/nico-admin-cli',
                     binary_dir / 'nico-admin-cli')
        finally:
            self.run('docker', 'rm', container)
        for name in ('nico-admin-cli', 'grpcurl', 'helm'):
            path = binary_dir / name
            path.chmod(0o755)
            self.check_elf(path)
            self.file('pxeye/bin/' + name, path)
        version = read_toml(self.pxeye / 'pyproject.toml')['project']['version']
        commit = self.state['sources']['pxeye']['commit']
        tag = f'{version}-{commit[:7]}-{self.run_id}'
        image = f'pxeye-build/pxeye:{tag}'
        self.run('docker', 'build', '--platform', PLATFORM, '-t', image,
                 '--build-arg', f'BASE_IMAGE={self.args.base_image}',
                 '--build-arg', f'VCS_REF={commit}', '--build-arg', f'VERSION={version}',
                 '--label', f'io.pxeye.core.revision={self.state["sources"]["core"]["commit"]}',
                 self.pxeye)
        self.publish('pxeye', image, tag)

    @staticmethod
    def check_elf(path):
        with path.open('rb') as stream:
            header = stream.read(20)
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
            raise RuntimeError(f'{path} must be a Linux amd64 ELF executable.')

    def prepare_tools(self):
        # Snapshot ignored, externally supplied tools before compiling, too.
        for name in ('grpcurl', 'helm'):
            source = self.repo / 'bin' / name
            self.check_elf(source)
            destination = self.pxeye / 'bin' / name
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, destination)
            self.file('pxeye/bin/' + name, destination)

    def execute(self):
        try:
            with self.stage('sources'):
                self.sources()
            if self.args.target != 'sources':
                self.check_docker()
            if self.args.target in ('boot', 'images'):
                self.prepare_ca()
            if self.args.target == 'images':
                self.prepare_tools()
            if self.args.target == 'libredfish':
                self.library()
            elif self.args.target == 'core':
                with self.stage('core'):
                    self.build_core()
            elif self.args.target == 'scout':
                self.scout()
            elif self.args.target in ('boot', 'images'):
                with self.stage('core'):
                    self.build_core()
                with self.stage('x86-scout-boot'):
                    self.boot()
                if self.args.target == 'images':
                    with self.stage('pxeye'):
                        self.build_pxeye()
            self.state['status'] = 'complete'
            for name, source in self.state['sources'].items():
                print(f'SOURCE {name}: main @ {source["commit"]}')
            for name, item in self.state['images'].items():
                print(f'IMAGE {name}: {item.get("immutable_reference", item["reference"])}')
        except (Exception, KeyboardInterrupt) as error:
            self.state['status'] = 'failed'
            self.state['error'] = str(error) or 'Interrupted'
            raise
        finally:
            self.save()
            print(f'BUILD_STATUS={self.state["status"]}\nBUILD_LOCK={self.lock_path}', flush=True)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog='Examples: make nico-sources; make nico-core; make libredfish; '
               'make images REGISTRY=registry.example:5000 SCOUT_CA_FILE=/private/core-ca.crt. '
               'Every invocation resolves a fresh set of maintained main revisions. '
               'Does not update Charts, build an offline archive, or deploy services.',
    )
    parser.add_argument('target', choices=('sources', 'core', 'libredfish', 'scout', 'boot', 'images'))
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--registry', default='', help='Optional push destination; required for images')
    parser.add_argument('--scout-ca', type=Path, help='Public Core CA PEM embedded in Scout (boot/images)')
    parser.add_argument('--base-image', default='ubuntu:24.04')
    parser.add_argument('--jobs', type=int, default=8, help='Maximum concurrent Cargo jobs in build images (default: 8)')
    parser.add_argument('--image-mirror', default='', help='Optional Docker Hub mirror prefix, e.g. m.daocloud.io; preserves pinned digests')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if args.target == 'images' and not args.registry:
        parser.error('images requires --registry (Make: REGISTRY=host:port)')
    if args.target in ('boot', 'images') and (not args.scout_ca or not args.scout_ca.is_file()):
        parser.error('boot/images requires --scout-ca (Make: SCOUT_CA_FILE=/path/to/core-ca.crt)')
    args.output = args.output or args.repo / 'outputs_/source-builds'
    try:
        Build(args).execute()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
