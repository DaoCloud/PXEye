# NICo / PXEye offline delivery in three steps

**English** · [简体中文](README.zh-CN.md)

Steps 1–2 share one `build-config.json` on the builder; each script owns only its section. Step 3 uses a separate site configuration on the fireseed host. Step one exports images; step two consumes them from the same work directory, downloads pinned Charts and builds the delivery.

| Step | Purpose | Input | Output |
| --- | --- | --- | --- |
| [1. Export images](material-prepare/README.md) | Export listed local containerd images | Work directory and image list | Compatible OCI archive and image lock file |
| [2. Package](helm-bundle/README.md) | Render Charts, package images with relok8s, compress and verify | Step-one image export, Chart sources and optional materials | `bundle.tar.gz`, `onsite-tools.tar.gz`, `SHA256SUMS` |
| [3. Deploy](onsite/README.md) | Unpack, import images/Charts, install through Helm in order | Those three files and one site configuration | Optional PXEye, NICo Core/dependencies, progress and logs |

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
  material-prepare/     # build.py + images.txt
  helm-bundle/          # build.py + chart-sources.json
  onsite/               # run.py + run-config.example.json

/srv/nico-build/        # builder configuration, prepared data, caches and delivery
/srv/nico/              # onsite delivery files, tools, configuration and records
```

The pinned e703 profile covers single-node Core/PXEye, without REST/Temporal/Keycloak, DPF services or Ubuntu ISOs. It does not discover current running images. Step one only exports images. Step two wraps optional binary materials as images; existing prepared / nico-materials inputs remain compatible. Material HTTP readiness does not establish consumer URLs or physical connectivity.

Compatibility-format maintenance is documented in [legacy material preparation](legacy-materials.md) and [legacy deployment configuration](CONFIGURE.md). Those input formats and entry points are separate from this workflow.
