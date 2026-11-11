# 一键构建 PXEye / NICo Helm离线包

[English](README.md) · **简体中文**

本目录是新的relok8s打包入口。输入是上一版构建器已经验收的`kind=nico-materials`解压目录，脚本自动复用其中的23张Core镜像、2张PXEye镜像和固定Chart，构建选中的材料镜像，再交付一个完整归档。不需要填写目标现场Registry、IP、网关或namespace。

## 1. 检查构建机

主要目标：使用Linux x86_64、Python3.11+/PyYAML、Docker服务、Helm3。以下命令在构建机同一个Bash终端执行；假定仓库已经在`/srv/PXEye`，输入材料包在`/srv/nico-input/materials-bundle`。

执行命令：

```bash
bash
set -euo pipefail
export REPO=/srv/PXEye
export MATERIALS=/srv/nico-input/materials-bundle
export BUILD_WORK=/srv/nico-build
cd "$REPO"
uname -m
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print(yaml.__version__)'
docker version --format '{{.Server.Version}}'
helm version --short
mkdir -p "$BUILD_WORK"
```

确认命令：

```bash
test -r "$MATERIALS/bundle.json"
test -r "$MATERIALS/manifests/file-inventory.json"
test -r "$REPO/offline-build/helm-bundle/build.py"
df -h "$BUILD_WORK"
python3 "$REPO/offline-build/helm-bundle/build.py" --help
```

输入必须是已有通用材料包，不是原始上游目录，也不是现场初始化后的包。脚本要求至少“输入目录总大小×4＋2GiB”空闲空间，本机Unix socket的Docker存储至少需要“输入大小×2＋2GiB”空闲空间；与输出同盘时仍需满足总容量。首次构建会下载锁定的relok8s 0.5.4 Linux x86_64发行件并校验仓库中固定SHA256，且通过Docker准备锁定digest的Registry镜像；已缓存时复用。完全断网的构建机须预先缓存Registry镜像，并在配置`tools.relok8s`中填写已有0.5.4二进制绝对路径；不能在缺工具时假报成功。构建用临时无认证HTTP仓库，仅绑定127.0.0.1随机端口，不修改Docker/containerd配置。

## 2. 创建一次配置

主要目标：只填写本地路径和材料开关，重复构建复用同一配置；已有文件不会覆盖。

执行命令（同一终端、仓库根目录）：

```bash
export CONFIG="$BUILD_WORK/helm-build.json"
python3 "$REPO/offline-build/helm-bundle/build.py" \
  --write-config "$CONFIG" \
  --materials-bundle "$MATERIALS" \
  --output-root "$BUILD_WORK/output"
```

确认命令：

```bash
cat "$CONFIG"
python3 "$REPO/offline-build/helm-bundle/build.py" --config "$CONFIG" --plan
```

| 字段 | 作用 |
| --- | --- |
| materials_bundle | 已验收的通用材料包根目录 |
| output_root / bundle_id | 版本输出父目录、归档内的根目录名 |
| include.aarch64 / bfb / apt | 是否把这三组原文件构建为材料镜像，默认均开启 |
| tools.docker / helm | 构建工具命令或绝对路径 |
| tools.relok8s | null表示自动准备固定版本；也可以提供已有二进制绝对路径 |

逐文件列表/SHA由输入包inventory读取；工具版本和构建Registry digest在`toolchain-lock.json`维护，不要求用户手工复制几百项材料配置。x86_64 Scout继续使用已锁定的原boot-artifacts镜像及NICo原生加载方式，不重复打入一份松散文件。材料清单记录镜像内/payload及PVC版本目录。原x86_64镜像仅校验镜像层digest，本轮不把松散x86文件清单当作镜像内部核验结果。当前不增加Ubuntu ISO、GPU软件或启用DPF。

## 3. 一键构建

主要目标：一个命令完成输入完整性校验、临时Registry、镜像导入、材料镜像构建、5组Chart/6种模式渲染、relok8s打包、文件清单、压缩及逐文件读回。不会访问Kubernetes或执行部署。

执行命令：

```bash
python3 "$REPO/offline-build/helm-bundle/build.py" --config "$CONFIG"
```

需要固定输出版本或保留终端日志时执行下面这一组，替代上面命令：

```bash
export VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
export OUTPUT="$BUILD_WORK/output/$VERSION"
python3 "$REPO/offline-build/helm-bundle/build.py" \
  --config "$CONFIG" --version "$VERSION" \
  2>&1 | tee "$BUILD_WORK/build-$VERSION.log"
```

