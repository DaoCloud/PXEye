# NICo / PXEye 离线交付

[English](README.md) · **简体中文**

标准流程只使用一份 `build-config.json` 和依序执行的三个 Make 目标：发布 PXEye、缓存父
Chart 镜像闭包、构建交付包。最后一步从指定 Registry 导出精确镜像闭包，执行一次
relocation，并校验最终离线交付包。现场部署仍在火种机执行。

简洁、可直接复制的构建步骤、交付文件和解压目录见[构建离线交付包](BUILD.zh-CN.md)。

## 构建

按以下章节顺序执行：发布 PXEye、缓存锁定 Chart 的镜像闭包、再构建离线交付物。所有
命令均在 PXEye 源码目录执行：

```bash
cd ~/pxeye-build/PXEye
```

## 发布 PXEye

缓存 Chart 镜像或构建交付包之前，先构建并发布 PXEye 镜像：

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make images
```

`make images` 从干净的已提交源码构建并推送 `REGISTRY/pxeye:<版本>-<YYYYMMDDHHmm>-<commit前7位>`，
时间使用 Asia/Shanghai，完整 commit 写入镜像元数据。同一分钟的相同 commit 不覆盖已有本地 tag。
它不读取或改写 Chart 镜像引用。将成功输出的 `PUBLISHED_PXEYE_IMAGE` 手动写入
`charts/pxeye/values.yaml` 的 `image` 字段，再执行后续缓存和打包；
具体命令见[构建指南](BUILD.zh-CN.md)。HTTP Registry 需要由 Docker daemon 配置为不安全仓库；Docker 的单次
push 没有 TLS 跳过参数。

## 可选 ARM64 引导材料

ARM64 引导材料默认关闭；默认构建不会读取 ARM 源目录。如需将锁定的 Grace/ARM64
引导文件加入交付包，必须显式启用，并指定直接包含
`BUILD-INFO.json`、`ROOTFS-PACKAGES.json`、`golan.efi`、`ipxe.efi`、
`scout.efi` 和 `scout.squashfs` 的目录：

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true \
  INCLUDE_ARM64_MATERIALS=1 \
  ARM64_MATERIALS_DIR=/absolute/path/to/boot/aarch64 \
  make bundles
```

构建会校验固定校验和、生成 `linux/amd64` 的内容寻址材料镜像，并由 Core PXE 服务通过既有的
引导材料路径发布。镜像身份同时包含 payload、基础 manifest、初始化程序和渲染后的镜像定义，
因此镜像合同变更不会错误复用旧 tag。为 ARM 构建预热 Registry 时，`make cache-images`
也使用同样的两个变量。

## 镜像缓存

PXEye 发布后，将父 Chart 渲染出的镜像缓存到同一个 Registry：

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true \
  make cache-images
```

该命令不读取 `images.txt`：它从 PXEye 父 Chart 及锁定子 Chart 自动得到镜像闭包，缺失镜像才从其原始公网引用拉取，再推送到 `REGISTRY`。第三方和 NICo 镜像仅替换 Registry 主机名，保留 repository 路径和 tag；PXEye 自建镜像使用 `REGISTRY/pxeye:<tag>`。该步骤不制作 bundle、不部署 Kubernetes。

## 构建离线交付物

Registry 就绪后，制作离线交付物：

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make bundles
```

`make bundles` 会在仓库忽略的 `outputs_/` 下创建配置和可恢复构建状态；它渲染父 Chart、
只读取指定 Registry，然后打包并验证交付物。默认使用 `outputs_/build-config.json`，并生成
`outputs_/output/bundle-<PXEye版本>-<Asia/Shanghai时间戳>/`，例如
`bundle-0.22.16-202611121650`。只有需要固定版本（例如 `BUNDLE_VERSION=release-1`）时才覆盖。

