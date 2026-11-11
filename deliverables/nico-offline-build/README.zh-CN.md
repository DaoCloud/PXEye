# 第一部分：构建 NICo 离线安装包

[English](README.md) · **简体中文**

这份文档只负责准备输入、查看文件清单、构建、验包及说明产物。通过离线包部署 NICo 的操作由另一份文档负责，生成位置为最终包的 `docs/INSTALL.md`。

当前配方：NICo Core e703126e4、官方 nico-0.1.1/cert-manager-v1.17.1 Chart，加上已收敛的兼容补丁和平台依赖。组装预先构建的镜像和材料，不编译 NICo、不构建 PXEye 镜像。目标为已有 Podman Kind 的单副本 Core 演练，不包含 REST/Temporal/Keycloak。

## 1. 构建目录与依赖

**主要目标：** 将整个构建工具目录放在构建机 `/srv/nico-build-kit`，后续所有命令都在该机的 Bash 中执行。目录可整体复制，不依赖原 PXEye Git 工作区。大文件从配置指定的输入目录读取。

交付的构建目录：

```text
/srv/nico-build-kit/
├── README.zh-CN.md                 # 本文：构建与产物说明
├── README.md                       # 英文对应文档
├── build.py                        # 实际构建脚本
├── build-config.json               # 本次构建配置，编辑入口
├── build-config.example.json       # 通用配置示例
├── source-revision.txt             # 导出这些脚本/模板的固定 Git commit
├── FILE-PLAN.txt                   # 导出时生成的完整文件计划
├── deploy/
│   ├── bootstrap-kubernetes.yaml   # 生成完整 PXEye Deployment 的源模板
│   ├── nico-cluster-permissions.yaml
│   ├── nico-platform/              # PostgreSQL TLS、Vault、CA 等平台 Chart 源码
│   └── offline-core/               # 四阶段定义、values 模板、兼容补丁
└── tools/
    ├── import-oci-bundle.py         # 已修复的 OCI 集合导入工具
    └── offline-field/              # 现场工具/部署文档模板
```

仓库中的维护入口是本目录 `build.py`、`export.py`、`build-config.example.json`。`export.py`从指定 Git 提交导出以上独立目录，模板仍以仓库原路径为唯一源码。旧 `tools/build-nico-offline-bundle.py` 仅兼容转发，不维护另一份实现。

**执行命令：** 构建机 Bash。

```bash
bash
set -euo pipefail
cd /srv/nico-build-kit
python3 --version
python3 -c 'import yaml; print("PyYAML", yaml.__version__)'
command -v patch helm
```

**确认命令：** 同一终端。

```bash
test -r build.py
test -r build-config.json
test -r source-revision.txt
python3 -m json.tool build-config.json >/dev/null
```

依赖 Linux、Python3.11+/PyYAML、Helm3、GNU patch。构建脚本不访问 Kubernetes/Registry，不需要 Docker socket、skopeo、kubeconfig 或登录凭据。空间门禁按输入大小的两倍加2GiB估算；压缩和归档读回需要时间。

## 2. 配置文件：打包什么、从哪里来

**主要目标：** `build-config.json`是本次构建的配置入口。文件列表逐项明确，没有通配符，也不自动扫描目录补入其他材料。

| 字段 | 作用 |
| --- | --- |
| `schema_version` | 固定为2，使用显式文件计划 |
| `build.source_bundle` | 原始固定版本材料目录，包含raw charts、23镜像OCI及材料 |
| `build.output_root` | 构建输出的父目录；每个版本生成一个新子目录 |
| `site` | 生成配方所需的站点参数：namespace、发布名、镜像仓库、Service IP、HostInband等；不含密码 |
| `site.ui` / `site.bootstrap` | 两张额外PXEye OCI归档的路径、归档内原引用、目标tag、镜像manifest digest |
| `files.base_image_manifests` | 原始OCI中23张镜像的完整引用和manifest摘要；UI/初始化另由site声明 |
| `files.inputs` | 每个大文件/二进制/raw Chart的输入和包内路径；含字节数、SHA256与处理角色 |
| `files.generated` | 脚本会生成的每一个文件在最终包中的路径 |
| `files.repository` | 随构建工具一起交付的每个模板/Chart源码/辅助脚本，共24项 |
| `files.toolkit` | 构建脚本、双语文档、通用配置模板的源码与工具目录内路径 |

`files.inputs`每项的格式：

