# 第一步：导出离线镜像

[English](README.md) · **简体中文**

在本地 containerd 所在的 Linux 主机执行，需要 Python 3.11+ 和 ctr。镜像必须已存在于本地。

## 共用配置

两步只使用工作目录下的 `build-config.json`。第一步只管理 `image_export`：

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

默认镜像清单为仓库 [images.txt](images.txt)，固定12张 Core/PXEye 镜像。`image_list` 相对配置文件目录解析。行尾 `# roles=ui,bootstrap` 标记镜像用途，第一步将用途写入产物，第二步自动读取。

## 执行命令

在构建工作目录执行，仓库子目录为 `PXEye/`：

```bash
cd ~/pxeye-build
python3 ./PXEye/offline-build/material-prepare/build.py --write-config ./build-config.json --work-directory "$PWD"
python3 ./PXEye/offline-build/material-prepare/build.py --config ./build-config.json
```

初始化只补齐本步骤缺少的配置和 `images.txt`，保留已有值、镜像清单及第二步配置。需要改镜像时编辑工作目录的 `images.txt`。只读检查可在执行命令后加 `--plan`。

## 输出

```text
offline-images/
  images/nico-amd64.oci.tar
  manifests/images.txt
  manifests/images-lock.json
  export.json
  SHA256SUMS
logs/image-export/
  progress.json
  events.jsonl
  run.log
```

成功打印 `IMAGE_EXPORT_COMPLETE`；原五字段镜像锁格式保留，`export.json` 增加镜像用途。失败后重复执行原命令续跑。已完成的导出不会被覆盖；镜像集合变化时使用新工作目录。

[第二步](../helm-bundle/README.zh-CN.md)使用同一个 `build-config.json`，不再选择镜像。
