# NICo / PXEye offline delivery

**English** · [简体中文](README.zh-CN.md)

Run one builder script with one `build-config.json`. It exports local containerd images, prepares pinned Charts, and builds and verifies the offline delivery. Onsite deployment still runs on the fireseed host.

## Build

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/delivery.py --write-config ./build-config.json --work-directory "$PWD"
python3 ./PXEye/offline-build/delivery.py --seed-cache --config ./build-config.json
python3 ./PXEye/offline-build/delivery.py --config ./build-config.json
```

The first command is only needed once to initialize the shared configuration and default source files. The second command is a separate cache-seed action: it renders the parent Chart, derives its image closure, and exports those images from local containerd. Run it only for the initial cache or after a Chart/image version change. The final command is the normal delivery build; it never reads containerd and reuses the persistent loopback Registry at `localhost:1027`.

Read-only validation of local images, roles, Chart sources and delivery input:

```bash
python3 ./PXEye/offline-build/delivery.py --config ./build-config.json --plan
```

| Internal stage | Purpose | Delivery/cache |
| --- | --- | --- |
| cache seed (explicit) | Render the parent Chart and export its exact local containerd image closure | `offline-images/` |
| package | Verify the cached closure, vendor locked child Charts under the PXEye parent, use `localhost:1027`, run relok8s once, and produce the delivery | `registry-cache/`, `charts/`, `package-input/`, `output/` |

| Step | Purpose | Input | Output |
| --- | --- | --- | --- |
| [Internal image export](material-prepare/README.md) | Export listed local containerd images | Image list | `offline-images/` |
| [Internal packaging](helm-bundle/README.md) | Prepare the PXEye parent/dependencies, relocate one image closure and verify | Exported images and Chart sources | Three delivery files |
| [Onsite deployment](onsite/README.md) | Unpack, import images/Charts, install through Helm in order | Three delivery files and site configuration | PXEye, NICo Core and dependencies |

## Configuration and state management

- Configure contents/versions during building; configure Registry, namespace, networking, storage and authentication onsite. The default namespace is `nico-system`.
- Scripts manage image imports, and project Helm Charts manage Kubernetes resources.
- Recovery reuses verified materials and completed stages with the same configuration. Progress records are associated with their inputs; changed inputs require a separate version or work directory.
- Package verification, Helm readiness and physical provisioning acceptance are separate outcomes.

## Requirements and paths

Builder: Linux amd64, Python 3.11+/PyYAML, local Docker, Helm 3 and sufficient space. Fully offline builds require cached locked tools and base images.

Fireseed: Linux amd64, Python 3.11+/PyYAML, kubectl, an available cluster/Registry and working node image pulls. Helm and relok8s are delivered in the bundle.

```text
/srv/PXEye/offline-build/
  build-config.example.json  # shared build configuration
  delivery.py           # unified builder entry
  material-prepare/     # legacy explicit-image exporter
  helm-bundle/          # chart-sources.json
  onsite/               # run.py + run-config.example.json

/srv/nico-build/        # builder configuration, prepared data, caches and delivery
/srv/nico/              # onsite delivery files, tools, configuration and records
```

The pinned e703 profile covers single-node Core/PXEye, without REST/Temporal/Keycloak, DPF services or Ubuntu ISOs. It does not discover current running images. Step one only exports images. Step two wraps optional binary materials as images; existing prepared / nico-materials inputs remain compatible. Material HTTP readiness does not establish consumer URLs or physical connectivity.

Compatibility-format maintenance is documented in [legacy material preparation](legacy-materials.md) and [legacy deployment configuration](CONFIGURE.md). Those input formats and entry points are separate from this workflow.
