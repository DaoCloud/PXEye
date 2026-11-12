# 第二步参考：来源与可选配置

[English](REFERENCE.md) · **简体中文** · [执行步骤](README.zh-CN.md)

`build.py` 读取第一步导出的镜像，下载固定版本的上游 Chart，准备项目 Chart，并使用 relok8s 生成离线交付包。执行位置为 Linux amd64 构建机，依赖 Python 3.11+/PyYAML、Docker 和 Helm 3。

## 配置

默认配置只需指定与第一步相同的工作目录：

```json
{
  "work_directory": "~/pxeye-build"
}
```

脚本从 `<work_directory>/offline-images/` 读取 OCI 归档及镜像锁文件，自动创建 Chart、缓存、打包输入和交付输出目录。用户无需填写派生目录、schema 或包名。

## Chart 来源

[chart-sources.json](chart-sources.json) 维护下载地址、归档 SHA256、Chart 名称、版本及归档内目录。

| Chart | 来源 | 处理方式 |
| --- | --- | --- |
| NICo `0.1.1` | [上游 helm 源码](https://github.com/dsx-ai-factory/infra-controller/tree/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921/helm) | 下载固定提交源码归档，提取 `helm/`；应用项目兼容补丁后打包 |
| cert-manager `v1.17.1` | `oci://quay.io/jetstack/charts/cert-manager` | Helm 拉取固定版本，校验归档摘要并解压 |
| PXEye | [charts/pxeye](../../charts/pxeye/README.zh-CN.md) | 读取仓库 Chart，注入镜像引用；与直接 Helm 部署使用同一份源码 |
| 平台依赖 | [deploy/nico-platform](../../deploy/nico-platform/Chart.yaml) | 使用仓库 Chart，提供数据库、证书与 Vault 初始化 |
| 材料发布 | [charts.py](charts.py) | 根据选中的材料镜像生成 Chart |

NICo 下载地址为：

```text
https://codeload.github.com/dsx-ai-factory/infra-controller/tar.gz/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921
```

该提交匹配当前 e703 镜像配方；`main` 和仅含 `0.1.1` 的版本号不足以标识具体源码。原始源码中的 Chart 内部符号链接会转换为普通文件。名称、版本或摘要不匹配时停止处理。

镜像站或本地归档可通过 `sources.charts` 覆盖。支持 HTTP(S)、OCI 和本地 `file://` 归档；每个来源必须有 SHA256，`subdirectory` 是归档内含 `Chart.yaml` 的目录。例如，将默认下载切换到本地保留的原始包：

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "charts": {
      "core": {
        "url": "file:///srv/nico-input/nico-0.1.1.tgz",
        "sha256": "9e38837fcd7305ffd5e060ba18e973794388d3b0f83363b7903a21d3ae94ad67",
        "subdirectory": "nico"
      }
    }
  }
}
```

版本升级需要同步更新下载锁、镜像清单和兼容配方；覆盖来源地址只用于同版本发布件或镜像站。

## 可选材料与镜像角色

按第一步清单打包 Core/PXEye 镜像，不附加 ARM64 Scout、APT 或 BFB 文件。需要这些材料时，`sources.materials` 指定对应的二进制来源目录，第二步按锁定文件清单校验并构建材料镜像：

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "materials": {
      "aarch64": "/srv/nico-input/scout-aarch64",
      "apt": "/srv/nico-input/apt",
      "bfb": "/srv/nico-input/dpu"
    }
  }
}
```

ARM64 目录包含六份 Scout 发布文件；APT 目录包含 `dists/` 和 `pool/`；BFB 目录包含 `bf3-doca3.4.0-26.04/`。省略的材料组不处理。该流程封装已有发布件，不编译 NICo/Scout。

PXEye 与工具镜像的默认角色取自 e703 配方。第一步选择其他版本时，通过 `sources.images.ui` 和 `sources.images.bootstrap` 指定导出清单中的完整镜像引用。`tools` 可选覆盖 `docker`、`helm`、`relok8s` 路径；默认通过环境查找或准备锁定版本。

## 执行

以下命令在构建机执行，假设仓库位于 `/srv/PXEye`。第一步已完成镜像导出。

```bash
mkdir -p "$HOME/pxeye-build"
test ! -e "$HOME/pxeye-build/helm-build.json" &&
cp /srv/PXEye/offline-build/helm-bundle/build-config.example.json "$HOME/pxeye-build/helm-build.json"
```

仅下载、校验、解压和准备 Chart，不要求先导出镜像，不使用 Docker 或集群：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json" --prepare-charts
```

完成后输出 `CHARTS_READY`；重复执行验证后输出 `REUSE_CHARTS`。检查完整构建输入计划，不下载或构建：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json" --plan
```

完整构建命令会自动执行 Chart 准备：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HOME/pxeye-build/helm-build.json"
```

成功输出 `HELM_BUILD_COMPLETE`；`DELIVERY_FILES` 列出第三步需要的三个文件。

## 目录结构

```text
work_directory/
  offline-images/                 # 第一步产物
  cache/charts/                   # 按SHA256保存的下载归档
  charts/<id>/
    upstream/{core,cert-manager}/  # 原始Chart目录：Chart.yaml、values.yaml、templates/等
    raw/charts/                   # 原始Chart的规范化归档
    trees/{core,cert-manager,platform,pxeye}/
    deployment/charts/            # 与既有打包入口兼容的Chart归档
    deployment/patches/
    sources.json                  # 来源及全部Chart文件摘要
  package-input/<id>/             # 自动适配第一步镜像与本步Chart/材料
  logs/chart-preparation/run.log
  output/<version>/
    bundle.tar.gz
    onsite-tools.tar.gz
    SHA256SUMS
    bundle/                       # Chart、relok8s镜像包、清单、安装顺序及工具
    progress.json
    events.jsonl
    run.log
    logs/
```

前三个交付文件构成[第三步](../onsite/README.zh-CN.md)输入。第二、三步之间的包格式和执行入口保持兼容。交付包内的 `manifests/build-report.json` 同时保存上游 Chart 地址和归档摘要。

## 恢复与兼容

相同配置重复执行会校验并复用下载、Chart、完整打包输入和已完成的打包阶段。Chart 准备失败时保留暂存目录，重试复用已校验的下载归档。完整构建的进度及日志位于 `output/.<version>.building/`，成功后随版本目录发布。改变输入或实现版本时使用独立工作目录或交付版本。

既有 schema 1 的 `nico-prepared` / `nico-materials` 配置继续支持。需要在该模式下下载 Chart，可添加 `chart_sources`，其内容与 `sources.charts` 相同；默认仍使用旧输入中的 Chart。`--prepare-charts` 可单独执行准备。
