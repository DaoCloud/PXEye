# 第一部分：我如何构建 NICo 离线材料包

[English](README.md) · **简体中文**

我在一台Linux构建机上完成以下步骤。构建只确定材料和版本，不需要目标现场Registry、IP、网关或Kubernetes信息。现场初始化与部署另见[第二部分](CONFIGURE.zh-CN.md)。本配方固定NICo e703126e4、官方Chart及兼容补丁，为单节点Podman Kind/单副本Core准备材料，不包含REST/Temporal/Keycloak；不编译NICo或构建PXEye镜像。

当前推荐流程分为[第一步：单脚本准备材料](material-prepare/README.zh-CN.md)和[第二步：Helm/relok8s打包](helm-bundle/README.zh-CN.md)。第一步自动生成第二步配置，不再要求先执行本文的旧通用包构建。下文保留原schema4流程供历史产物使用。

## 第一步：我检查构建机的条件

主要目标：我确认机器、工具和空间，避免构建中途才发现依赖缺失。本文件所有命令均在构建机root的同一个Bash终端执行；此时工作目录任意。下列三个输入路径必须指向事先准备好的材料；已有环境可以在执行本节前设置同名环境变量覆盖默认路径。

执行命令：

```bash
bash
set -euo pipefail
export BUILD_WORK="${BUILD_WORK:-/srv/nico-build}"
export SOURCE_BUNDLE="${SOURCE_BUNDLE:-/srv/nico-input/base-bundle}"
export UI_ARCHIVE="${UI_ARCHIVE:-/srv/nico-input/pxeye-ui.oci.tar}"
export BOOTSTRAP_ARCHIVE="${BOOTSTRAP_ARCHIVE:-/srv/nico-input/pxeye-bootstrap.oci.tar}"
hostname
uname -m
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print("PyYAML",yaml.__version__)'
git --version
helm version --short
patch --version | head -1
```

确认命令：

```bash
test -d "$SOURCE_BUNDLE"
test -f "$UI_ARCHIVE"
test -f "$BOOTSTRAP_ARCHIVE"
mkdir -p "$BUILD_WORK"
df -h "$BUILD_WORK"
df -i "$BUILD_WORK"
```

我要具备Linux、Python3.11+/PyYAML、Git、Helm3、GNU patch。默认材料约16GiB，构建至少要求选中输入总大小两倍加2GiB空闲；第六步解压还需另一份材料大小的空间。构建不访问Kubernetes或Registry，不需要kubeconfig、Docker socket或登录凭据。

## 第二步：我获取工具并确认版本

主要目标：我使用Git中的独立工具目录，记录真实源码版本，不在运行Pod中修改代码。`BUILD_WORK/PXEye`必须是新目录，已有工作区不覆盖。

执行命令（同一终端）：

```bash
test ! -e "$BUILD_WORK/PXEye"
git clone --branch main https://github.com/DaoCloud/PXEye.git "$BUILD_WORK/PXEye"
export KIT="$BUILD_WORK/PXEye/deliverables/nico-offline-build"
cd "$KIT"
```

确认命令：

```bash
git -C "$BUILD_WORK/PXEye" rev-parse HEAD
cat "$KIT/source-revision.txt"
test -r "$KIT/build.py"
test -r "$KIT/materials-lock.json"
python3 "$KIT/build.py" --help
```

完整工具目录也可以整体复制使用，此时将`KIT`设置为其绝对路径即可，不必克隆。`source-revision.txt`记录导出模板/脚本的固定提交，与包含该导出件的Git交付提交可能不同。

## 第三步：我生成小配置，只填写路径和选项

主要目标：我只维护16行配置，不填写逐文件摘要或现场信息。配置放在工具目录外，重复构建可以复用；配置已存在时脚本会停止，不覆盖。

执行命令（同一终端、`KIT`目录）：

