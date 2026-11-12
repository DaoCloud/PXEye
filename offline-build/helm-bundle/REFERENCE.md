# Build configuration reference

**English** · [简体中文](REFERENCE.zh-CN.md) · [Step two](README.md)

## One user configuration

Maintain only `build-config.json` in the work directory. Template: [../build-config.example.json](../build-config.example.json).

| Section | Owner | Contents |
| --- | --- | --- |
| `work_directory` | Initial setup | Shared work directory; initialization cannot change an existing value |
| `image_export` | Step one | Image-list file and optional containerd access settings |
| `helm_bundle` | Step two | Chart-source file, optional binary materials and tool paths |

`--write-config` locks and atomically updates the file, filling only missing fields owned by that step. Existing values, other steps and extension fields are preserved. Default source files are copied only when absent. Normal execution does not modify user configuration.

Relative file paths resolve from the configuration directory; `~/` is supported. Output, log and cache paths derive from the work directory.

## Step one

[images.txt](../material-prepare/images.txt) lists exact local image references, with blank lines, comments and optional trailing roles:

```text
docker.io/library/mmzhou-os-install-console:0.22.16-2edc182 # roles=ui,bootstrap
```

Roles are `ui` and `bootstrap`; one image may serve both. The tool image must provide skopeo, Python and related tools. Step one records roles in `export.json` without changing the historical five-field lock or OCI layout. An unannotated, unique image carrying the PXEye product label can serve both roles. Plain image export does not require PXEye, but packaging needs both roles resolved.

Optional `image_export` fields:

| Field | Default |
| --- | --- |
| `image_list` | Initialized `images.txt` |
| `containerd_address` | `/run/containerd/containerd.sock` |
| `containerd_namespace` | `k8s.io` |
| `containerd_content` | `/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256` |
| `ctr` | `ctr` |

## Step two

[chart-sources.json](chart-sources.json) declares each upstream Chart's `url`, `sha256`, `subdirectory`, `name` and `version`.

- NICo: [e703126e4 helm source](https://github.com/dsx-ai-factory/infra-controller/tree/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921/helm), Chart `0.1.1`, with project compatibility patches.
- cert-manager: `oci://quay.io/jetstack/charts/cert-manager`, pinned `v1.17.1`.
- PXEye: [repository Chart](../../charts/pxeye/README.md). Platform: `deploy/nico-platform`. Materials: generated per group.

HTTP(S), OCI and `file://` archives are supported and verified by hash/version. Versions must match the e703 compatibility profile; upgrading requires coordinated image, source-lock and patch changes. Provenance is recorded in `charts/<id>/sources.json` and the delivery report.

Optional additions inside `helm_bundle`:

```json
{
  "chart_sources": "chart-sources.json",
  "materials": {
    "aarch64": "/srv/nico-input/scout-aarch64",
    "apt": "/srv/nico-input/apt",
    "bfb": "/srv/nico-input/dpu"
  },
  "tools": {"docker": "docker", "helm": "helm", "relok8s": null}
}
```

Materials are excluded by default. Selected binaries must match the pinned inventory/hashes and are wrapped into images in step two, without compiling NICo/Scout. Omitted tools use installed or locked versions.

Both commands read the same configuration:

```bash
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json --plan
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json --prepare-charts
```

`--plan` reads inputs and source settings. `--prepare-charts` downloads and prepares Charts without Docker or cluster access.

## Existing artifacts

Older exports without role metadata are recognized through a unique PXEye product label in OCI configuration. The retained pinned two-image profile also remains supported. Ambiguous roles fail rather than guessing by similar image names. Existing exports remain untouched and do not require re-export solely for the configuration change. Legacy standalone configurations and prepared/nico-materials inputs remain readable; new workflows use the shared configuration above.
