# NICo / PXEye 离线交付：三步流程

[English](README.md) · **简体中文**

构建两步共用唯一的 `build-config.json`，各脚本只管理自己的配置区域。前两步在构建机执行；第三步在火种机使用独立的现场部署配置。第一步只导出镜像；第二步从同一工作目录读取镜像，下载固定版本 Chart 并生成交付包。

| 步骤 | 做什么 | 关键输入 | 输出与交接 |
| --- | --- | --- | --- |
| [1. 导出镜像](material-prepare/README.zh-CN.md) | 按清单导出本地 containerd 镜像 | 工作目录、镜像清单 | 兼容既有格式的 OCI 归档与镜像锁文件 |
| [2. 构建交付包](helm-bundle/README.zh-CN.md) | 渲染 Chart，relok8s 打包镜像，压缩验包 | 第一步镜像导出、Chart 来源及可选材料 | `bundle.tar.gz`、`onsite-tools.tar.gz`、`SHA256SUMS` |
| [3. 现场部署](onsite/README.zh-CN.md) | 解包、镜像与 Chart 入库、顺序 Helm 安装 | 上述三个文件；一份现场配置 | 可选 PXEye、NICo Core 及其依赖；安装日志和进度 |

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
  material-prepare/     # 第一步：build.py + images.txt
  helm-bundle/          # 第二步：build.py + chart-sources.json
  onsite/               # 第三步：run.py + run-config.example.json

/srv/nico-build/        # 构建机配置、镜像导出、缓存和交付包
/srv/nico/              # 火种机三个交付文件、工具、现场配置及运行记录
```

当前配方是固定 e703 的单节点 Core/PXEye，不自动追踪运行集群镜像；不包含 REST/Temporal/Keycloak、DPF 服务或 Ubuntu ISO。第一步只导出镜像。第二步按需将独立材料封装为镜像；已有 prepared / nico-materials 输入保留兼容。材料 HTTP 就绪不等于消费者 URL 或实机链路已验证。

兼容格式的维护说明见[旧版材料构建](legacy-materials.zh-CN.md)和[旧版部署配置](CONFIGURE.zh-CN.md)；其输入格式和执行入口独立于本流程。
