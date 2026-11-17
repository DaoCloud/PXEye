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

默认构建 x86_64 控制面和 x86_64 目标主机材料；设置 `INCLUDE_ARM64_MATERIALS=1 make images` 会从同一份源码重建 Grace ARM64 Scout/rootfs/UEFI。独立入口为 `make nico-boot-arm64`，见[Grace ARM64 材料](arm64-materials.zh-CN.md)。DPU BFB 不在本入口生产。

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

**构建不会自动改 Chart、打离线包或部署。** 将锁文件中的 PXEye、Core 各服务和 Boot 镜像引用更新到交付 Chart/构建配置，再按[离线交付构建](../offline-build/BUILD.zh-CN.md)执行 `make cache-images`、`make bundles`。Core 多个服务可使用同一个整合镜像，保留各自的启动命令；Boot 镜像包含 `/x86_64`、`/apt`，作为 PXE 的材料 init container 使用；保留镜像默认命令，或显式使用 `sh -ec 'cp -r /x86_64 /apt /forge-boot-artifacts/blobs/internal/'`，不要遗漏 `/apt`。设置 `SOURCE_BUILD_LOCK` 可让打包器校验并归档指定构建锁；它不会自动更新 Chart，未更新的 Chart 仍指向旧版本。ISO 等外部材料继续按交付清单准备。

## 构建后同步哪些 Chart 配置

镜像构建与 Chart 选择是两件事。`make bundles` 渲染配置得到镜像清单，不会查找 Registry 中的最新 tag。以同一份成功的 `build-lock.json` 为准：

| 输入文件 | 字段 | 使用的构建结果 |
| --- | --- | --- |
| `charts/pxeye/values.yaml` | `image` | `images.pxeye.reference` 的唯一 tag 地址 |
| `deploy/offline-core/values/core.yaml` | `global.image.repository` / `tag` | 将 `images.core.reference` 拆成仓库和唯一 tag；API、迁移任务、DHCP、DNS、硬件健康、SSH console 等沿用全局镜像 |
| 同上 | `nico-bmc-proxy.image.repository` / `tag` | 同一 Core 镜像，覆盖旧的独立镜像引用 |
| 同上 | `nico-pxe.image.repository` / `tag` | 同一 Core 镜像，覆盖旧的独立镜像引用 |
| 同上 | `nico-pxe.bootArtifactContainers` 中 x86 Boot 项的 `image` | `images.boot-artifacts-x86_64.reference` 的唯一 tag 地址；复制命令同时包含 `/x86_64` 和 `/apt` |

现有离线重定位流程使用带唯一 tag 的镜像引用，内容由构建锁校验；不要把 `@sha256:` 地址直接替换进该流程。当前 Core Chart 把 `repository:tag` 拼成引用，不支持单独的 `digest` 字段；使用本轮唯一 tag，并核对归档镜像摘要与构建锁一致，不要只补一个被模板忽略的 `digest`。修改的是上述仓库输入文件；最终父 Chart 会将 Core 设置放到 `nicoCore` 下，生成目录无需手工再改。没有启用的可选组件不因本次换镜像而自动启用。

Chart 模板的版本另外由 `offline-build/helm-bundle/chart-sources.json` 的 `core.url`、`core.sha256`、`core.subdirectory` 固定。仅更新镜像可保留已验证的模板；升级模板时，选择固定 Core commit 的源码归档、计算归档 SHA256，并核对 `deploy/offline-core/patches/` 的兼容补丁和启动参数。不要把 URL 换成移动的 `main`，也不要只看 Chart 的 `version: 0.1.1` 判断源码是否一致。如果工作目录的 `build-config.json` 指向了自定义 `helm_bundle.chart_sources`，还要修改实际引用的那份文件。

准备新一轮发布时，提交上述输入，再执行：

```bash
make cache-images
make bundles
```

检查 `outputs_/generated/resolved-images.txt` 是否包含本轮 PXEye/Core/Boot，再检查交付输出中的 `build-result.json`、归档中的 `manifests/images-lock.json` 与重定位后的父 Chart；镜像 digest 应与源码构建锁一致。设置 `SOURCE_BUILD_LOCK=/absolute/path/to/build-lock.json` 后，打包会校验 PXEye/Core/x86 Boot 的实际归档 digest 与该锁一致，并将锁收入 `manifests/source-build-lock.json`。这不会自动修改 Chart 镜像引用。无需修改生成的镜像缓存或历史 `materials-lock.json` 来冒充升级。

Grace 的材料生成、固定配方和打包开关见 [Grace ARM64 启动材料](arm64-materials.zh-CN.md)。

## 为什么使用独立源码目录

这些目录是独立 Git 仓库，放在忽略的 `outputs_` 下，不提交进 PXEye。构建锁负责记录跨仓库的精确提交，Cargo 锁负责记录实际编译依赖。

Git submodule 则把“子仓库地址 + 固定提交指针”提交进父仓库，需要 `git clone --recurse-submodules` / `git submodule update --init`；更新第三方版本还要提交父仓库指针。它适合父子源码长期严格绑定。这里采用独立目录，便于分别维护 fork 和构建缓存；不能只依赖目录名或分支名判断版本。

这里不把两个 fork 注册为 PXEye 的 submodule；Core 自身已有的 mkosi/iPXE 子模块仍按其固定指针初始化。

构建方式参考 NVIDIA [容器构建](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers)和[启动材料](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts)，具体任务以所锁定的 fork 源码为准。

源码构建各阶段和命令耗时写入 `build-lock.json` 的 `timings` 和 `commands`；失败尝试保留耗时及退出码。

Docker Hub 不可达时可设置 `BUILD_IMAGE_MIRROR=m.daocloud.io`。构建器仅替换 Dockerfile 的 Docker Hub `FROM` 地址，保留已有 digest，并记录原配方、改写配方和地址映射；不会改宿主机 Docker/集群配置。Dockerfile 内的软件源下载仍需可达。

默认 `BUILD_JOBS=8` 限制构建镜像内 Cargo 并发，避免按宿主机全部 CPU 并发编译挤占运行服务内存。可按构建机资源调整；实际值和生成配方写入构建锁。

推荐完整交付命令：`make bundles SOURCE_BUILD_LOCK=/absolute/path/to/build-lock.json`。任一源码构建镜像未被归档或摘要不一致时停止，不用旧镜像替代。

Rust 官方下载域名不可达时，可设置 `RUST_MIRROR=https://rsproxy.cn`，仅构建镜像使用该工具链分发源；rustup 继续校验组件摘要，实际地址和配方写入构建记录。

Cargo 索引不可达时，可设置 `CARGO_MIRROR=https://rsproxy.cn/index`。仅构建器使用该 sparse 索引及其下载入口，Cargo 继续校验包摘要；实际地址与生成配方写入构建锁。