打包默认接受未提交修改，无需配置 Git 作者账号。时间版本标识本次构建，实际打包文件摘要
用于识别内容和校验续跑，记录在 `manifests/build-source.json`；内容变化后使用新版本。
需要强制已提交打包文件时，可设置 `REQUIRE_CLEAN_BUILD=true`；该开关不改变镜像构建的干净源码要求。

每次从 Registry 拉取后，构建器都会校验 containerd 内对应 amd64 内容图。如果本地旧镜像记录
指向缺失内容，它只会从同一 Registry 补拉该镜像内容一次并再次校验；不会删除镜像 tag 或
Kubernetes 资源。
Registry 输入镜像使用确定性的构建私有 containerd namespace
`pxeye-offline-<closure-id>`，而不是 `k8s.io`；缓存为失败重试保留，且不会参与运行工作负载的
镜像状态。

Registry OCI 导出和 bundle staging 缓存在 `cache/registry-exports/`；最终交付文件始终写入构建工作目录根部的 `output/bundle-<version>/`。

| 内部阶段 | 作用 | 交付/缓存 |
| --- | --- | --- |
| Registry 输入 | 渲染父 Chart，从 `REGISTRY` 拉取精确镜像闭包，再生成隔离的 OCI 导出 | `cache/registry-exports/` |
| package | 将锁定子 Chart 引入 PXEye 父 Chart、只执行一次 relok8s，并校验最终交付物 | `bundle-staging/`、`output/` |

旧版[显式镜像导出器](material-prepare/README.zh-CN.md)和
[schema-1 打包器](helm-bundle/README.zh-CN.md)只保留兼容用途，不是本流程的步骤。
现场交接从[现场部署](onsite/README.zh-CN.md)开始。

## 配置与状态管理

- **配置分层。** 构建配置只定义内容与版本；现场执行器只接收离线归档路径，并固定部署到 `nico-system`。物理引导网络端点、HostInband 子网和装机策略由 PXEye 后续的站点配置维护，不能写成 Kubernetes Service ClusterIP。
- **资源管理。** 镜像导入由脚本统一处理，Kubernetes 资源通过项目提供的 Helm Chart 管理。
- **故障恢复。** 相同归档可复用已完成阶段；解压目录与运行状态目录从归档名自动派生。变更归档后使用不同文件名。
- **验收范围。** 构建校验、Helm 就绪和物理装机分别验收。

## 执行条件与路径

构建机：Linux amd64、Python 3.11+/PyYAML、Docker 本地服务、可通过 `ctr` 访问的本机
containerd 内容存储、Helm 3、足够空间。ARM 材料构建会在 Docker 修改本地或 Registry
状态前拒绝其他主机架构。断网构建需预置锁定的工具和基础镜像。

火种机：Linux amd64、Python 3.11+/PyYAML、kubectl、可用 Registry 和 Kubernetes；节点已能从该 Registry 拉镜像。Helm、relok8s 随离线包交付。

文档统一使用这些路径；真实路径只在相应配置中设置：

```text
/srv/PXEye/offline-build/
  build-config.example.json  # 共用构建配置
  delivery.py           # 统一构建入口
  material-prepare/     # 兼容的显式镜像导出器
  helm-bundle/          # chart-sources.json
  onsite/               # 第三步：run.py（唯一输入为 --archive）

/srv/nico-build/        # 构建机配置、镜像导出、缓存和交付包
/srv/nico/              # 火种机交付文件、执行器、自动派生的解压目录和运行记录
```

当前配方是固定 e703 的单节点 Core/PXEye，不自动追踪运行集群镜像；不包含 REST/Temporal/Keycloak、DPF 服务或 Ubuntu ISO。第一步只导出镜像。第二步按需将独立材料封装为镜像；已有 prepared / nico-materials 输入保留兼容。材料 HTTP 就绪不等于消费者 URL 或实机链路已验证。

兼容格式的维护说明见[旧版材料构建](legacy-materials.zh-CN.md)和[旧版部署配置](CONFIGURE.zh-CN.md)；其输入格式和执行入口独立于本流程。
