# Runtime tools

**English** · [简体中文](README.zh-CN.md)

PXEye invokes `nico-admin-cli` and `grpcurl` in the backend runtime. Supply compatible Linux binaries in this directory before building the image:

```text
bin/nico-admin-cli
bin/grpcurl
bin/helm
```

Match the binaries to the container architecture. Use the NICo client built from the target Core revision. Obtain `grpcurl` from its [official releases](https://github.com/fullstorydev/grpcurl/releases) and verify the release checksum. The existing image path was validated on amd64; arm64 needs separate validation.

These binaries are deployment inputs, excluded from version control. Copying them here does not grant redistribution rights; retain their upstream license obligations. See [Deployment](../docs/deployment.md).

The NICo deployment module additionally requires Linux Helm 3, also excluded from version control. Startup and login do not require Core certificates; see [independent startup and deployment](../docs/nico-deployment.md).
