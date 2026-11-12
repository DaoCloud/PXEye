# 第二步：构建离线交付包

[English](README.md) · **简体中文**

执行环境：Linux amd64 构建机；已安装 Python 3.11+、PyYAML、Docker、Helm 3，并完成第一步导出。

## 示例配置

[build-config.example.json](build-config.example.json)：

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "images": {
      "ui": "docker.io/library/mmzhou-os-install-console:0.22.16-2edc182",
      "bootstrap": "docker.io/library/mmzhou-os-install-console:0.22.16-2edc182"
    }
  }
}
```

示例中的 PXEye 镜像同时提供控制台和构建工具，第一步导出清单需包含该引用。

## 执行命令

在构建工作目录执行，仓库子目录为 `PXEye/`：

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/helm-bundle/build.py --write-config ./helm-build.json --work-directory "$PWD"
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./helm-build.json
```

配置已存在时，省略创建配置的命令。失败后重复最后一条命令续跑。

## 结果

成功打印 `HELM_BUILD_COMPLETE`。`DELIVERY_FILES` 列出：

```text
output/<version>/bundle.tar.gz
output/<version>/onsite-tools.tar.gz
output/<version>/SHA256SUMS
```

当前阶段和日志：`output/.<version>.building/progress.json`、`run.log`；成功后移入 `output/<version>/`。

[Chart 来源与可选配置](REFERENCE.zh-CN.md) · [第三步部署](../onsite/README.zh-CN.md)
