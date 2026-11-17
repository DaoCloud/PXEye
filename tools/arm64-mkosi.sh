#!/bin/bash
# Runs only in the privileged, task-owned mkosi builder container.
set -euo pipefail
: "${ARM_BINFMT_NAME:?}"
[[ "$ARM_BINFMT_NAME" =~ ^pxeye-[a-z0-9-]+$ ]]
test -e /binfmt/register
test ! -e "/binfmt/$ARM_BINFMT_NAME"
cleanup() {
  if test -e "/binfmt/$ARM_BINFMT_NAME"; then
    echo -1 >"/binfmt/$ARM_BINFMT_NAME"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
magic='\x7f\x45\x4c\x46\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00'
mask='\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff'
printf ':%s:M:0:%s:%s:/usr/bin/qemu-aarch64-static:CF' "$ARM_BINFMT_NAME" "$magic" "$mask" >/binfmt/register
cd /code
# Each task reads the pinned submodule and the current source checkout.
git config --global --add safe.directory /code
git config --global --add safe.directory /code/pxe/ipxe/upstream
cargo make --cwd pxe ipxe-aarch64
cargo make --cwd pxe --env FORGE_CA_PATH=/inputs/scout-ca.crt create-ephemeral-image-arm-host-ci