```bash
export CONFIG="$BUILD_WORK/build-config.json"
python3 "$KIT/build.py" --write-config "$CONFIG" \
  --source-bundle "$SOURCE_BUNDLE" \
  --output-root "$BUILD_WORK/output" \
  --ui-archive "$UI_ARCHIVE" \
  --bootstrap-archive "$BOOTSTRAP_ARCHIVE"
```

确认命令：

```bash
cat "$CONFIG"
python3 - "$KIT" <<'PY'
import json,sys
from pathlib import Path
lock=json.loads((Path(sys.argv[1])/'materials-lock.json').read_text())
print('材料配方：',lock['profile'])
print('固定镜像：',json.dumps(lock['images'],ensure_ascii=False))
PY
```

| 我编辑的配置 | 作用 |
| --- | --- |
| `build.source_bundle` | 原始锁定材料目录 |
| `build.output_root` | 每个版本的输出父目录 |
| `package.bundle_id` | 通用材料包标识 |
| `package.ui_archive`、`package.bootstrap_archive` | 两张已构建PXEye镜像的OCI归档路径 |
| `include.dpu` | 默认true，包含DPF/DOCA/BFB材料；与固定Core的23镜像集合独立 |
| `include.history` | 默认false，不包含72项历史源码备份；保留溯源时才设true |

机器维护的`materials-lock.json`单独保存文件列表、大小、SHA256、镜像tag/digest及模板清单。普通构建不编辑这个锁文件。我要看完整打包内容时执行下一步`--plan`；不需要再复制`FILE-PLAN.txt`。输入文件的`source/target`同名只表示保留相对路径，不是重复打包。

## 第四步：我检查计划和输入

主要目标：我在长时间构建前，确认本次到底包含哪些文件、有没有缺件。

执行命令（同一终端）：

```bash
python3 "$KIT/build.py" --config "$CONFIG" --plan > "$BUILD_WORK/FILE-PLAN.txt"
cat "$BUILD_WORK/FILE-PLAN.txt"
python3 "$KIT/build.py" --config "$CONFIG" --check-inputs
```

确认命令：

```bash
tail -1 "$BUILD_WORK/FILE-PLAN.txt"
```

默认计划为`inputs=50 generated=52 bundle_files=102`，不含`source/`历史文件。开启history后输入122项，总文件174项；关闭dpu会移除对应22项材料。macOS `._`文件、Ubuntu安装ISO及额外GPU软件不在当前清单中。

`INPUTS_READY`仅表示选中输入的存在/尺寸、必要哈希及工具清单检查通过；长构建仍会验证全部输入SHA、OCI blobs/闭包。默认两张额外OCI的归档内源引用按锁定digest读取，不要求我知道原Registry地址。

## 第五步：我开始构建一个新版本

主要目标：我只创建新产物，不覆盖原材料、旧包或运行服务。

执行命令（同一终端）：

```bash
export VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
export OUTPUT="$BUILD_WORK/output/$VERSION"
python3 "$KIT/build.py" --config "$CONFIG" --version "$VERSION" \
  2>&1 | tee "$BUILD_WORK/build-$VERSION.log"
```

确认命令：

```bash
test -f "$OUTPUT/build-result.json"
python3 -m json.tool "$OUTPUT/build-result.json"
ls -lh "$OUTPUT/bundle.tar.gz"
```

我应看到`BUILD_COMPLETE`。阶段依次是输入检查、OCI验证、材料复制、四阶段真实Helm渲染、完整目录验证、ARCHIVE、HASH_ARCHIVE、VERIFY_ARCHIVE_CONTENTS。哈希和读回期间文件不增长属正常行为，不因此重启构建。失败会保留`.building-*`目录；我先查看日志解决原因，再以新版本重试。

构建只用临时验证参数检查模板，通用包`recipe_ready=false`且没有`deployment/deployment.json`，必须现场初始化后才能在UI安装。构建不修改任何集群资源。

## 第六步：我独立验包并实际解压

主要目标：我确认交付压缩件、目录内容和解压后的工具一致，而不是仅看“构建完成”。

