#!/usr/bin/env bash
# Build a reusable loader once. Site URLs and MAC addresses are never compiled in.
set -euo pipefail
umask 022

revision=bbd7821bd42da5456ee068a471ef73d525ea26a1
repository=https://github.com/ipxe/ipxe.git
source_directory=
output_directory=
while (($#)); do
  case "$1" in
    --source) source_directory="$2"; shift 2 ;;
    --output) output_directory="$2"; shift 2 ;;
    *) echo "Usage: $0 [--source PINNED_IPXE_CHECKOUT] --output DIRECTORY" >&2; exit 2 ;;
  esac
done
test -n "$output_directory" || { echo "Missing --output" >&2; exit 2; }
mkdir -p "$output_directory"
output_directory="$(cd "$output_directory" && pwd)"
work_directory="$(mktemp -d)"
trap 'rm -rf "$work_directory"' EXIT
if test -z "$source_directory"; then
  source_directory="$work_directory/ipxe"
  git init -q "$source_directory"
  git -C "$source_directory" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 \
    fetch -q --depth 1 "$repository" "$revision"
  git -C "$source_directory" checkout -q --detach FETCH_HEAD
fi
test "$(git -C "$source_directory" rev-parse HEAD)" = "$revision" || {
  echo "Expected iPXE revision $revision" >&2; exit 1;
}
test -z "$(git -C "$source_directory" status --porcelain --untracked-files=normal)" || {
  echo "Use a clean pinned iPXE checkout" >&2; exit 1;
}
export SOURCE_DATE_EPOCH="$(git -C "$source_directory" show -s --format=%ct HEAD)"
mkdir -p "$source_directory/src/config/local"
printf '#define CONSOLE_SERIAL\n' > "$source_directory/src/config/local/console.h"
printf '#define SERIAL_FIXED\n' > "$source_directory/src/config/local/serial.h"
make -C "$source_directory/src" -j "${BUILD_JOBS:-2}" \
  bin-x86_64-efi/ipxe.efi EMBED=
cp "$source_directory/src/bin-x86_64-efi/ipxe.efi" "$output_directory/ipxe.efi"
# genfsimg needs syslinux only in this build stage. The runtime receives the FAT
# template and needs only mcopy and xorriso to insert /autoexec.ipxe.
"$source_directory/src/util/genfsimg" -p 1024 \
  -o "$work_directory/generic.iso" "$output_directory/ipxe.efi"
xorriso -osirrox on -indev "$work_directory/generic.iso" \
  -extract /esp.img "$output_directory/esp.img"
cp "$source_directory"/COPYING* "$output_directory/"
python3 - "$output_directory" "$revision" "$repository" "$SOURCE_DATE_EPOCH" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output, revision, repository, epoch = sys.argv[1:]
root = Path(output)
manifest = {
    "schema_version": 1,
    "architecture": "x86_64",
    "ipxe_revision": revision,
    "ipxe_repository": repository,
    "source_date_epoch": int(epoch),
    "efi_sha256": hashlib.sha256((root / "ipxe.efi").read_bytes()).hexdigest(),
    "esp_sha256": hashlib.sha256((root / "esp.img").read_bytes()).hexdigest(),
    "embedded_script": False,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
chmod 0644 "$output_directory"/*
printf 'BOOT_MEDIA_ASSETS_COMPLETE %s\n' "$output_directory"
