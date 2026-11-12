# Step 2: Chart preparation and offline packaging

**English** · [简体中文](README.zh-CN.md) · [Overview](../README.md)

`build.py` consumes step-one images, downloads pinned upstream Charts, prepares project Charts and creates a relok8s offline delivery. Run on a Linux amd64 builder with Python 3.11+/PyYAML, Docker and Helm 3.

## Configuration

Use the same work directory as step one:

```json
{
  "work_directory": "~/pxeye-build"
}
```

The script reads OCI archives and image locks from `<work_directory>/offline-images/`. Chart, cache, packaging-input and output paths are derived automatically.

## Chart sources

[chart-sources.json](chart-sources.json) locks download URLs, archive SHA256, names, versions and archive subdirectories.

| Chart | Source | Preparation |
| --- | --- | --- |
| NICo `0.1.1` | [Pinned upstream helm source](https://github.com/dsx-ai-factory/infra-controller/tree/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921/helm) | Download the commit archive, extract `helm/`, apply compatibility patches and package |
| cert-manager `v1.17.1` | `oci://quay.io/jetstack/charts/cert-manager` | Pull the version, verify its archive and extract |
| PXEye | [charts/pxeye](../../charts/pxeye/README.md) | Use the same repository Chart as direct Helm installation, with the selected image |
| Platform | [deploy/nico-platform](../../deploy/nico-platform/Chart.yaml) | Repository Chart for database, certificates and Vault bootstrap |
| Materials | [charts.py](charts.py) | Generate from the selected material images |

The NICo source URL is:

```text
https://codeload.github.com/dsx-ai-factory/infra-controller/tar.gz/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921
```

This commit matches the e703 image profile; `main` and the Chart version alone do not identify the source revision. Internal Chart symlinks become regular files. Name, version or hash mismatches stop preparation.

Optional `sources.charts` overrides support HTTP(S), OCI and local `file://` archives. Every source requires SHA256; `subdirectory` identifies the archive directory containing `Chart.yaml`. Example using a retained original Chart package:

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "charts": {
      "core": {
        "url": "file:///srv/nico-input/nico-0.1.1.tgz",
        "sha256": "9e38837fcd7305ffd5e060ba18e973794388d3b0f83363b7903a21d3ae94ad67",
        "subdirectory": "nico"
      }
    }
  }
}
```

Upgrades require coordinated changes to the download lock, image list and compatibility profile. Source overrides select equivalent versioned releases or mirrors.

## Optional materials and image roles

The default packages the 13 Core/PXEye images without additional ARM64 Scout, APT or BFB files. `sources.materials` enables selected binary inputs; step two verifies their locked inventory and builds material images:

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "materials": {
      "aarch64": "/srv/nico-input/scout-aarch64",
      "apt": "/srv/nico-input/apt",
      "bfb": "/srv/nico-input/dpu"
    }
  }
}
```

ARM64 contains six Scout release files, APT contains `dists/` and `pool/`, and BFB contains `bf3-doca3.4.0-26.04/`. Omitted groups are excluded. This wraps binary releases; it does not compile NICo/Scout.

UI/bootstrap roles default to the e703 profile. For other step-one versions, set `sources.images.ui` and `sources.images.bootstrap` to exact exported references. Optional `tools` overrides `docker`, `helm` and `relok8s` paths; defaults use installed or locked tools.

## Execution

Run on the builder with the repository at `/srv/PXEye` and step-one export completed:

```bash
mkdir -p "$HOME/pxeye-build"
test ! -e "$HOME/pxeye-build/helm-build.json" &&
cp /srv/PXEye/offline-build/helm-bundle/build-config.example.json "$HOME/pxeye-build/helm-build.json"
```

Prepare Charts only, without an image export, Docker or cluster access:

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json" --prepare-charts
```

Success emits `CHARTS_READY`; verified reuse emits `REUSE_CHARTS`. Inspect the full packaging plan without downloads or builds:

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json" --plan
```

The complete build includes Chart preparation automatically:

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json"
```

Success emits `HELM_BUILD_COMPLETE`; `DELIVERY_FILES` lists the three step-three inputs.

## Directory structure

```text
work_directory/
  offline-images/
  cache/charts/
  charts/<id>/
    upstream/{core,cert-manager}/
    raw/charts/
    trees/{core,cert-manager,platform,pxeye}/
    deployment/charts/
    deployment/patches/
    sources.json
  package-input/<id>/
  logs/chart-preparation/run.log
  output/<version>/
    bundle.tar.gz
    onsite-tools.tar.gz
    SHA256SUMS
    bundle/
    progress.json
    events.jsonl
    run.log
    logs/
```

Extracted Chart directories contain `Chart.yaml`, `values.yaml`, `templates/` and dependencies. `deployment/charts/` preserves the archive layout used by the existing packager. `sources.json` inventories Chart provenance and file hashes. The delivered `manifests/build-report.json` also records upstream URLs and archive hashes.

The three delivery files are the inputs for [step three](../onsite/README.md). The delivery format and onsite entry point remain compatible.

## Recovery and compatibility

Repeated runs verify and reuse downloads, Charts, complete packaging inputs and packaging stages. Failed Chart attempts retain staging evidence; retries reuse verified downloads. Build progress resides under `output/.<version>.building/`, then moves into the completed version directory. Changed inputs or implementation require a separate work directory or delivery version.

Existing schema-1 `nico-prepared` / `nico-materials` configurations remain supported. An optional `chart_sources` object enables downloads in that mode, with the same fields as `sources.charts`; otherwise input Charts remain in use. `--prepare-charts` can run preparation separately.
