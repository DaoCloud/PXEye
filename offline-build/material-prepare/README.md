# Step 1: Export offline images

**English** · [简体中文](README.zh-CN.md)

Run on the local containerd Linux host with Python 3.11+ and ctr. Listed images must already exist locally.

## Shared configuration

Both build steps use only `build-config.json` in the work directory. Step one owns `image_export`:

```json
{
  "work_directory": "~/pxeye-build",
  "image_export": {
    "image_list": "images.txt"
  },
  "helm_bundle": {
    "chart_sources": "chart-sources.json"
  }
}
```

The repository [images.txt](images.txt) selects 12 pinned Core/PXEye images. `image_list` resolves relative to the configuration file. A trailing `# roles=ui,bootstrap` assigns roles, which step one records for step two.

## Commands

Run in the build work directory with the checkout under `PXEye/`:

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/material-prepare/build.py --write-config ./build-config.json --work-directory "$PWD"
python3 ./PXEye/offline-build/material-prepare/build.py --config ./build-config.json
```

Initialization fills only missing step-one settings and `images.txt`, preserving existing values, lists and step-two settings. Edit the work-directory list to change image selection. Add `--plan` for a read-only prerequisite check.

## Output

```text
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

Success prints `IMAGE_EXPORT_COMPLETE`. The historical five-field image lock remains unchanged; `export.json` adds image roles. Repeat the command to resume. Completed exports are never overwritten; changed image sets need a new work directory.

[Step two](../helm-bundle/README.md) reads the same `build-config.json` without selecting images again.
