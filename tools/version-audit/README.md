# Runtime and offline packaging version audit

**English** · [简体中文](README.zh-CN.md)

Export and compare committed packaging inputs with running artifacts. The tool does not build or pull images, change Kubernetes resources, or modify existing bundles.

## Usage

Run on a Linux host with access to Kubernetes and the build image cache. Requires Python 3.11+, PyYAML, Git, Helm 3 and kubectl. Reading containerd blobs usually requires root.

```bash
cd /path/to/PXEye
AUDIT=tools/version-audit/audit.py

python3 "$AUDIT" package --repo "$PWD" \
  --registry 127.0.0.1:1027 --registry-http --output /tmp/pxeye-audit/package.json

python3 "$AUDIT" runtime --context kubernetes-admin@kubernetes \
  --output /tmp/pxeye-audit/runtime.json

python3 "$AUDIT" compare \
  --package /tmp/pxeye-audit/package.json \
  --runtime /tmp/pxeye-audit/runtime.json \
  --output /tmp/pxeye-audit/comparison.json
```

Snapshots may be collected on different hosts and copied together for comparison. Consult `--help` and subcommand help for options.

## Coverage

| Artifact | Packaging baseline | Runtime evidence | Comparison |
| --- | --- | --- | --- |
| Images | Reuse the packager from a committed Git snapshot to render the full parent Chart and dependency image closure | Active Pod main/init containers, actual imageID, Pod UID and node | Linux platform manifest digest by image role |
| x86 Boot / Scout | Hash selected files from the configured Boot image's local layers | Hash files actually published by NICo PXE, including external mounts | Relative path and SHA256 |
| ARM Boot / Scout | With `--include-arm64`, read the committed ARM file recipe | Published `aarch64/` files | Relative path and SHA256 |
| Additional ISO/materials | The default bundle excludes externally supplied ISO files | With `--include-site-files`, hash published site materials under `nico/` | Report runtime-only files separately |

JSON preserves image references, available OCI version/revision labels and the Scout revision declared by `BUILD-INFO.json`. Actual file hashes determine equality. Credentials, file contents and cloud-init/user-data are not exported.

## Results

Reports use these Chinese status labels:

| Status | Meaning |
| --- | --- |
| 一致 | Both content hashes are available and equal |
| 不一致 | Hashes differ, or a role/path contains conflicting content versions |
| 仅打包 | Present only in packaging, such as a Boot init image replaced by external runtime files; also inspect the file results |
| 仅环境 | Present only in runtime, such as an external ISO or extra service |
| 无法确认 | Content, identity or access is unavailable; equal tags alone never imply equality |

Console output and `comparison.txt` group images and files, showing up to 12 files per status plus counts. JSON contains every item, full hashes, consumers and collection errors. Exit codes: `0` complete export/all equal; `2` differences or incomplete verification; `1` command failure.

## Options and limits

- `package --revision <commit>` defaults to `HEAD`. Chart values, patches, packaging code and recipes all come from that commit, ignoring dirty files and old bundle locks.
- `package --registry <host:port>` uses the same cache hostname mapping as `make bundles`. It reads current Registry tag metadata instead of trusting stale local tags. Add `--registry-http` for HTTP; otherwise HTTPS uses system CA validation. Without a Registry, resolve local containerd records.
- `package --chart-cache <directory>` reuses checksum-named archives from the build workspace's `cache/charts`, verifying hashes first. Missing pinned Helm sources may be downloaded. No prebuilt bundle is required.
- `package --include-arm64` corresponds to `make bundles INCLUDE_ARM64_MATERIALS=1`. Default is disabled, matching Make. The material image digest is generated during an actual build; this audit exports the committed payload file identities.
- `runtime --namespace <name>` is repeatable; defaults to `nico-system`, `mmzhou` and `cert-manager`. The default Pod name pattern is `nico|pxeye|os-install-console|cert-manager`, adjustable via `--name-pattern`. Finished and deleting Pods are excluded.
- `runtime --include-site-files` also hashes uploads under `nico/`. Default skips site uploads and focuses on Boot/Scout infrastructure files. Large ISO hashes can take time.
- `runtime --boot-root <path>` defaults to `/forge-boot-artifacts/blobs/internal` inside PXE. Actual hashing, particularly ISO files, can take time. Requires `sh`, `find`, `sha256sum` and, for build metadata, `head` in that container.
- `--architecture amd64|arm64` selects the control-plane container platform, default `amd64`, independently of the installed host architecture.
- `--content-dir`, `--ctr`, `--containerd-namespace` adapt local storage access. Kind stores content inside its node containers; supply accessible paths/tools. Missing content remains unverified.

Registry requests do not read private login credentials. Pre-cache images and omit `--registry` when necessary. Large image layers are never downloaded implicitly. Linked Boot files remain unverified. The tool does not scan other nodes' stores automatically.

This compares committed packaging inputs with runtime artifacts; it does not verify a produced archive or certify a physical OS installation. Retain reports and use immutable release references because mutable tags can change after collection.
