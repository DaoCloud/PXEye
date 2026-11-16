# Shared storage

**English** · [简体中文](STORAGE.zh-CN.md)

PXEye uses one PVC for application data, source ISOs and imported materials. NICo PXE mounts only the HTTP subtree read-only and serves it through its existing HTTP server. No additional HTTP service or material PVC is required. PostgreSQL and Vault keep their own PVCs.

## Directories

| PVC subdirectory | PXEye path | Purpose | Mounted by NICo PXE |
| --- | --- | --- | --- |
| `data` | `/data` | Configuration, database and task records | No |
| `iso-sources` | `/iso-sources` | ISOs awaiting import | No |
| `staging` | `/staging` | Reserved preparation space; existing import behavior is unchanged | No |
| `http/nico/os-library` | `/materials` | Imported ISO, kernel and initrd | Yes, its parent `http/nico`, read-only |

NICo PXE mounts the subtree at `<servePath>/blobs/internal/nico`. Material URLs remain `/public/blobs/internal/nico/os-library/<OS-ID>/<filename>`. Existing Boot materials under `blobs/internal/x86_64`, `aarch64` and other directories, and dynamic NoCloud routes retain their existing handling.

An initContainer runs a ConfigMap script with Python from the existing PXEye image before the main container starts. It creates missing directories and configures the default ISO source. Existing directories and files are preserved without recursive permission changes. Conflicting files, symlinks or insufficient permissions fail initialization with a specific error. Missing ISO sources in persisted configuration receive defaults; other fields are preserved.

## Values and scheduling

```yaml
storageClass: your-storage-class
sharedStorage:
  size: 200Gi
  accessMode: ReadWriteOnce
  existingClaim: ''
```

An empty `existingClaim` creates `<PXEye release>-storage`; otherwise the existing claim in the same namespace is reused without creating a PVC. Account for both source and imported ISO copies, extracted files, application data and spare space. `size` applies to newly created claims; expand existing claims separately if supported by the storage class.

The second offline stage extends the pinned NICo PXE child Chart with shared mounts. The third stage configures:

```yaml
nicoCore:
  nico-pxe:
    pxeyeStorage:
      enabled: true
      claimName: <PXEye release>-storage
      ownerRelease: <PXEye release>
```

These values require the extended delivery Chart and do not add support to an unmodified upstream Chart. When using `existingClaim`, set the NICo PXE `claimName` to the same actual claim. The third stage defaults to an automatically created claim.

Required Pod affinity schedules NICo PXE on the same node as PXEye. PXEye uses only preferred affinity toward PXE to avoid a mutual startup dependency. Both Pods must use the same namespace, and their resource requirements and node selectors must be satisfiable together. PXE uses Recreate updates when sharing is enabled.

RWO requires a driver supporting multiple Pods mounting the volume on the same node; affinity cannot add missing driver support. RWX is also accepted, while this design still schedules the Pods together. RWOP is unsupported. Do not bypass scheduling with `nodeName`.

## Add an ISO

Run from a terminal with kubectl access:

```bash
kubectl --context "$CONTEXT" -n "$NAMESPACE" cp \
  ./ubuntu-server.iso "$PXEYE_POD:/iso-sources/ubuntu-server.iso.part"
kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "$PXEYE_POD" -- \
  mv /iso-sources/ubuntu-server.iso.part /iso-sources/ubuntu-server.iso
```

Select and import the file under “Operating systems → Use server ISO”. Only top-level regular `.iso` files are scanned; subdirectories and symlinks are excluded. No manual directory creation or node access to the underlying PVC path is needed.

## Upgrade from two PVCs

Do not replace existing data with an empty volume. Confirm there are no active installations, pause PXEye writes, back up and copy the old data and materials into the matching subdirectories, verify the copy, then switch mounts. Keep old claims for rollback; they are not automatically deleted. Preserve OS IDs and URLs rather than reimporting materials as migration.

Minimum verification covers same-node scheduling, directory initialization, source discovery, byte-identical HTTP downloads after PXEye writes, read-only publishing, private-directory exclusion and file persistence after Pod recreation. Pod readiness does not establish successful physical installation.
