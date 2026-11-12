# Step 2: Build the offline delivery

**English** · [简体中文](README.zh-CN.md)

Run on a Linux amd64 builder with Python 3.11+, PyYAML, Docker, Helm 3 and the step-one export.

## Shared configuration

Continue using the same `build-config.json`. Step two owns only `helm_bundle`:

```json
{
  "work_directory": "~/pxeye-build",
  "image_export": {},
  "helm_bundle": {
    "chart_sources": "chart-sources.json"
  }
}
```

The default [chart-sources.json](chart-sources.json) lists the NICo e703126e4 download URL, Chart 0.1.1 and checksum, plus the cert-manager v1.17.1 OCI source and checksum. A source is checked only when first downloaded; the resulting checksum-named file in `cache/charts/` is reused without network access or rehashing. The builder vendors both under the PXEye parent, adds the repository platform and optional-material Charts, generates `Chart.lock`, renders the complete dependency closure, then runs relok8s once. `chart_sources` resolves relative to the configuration file.

## Commands

Run in the build work directory with the checkout under `PXEye/`:

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/helm-bundle/build.py --write-config ./build-config.json
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json
```

Initialization fills only missing step-two settings and `chart-sources.json`, preserving existing values and sources. In the unified workflow the parent Chart generates the image closure; images and roles come from the explicit cache-seed artifact. Repeat the final command to resume.

## Output

Success prints `HELM_BUILD_COMPLETE`; `DELIVERY_FILES` lists:

```text
output/<version>/bundle.tar.gz
output/<version>/onsite-tools.tar.gz
output/<version>/SHA256SUMS
```

Progress and logs reside under `output/.<version>.building/`, moved into the version directory on success.

[Optional configuration](REFERENCE.md) · [Step three](../onsite/README.md)
