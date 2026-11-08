# 运行工具

[English](README.md) · **简体中文**

PXEye 后端在自己的运行环境调用 `nico-admin-cli` 和 `grpcurl`。构建镜像前，在本目录准备兼容的 Linux 二进制：

```text
bin/nico-admin-cli
bin/grpcurl
bin/helm
```

二进制架构与容器保持一致。NICo 客户端应来自目标 Core 对应版本；`grpcurl` 从[官方发布](https://github.com/fullstorydev/grpcurl/releases)获取并校验摘要。已有镜像路径在 amd64 验证，arm64 需要独立验证。

二进制是部署输入，不纳入版本控制。复制到本目录不代表获得再分发授权，仍需遵守上游许可证。参阅[部署指南](../docs/deployment.zh-CN.md)。

NICo 集群部署模块还需要 Linux Helm 3；该文件同样不纳入版本控制。初次启动和登录不依赖 Core 证书，详见[独立启动与部署](../docs/nico-deployment.zh-CN.md)。
