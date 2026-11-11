# 第一部分：构建通用 NICo 离线材料包

[English](README.md) · **简体中文**

构建只确定材料和版本，不需要目标现场的Registry、IP、网关、Kubernetes context或节点名。现场初始化与部署见[第二部分](CONFIGURE.zh-CN.md)。namespace默认`nico-system`，在现场初始化时统一使用。

固定配方为NICo e703126e4、官方nico-0.1.1/cert-manager-v1.17.1 Chart及已收敛兼容补丁，单节点Podman Kind、单副本Core；不包含REST/Temporal/Keycloak。本工具组装现有镜像，不编译NICo或构建PXEye镜像。

## 1. 准备构建工具和依赖

主要目标：使用Git中的独立工具目录，或将整个目录放在构建机`/srv/nico-build-kit`。本文件所有构建命令均在构建机Bash、该工具目录执行。Git克隆后也可直接进入`deliverables/nico-offline-build`执行，不强制使用`/srv`。

执行命令：

```bash
bash
set -euo pipefail
cd /srv/nico-build-kit
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print("PyYAML",yaml.__version__)'
command -v helm
command -v patch
cp -n build-config.example.json build-config.json
vi build-config.json
```

确认命令：

```bash
python3 -m json.tool build-config.json >/dev/null
python3 -c 'import json; c=json.load(open("build-config.json")); assert c["schema_version"]==3 and "site" not in c; print(c["build"]); print(c["package"])'
```

依赖Linux、Python3.11+/PyYAML、Helm3、GNU patch。构建不访问Kubernetes或Registry，不需要kubeconfig、Docker socket或登录凭据。空间检查按输入总大小两倍加2GiB估算。不需要另外创建固定名称的配置目录；`--config`可以指向Git仓库外任意文件。

## 2. 配置输入并查看完整计划

主要目标：只声明构建机能够确定的输入。配置不含现场网络或集群信息。

| 字段 | 构建时提供的内容 |
| --- | --- |
| `schema_version` | `3`，通用材料模式 |
| `build.source_bundle` | 原始锁定材料目录，含raw Charts、23镜像OCI、引导和DPU材料 |
| `build.output_root` | 输出父目录，每次生成新的版本子目录 |
| `package.bundle_id` | 通用材料包标识，与现场站点名无关 |
| `package.ui`、`package.bootstrap` | 镜像归档路径、tag、manifest digest；归档内源引用自动按digest读取 |
| `files.inputs` | 每项输入的来源、角色、目标路径、字节数、SHA256；不使用通配符 |
| `files.base_image_manifests` | 23张原始镜像的引用和manifest摘要 |
| `files.repository`、`files.toolkit` | 随包模板、工具和说明的逐文件列表 |
| `files.generated` | 每个生成文件的最终路径 |

`root=bundle`相对`build.source_bundle`读取；`root=package`从`package.ui.archive`或`package.bootstrap.archive`读取两张额外镜像。归档路径相对配置文件解析，也可为绝对路径。tag/digest与`files.inputs`的大小/文件SHA256必须一起更新。归档原始Registry引用只用于材料溯源，不作为部署Registry。

当前清单含122项输入：3个OCI归档、原始镜像锁、2个raw Chart、Helm/CLI、20项boot、20项DPF/DOCA、2项BFB及72项历史材料。8个macOS `._`文件、Ubuntu安装ISO和额外GPU软件不在清单中。NICo Chart应用补丁后打包；其他材料按锁复制。工具自身和部署模板也逐项声明，不扫描新增文件补入包。

执行命令：

```bash
python3 build.py --config build-config.json --plan > FILE-PLAN.current.txt
cat FILE-PLAN.current.txt
```

确认命令：

```bash
tail -1 FILE-PLAN.current.txt
```

计划末行报告实际输入/生成/总文件数和输入字节数；本版默认122项输入、50项生成、172个最终文件。`--plan`只检查清单和工具依赖，不读取大材料、不构建。`FILE-PLAN.txt`是参考输出，不是额外构建输入，不必从另一台机器复制。

## 3. 构建并验包

主要目标：产生与现场无关、版本锁定的材料包，禁止把演练地址当作现场配置写入可部署recipe。

执行命令（同一构建机Bash、工具目录）：