```json
{
  "role": "material",
  "root": "bundle",
  "source": "boot/x86_64/ipxe.efi",
  "target": "boot/x86_64/ipxe.efi",
  "bytes": 352256,
  "sha256": "完整的64位SHA256，实际值已在配置文件中提供"
}
```

`root=bundle`表示相对`build.source_bundle`读取；`root=site`用于两张额外镜像，例如`source=ui.archive`引用`site.ui.archive`，不重复维护路径。归档路径相对配置文件解析，也可使用绝对路径。

当前默认清单的准确内容：

| 内容 | 输入文件数 | 处理与最终位置 |
| --- | ---: | --- |
| 原始23镜像集合 | 1 | 原样复制为`images/nico-amd64.oci.tar`，不拆分/重打包其manifest |
| UI与Vault初始化镜像 | 2 | 两个独立`images/pxeye-<tag>.oci.tar` |
| 原始镜像锁 | 1 | 原样复制为`manifests/images-lock.json` |
| 原始官方Chart | 2 | cert-manager复制；NICo解包、应用兼容补丁再重新打包 |
| Helm与nico-admin-cli | 2 | 原样复制到`tools/`，保留可执行权限 |
| Scout/iPXE引导材料 | 20 | `boot/`，包含x86_64/aarch64、Scout包及摘要 |
| DPF/DOCA材料 | 20 | `dpu/dpf-v26.4.0/`，含Chart、3个OCI、源码及dpfctl |
| BlueField BFB及摘要 | 2 | `http/nico/dpu/...` |
| 历史源码/二进制备份 | 72 | `source/`，供溯源；不作为当前PXEye应用源码维护入口 |
| **合计输入文件** | **122** | 输入摘要在复制/使用时核对 |
| **生成文件** | **28** | 配方、values、平台Chart、完整Deployment/RBAC、runtime、工具、部署文档、清单等 |
| **最终包内文件** | **150** | file-inventory记录149项，自身不记录自己 |

原始OCI保留其23张锁定镜像，其中含历史材料；实际部署引用以生成的recipe为准。

8个macOS `._`伴生文件已从新清单排除。Ubuntu安装ISO、额外GPU驱动/业务软件不在当前清单内；如需增加，须明确加入`files.inputs`中受支持的材料路径及对应大小/摘要。普通材料可放在`boot/`、`dpu/`、`http/`或`source/`下；它们的source与target须一致。8项核心输入角色及固定生成路径按配方约束，不随意更名。

`files.inputs[].sha256`校验输入文件；`site.ui.digest`等校验镜像manifest，二者不同。应用补丁后的NICo Chart与输入raw Chart摘要不同，最终摘要写入`deployment/deployment.json`和`manifests/file-inventory.json`。

**执行命令：** 同一构建机终端，先查看输入根路径和完整计划。

```bash
python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('build-config.json').read_text())
print('原始材料：',c['build']['source_bundle'])
print('输出父目录：',c['build']['output_root'])
print('UI归档：',c['site']['ui']['archive'])
print('初始化归档：',c['site']['bootstrap']['archive'])
PY
python3 build.py --config build-config.json --plan | tee /tmp/nico-build-plan.txt
```

**确认命令：** 同一终端。

```bash
tail -1 /tmp/nico-build-plan.txt
```

默认清单显示`PLAN_COMPLETE inputs=122 generated=28 bundle_files=150`。`--plan`只解析计划，不读取大文件内容、不构建。输出的每一行显示复制/生成方式及包内路径；编辑材料清单后按实际数量输出。

## 3. 执行构建与确认

**主要目标：** 只打包已列出的输入，生成完整四阶段配方，并核对实际产物与配置计划完全一致。

**执行命令：** 同一构建机Bash、`/srv/nico-build-kit`。

```bash
VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_ROOT="$(python3 -c 'import json; print(json.load(open("build-config.json"))["build"]["output_root"])')"
OUTPUT="$OUTPUT_ROOT/$VERSION"
python3 build.py --config build-config.json --version "$VERSION"
```

版本使用UTC；源码commit自动读取`source-revision.txt`。输出目录必须不存在且在输入/工具目录之外；旧产物不会覆盖。失败打印保留的`.building-*`路径，先排查原因，再以新版本重试。

