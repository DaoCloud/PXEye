# 第二步：构建离线交付包

[English](README.md) · **简体中文**

在 Linux amd64 构建机执行，需要 Python 3.11+、PyYAML、Docker、Helm 3，以及第一步导出。

## 共用配置

继续使用同一个 `build-config.json`。第二步只管理 `helm_bundle`：

```json
{
  "work_directory": "~/pxeye-build",
  "image_export": {},
  "helm_bundle": {
    "chart_sources": "chart-sources.json"
  }
}
```

Chart 来源文件默认使用仓库 [chart-sources.json](chart-sources.json)，包含 NICo 固定提交 `e703126e4` 的下载地址、Chart `0.1.1` 及摘要，和 cert-manager `v1.17.1` 的 OCI 地址及摘要。来源只在首次下载时校验；随后使用 `cache/charts/` 中以摘要命名的文件，不再联网或重复计算 SHA。构建器将两者引入 PXEye 父 Chart，再加入仓库内的平台和可选材料 Chart，生成 `Chart.lock`、渲染完整依赖闭包，最后只执行一次 relok8s。`chart_sources` 相对配置文件目录解析。

## 执行命令

在构建工作目录执行，仓库子目录为 `PXEye/`：

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/helm-bundle/build.py --write-config ./build-config.json
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json
```

初始化只补齐本步骤缺少的配置和 `chart-sources.json`，保留已有值和来源文件。统一流程由父 Chart 自动得出镜像闭包，镜像和用途来自显式缓存初始化产物，无需再次填写。失败后重复最后一条命令续跑。

## 结果

成功打印 `HELM_BUILD_COMPLETE`；`DELIVERY_FILES` 列出：

```text
output/<version>/bundle.tar.gz
output/<version>/onsite-tools.tar.gz
output/<version>/SHA256SUMS
```

进度和日志位于 `output/.<version>.building/`，成功后移入版本目录。

[可选配置](REFERENCE.zh-CN.md) · [第三步部署](../onsite/README.zh-CN.md)
