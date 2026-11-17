"""Build Grace boot payloads from the source build's frozen Core checkout."""
import json
import shutil


def build(owner):
    """Cross-compile Scout, rebuild ARM rootfs/UEFI, then inspect final bytes."""
    version = '0.0.0-main-' + owner.state['sources']['core']['commit'][:12]
    with owner.stage('arm64-cross-builder'):
        recipe = owner.root / 'Dockerfile.arm-cross-builder'
        recipe.write_text(
            f'FROM {owner.build_builder()}\n'
            'RUN dpkg --add-architecture arm64 && apt-get update && '
            'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends '
            'g++-aarch64-linux-gnu libc6-dev-arm64-cross libssl-dev:arm64 '
            'libudev-dev:arm64 libtss2-dev:arm64 && rm -rf /var/lib/apt/lists/*\n'
            'RUN rustup target add aarch64-unknown-linux-gnu\n'
            'ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc '
            'CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc '
            'CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++ '
            'PKG_CONFIG_ALLOW_CROSS=1 '
            'PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig\n'
            'ENV RUSTFLAGS="--cfg tokio_unstable -C link-arg=-Wl,-z,max-page-size=65536"\n'
        )
        cross = owner.image('arm-cross-builder', recipe, owner.core)
    common = ['docker', 'run', '--rm', '--platform', 'linux/amd64',
              '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
              '-e', 'GIT_CONFIG_VALUE_0=/code', '-e', f'VERSION={version}',
              '-v', f'{owner.core}:/code', '-w', '/code']
    with owner.stage('arm64-scout-compile-package'):
        owner.run(*common, cross, 'cargo', 'make', 'package-scout-aarch64-release-local')
        owner.dependencies()
        for name in ('forge-scout', 'mlx-firmware-supervisor'):
            owner.file('arm64/bin/' + name,
                       owner.core / 'target/aarch64-unknown-linux-gnu/release' / name)
        owner.file('arm64/scout.deb', owner.core / f'target/debs/forge-scout_{version}_arm64.deb')
    with owner.stage('arm64-mkosi-builder'):
        owner.run('git', 'submodule', 'update', '--init', '--depth=1', '--',
                  'pxe/mkosi', 'pxe/ipxe/upstream', cwd=owner.core)
        pxe = owner.image('pxe-builder', owner.core / 'dev/docker/Dockerfile.pxe-build-container',
                          owner.core / 'dev/docker')
        recipe = owner.root / 'Dockerfile.arm-mkosi-builder'
        recipe.write_text(f'FROM {pxe}\nRUN apt-get update && '
                          'DEBIAN_FRONTEND=noninteractive apt-get install -y '
                          'qemu-user-static gcc-aarch64-linux-gnu && rm -rf /var/lib/apt/lists/*\n')
        assembly = owner.image('arm-mkosi-builder', recipe, owner.core)
    with owner.stage('arm64-rootfs-uefi'):
        script = owner.repo / 'tools/arm64-mkosi.sh'
        owner.file('recipes/arm64-mkosi.sh', script)
        owner.run(*common, '--privileged',
                  '-v', '/proc/sys/fs/binfmt_misc:/binfmt',
                  '-v', f'{owner.public_ca}:/inputs/scout-ca.crt:ro',
                  '-v', f'{script}:/inputs/build.sh:ro',
                  '-e', 'ARM_BINFMT_NAME=pxeye-' + owner.run_id.lower(),
                  assembly, 'bash', '/inputs/build.sh')
    with owner.stage('arm64-content-inspection'):
        inspector = owner.repo / 'tools/arm64-inspect.py'
        owner.file('recipes/arm64-inspect.py', inspector)
        owner.run(*common, '-v', f'{owner.public_ca}:/inputs/scout-ca.crt:ro',
                  '-v', f'{inspector}:/inputs/inspect.py:ro', assembly,
                  'python3', '/inputs/inspect.py', '--version', version,
                  '--core', owner.state['sources']['core']['commit'],
                  '--libredfish', owner.state['sources']['libredfish']['commit'])
        payload = owner.core / 'pxe/static/blobs/internal/aarch64'
        destination = owner.root / 'arm64-materials'
        destination.mkdir()
        names = ('BUILD-INFO.json', 'ROOTFS-PACKAGES.json', 'golan.efi',
                 'ipxe.efi', 'scout.efi', 'scout.squashfs', 'MATERIAL-RECIPE.json')
        for name in names:
            shutil.copyfile(payload / name, destination / name)
            owner.file('arm64/' + name, destination / name)
        owner.state['arm64_materials'] = {
            'directory': str(destination), 'recipe': str(destination / 'MATERIAL-RECIPE.json'),
            'core_commit': owner.state['sources']['core']['commit'],
            'libredfish_commit': owner.state['sources']['libredfish']['commit'],
            'inspection': json.loads((destination / 'BUILD-INFO.json').read_text()),
        }
        owner.save()
        print('ARM64_MATERIALS_DIR=' + str(destination), flush=True)