**确认命令：** 同一Bash，保留上面的`OUTPUT`变量。

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
python3 -m json.tool build-result.json
ls -lh bundle.tar.gz
```

必须输出`BUILD_COMPLETE`、`bundle.tar.gz: OK`、`BUNDLE_VERIFIED`，并确认源码commit和版本。日志阶段包括`VERIFY_DECLARED_INPUTS`、`VERIFY_INPUT_OCI`、`COPY_VERIFIED_MATERIALS`、`ARCHIVE`、`HASH_ARCHIVE`、`VERIFY_ARCHIVE_CONTENTS`。计算摘要和读回期间文件不增长属于正常行为。

构建门禁包含：raw Chart/OCI固定摘要、完整amd64 OCI blobs/镜像闭包、输入大小/摘要、24项模板依赖一致性、四阶段真实Helm渲染、13单副本、证书CN、规范服务身份、镜像锁、DNS/PXE/NTP地址一致性、输出与配置完全一致、tar逐文件读回。历史故障修复已固化到模板/导入器，不在现场临时补文件。

## 4. 构建产物与压缩包目录结构

**主要目标：** 清楚区分构建工具目录、未压缩产物和最终压缩包。

```text
<build.output_root>/<VERSION>/
├── bundle/                 # 可直接检查的完整离线材料目录
├── bundle.tar.gz           # 整个bundle目录的压缩交付件
├── SHA256SUMS              # 压缩交付件SHA256
└── build-result.json       # 版本、源码commit、归档大小/摘要、镜像及workload数量
```

压缩包顶层名使用`site.bundle_id`，解压后的结构为：

```text
<site.bundle_id>/
├── bundle.json
├── config/
│   ├── runtime.json
│   └── deployment-settings.json
├── deployment/
│   ├── deployment.json
│   ├── pxeye-bootstrap.yaml
│   ├── nico-cluster-permissions.yaml
│   ├── nico-target-namespace-rbac.yaml
│   ├── charts/
│   │   ├── cert-manager-v1.17.1.tgz
│   │   ├── nico-0.1.1.tgz
│   │   └── pxeye-nico-platform-0.1.0.tgz
│   ├── values/              # cert-manager/platform/vault/core四份yaml
│   └── patches/             # migration、Core、平台与固定Service IP补丁
├── images/
│   ├── nico-amd64.oci.tar   # 23张原镜像集合
│   └── pxeye-<tag>.oci.tar  # UI和初始化两份
├── manifests/
│   ├── images-lock.json
│   ├── deployment-images-lock.json
│   ├── materials-input-lock.json
│   ├── build-file-plan.json
│   ├── build-report.json
│   └── file-inventory.json
├── tools/
│   ├── helm
│   ├── nico-admin-cli
│   ├── import-oci-bundle.py
│   ├── import-pxeye-images.py
│   ├── prepare-auth.py
│   ├── deployment-client.py
│   ├── verify-core.py
│   └── verify-bundle.py
├── docs/INSTALL.md          # 第二部分：通过离线包部署NICo
├── boot/                   # 20项，完整文件名见构建配置
├── dpu/                    # 20项
├── http/                   # 2项
└── source/                 # 72项历史材料
```

`FILE-PLAN.txt`与配置中的`files.inputs/ generated`逐项列出全部150个文件，而不只列出目录。

**执行命令：** 同一构建机Bash，演示解压到独立目录；至少预留另一个完整材料目录的空间。

```bash
UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
BUNDLE_ID="$(python3 -c 'import json; print(json.load(open("/srv/nico-build-kit/build-config.json"))["site"]["bundle_id"])')"
```

**确认命令：** 同一终端。

```bash
python3 "$UNPACK/$BUNDLE_ID/tools/verify-bundle.py" "$UNPACK/$BUNDLE_ID"
find "$UNPACK/$BUNDLE_ID" -maxdepth 2 -type d | sort
```

`build-report.json`记录渲染、来源和兼容配方；`build-file-plan.json`记录本次实际输入与输出规则；`file-inventory.json`记录最终文件摘要。登录口令、kubeconfig、运行数据库和Vault恢复材料由部署现场维护，不从运行站点采集到包里。

## 5. 验证边界

此前`1c732234`版本已在构建机完成完整17GiB目录及12.16GiB压缩包的构建/验包。该结果属于旧布局；本版增加显式文件清单、独立工具目录并移除8个伴生文件，实际大小以新构建的`build-result.json`为准。

构建检查和空集群安装验收是两个结果。当前兼容配方只支持固定e703版本的Core演练；保留ARM/DPU材料不代表ARM装机、完整DPU管理、物理DHCP/PXE或生产HA已验证。


参考：[NVIDIA Machine-a-Tron部署指南](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment)。当前配方以固定e703源码和已收敛修复为准，不推定在线最新版兼容。