确认命令（固定版本这一组执行后）：

```bash
test -r "$OUTPUT/build-result.json"
cat "$OUTPUT/build-result.json"
ls -lh "$OUTPUT/bundle.tar.gz"
```

成功终端显示`HELM_BUILD_COMPLETE <绝对输出目录>`。源码必须已提交；脚本检查本次构建涉及的源码路径，不把用户其他无关改动纳入镜像。创建新版本目录，不覆盖已有产物。临时Registry和本轮Docker标签在退出时清理；成功后删除临时仓库存储与材料构建目录，保留日志。失败保留`.building-*`暂存目录及真实日志，以新版本重试；不会清空旧包或执行全局Docker prune。

## 4. 验证交付件

主要目标：确认压缩件和解压目录完整。构建器已自动读回压缩包每个文件；以下为独立验包命令。

执行命令（同一终端）：

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify.py bundle
export UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir "$UNPACK"
tar -xzf bundle.tar.gz -C "$UNPACK"
```

确认命令：

```bash
export BUNDLE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle_id"])' "$CONFIG")"
python3 "$UNPACK/$BUNDLE_ID/tools/verify.py" "$UNPACK/$BUNDLE_ID"
cat "$UNPACK/$BUNDLE_ID/bundle.json"
```

目录结构：

```text
<output_root>/<version>/
  bundle.tar.gz
  SHA256SUMS
  build-result.json
  logs/                         # 临时Registry/镜像导入/材料镜像日志
  *-relok8s.log                  # 真实relok8s输出
  render/                       # 构建期渲染证据，不用于部署
  bundle/
    bundle.json
    charts/                     # pxeye/cert-manager/platform/core/materials
    relocation/                 # 5个真实Chart对应的relok8s中间包
    profiles/
      install-plan.json         # 继承原四阶段；Vault复用platform Chart
      site-values.example.yaml  # 现场待填写项，尚未绑定现场
    manifests/
      file-inventory.json       # 解压文件的路径/大小/SHA
      images-lock.json          # 镜像引用/digest/用途
      materials.json            # 材料镜像内部文件清单与SHA
      toolchain-lock.json
      build-report.json
    tools/helm
    tools/relok8s
    tools/verify.py
    docs/README.md
    docs/README.zh-CN.md
    docs/relok8s-LICENSE
```

外层归档仅包含`bundle/`的内容，解压根名为`bundle_id`。没有另外交付原始OCI归档或材料原文件副本；大材料在镜像中，镜像字节在relok8s中间包中。多个真实Chart引用共同镜像时，中间包之间可能重复保存镜像，当前不宣称跨包去重。

## 5. 构建成功的边界

主要目标：明确新打包格式与现有部署入口的兼容范围，防止把构建完成当成安装通过。

执行命令：

```bash
python3 -m json.tool "$OUTPUT/bundle/bundle.json"
python3 -m json.tool "$OUTPUT/bundle/manifests/build-report.json"
```

确认命令：

```bash
python3 - "$OUTPUT/bundle/bundle.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['kind']=='pxeye-nico-helm'
assert d['requires_site_configuration'] is True
assert d['multi_phase_oci_ui_ready'] is False
print('RELOK8S_DELIVERY_READY; ONSITE/UI_ADAPTER_PENDING')
PY
```

这个脚本实现构建交付，尚未实现上一轮方案中的“现场迁移→Helm OCI发布→PXEye多阶段OCI目录接入”。因此新包明确标记`requires_site_configuration=true`、`multi_phase_oci_ui_ready=false`；不能把它直接交给旧版FieldBundles扫描器或按旧OCI导入命令运行。现场迁移使用relok8s中间包格式，不能把它当作`nico-amd64.oci.tar`。

构建使用临时验证参数，不是目标现场参数。新PXEye和材料发布Chart只有构建渲染证据，尚无冷启动安装/升级/实际网络验证；原有固定e703兼容补丁继续保留。脚本不改变生产/学习集群、物理机器、DHCP、证书或数据库，也不执行回归/GPU工作负载。

依据：[relok8s源代码v0.5.4](https://github.com/vmware-tanzu/asset-relocation-tool-for-kubernetes/tree/v0.5.4)、[Helm OCI](https://helm.sh/docs/v3/topics/registries/)、[NVIDIA参考安装](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation)。