执行命令（同一终端）：

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
export UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
export BUNDLE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["package"]["bundle_id"])' "$CONFIG")"
export MATERIALS="$UNPACK/$BUNDLE_ID"
```

确认命令：

```bash
python3 "$MATERIALS/tools/verify-bundle.py" "$MATERIALS"
python3 "$MATERIALS/deployment-kit/configure.py" --help
find "$MATERIALS" -maxdepth 2 -type d | sort
```

我应看到`bundle.tar.gz: OK`、两次`BUNDLE_VERIFIED`和现场初始化帮助。默认最终102文件，inventory记录101项（不记录自己）。这些结果证明打包完整，不代表空集群安装或物理DHCP/Relay/HTTP Boot已验证。

## 第七步：我记录交付件和后续入口

主要目标：我留下版本、摘要和目录，下一位使用者不需要猜文件位置。

执行命令（同一终端）：

```bash
cat "$OUTPUT/SHA256SUMS"
cat "$OUTPUT/build-result.json"
du -sh "$OUTPUT/bundle" "$OUTPUT/bundle.tar.gz" "$MATERIALS"
```

确认命令：

```bash
test -r "$MATERIALS/docs/CONFIGURE.zh-CN.md"
test -r "$MATERIALS/config/site-config.example.json"
```

```text
<BUILD_WORK>/
├── PXEye/deliverables/nico-offline-build/  # 工具及独立材料锁
├── build-config.json                     # 我填写的16行路径/选项
├── FILE-PLAN.txt                         # 本次完整内容
├── build-<VERSION>.log
└── output/
    ├── <VERSION>/
    │   ├── bundle/
    │   ├── bundle.tar.gz
    │   ├── SHA256SUMS
    │   └── build-result.json
    └── <VERSION>-unpacked/<BUNDLE_ID>/
        ├── bundle.json                   # kind=nico-materials；recipe_ready=false
        ├── config/site-config.example.json
        ├── deployment/charts/            # 3个已准备Chart
        ├── deployment/patches/           # 4个补丁记录
        ├── deployment-kit/               # configure.py、脚本/模板和材料锁
        ├── images/                       # 23镜像集合与2个PXEye归档
        ├── manifests/                    # 镜像锁、计划、报告、文件inventory
        ├── tools/                        # Helm、CLI及验包工具
        ├── docs/CONFIGURE.zh-CN.md
        ├── docs/CONFIGURE.md
        ├── boot/
        ├── dpu/                          # include.dpu=true
        └── http/                         # include.dpu=true的BFB材料
```

密码、kubeconfig、运行数据库和Vault恢复材料不入包。`source/`只在include.history=true时出现；历史UI源码不参与运行，实际应用来自锁定的PXEye镜像。

## 材料更新与已有大包

普通构建不执行本节。维护者更新选中材料后，可自动生成新的独立锁文件，供差异审查；不手工抄写摘要，不直接覆盖旧锁。

```bash
python3 "$KIT/refresh-lock.py" --config "$CONFIG" \
  --output "$BUILD_WORK/materials-lock.updated.json"
diff -u "$KIT/materials-lock.json" "$BUILD_WORK/materials-lock.updated.json"
```

`diff`有差异时退出1是正常结果。维护者在源码入口审查/替换锁并提交，再重新导出工具。未选中的可选材料保留既有锁记录，生成器不会扫描并加入未知文件。固定Core镜像或raw Chart变化需要新兼容配方，不能仅更新摘要绕过约束。

旧完整Core构建器产物可交给新版`configure.py`复用，原大包无需重建；同文件系统用硬链接复用大材料，只生成新现场配置。若交付自带新工具的单一压缩件，才重新组装压缩包，不重编译镜像。现场Registry/IP/网关变化只需新目录初始化，见[第二部分](CONFIGURE.zh-CN.md)。

参考：[NVIDIA Machine-a-Tron部署指南](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment)。离线包格式是本项目定义，不是NVIDIA官方打包格式；配方能力以固定e703源码和模板为准。
