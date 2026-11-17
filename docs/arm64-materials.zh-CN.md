# Grace ARM64 启动材料

[English](arm64-materials.md) · **简体中文** · [文档中心](README.zh-CN.md)

Grace 主机需要 ARM64 iPXE、Scout 引导系统及 ARM64 目标 OS。控制面运行在 x86 K8s，不代表被安装的主机可以执行 x86 引导程序。BlueField DPU 的 BFB 是另一套材料。

## 从 main 重建

在 Linux x86_64 构建机准备本机 Docker、构建依赖和公开 Core CA，见[统一源码构建](source-build.zh-CN.md)。完整构建使用同一份冻结的 main：

```bash
export REGISTRY=registry.example:5000
export SCOUT_CA_FILE=/private/core-ca.crt
export INCLUDE_ARM64_MATERIALS=1
make images
```

这会重建 Core、x86 Boot、Grace ARM64 Scout/rootfs/UEFI 和 PXEye。libredfish 按 Core 锁定的相同 main 提交编译。只重建 ARM 的独立入口为 `make nico-boot-arm64`；每次独立调用会重新冻结 main，不要把不同 Core 提交的结果混用。

ARM 构建依次执行交叉工具链准备、Scout Debian 包编译、mkosi 根文件系统与 UEFI 组装、最终内容检查。QEMU 解释 ARM 用户空间；构建容器需要 `--privileged`，临时注册本轮专用 binfmt 条目，退出时清理该条目。它不操作真实主机或运行 GPU 测试。

构建检查 ARM64 EFI/ELF、两个 Scout 二进制与根文件系统内文件的摘要一致性、64 KiB 页兼容性、CA、Scout 版本、包配置状态及关键模块 ABI。检查通过不能代替真实 Grace 引导验收。

模块检查只读取 `/usr/lib/modules/` 或 `/lib/modules/` 下的正式安装文件，不计入 DKMS 构建副本。[恢复失败的完整构建](source-build.zh-CN.md)时，若 ARM 组装已成功且组装脚本未变，可保留该组装结果；已有检查点按摘要校验，最终内容检查仍重新执行。旧构建若没有组装检查点，恢复时会记录当前文件摘要并标记 `checkpoint_origin=post-failure-recovery`，不会将恢复时的摘要冒充原组装阶段的记录。

## 输出目录

成功后命令打印 `ARM64_MATERIALS_DIR`，并在对应 `build-lock.json` 的 `arm64_materials` 中记录目录和来源：

```text
outputs_/source-builds/<运行ID>/arm64-materials/
├── ipxe.efi
├── golan.efi
├── scout.efi
├── scout.squashfs
├── BUILD-INFO.json
├── ROOTFS-PACKAGES.json
└── MATERIAL-RECIPE.json
```

前四个是引导材料；`BUILD-INFO.json` 记录源码和内容检查，`ROOTFS-PACKAGES.json` 记录实际安装包，`MATERIAL-RECIPE.json` 锁定交付六文件的大小和 SHA256。这些 JSON 是本项目审计材料，不是 NICo 主机导入格式。

## 接入离线包

将同一次成功完整构建的输出用于打包，并先按构建锁更新 Chart 镜像引用：

```bash
export REGISTRY_INSECURE=true
export SOURCE_BUILD_LOCK=/absolute/path/to/build-lock.json
export ARM64_MATERIALS_DIR=/absolute/path/to/arm64-materials
make arm64-materials
make cache-images
make bundles
```

`make arm64-materials` 校验并发布材料镜像；它不重新编译，也不生成归档。`make bundles` 仍是最终归档入口。生成配方优先于历史 `recipe-e703.json`；指定 `SOURCE_BUILD_LOCK` 时，六文件必须与其中记录的 ARM 材料摘要一致，且 ARM、Core/libredfish 来源一致。

最终 Chart 自动追加 `boot-artifacts-aarch64` init container，将材料复制到 NICo PXE 的 `/forge-boot-artifacts/blobs/internal/aarch64`，由 `/public/blobs/internal/aarch64/` 发布。材料镜像由 x86 控制面运行，容器架构为 amd64，内含 AArch64 文件；保留其 ENTRYPOINT，不覆盖 command/args，也无需另建 HTTP 服务。

核对归档中的 `manifests/source-build-lock.json`、`manifests/materials.json` 和 `manifests/images-lock.json`。阶段耗时见源码构建锁、`outputs_/logs/delivery/<运行ID>/timings.json` 及归档 `progress.json`。

目标 OS 的 ARM64 ISO 另行导入；从中提取的 kernel/initrd 与 Scout 是不同材料。当前外部 DHCP 通用小型启动 ISO 仍是 x86，Grace 需要 ARM64 兼容介质或原生网络引导路径。本入口不生产 DPU BFB/固件，也不单独交付 ARM APT 仓库。

参考 NVIDIA [容器与启动材料构建](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers)和[Bootable Artifacts](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts)。
