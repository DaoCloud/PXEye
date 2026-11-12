# Step 1: offline image and material preparation

**English** · [简体中文](README.zh-CN.md) · [Three-step overview](../README.md)

`build.py` generates an offline image directory, builds material images and publishes a prepared directory for step two. It runs on a Linux amd64 build host with one configuration declaring the build contents and paths.

## Offline image directory

`input_root/<source-id>/` contains exported OCI image archives, Helm Charts and boot materials. The script generates the directory; its identifier is derived from source settings, the version recipe and material switches. The `sources` configuration declares the upstream inputs:

| Source | Script action | Required upstream input |
| --- | --- | --- |
| `sources.containerd_content` | Export three OCI archives from the 13 locked amd64 manifest graphs | Previously built or pulled image blobs, selected by immutable recipe digests |
| `sources.charts` | Collect and verify two Charts | `nico-0.1.1.tgz`, `cert-manager-v1.17.1.tgz`, matching recipe hashes |
| `sources.materials.aarch64` | Collect six ARM64 Scout outputs | `BUILD-INFO.json`, `ROOTFS-PACKAGES.json`, `ipxe.efi`, `golan.efi`, `scout.efi`, `scout.squashfs` |
| `sources.materials.apt` | Collect indexes and two Scout packages | `dists/` and `pool/` under this root |
| `sources.materials.bfb` | Collect vendor BFB and checksum | `bf3-doca3.4.0-26.04/` under this root |

## Supported scope

`recipe-e703.json` locks image, Chart and material digests for the e703 profile and its customized artifacts. Preparation exports existing images, collects binary releases and builds material images. NICo and ARM64 Scout compilation belongs to upstream build workflows; BFB uses a vendor release.

Enabled material groups require source files matching the recipe. Missing sources are reported together before generation; disabled groups do not require their files. Containerd content is accessed read-only, with image versions pinned by the recipe.

## Build stages

| Stage | Action | Key point |
| --- | --- | --- |
| 1. Collect files | Verify and copy Charts and selected materials | Recipe files only; no credentials, site configuration or databases |
| 2. Export images | Read locked manifest/config/layers from containerd content | Export complete amd64 graphs without requiring other architectures |
| 3. Verify inputs | Verify files and prepare the OCI layout | Archive tar hashes may change; locked image manifest digests must match |
| 4. Build material images | Build or reuse ARM64 Scout, APT and BFB images | 13 input images plus three material images when all enabled |
| 5. Publish prepared | Prepare compatible Charts, verify, emit step-two configuration | Copy the printed `NEXT_COMMAND` |

## Configure and run

The configuration declares upstream sources and output locations. These examples run on the build host with the repository at `/srv/PXEye`:

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

`sources` points to existing upstream inputs. `input_root` is the generated raw-input parent. `output_root`, `cache_directory` and `package_output_root` are the prepared, cache and packaging parents. Keep them separate from sources and the checkout. `/srv/nico-sources/` in the example is only a placeholder; the script does not create or download its contents.

`--plan` checks source presence, sizes and image graphs without generating build artifacts:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

Build command:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

Successful completion emits `RAW_INPUT_COMPLETE`, `MATERIAL_PREPARE_COMPLETE`, `HELM_BUILD_CONFIG` and `NEXT_COMMAND`. The last two provide the generated configuration path and build command for [step two](../helm-bundle/README.md).

## Directory structure and recovery

```text
input_root/<source-id>/
  images/{base,ui,bootstrap}.oci.tar
  charts/*.tgz
  boot/{aarch64,apt}/...
  http/nico/dpu/...
  manifests/{images.txt,images-lock.json,source-files.json}
  source-progress.json
output_root/<id>/
  prepared.json
  images/layout/
  deployment/
  tools/helm
  manifests/
  reports/
  logs/
output_root/<id>.helm-build.json
output_root/<id>.result.json
```

Recovery uses the same configuration and build command. Raw inputs are verified and reused per file; material images and complete prepared outputs are reused by digest. Unrecorded or changed files block overwrites, and existing outputs are retained. Terminal output reports stages and file generation/reuse status. `source-progress.json` records source-stage progress, sizes, hashes and origins; prepared `logs/` and `reports/` retain build output and provenance. Step two creates the final compressed bundle.

Configuration schema 2 generates the offline image directory; schema 1 supports existing archives.
