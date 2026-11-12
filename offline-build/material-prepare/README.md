# Step 1: export offline images

**English** · [简体中文](README.zh-CN.md) · [Overview](../README.md)

`build.py` exports listed linux/amd64 images from local containerd into a fixed directory structure and OCI archive. Requirements: Linux, Python 3.11+, ctr, and permission to read the containerd socket and content store. Images must already exist locally. The exporter does not pull images, generate Charts or build material images.

## Configuration

The configuration template explicitly names the work directory and image list; `~/` is supported:

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "image_list": "images.txt"
  }
}
```

The default [images.txt](images.txt) lists one exact local image reference per line, with blank lines and `#` comments supported. The supplied list selects 13 Core/PXEye e703-series images; it does not discover running Pods or include unlisted images. Each execution resolves and records the image digests.

`sources.image_list` resolves relative to the configuration file, so this example uses `$HOME/pxeye-build/images.txt`. The repository source list is `offline-build/material-prepare/images.txt`; edit the working copy to select images for the export. Other `sources` fields support nonstandard environments:

| Field | Default | Purpose |
| --- | --- | --- |
| `image_list` | `images.txt` beside the script | Custom image list |
| `containerd_address` | `/run/containerd/containerd.sock` | Local containerd socket |
| `containerd_namespace` | `k8s.io` | Namespace containing image references |
| `containerd_content` | `/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256` | Matching SHA256 content store |
| `ctr` | `ctr` | ctr executable |

Custom paths support `~/`; relative source paths resolve against the configuration directory. The socket and content store must belong to the same runtime. Sources do not include Charts or independent material directories.

## Execution

These examples assume the repository is `/srv/PXEye` and run on the containerd host:

```bash
mkdir -p "$HOME/pxeye-build"
test ! -e "$HOME/pxeye-build/build-config.json" &&
test ! -e "$HOME/pxeye-build/images.txt" &&
cp /srv/PXEye/offline-build/material-prepare/images.txt "$HOME/pxeye-build/images.txt" &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json "$HOME/pxeye-build/build-config.json"
```

Inspect and edit the image list for this export:

```bash
cat "$HOME/pxeye-build/images.txt"
${EDITOR:-vi} "$HOME/pxeye-build/images.txt"
```

Check references and required amd64 content without creating output directories:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config "$HOME/pxeye-build/build-config.json" --plan
```

Export:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config "$HOME/pxeye-build/build-config.json"
```

Completion prints `IMAGE_EXPORT_COMPLETE`; verified reuse prints `IMAGE_EXPORT_REUSED`.

## Output format

```text
work_directory/
  offline-images/
    images/nico-amd64.oci.tar
    manifests/images.txt
    manifests/images-lock.json
    export.json
    SHA256SUMS
  logs/image-export/
    progress.json
    events.jsonl
    run.log
```

The existing image-export format is preserved:

- `images/nico-amd64.oci.tar` uses OCI Image Layout with `oci-layout`, `index.json` and `blobs/sha256/`.
- Index descriptors retain the `linux/amd64` platform, original reference, and both `io.containerd.image.name` and `org.opencontainers.image.ref.name` annotations.
- `images-lock.json` remains an array with `image`, `source_descriptor`, `amd64_manifest`, `config` and `layers`, with the same meanings as the original exporter.
- Only selected amd64 manifests, configurations and layers are included. Shared blobs appear once; other architectures need not be cached.
- `export.json`, checksums and logs are additional metadata. Archive hashes change when image contents change; byte-for-byte identity with historical archives is not required.

Verify outputs:

```bash
cd "$HOME/pxeye-build/offline-images"
sha256sum -c SHA256SUMS
```

## Stages and recovery

| Stage | Action |
| --- | --- |
| resolve | Read the list, resolve local references and validate required platform content |
| export | Verify blob digests and write the OCI archive |
| publish | Generate compatible inventories/checksums and atomically publish outputs |

Fix failures and rerun the same command. Completed archives are verified before reuse; interrupted archive writes restart the archive stage rather than resuming by byte offset. `.offline-images.building/` and logs are retained. Changed image versions or lists require a new work directory. Unknown or damaged completed files are not overwritten automatically.

[Step two](../helm-bundle/README.md) uses the same work directory, consumes this export, downloads and prepares Charts, and generates its internal packaging input. Chart and independent material sources belong to step two. Legacy schema 1/2 material-preparation configurations remain compatible.