```bash
VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_ROOT="$(python3 -c 'import json; print(json.load(open("build-config.json"))["build"]["output_root"])')"
OUTPUT="$OUTPUT_ROOT/$VERSION"
python3 build.py --config build-config.json --version "$VERSION"
```

确认命令：

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
python3 -m json.tool build-result.json
ls -lh bundle.tar.gz
```

必须输出`BUILD_COMPLETE`、`bundle.tar.gz: OK`、`BUNDLE_VERIFIED`。构建检查输入摘要、OCI blobs/闭包、四阶段真实Helm渲染、13单副本、证书身份/服务IP一致性、完整输出集合及归档逐文件读回。渲染使用临时验证参数，仅作为模板组合检查，最终材料包没有`deployment/deployment.json`，`recipe_ready=false`。它必须先现场初始化，不能在UI直接安装。

版本目录必须不存在且在工具/输入目录之外。失败保留`.building-*`目录；先排查，再使用新版本。摘要计算和归档读回时文件不增长属正常行为，不以此判断卡住。

## 4. 产物与解压结构

主要目标：区分构建工具、通用材料和现场生成文件。

```text
<build.output_root>/<VERSION>/
├── bundle/                       # 未压缩通用材料
├── bundle.tar.gz                 # 压缩交付件
├── SHA256SUMS
└── build-result.json

<package.bundle_id>/              # tar解压后的顶层目录
├── bundle.json                   # kind=nico-materials；recipe_ready=false
├── config/site-config.example.json
├── deployment/
│   ├── charts/                   # 3个已准备Chart
│   └── patches/                  # 4个补丁记录
├── deployment-kit/               # 独立现场初始化工具及逐项锁定模板
│   ├── configure.py
│   ├── generic.py
│   ├── build.py
│   ├── site-config.example.json
│   ├── deploy/
│   └── tools/
├── images/                       # 23镜像OCI集合及2个PXEye归档
├── manifests/                    # 镜像锁、输入锁、计划、构建报告和文件inventory
├── tools/                        # Helm、CLI及验包工具
├── docs/CONFIGURE.md
├── docs/CONFIGURE.zh-CN.md
├── boot/
├── dpu/
├── http/
└── source/
```

执行命令（同一终端，保留`OUTPUT`；解压需要额外空间）：

```bash
UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
find "$UNPACK" -mindepth 1 -maxdepth 1 -type d
```

确认命令：

```bash
MATERIALS="$(find "$UNPACK" -mindepth 1 -maxdepth 1 -type d)"
python3 "$MATERIALS/tools/verify-bundle.py" "$MATERIALS"
python3 "$MATERIALS/deployment-kit/configure.py" --help
```

完整逐文件目录由`--plan`和最终`manifests/file-inventory.json`提供。密码、kubeconfig、数据库和Vault恢复材料不入包。

## 5. 已有大包如何处理

主要目标：复用材料，避免因现场地址变化重复构建十几GiB归档。

当前工具支持把此前`1c732234`构建器产出的完整Core包作为现场初始化输入。保留原`bundle.tar.gz`及SHA256SUMS，使用其已解压`bundle/`和新版`configure.py`即可，具体命令见[第二部分](CONFIGURE.zh-CN.md)。不支持缺少`build-report`/完整inventory的任意旧包。

现场初始化校验旧材料，在同一文件系统的新目录中硬链接大文件，只重新生成小配置/工具及清单；不重新编译、下载、复制或压缩大镜像。硬链接失败会停止，不偷偷退化成大文件复制。只能编辑现场配置，镜像/引导材料按不可变文件使用；Pod只读挂载它们。

如要交付一个已经自带新版初始化工具的单一`bundle.tar.gz`，须用schema3重新组装压缩交付件，镜像内容仍原样复用。新材料版本或镜像摘要变化也需重新构建。现场Registry/IP/网关变化，只需在新目录重新初始化，不重打通用大包。

本次仅更新工具；旧版12.16GiB实际构建证据不等于schema3已完整重打包或空集群安装成功。真实DHCP/Relay/HTTP Boot、ARM/DPU及生产HA仍需另验收。

参考：[NVIDIA Machine-a-Tron部署指南](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment)。配方能力以固定e703源码和模板为准。
