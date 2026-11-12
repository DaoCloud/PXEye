# Step 2: Build the offline delivery

**English** · [简体中文](README.zh-CN.md)

Run on a Linux amd64 builder with Python 3.11+, PyYAML, Docker, Helm 3 and a completed step-one image export.

## Example configuration

[build-config.example.json](build-config.example.json):

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "images": {
      "ui": "docker.io/library/mmzhou-os-install-console:0.22.16-2edc182",
      "bootstrap": "docker.io/library/mmzhou-os-install-console:0.22.16-2edc182"
    }
  }
}
```

This PXEye image serves both application and build-tool roles. The step-one export must include this reference.

## Commands

Run in the build work directory with the checkout under `PXEye/`:

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/helm-bundle/build.py --write-config ./helm-build.json --work-directory "$PWD"
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./helm-build.json
```

Skip configuration creation when the file already exists. Repeat the final command to resume a failed build.

## Output

Success prints `HELM_BUILD_COMPLETE`. `DELIVERY_FILES` lists:

```text
output/<version>/bundle.tar.gz
output/<version>/onsite-tools.tar.gz
output/<version>/SHA256SUMS
```

Progress and logs: `output/.<version>.building/progress.json` and `run.log`, moved to `output/<version>/` on success.

[Chart sources and optional settings](REFERENCE.md) · [Step 3](../onsite/README.md)
