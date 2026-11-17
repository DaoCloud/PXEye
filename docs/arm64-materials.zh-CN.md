# Grace ARM64 启动材料

[English](arm64-materials.md) · **简体中文** · [文档中心](README.zh-CN.md)

控制面运行在 x86 K8s，不代表被安装的 Grace 主机可以执行 x86 引导程序。Grace 需要 ARM64 iPXE、Scout 引导系统及 ARM64 目标 OS。BlueField DPU 的 BFB 是另一套材料，不能替代 Grace 主机材料。

当前已有固定配方的**校验、镜像封装和离线交付流程**；`make images` 只构建 x86 Boot，尚未统一生成新版本 Grace 材料。ARM 源码构建需要单独的构建环境与材料检查。

## 材料目录

`ARM64_MATERIALS_DIR` 必须是绝对路径，直接包含六个普通文件：

```text
/srv/nico-materials/aarch64/
├── ipxe.efi
├── golan.efi
├── scout.efi
├── scout.squashfs
├── BUILD-INFO.json
└── ROOTFS-PACKAGES.json
```

| 文件 | 作用 |
| --- | --- |
| `ipxe.efi`、`golan.efi` | ARM64 UEFI 网络引导器及网卡适配变体 |
| `scout.efi` | Scout 引导内核与 loader |
| `scout.squashfs` | Scout 根文件系统，包含 `forge-scout`、`mlx-firmware-supervisor`、驱动和依赖 |
| `BUILD-INFO.json` | 构建来源、版本、架构及启动文件大小/摘要 |
| `ROOTFS-PACKAGES.json` | 从最终根文件系统导出的实际包名、版本及架构 |

后两个文件是本项目的交付审计材料，不是 NICo 规定的主机装机输入格式。最终 OS 的 ARM64 ISO 由安装流程另行导入；从该 ISO 提取 kernel/initrd，不能用 Scout 文件替代它们。

## 新版本材料如何准备

1. **冻结版本。** 使用与本轮 Core 一致的 `infra-controller` 完整提交及其 Cargo/libredfish 锁；记录 Rust 工具链、mkosi/iPXE 子模块提交、基础系统、内核、NVIDIA 驱动和公开 CA。不能把旧 Scout 改文件名作为新版本。
2. **准备 ARM 构建环境。** 优先使用原生 Linux ARM64 构建机；交叉编译和 QEMU 也可作为构建方案，但需额外处理 ARM 软件包安装、内核模块构建和 mkosi 的运行条件。x86 控制机不会自动提供这些能力。
3. **编译并组装。** 源码入口是 `package-scout-aarch64-release-local`、`pxe/Makefile.toml` 的 `ipxe-aarch64`、`create-ephemeral-image-arm-host-ci` 和 `setup-apt-repo-arm64`。后者需要已生成的 Scout 包；生产组装显式提供 `FORGE_CA_PATH`，不要误用开发 CA。完整 `build-boot-artifacts-arm-host` 还混有 DPU 构建任务，源码注明本地 ARM 路径存在限制，不能直接视为本项目已验证的一键命令。
4. **检查最终内容。** 核对 EFI 和两个 Scout ELF 均为 AArch64；验证 Grace 使用的 64 KiB 页兼容性、内核与驱动模块 ABI、动态库和软件包完整性、Core CA 与 Secure Boot 策略。Core 自带 `scripts/check-aarch64-pagesize.sh` 可检查 ELF；检查通过不等于真实 Grace 已能启动。
5. **生成记录和配方。** 从最终文件生成上述两个 JSON，记录实际 SHA256、源提交与检查结果；同步 `offline-build/material-prepare/recipe-e703.json` 的六个 `group: aarch64` 条目的 `bytes` / `sha256`，保留其文件名、顺序及目标路径。文件名里的 `e703` 是现有配方名，不表示新材料仍来自该提交。完成评审并提交后再打包。
6. **交付验证。** 完成下述离线封装，部署后检查 PXE HTTP 全量下载、摘要及真实 Grace 的 UEFI → iPXE → Scout 回报，再验证 ARM64 OS 安装。内容检查、Pod Ready 和真实装机分别记录。

这些是材料生产要求与现有源码入口；仓库尚无覆盖这六步的一键 ARM 生成脚本。不能把旧材料封装成功描述为本轮 ARM 重新编译或硬件验收通过。

## 纳入离线包

准备好与已提交配方匹配的六个文件后，在 Linux x86_64 打包机执行：

```bash
export REGISTRY=registry.example:5000
export REGISTRY_INSECURE=true
export INCLUDE_ARM64_MATERIALS=1
export ARM64_MATERIALS_DIR=/srv/nico-materials/aarch64
make arm64-materials
make cache-images
make bundles
```

此阶段**不重新编译 Scout**。打包器校验六个文件的大小/SHA256，构建或复用内容寻址的 ARM 材料镜像，并记录镜像 digest。镜像由 x86 控制面上的 init container 运行，内含 ARM64 文件；容器镜像架构可以是 amd64，文件架构必须是 AArch64。

最终 Chart 自动追加 `nicoCore.nico-pxe.bootArtifactContainers` 的 `boot-artifacts-aarch64` 项。它校验并复制文件到 `/forge-boot-artifacts/blobs/internal/aarch64`，由 NICo PXE 发布到 `/public/blobs/internal/aarch64/`。保留材料镜像 ENTRYPOINT，不配置 `command` / `args` 覆盖，不需再搭建 HTTP 服务。

核对交付中的 `manifests/materials.json`、`manifests/images-lock.json` 和最终 Chart 的 ARM init container。新文件与固定配方不一致时会失败；设置环境变量不会使任意 ARM 材料自动被接受。这条六文件流程不额外交付 ARM APT 仓库或 DPU BFB，如需使用它们必须单独纳入材料规划。

当前外部 DHCP 通用小型启动 ISO 的构建入口仍为 x86_64；Grace 场景需提供 ARM64 兼容启动介质或使用已匹配的原生网络引导路径，不能直接复用 x86 小型 ISO。

参考 NVIDIA [容器与启动材料构建](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers)和[Bootable Artifacts](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts)。BFB 的 `BOOTSTRAP_CA_PATH` 属于 DPU 路径，与主机 Scout 的 `FORGE_CA_PATH` 分开。

`make arm64-materials` 只校验并发布现有材料镜像，不重新编译 Scout，也不生成归档；生成记录位于 `outputs_/generated/arm64-materials.json`。`make bundles` 仍会检查并复用相同内容的镜像。阶段耗时保存在 `outputs_/logs/delivery/<运行ID>/timings.json`，归档细分阶段见对应 `progress.json`。
