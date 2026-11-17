"""Build Grace boot payloads from the source build's frozen Core checkout."""
import json
import shutil


def build(owner):
    """Cross-compile Scout, rebuild ARM rootfs/UEFI, then inspect final bytes."""
    version = '0.0.0-main-' + owner.state['sources']['core']['commit'][:12]
    # Cargo host build scripts are native executables. Ubuntu-built scripts
    # cannot be reused in the Debian cross builder even with the same rustc.
    target = owner.root / 'arm64-target'
    target.mkdir(exist_ok=True)
    owner.state['arm64_target_directory'] = str(target)
    common = ['docker', 'run', '--rm', '--platform', 'linux/amd64',
              '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
              '-e', 'GIT_CONFIG_VALUE_0=/code', '-e', f'VERSION={version}',
              '-v', f'{owner.core}:/code', '-v', f'{target}:/code/target', '-w', '/code']
    if getattr(owner, 'arm64_reuse', False):
        finish(owner, version, common, owner.state['builders']['arm-mkosi-builder']['reference'])
        return
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
    with owner.stage('arm64-scout-compile-package'):
        owner.run(*common, cross, 'cargo', 'make', 'package-scout-aarch64-release-local')
        owner.dependencies()
        for name in ('forge-scout', 'mlx-firmware-supervisor'):
            owner.file('arm64/bin/' + name,
                       target / 'aarch64-unknown-linux-gnu/release' / name)
        owner.file('arm64/scout.deb', target / f'debs/forge-scout_{version}_arm64.deb')
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
    finish(owner, version, common, assembly)


def finish(owner, version, common, assembly):
    """Checkpoint assembly bytes and require full inspection before publication."""
    payload = owner.core / 'pxe/static/blobs/internal/aarch64'
    previous_recipe = owner.state['files'].get('recipes/arm64-mkosi.sh', {}).get('sha256')
    script = owner.snapshot_recipe('arm64-mkosi.sh', owner.arm_recipe_repo / 'tools/arm64-mkosi.sh')
    recipe_sha = owner.state['files']['recipes/arm64-mkosi.sh']['sha256']
    last_assembly = next((row for row in reversed(owner.state['timings'])
                          if row['stage'] == 'arm64-rootfs-uefi'), {})
    completed = last_assembly.get('status') == 'completed'
    reuse = bool(owner.args.resume and completed and previous_recipe == recipe_sha)
    if reuse:
        # restore() already checked frozen sources and every existing checkpoint.
        # Older failed builds have no assembly checkpoint: capture their bytes
        # now, explicitly recording that origin, then run full content inspection.
        with owner.stage('arm64-rootfs-reuse'):
            print('Reusing completed ARM assembly; full content inspection remains required.', flush=True)
    else:
        with owner.stage('arm64-rootfs-uefi'):
            owner.run(*common, '--privileged',
                      '-v', '/proc/sys/fs/binfmt_misc:/binfmt',
                      '-v', f'{owner.public_ca}:/inputs/scout-ca.crt:ro',
                      '-v', f'{script}:/inputs/build.sh:ro',
                      '-e', 'ARM_BINFMT_NAME=pxeye-' + owner.run_id.lower(),
                      assembly, 'bash', '/inputs/build.sh')
    prior = owner.state.get('arm64_assembly', {})
    origin = prior.get('checkpoint_origin') if reuse and prior else (
        'post-failure-recovery' if reuse else 'assembly-completion')
    for name in ('ipxe.efi', 'golan.efi', 'scout.efi', 'scout.squashfs'):
        owner.file('checkpoints/arm64/' + name, payload / name)
    owner.state['arm64_assembly'] = {
        'recipe_sha256': recipe_sha, 'checkpoint_origin': origin,
        'reused_on_this_attempt': reuse,
    }
    owner.save()
    with owner.stage('arm64-content-inspection'):
        inspector = owner.snapshot_recipe('arm64-inspect.py', owner.arm_recipe_repo / 'tools/arm64-inspect.py')
        owner.run(*common, '-v', f'{owner.public_ca}:/inputs/scout-ca.crt:ro',
                  '-v', f'{inspector}:/inputs/inspect.py:ro', assembly,
                  'python3', '/inputs/inspect.py', '--version', version,
                  '--core', owner.state['sources']['core']['commit'],
                  '--libredfish', owner.state['sources']['libredfish']['commit'])
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
