# NICo / PXEye 离线交付

[English](README.md) · **简体中文**

构建机只执行一个脚本、使用一份 `build-config.json`。它依次导出本地 containerd 镜像、准备固定 Chart、生成并校验离线交付包。现场部署仍在火种机执行。

## 构建

```bash
cd ~/pxeye-build/PXEye
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make bundles
```

`make bundles` 是完整构建入口。首次运行时会在仓库已忽略的 `outputs_/` 下创建配置和可恢复构建状态；随后渲染父 Chart、读取配置的 Registry，并完成打包与校验。

`make bundles` 默认使用 `outputs_/build-config.json`，并生成 `outputs_/output/bundle-<PXEye版本>-<Asia/Shanghai时间戳>/`，例如 `bundle-0.22.16-202611121650`。只有需要固定版本（例如 `BUNDLE_VERSION=release-1`）时才覆盖。

## 镜像缓存

首次构建或 Chart 镜像版本变化后，先将父 Chart 渲染出的镜像缓存到 Registry：

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true \
  make -f ./PXEye/Makefile cache-images
```

该命令不读取 `images.txt`：它从 PXEye 父 Chart 及锁定子 Chart 自动得到镜像闭包，缺失镜像才从其原始公网引用拉取，再推送到 `REGISTRY`。第三方和 NICo 镜像仅替换 Registry 主机名，保留 repository 路径和 tag；PXEye 自建镜像使用 `REGISTRY/pxeye:<tag>`。该步骤不制作 bundle、不部署 Kubernetes。

Registry OCI 导出和 bundle staging 缓存在 `cache/registry-exports/`；最终交付文件始终写入构建工作目录根部的 `output/bundle-<version>/`。

只读检查本地镜像、用途、Chart 来源和交付输入：

```bash
python3 ./PXEye/offline-build/delivery.py --config ./build-config.json --plan
```

| 内部阶段 | 作用 | 交付/缓存 |
| --- | --- | --- |
| 缓存初始化（`make bundles` 内部） | 渲染父 Chart；仅闭包变化时才从本地 containerd 导出精确镜像闭包 | `offline-images/` |
| package | 核对缓存闭包、将锁定子 Chart 引入 PXEye 父 Chart、使用配置的 Registry、只执行一次 relok8s 并交付 | `cache/registry-exports/`、`charts/`、`bundle-staging/`、`output/` |

| 步骤 | 做什么 | 关键输入 | 输出与交接 |
| --- | --- | --- | --- |
| [构建内部镜像导出](material-prepare/README.zh-CN.md) | 按清单导出本地 containerd 镜像 | 镜像清单 | `offline-images/` |
| [构建内部打包](helm-bundle/README.zh-CN.md) | 准备 PXEye 父/子 Chart、一次 relok8s 搬迁和验包 | 导出镜像与 Chart 来源 | 三个交付文件 |
| [现场部署](onsite/README.zh-CN.md) | 解包、镜像与 Chart 入库、顺序 Helm 安装 | 三个交付文件；现场配置 | PXEye、NICo Core 与依赖 |

## 配置与状态管理

- **配置分层。** 构建配置定义内容与版本；部署配置定义 Registry、namespace、网络地址、存储和认证。namespace 默认 `nico-system`。
- **资源管理。** 镜像导入由脚本统一处理，Kubernetes 资源通过项目提供的 Helm Chart 管理。
- **故障恢复。** 相同配置可复用已验证的材料缓存和已完成阶段。进度记录与输入版本关联，变更输入后使用独立版本或工作目录。
- **验收范围。** 构建校验、Helm 就绪和物理装机分别验收。

## 执行条件与路径

构建机：Linux amd64、Python 3.11+/PyYAML、Docker 本地服务、Helm 3、足够空间。断网构建需预置锁定的工具和基础镜像。

火种机：Linux amd64、Python 3.11+/PyYAML、kubectl、可用 Registry 和 Kubernetes；节点已能从该 Registry 拉镜像。Helm、relok8s 随离线包交付。

文档统一使用这些路径；真实路径只在相应配置中设置：

```text
/srv/PXEye/offline-build/
  build-config.example.json  # 共用构建配置
  delivery.py           # 统一构建入口
  material-prepare/     # 兼容的显式镜像导出器
  helm-bundle/          # chart-sources.json
  onsite/               # 第三步：run.py + run-config.example.json

/srv/nico-build/        # 构建机配置、镜像导出、缓存和交付包
/srv/nico/              # 火种机三个交付文件、工具、现场配置及运行记录
```

当前配方是固定 e703 的单节点 Core/PXEye，不自动追踪运行集群镜像；不包含 REST/Temporal/Keycloak、DPF 服务或 Ubuntu ISO。第一步只导出镜像。第二步按需将独立材料封装为镜像；已有 prepared / nico-materials 输入保留兼容。材料 HTTP 就绪不等于消费者 URL 或实机链路已验证。

兼容格式的维护说明见[旧版材料构建](legacy-materials.zh-CN.md)和[旧版部署配置](CONFIGURE.zh-CN.md)；其输入格式和执行入口独立于本流程。
