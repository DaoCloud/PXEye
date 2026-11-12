# 第二步：构建离线交付包

[English](README.md) · **简体中文**

在 Linux amd64 构建机执行，需要 Python 3.11+、PyYAML、Docker、Helm 3，以及第一步导出。

## 共用配置

继续使用同一个 `build-config.json`。第二步只管理 `helm_bundle`：

```json
{
  "work_directory": "~/pxeye-build",
  "image_export": {
    "image_list": "images.txt"
  },
  "helm_bundle": {
    "chart_sources": "chart-sources.json"
  }
}
```

Chart 来源文件默认使用仓库 [chart-sources.json](chart-sources.json)，包含 NICo 固定提交 `e703126e4` 的下载地址、Chart `0.1.1` 及摘要，和 cert-manager `v1.17.1` 的 OCI 地址及摘要。`chart_sources` 相对配置文件目录解析。

## 执行命令

在构建工作目录执行，仓库子目录为 `PXEye/`：

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/helm-bundle/build.py --write-config ./build-config.json
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json
```

初始化只补齐本步骤缺少的配置和 `chart-sources.json`，保留已有值、来源文件及第一步配置。镜像和用途从第一步产物读取，无需再次填写。失败后重复最后一条命令续跑。

## 结果

成功打印 `HELM_BUILD_COMPLETE`；`DELIVERY_FILES` 列出：

```text
output/<version>/bundle.tar.gz
output/<version>/onsite-tools.tar.gz
output/<version>/SHA256SUMS
```

进度和日志位于 `output/.<version>.building/`，成功后移入版本目录。

[可选配置](REFERENCE.zh-CN.md) · [第三步部署](../onsite/README.zh-CN.md)
