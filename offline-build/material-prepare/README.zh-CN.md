# 第一步：离线镜像与材料准备

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

`build.py` 在 Linux amd64 构建机上生成离线镜像目录，构建材料镜像，并发布供第二步使用的 prepared 目录。构建内容及路径由一份配置文件声明。

## 离线镜像目录

`input_root/<来源标识>/` 保存导出的 OCI 镜像归档、Helm Chart 和引导材料。目录由脚本生成，来源标识根据输入配置、版本配方和材料开关计算。镜像及文件来源在配置的 `sources` 中声明：

| 配置项 | 处理内容 | 上游输入 |
| --- | --- | --- |
| `sources.containerd_content` | 按配方中13张镜像的 manifest 摘要读取完整 amd64 内容图，导出3份 OCI 归档 | 构建机已构建或拉取的锁定镜像内容 |
| `sources.charts` | 收集并校验 `nico-0.1.1.tgz`、`cert-manager-v1.17.1.tgz` | 与配方摘要一致的原始 Chart 发布件 |
| `sources.materials.aarch64` | 收集6个 ARM64 Scout 构建产物 | `BUILD-INFO.json`、`ROOTFS-PACKAGES.json`、`ipxe.efi`、`golan.efi`、`scout.efi`、`scout.squashfs` |
| `sources.materials.apt` | 按清单收集 APT 索引和两个 Scout deb | 根目录内的 `dists/` 和 `pool/` |
| `sources.materials.bfb` | 按清单收集厂商 BFB 和校验文件 | 根目录内的 `bf3-doca3.4.0-26.04/` |

## 支持范围

`recipe-e703.json` 定义固定 e703 版本及定制产物的镜像、Chart 和材料摘要。准备流程导出已有镜像、收集二进制发布件并构建材料镜像；NICo 和 ARM64 Scout 的源码编译需在上游构建流程中完成，BFB 使用厂商发布件。

启用的材料组必须具有匹配配方的源文件。缺失文件会在生成前集中报告；关闭的材料组不要求提供源文件。脚本以只读方式访问 containerd 内容存储，镜像版本由配方锁定。

## 构建阶段

| 阶段 | 处理内容 | 约束与产物 |
| --- | --- | --- |
| 1. 收集文件 | 校验并复制 Chart 和选中的材料 | 只收集配方清单；排除凭据、站点配置、数据库等运行数据 |
| 2. 导出镜像 | 从 containerd 内容存储读取锁定 manifest、config、layers | 仅依赖完整的 amd64 内容图，无需缓存其他架构 |
| 3. 验证原始输入 | 完整校验文件与镜像，整理 OCI 布局 | 新归档允许 tar 摘要变化，镜像 manifest 摘要必须一致 |
| 4. 构建材料镜像 | 构建或复用 ARM64 Scout、APT、BFB 镜像 | 全开时13张输入镜像加3张材料镜像 |
| 5. 发布 prepared | 准备兼容 Chart，验收并生成第二步配置 | 复制输出的 `NEXT_COMMAND` |

## 配置与执行

配置文件指定上游来源及输出位置。以下示例在构建机执行，仓库路径为 `/srv/PXEye`：

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

配置中 `sources` 是已有上游来源；`input_root` 是脚本要创建的原始输入父目录。
`output_root`、`cache_directory`、`package_output_root` 分别是 prepared、缓存和第二步输出父目录；都应与源码及上游来源分开。配置模板中的 `/srv/nico-sources/` 仅是路径示例，脚本不会下载或创建其中的文件。

`--plan` 检查源文件、大小及镜像内容图，不生成构建产物：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

构建命令：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

成功完成后依次输出 `RAW_INPUT_COMPLETE`、`MATERIAL_PREPARE_COMPLETE`、`HELM_BUILD_CONFIG`、`NEXT_COMMAND`。`HELM_BUILD_CONFIG` 提供[第二步](../helm-bundle/README.zh-CN.md)配置路径，`NEXT_COMMAND` 提供对应构建命令。

## 目录结构与恢复机制

```text
input_root/<来源标识>/           # 离线镜像、Chart及材料归档
  images/{base,ui,bootstrap}.oci.tar
  charts/*.tgz
  boot/{aarch64,apt}/...
  http/nico/dpu/...
  manifests/{images.txt,images-lock.json,source-files.json}
  source-progress.json           # 文件来源、完成记录、大小与摘要
output_root/<id>/
  prepared.json
  images/layout/
  deployment/
  tools/helm
  manifests/
  reports/
  logs/
output_root/<id>.helm-build.json
output_root/<id>.result.json
```

恢复使用相同配置和构建命令。原始材料按文件校验后复用，材料镜像和完整 prepared 按摘要复用。未登记或内容变化的文件会阻止覆盖，已有产物予以保留。终端输出当前阶段和文件生成/复用状态；`source-progress.json` 保存来源阶段进度，prepared 中的 `logs/` 和 `reports/` 保存构建日志与来源报告。最终压缩包由第二步生成。

配置 schema 2 支持生成离线镜像目录；schema 1 兼容直接读取既有归档。
