# 第一步：导出离线镜像

[English](README.md) · **简体中文** · [总览](../README.zh-CN.md)

`build.py` 按镜像清单从本地 containerd 导出 linux/amd64 镜像，生成固定目录结构和 OCI 归档。运行要求为 Linux、Python 3.11+、ctr，以及读取 containerd socket 和内容存储的权限。镜像必须已存在于本地；该流程不拉取镜像、不生成 Chart、不构建材料镜像。

## 配置

配置模板显式指定工作目录和镜像清单文件，支持 `~/`：

```json
{
  "work_directory": "~/pxeye-build",
  "sources": {
    "image_list": "images.txt"
  }
}
```

[images.txt](images.txt) 为默认镜像清单，每行一个完整的本地镜像引用，支持空行与 `#` 注释。随项目提供的清单选择13张 Core/PXEye e703系列镜像；它不会自动枚举运行中的 Pod，也不会导出未列出的其他镜像。镜像内容以执行时解析并记录的摘要为准。

`sources.image_list` 相对配置文件所在目录解析，因此示例使用 `$HOME/pxeye-build/images.txt`。仓库原始清单位于 `offline-build/material-prepare/images.txt`；修改工作目录内的清单可选择本次导出的镜像。其他 `sources` 字段仅在非标准环境下需要：

| 字段 | 默认值 | 用途 |
| --- | --- | --- |
| `image_list` | 脚本同目录的 `images.txt` | 自定义镜像清单 |
| `containerd_address` | `/run/containerd/containerd.sock` | 本地 containerd socket |
| `containerd_namespace` | `k8s.io` | 查找镜像引用的 namespace |
| `containerd_content` | `/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256` | 对应 containerd 的 SHA256 内容存储 |
| `ctr` | `ctr` | ctr 可执行文件 |

自定义路径支持 `~/`；相对来源路径以配置文件所在目录为基准。containerd socket 与内容存储必须对应同一个运行时。来源配置不包含 Chart 或独立材料目录。

## 执行

以下示例假设仓库位于 `/srv/PXEye`，在 containerd 所在主机执行：

```bash
mkdir -p "$HOME/pxeye-build"
test ! -e "$HOME/pxeye-build/build-config.json" &&
test ! -e "$HOME/pxeye-build/images.txt" &&
cp /srv/PXEye/offline-build/material-prepare/images.txt "$HOME/pxeye-build/images.txt" &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json "$HOME/pxeye-build/build-config.json"
```

查看和修改本次镜像清单：

```bash
cat "$HOME/pxeye-build/images.txt"
${EDITOR:-vi} "$HOME/pxeye-build/images.txt"
```

检查清单、镜像引用与所需 amd64 内容是否存在；不创建输出目录：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config "$HOME/pxeye-build/build-config.json" --plan
```

导出：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config "$HOME/pxeye-build/build-config.json"
```

完成后输出 `IMAGE_EXPORT_COMPLETE`；复用已完成包时输出 `IMAGE_EXPORT_REUSED`。

## 输出格式

```text
work_directory/
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

与既有镜像导出格式保持一致：

- 归档路径为 `images/nico-amd64.oci.tar`，使用 OCI Image Layout，包含 `oci-layout`、`index.json`、`blobs/sha256/`。
- 每个 index 描述符保留 `linux/amd64` 平台、原始引用，以及 `io.containerd.image.name` 和 `org.opencontainers.image.ref.name` 两个注解。
- `images-lock.json` 是数组，每项包含 `image`、`source_descriptor`、`amd64_manifest`、`config`、`layers`，字段含义与原导出器相同。
- 只收集所选 amd64 manifest、config 和 layers，共享 blob 在归档中仅保存一次；无需缓存其他架构的层。
- `export.json`、校验文件及运行日志为附加元数据，不改变上述格式。镜像集合变化会改变归档摘要，不要求与历史包逐字节相同。

校验产物：

```bash
cd "$HOME/pxeye-build/offline-images"
sha256sum -c SHA256SUMS
```

## 阶段与恢复

| 阶段 | 处理内容 |
| --- | --- |
| resolve | 读取镜像清单，解析本地引用并校验所选平台的内容完整性 |
| export | 校验 blob 摘要并写入 OCI 归档 |
| publish | 生成兼容清单、校验文件，原子发布输出目录 |

失败后修复原因，再运行原命令。完成的归档经校验后复用；归档写入中断时从归档阶段重新开始，不支持字节级续传。中间目录 `.offline-images.building/` 与日志保留。输入镜像版本或清单变化时使用新的工作目录；未知或损坏的已完成文件不会被自动覆盖。

此产物是镜像导出包。第二步当前完整 prepared 输入还包含 Chart、材料描述和工具，不能将镜像导出目录直接作为完整 prepared 使用。原有 schema 1/2 完整材料准备配置仍保留兼容；第二步输入适配独立于本导出格式。
