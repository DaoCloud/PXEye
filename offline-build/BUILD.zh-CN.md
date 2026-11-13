# 构建离线交付包

[English](BUILD.md) · **简体中文**

这是 PXEye / NICo 离线交付的标准构建流程。它生成一个经过完整校验的交付包，包含
PXEye、NICo Core 及其所需的 Helm 依赖。现场导入和安装是独立步骤，见
[现场部署](onsite/README.zh-CN.md)。

## 前置条件

在 Linux amd64 构建机执行，并具备 Docker、可通过 `ctr` 访问的本机 containerd 内容存储、
Helm 3、Python 3.11+/PyYAML 及足够空间，用于 Registry 缓存和最终归档。执行 `make images`
前必须提交 PXEye 源码；该目标会主动拒绝脏工作树。

PXEye 镜像引用由 `charts/pxeye/values.yaml` 固定。在当前 shell 一次性设置构建 Registry；
它必须可被构建机访问并允许推送镜像。

```bash
cd /path/to/PXEye
export REGISTRY=127.0.0.1:1027
export REGISTRY_INSECURE=true
```

请按实际环境替换 Registry 地址和 TLS 设置。默认 `REGISTRY_INSECURE=true` 适用于 HTTP
Registry。

## 构建

按顺序执行三条命令：

```bash
make images
make cache-images
make bundles
```

`make images` 构建或复用并推送父 Chart 声明的精确 PXEye 镜像。`make cache-images`
渲染父 Chart，得到完整镜像闭包，并将缺失镜像缓存到 `REGISTRY`。`make bundles` 使用
这个 Registry 中已缓存的内容，将锁定的子 Chart 纳入 PXEye 父 Chart，执行一次 relocation，
并通过归档读回完成校验。启用 ARM 时，它还会基于已校验的本地 payload 构建或复用内容寻址的
ARM 材料镜像。

如需包含可选的 ARM64 引导材料，在后两步前设置以下变量：

```bash
export INCLUDE_ARM64_MATERIALS=1
export ARM64_MATERIALS_DIR=/absolute/path/to/boot/aarch64
make cache-images
make bundles
```

该目录必须直接包含 `BUILD-INFO.json`、`ROOTFS-PACKAGES.json`、`golan.efi`、
`ipxe.efi`、`scout.efi` 和 `scout.squashfs`。构建过程会校验这些文件，并将其封装为由
NICo PXE init container 使用的不可变材料镜像；它们不会作为散落的现场文件交付。

## 产物与交接

默认配置下，生成状态全部位于被 Git 忽略的 `outputs_/`：

```text
outputs_/
├── build-config.json                  # 首次自动创建；保留各阶段设置
├── chart-sources.json                  # 锁定的上游子 Chart 来源
├── generated/resolved-images.txt      # 父 Chart 渲染出的镜像闭包
├── cache/registry-exports/            # 可恢复构建缓存，不是交付文件
└── output/bundle-<version>/
    ├── bundle.tar.gz                  # 主离线交付包
    ├── onsite-tools.tar.gz            # 小型一键现场执行工具包
    ├── SHA256SUMS                     # 两个归档的校验和
    └── build-result.json              # 版本、镜像/Chart 数量和摘要
```

`SHA256SUMS` 是构建侧和传输侧的可选校验记录；一键现场执行器不依赖它。现场执行器只接收
`bundle.tar.gz` 的路径，并在解压后验证包内不可变文件清单。若现场传输流程要求人工校验，仍可执行：

```bash
cd outputs_/output/bundle-<version>
sha256sum -c SHA256SUMS
python3 -m json.tool build-result.json
```

解压后，`bundle.tar.gz` 只有一个 `<bundle-id>/` 根目录：

```text
bundle.json                         # 交付身份和父 Chart 元数据
charts/pxeye.tgz                    # 含锁定依赖的 PXEye 父 Chart
relocation/pxeye.tar                # relok8s 镜像迁移中间包
manifests/                          # 镜像、材料、工具链和文件锁
profiles/install-plan.json          # 有序 Helm 阶段
tools/                              # Helm、relok8s、校验器和现场工具
docs/                               # 交付文档和许可证
```

当前配方覆盖 PXEye / NICo Core 及必需的 cert-manager、platform、Vault 依赖，并可选包含
ARM64 引导材料；不包含 REST、Temporal、Keycloak、DPF 服务或操作系统 ISO。

现场执行器会使用包内 PXEye Chart 将 PXEye 接到同命名空间的 Core 客户端 Secret 和集群内 API；因此本次
源码变更后必须先用 `make images` 发布新的 PXEye 镜像，再运行 `make bundles`。它不把物理 DNS/PXE/NTP
端点或 HostInband 网络写入包。

首次安装要求 `nico-system` 除 Kubernetes 自动生成的默认对象外为空。执行器会拒绝遗留 PVC、Secret、Service
等 namespaced 资源，不会接管它们。旧的四个独立 NICo Release 需要明确迁移或使用干净的 `nico-system`；
本离线包不会接管它们。初始控制面包还会将 `nico-dhcp` 保持为零副本；真实 DNS/NTP/PXE/VIP 与显式启用 DHCP
属于后续站点网络配置。
