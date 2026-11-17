# 统一源码构建

[English](source-build.md) · **简体中文** · [文档中心](README.zh-CN.md)

`make images` 从三个维护仓库的 `main` 构建并发布 Core、x86_64 Scout/Boot 和 PXEye。libredfish 编译进 Core/Scout，不单独部署。

## 构建前准备

使用 Linux x86_64 构建机、本机 Docker/BuildKit、Git、Make、OpenSSL 和 Python 3.11+。构建需要访问 GitHub、容器仓库、Rust 和 Ubuntu/Debian 软件源，并留足编译和启动材料的磁盘空间。HTTP Registry 需要预先加入 Docker daemon 的 `insecure-registries`。

PXEye 工作树必须干净，当前提交必须等于远端 `DaoCloud/PXEye/main`。三个仓库都先合并功能、推送 `main`：

| 仓库 | 构建内容 |
| --- | --- |
| `DaoCloud/PXEye` | PXEye 与外部 DHCP 通用 UEFI 介质 |
| `SSmallMonster/infra-controller` | Core 各服务、配套 CLI、Scout 和 Boot 材料 |
| `SSmallMonster/libredfish` | Core/Scout 使用的 Redfish Rust 库 |

Core 的 `Cargo.toml` 和 `Cargo.lock` 必须将 libredfish 固定到本轮解析到的库 `main` 完整提交；可直接使用 fork Git 依赖，也可通过 `[patch."https://github.com/NVIDIA/libredfish.git"]` 覆盖。脚本发现旧提交、本地 `path` 或未同步的锁文件会停止；不会自动修改依赖或回退功能分支。

准备 `bin/helm`、`bin/grpcurl` 两个 Linux amd64 二进制。统一构建会从本轮 Core 镜像提取 `nico-admin-cli`，不使用本地旧 CLI。只构建 PXEye 的快捷入口仍需自行准备三个工具，见[运行工具](../bin/README.zh-CN.md)。

准备目标 NICo Core 的**公开 CA PEM**，供 Scout 验证 Core；文件不能包含私钥。这与跳过 BMC 自签名证书检查不同。构建的 Boot 材料只适用于信任该 CA 的环境。

## 执行命令

```bash
export REGISTRY=registry.example:5000
export SCOUT_CA_FILE=/private/core-ca.crt
make images
```

每轮先冻结三个 `main` 的完整提交，再执行依赖核对和编译；不会读取工作区旁边的第三方目录。Core 使用该提交自带的 Docker 配方和 `cargo make build-release-container-services`；Scout 与 Core 使用同一源码提交。Boot 阶段使用上游 mkosi/iPXE 任务及生产 CA 路径，将新 Scout 打包进引导材料。mkosi 需要启动本机 `--privileged` 构建容器；不连接 Kubernetes、不操作物理机。

| 命令 | 用途 |
| --- | --- |
| `make nico-sources` | 仅冻结源码并检查 libredfish 依赖，不编译 |
| `make nico-core` | 构建 Core；包含 libredfish、API、PXE、DHCP、DNS、BMC proxy 等服务二进制和 CLI |
| `make libredfish` | 在 Core 的锁定工作区单独编译库，不生成部署镜像 |
| `make nico-scout` | 编译 x86_64 Scout 二进制，不生成完整启动系统 |
| `make nico-boot` | 构建 Core、Scout、x86_64 启动文件与 Boot 镜像；需要 `SCOUT_CA_FILE` |
| `make images` | 构建整套并推送 Core、Boot、PXEye；需要 `REGISTRY`、`SCOUT_CA_FILE` |
| `make image` / `make pxeye-images` | 仅本地构建 / 构建推送 PXEye，使用当前干净提交及本地工具，不拉取 Core/libredfish |
| `make source-build-help` | 查看构建脚本参数 |

除 `images` 外，源码构建目标只在提供 `REGISTRY` 时推送镜像。每次命令独立冻结一套源码；要保证 Core/Scout/Boot/PXEye 完全配套，使用一次 `make images`，不要组合多次独立命令的产物。

当前入口只构建 **x86_64 控制面和 x86_64 目标主机材料**。Grace ARM64 Scout/iPXE 与 DPU BFB 不在本入口生成范围，需单独准备并记录版本。

## 输出与离线包

```text
outputs_/source-builds/<UTC时间>-<运行ID>/
├── build-lock.json          # 状态、三个提交、依赖、镜像引用/digest、文件 SHA256
├── build.log                # 实际命令、输出与退出码
├── scout-ca.crt             # 本轮公开 CA 副本
├── Dockerfile.boot          # 本轮 Boot 镜像配方
└── sources/
    ├── pxeye/              # 本轮 PXEye main；bin/ 使用配套 CLI
    ├── core/               # 本轮 Core main；编译/启动文件位于其 target/、pxe/static/
    └── libredfish/          # 本轮库 main；Cargo 按同一 commit 获取编译依赖
```

只使用 `status: complete` 的锁文件。失败时保留日志、源码及可能已经发布的部分镜像，状态标为 `failed`；不会退回旧镜像。Core/Boot tag 带源码提交和唯一运行 ID，PXEye tag 另带应用版本；部署引用使用锁文件里的 `immutable_reference`。

**构建不会自动改 Chart、打离线包或部署。** 将锁文件中的 PXEye、Core 各服务和 Boot 镜像引用更新到交付 Chart/构建配置，再按[离线交付构建](../offline-build/BUILD.zh-CN.md)执行 `make cache-images`、`make bundles`。Core 多个服务可使用同一个整合镜像，保留各自的启动命令；Boot 镜像包含 `/x86_64`、`/apt`，作为 PXE 的材料 init container 使用；保留镜像默认命令，或显式使用 `sh -ec 'cp -r /x86_64 /apt /forge-boot-artifacts/blobs/internal/'`，不要遗漏 `/apt`。现有打包器不会自动消费此构建锁；未更新的 Chart 仍会打入旧版本。ISO 等外部材料继续按交付清单准备。

## 为什么使用独立源码目录

这些目录是独立 Git 仓库，放在忽略的 `outputs_` 下，不提交进 PXEye。构建锁负责记录跨仓库的精确提交，Cargo 锁负责记录实际编译依赖。

Git submodule 则把“子仓库地址 + 固定提交指针”提交进父仓库，需要 `git clone --recurse-submodules` / `git submodule update --init`；更新第三方版本还要提交父仓库指针。它适合父子源码长期严格绑定。这里采用独立目录，便于分别维护 fork 和构建缓存；不能只依赖目录名或分支名判断版本。

这里不把两个 fork 注册为 PXEye 的 submodule；Core 自身已有的 mkosi/iPXE 子模块仍按其固定指针初始化。

构建方式参考 NVIDIA [容器构建](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers)和[启动材料](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts)，具体任务以所锁定的 fork 源码为准。
