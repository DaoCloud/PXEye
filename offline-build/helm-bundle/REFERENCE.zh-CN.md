# 构建配置参考

[English](REFERENCE.md) · **简体中文** · [第二步执行](README.zh-CN.md)

## 唯一用户配置

工作目录只维护 `build-config.json`，模板为 [../build-config.example.json](../build-config.example.json)。

| 区域 | 维护者 | 内容 |
| --- | --- | --- |
| `work_directory` | 初始配置 | 两步共用工作目录；初始化已有配置时不得改变 |
| `image_export` | 第一步 | 镜像清单文件及可选 containerd 接入参数 |
| `helm_bundle` | 第二步 | Chart 来源文件、可选二进制材料和工具路径 |

`--write-config` 采用加锁、原子更新，只补齐本步骤缺少的字段。已有用户值、其他步骤及未知扩展字段原样保留。默认清单/来源文件只在不存在时复制，已有文件不覆盖。正常导出和打包不改用户配置。

相对文件路径以 `build-config.json` 所在目录为基准，支持 `~/`。输出、日志及缓存路径从工作目录派生。

## 第一步

[images.txt](../material-prepare/images.txt) 每行一个本地完整镜像引用，支持空行、注释和行尾用途标记：

```text
docker.io/library/mmzhou-os-install-console:0.22.16-2edc182 # roles=ui,bootstrap
```

用途支持 `ui`、`bootstrap`，可由同一镜像承担；工具镜像需提供 skopeo、Python 等工具。第一步将用途写入 `export.json`，原五字段镜像锁和 OCI 结构不变。未显式标记时，唯一带 PXEye 产品标签的镜像可承担两种用途。仅导出普通镜像不要求存在 PXEye，但第二步必须能确定两个用途。

`image_export` 可选字段及默认值：

| 字段 | 默认值 |
| --- | --- |
| `image_list` | 初始化生成的 `images.txt` |
| `containerd_address` | `/run/containerd/containerd.sock` |
| `containerd_namespace` | `k8s.io` |
| `containerd_content` | `/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256` |
| `ctr` | `ctr` |

## 第二步

[chart-sources.json](chart-sources.json) 明确每个上游 Chart 的 `url`、`sha256`、`subdirectory`、`name`、`version`。

- NICo：从 [e703126e4提交的helm目录](https://github.com/dsx-ai-factory/infra-controller/tree/e703126e4a7a2fe1d4dab5f96cba9bdf055e0921/helm)下载，Chart `0.1.1`，应用项目兼容补丁。
- cert-manager：`oci://quay.io/jetstack/charts/cert-manager`，固定 `v1.17.1`。
- PXEye：[仓库Chart](../../charts/pxeye/README.zh-CN.md)。平台依赖：`deploy/nico-platform`。材料发布：按材料组生成。

下载支持 HTTP(S)、OCI、`file://`；核对摘要和版本。当前版本须匹配 e703 兼容配方，升级须同步镜像清单、下载锁与补丁。来源和文件摘要写入 `charts/<id>/sources.json`，交付报告保留来源。

可在 `helm_bundle` 中增加：

```json
{
  "chart_sources": "chart-sources.json",
  "materials": {
    "aarch64": "/srv/nico-input/scout-aarch64",
    "apt": "/srv/nico-input/apt",
    "bfb": "/srv/nico-input/dpu"
  },
  "tools": {"docker": "docker", "helm": "helm", "relok8s": null}
}
```

默认不附加材料。选中材料须符合固定配方的文件清单/摘要，由第二步封装为镜像；不编译 NICo/Scout。省略 `tools` 时自动使用环境或锁定版本。

以下均使用同一个配置文件：

```bash
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json --plan
python3 ./PXEye/offline-build/helm-bundle/build.py --config ./build-config.json --prepare-charts
```

`--plan` 只读检查输入及来源配置；`--prepare-charts` 仅下载、解压和准备 Chart，不使用 Docker/集群。

## 兼容已有产物

缺少用途标记的旧导出包可从 OCI 配置里的唯一 PXEye 产品标签识别用途；历史锁定双镜像配方仍可读取。不能唯一识别时停止，不按相似镜像名猜选。已有导出包不改写，不要求为配置格式升级重新导出。旧独立配置及 prepared/nico-materials 输入保留读取兼容；新流程统一使用上述共用配置。
