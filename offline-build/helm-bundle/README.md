# Legacy Helm bundle builder

**English** · [简体中文](README.zh-CN.md)

This directory is retained only for compatibility with the earlier schema-1
prepared-materials workflow. It is an internal implementation path, not the
supported entry point for a new PXEye/NICo offline delivery.

Use the repository-level workflow instead:

```bash
cd ~/pxeye-build/PXEye
REGISTRY=<registry-host:port> make images
# Set the Chart image to PUBLISHED_PXEYE_IMAGE manually.
vi charts/pxeye/values.yaml
REGISTRY=<registry-host:port> make cache-images
REGISTRY=<registry-host:port> make bundles
```

The supported `make bundles` path renders the locked PXEye parent Chart,
exports exactly that Registry image closure, relocates it once, and writes the
delivery below `outputs_/output/`. Optional ARM64 boot materials are enabled
only through `INCLUDE_ARM64_MATERIALS=1` and `ARM64_MATERIALS_DIR`; that
behavior belongs to the repository-level entry point so the material image is
present before the first Chart render.

`build.py` remains available for migration or inspection of an already-created
schema-1 `materials_bundle`. It expects that old input contract and may build
the historical material groups itself. Do not mix its `output_root`,
`bundle_id`, or `include` fields with the current `build-config.json`, and do
not use it for the standard field package.

For the current configuration, outputs, recovery behavior and onsite handoff,
see [the offline delivery guide](../README.md).
