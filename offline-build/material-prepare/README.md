# Step 1: generate raw inputs and prepare images

**English** · [简体中文](README.zh-CN.md) · [Three-step overview](../README.md)

**Run on a Linux amd64 build host. One configuration and one script, starting with creation of the raw input directory.** No running-cluster image discovery, containerd changes or deployment.

## Where raw inputs come from

The historical offline directory was assembled manually: 23 containerd images were exported, Charts, x86/APT artifacts and a vendor BFB were collected, and separately cross-compiled ARM64 Scout outputs were added. It was neither Git content nor the output of one reproducible historical entry point.

The script now creates `input_root/<source-id>/` itself. It does not require that historical directory. The same configuration declares its original sources:

| Source | Script action | Required upstream input |
| --- | --- | --- |
| `sources.containerd_content` | Export three OCI archives from the 13 locked amd64 manifest graphs | Previously built or pulled image blobs, selected by immutable recipe digests |
| `sources.charts` | Collect and verify two Charts | `nico-0.1.1.tgz`, `cert-manager-v1.17.1.tgz`, matching recipe hashes |
| `sources.materials.aarch64` | Collect six ARM64 Scout outputs | `BUILD-INFO.json`, `ROOTFS-PACKAGES.json`, `ipxe.efi`, `golan.efi`, `scout.efi`, `scout.squashfs` |
| `sources.materials.apt` | Collect indexes and two Scout packages | `dists/` and `pool/` under this root |
| `sources.materials.bfb` | Collect vendor BFB and checksum | `bf3-doca3.4.0-26.04/` under this root |

**Exporting images and collecting binary releases does not recompile NICo/Scout.** The current profile locks e703 and existing customized outputs; it cannot rebuild them starting solely from Git. ARM64 Scout requires independent cross-build outputs; BFB is a vendor release. Missing sources are listed together before generation, without falling back to the historical bundle. Disabled material groups do not require their files.

## Stages

| Stage | Action | Key point |
| --- | --- | --- |
| 1. Collect files | Verify and copy Charts and selected materials | Recipe files only; no credentials, site configuration or databases |
| 2. Export images | Read locked manifest/config/layers from containerd content | Export complete amd64 graphs without requiring other architectures |
| 3. Verify inputs | Verify files and prepare the OCI layout | Archive tar hashes may change; locked image manifest digests must match |
| 4. Build material images | Build or reuse ARM64 Scout, APT and BFB images | 13 input images plus three material images when all enabled |
| 5. Publish prepared | Prepare compatible Charts, verify, emit step-two configuration | Copy the printed `NEXT_COMMAND` |

## Configure and run

Goal: declare original source and output locations. Run on the build host; these commands assume the repository is `/srv/PXEye`. Create the configuration yourself:

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

`sources` points to existing upstream inputs. `input_root` is the generated raw-input parent. `output_root`, `cache_directory` and `package_output_root` are the prepared, cache and packaging parents. Keep them separate from sources and the checkout. `/srv/nico-sources/` in the example is only a placeholder; the script does not create or download its contents.

Confirm source presence, sizes and image graphs without copying, exporting or building:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

Execute:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

Confirm `RAW_INPUT_COMPLETE`, `MATERIAL_PREPARE_COMPLETE`, `HELM_BUILD_CONFIG` and `NEXT_COMMAND`. Run the last command to enter [step two](../helm-bundle/README.md); no manual packaging configuration is needed.

## Outputs and resume

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

Fix failures and rerun the same command. Raw-input generation resumes per file after checksum verification; material images and complete prepared outputs reuse verified content. Unrecorded or changed files are never overwritten, and old outputs are retained. The terminal prints stages and per-file generation/reuse. `source-progress.json` records source-stage progress, sizes, hashes and origins; prepared logs and provenance remain available. This step does not create the final compressed bundle.

Legacy schema 1 configurations still accept existing archives. New configurations use schema 2.
