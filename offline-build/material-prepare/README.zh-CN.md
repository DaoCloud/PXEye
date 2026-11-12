# 第一步：生成原始材料并准备镜像

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

**执行位置：Linux amd64 构建机。一个配置、一个脚本，从创建原始材料目录开始。**
不读取运行集群的镜像版本，不修改 containerd，不部署服务。

## 原始目录从哪里来

早期离线目录是人工汇集的产物：从 containerd 导出23张镜像，复制 Chart、x86启动/APT材料和厂商BFB，另外在构建机交叉编译 ARM64 Scout 后汇入。它不是 Git 仓库内容，也没有一个能重建全部内容的历史入口。

当前脚本自行创建 `input_root/<来源标识>/`，不要求先准备这份历史目录。来源由同一配置文件明确指定：

| 来源 | 脚本做什么 | 仍需具备的上游输入 |
| --- | --- | --- |
| `sources.containerd_content` | 按配方中13张镜像的 manifest 摘要读取完整 amd64 内容图，导出3份 OCI 归档 | 构建机已构建或拉取的锁定镜像内容；不按运行 Pod 或可变 tag 猜版本 |
| `sources.charts` | 收集并校验 `nico-0.1.1.tgz`、`cert-manager-v1.17.1.tgz` | 与配方摘要一致的原始 Chart 发布件 |
| `sources.materials.aarch64` | 收集6个 ARM64 Scout 构建产物 | `BUILD-INFO.json`、`ROOTFS-PACKAGES.json`、`ipxe.efi`、`golan.efi`、`scout.efi`、`scout.squashfs` |
| `sources.materials.apt` | 按清单收集 APT 索引和两个 Scout deb | 根目录内的 `dists/` 和 `pool/` |
| `sources.materials.bfb` | 按清单收集厂商 BFB 和校验文件 | 根目录内的 `bf3-doca3.4.0-26.04/` |

**边界：导出既有镜像、收集二进制发布件，不等于重新编译 NICo/Scout。** 当前配方锁定 e703 及既有定制产物；不支持只从 Git clone 开始重新编译它们。ARM64 Scout 来自独立交叉构建，BFB 来自厂商发布，不能由打包脚本凭空生成。原始来源缺失时，脚本一次列出缺失项并停止，不自动退回历史离线目录。关闭材料开关后，对应源文件无需存在。

## 阶段

| 阶段 | 做什么 | 关注什么 |
| --- | --- | --- |
| 1. 收集文件 | 校验并复制 Chart 和选中的材料 | 只收集配方清单；排除凭据、站点配置、数据库等运行数据 |
| 2. 导出镜像 | 从 containerd 内容存储读取锁定 manifest、config、layers | 只导出 amd64 内容图，避开缓存缺少其他架构导致的 export 失败 |
| 3. 验证原始输入 | 完整校验文件与镜像，整理 OCI 布局 | 新归档允许 tar 摘要变化，镜像 manifest 摘要必须一致 |
| 4. 构建材料镜像 | 构建或复用 ARM64 Scout、APT、BFB 镜像 | 全开时13张输入镜像加3张材料镜像 |
| 5. 发布 prepared | 准备兼容 Chart，验收并生成第二步配置 | 复制输出的 `NEXT_COMMAND` |

## 配置与执行

主要目标：指定上游来源及输出位置。执行位置为构建机；以下假设仓库在 `/srv/PXEye`。先自行创建配置：

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

配置中 `sources` 是已有上游来源；`input_root` 是脚本要创建的原始输入父目录。
`output_root`、`cache_directory`、`package_output_root` 分别是 prepared、缓存和第二步输出父目录；都应与源码及上游来源分开。配置模板中的 `/srv/nico-sources/` 仅是路径示例，脚本不会下载或创建其中的文件。

确认命令：仅核对全部源文件、大小及镜像内容图，不导出、不复制、不构建：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

执行命令：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

确认：依次出现 `RAW_INPUT_COMPLETE`、`MATERIAL_PREPARE_COMPLETE`、`HELM_BUILD_CONFIG`、`NEXT_COMMAND`。执行最后一项的完整命令进入[第二步](../helm-bundle/README.zh-CN.md)，无需手工创建第二步配置。

## 产物与续跑

```text
input_root/<来源标识>/           # 本次新增：脚本生成，不再预先要求旧离线目录
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

失败后修复原因，再运行原命令。原始材料按文件校验续跑，材料镜像和完整 prepared 按摘要复用；不会覆盖未登记或已变化的文件，不删除旧产物。终端会打印当前阶段及每个文件的生成/复用信息，`source-progress.json` 保留来源阶段进度；已有 prepared 的日志与来源报告继续保留。第一步不生成最终压缩包。

旧 schema 1 配置仍可读取既有归档，供历史构建继续使用；新配置使用 schema 2。
