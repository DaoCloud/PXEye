# 第二部分：现场初始化和使用离线包部署 NICo

[English](CONFIGURE.md) · **简体中文**

第一部分只构建通用材料包。现场才确定Registry、集群及网络参数；本工具一次性生成一致的Helm values、证书身份引用、RBAC、PXEye启动清单及可执行部署手册。初始化本身不访问Registry/Kubernetes，不安装服务、不修改原始材料。

## 1. 选择材料与工具

主要目标：使用新通用包，或复用此前完整Core构建器产物。以下命令在目标火种机root、Bash执行。该配方仍要求已有单节点Podman Kind、linux/amd64、`/home/kind`宿主共享目录和无认证Registry；不同运行时/认证仓库需要独立适配，不能只替换地址。

执行命令：

```bash
bash
set -euo pipefail
export MATERIALS=/home/kind/nico-bundles/nico-core-materials
export KIT="$MATERIALS/deployment-kit"
test -f "$MATERIALS/manifests/file-inventory.json"
test -f "$KIT/configure.py"
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(yaml.__version__)'
command -v helm
```

确认命令：

```bash
python3 "$KIT/configure.py" --help
python3 -m json.tool "$MATERIALS/bundle.json"
```

上面的`MATERIALS`是已解压目录，名字以交付件实际顶层目录为准。若使用旧完整包，把`MATERIALS`改成旧包已解压目录，`KIT`改成新版独立工具目录，例如`/srv/nico-build-kit`。旧包不需要先覆盖小文件或重新压缩；必须保留原inventory，初始化会先验包。不要使用缺少`manifests/build-report.json`的raw材料目录。

## 2. 填写现场参数

主要目标：未知值明确留为null并阻止初始化，不使用演练地址。`namespace=nico-system`、发布名前缀和repository前缀提供约定默认值。

执行命令（同一终端；配置路径可自选）：

```bash
export SITE_CONFIG=/root/nico-site-config.json
test ! -e "$SITE_CONFIG"
cp "$KIT/site-config.example.json" "$SITE_CONFIG"
vi "$SITE_CONFIG"
```

| 字段 | 现场需确认的内容 |
| --- | --- |
| `site.bundle_id` | 新输出目录名，默认nico-site，不能与材料包id重复 |
| `site.registry` | 镜像引用使用的host:port，不含协议或密码 |
| `registry_access.push_url` | 火种机可达的http(s)://host:port |
| `registry_access.pull_url` | Kind节点及PXEye Pod可达的Registry endpoint，可能与外部地址不同 |
| `registry_access.insecure` | 仅指定Registry是否跳过TLS校验；默认false，不影响Core/Vault TLS |
| `site.context`、`site.kind_node` | kubeconfig context、Kind容器及对应节点名 |
| `site.service_cidr`、`site.service_ips` | 目标Service网段及其中未占用的DNS/PXE/NTP内部地址 |
| `site.host_network` | HostInband名称、物理装机子网/网关/MTU；不同于Service网络 |
| `site.bundle_host_path` | Kind内外一致可见的宿主目录，默认/home/kind/nico-bundles |
| `site.node_port` | 未占用的UI端口，默认31808 |
| `storage_class` | 已存在且可供当前工作负载使用的StorageClass |

确认命令：

```bash
python3 -m json.tool "$SITE_CONFIG"
kubectl config get-contexts
kubectl --context "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["site"]["context"])' "$SITE_CONFIG")" get nodes,storageclass
```

Registry协议、CA/认证、Service网段、地址占用、NodePort、磁盘及共享挂载必须按现场核对。当前导入器仅支持无认证Registry；不得把账号密码写进URL或JSON。对已有部署要先核对发布/数据，不能重放首次安装。

## 3. 生成现场目录

主要目标：不复制大镜像，生成与现有PXEye UI兼容的完整目录。输出必须是新目录，与原材料位于同一文件系统；输出目录名必须等于site.bundle_id。

执行命令（同一火种机Bash；不要修改生成前的原始材料）：

```bash
export SITE_OUTPUT="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["site"]; print(s["bundle_host_path"]+"/"+s["bundle_id"])' "$SITE_CONFIG")"
python3 "$KIT/configure.py" \
  --bundle "$MATERIALS" \
  --site-config "$SITE_CONFIG" \
  --output "$SITE_OUTPUT"
chmod -R a+rX "$SITE_OUTPUT/config" "$SITE_OUTPUT/deployment" "$SITE_OUTPUT/docs"
```

确认命令：

```bash
python3 "$SITE_OUTPUT/tools/verify-bundle.py" "$SITE_OUTPUT"
python3 -m json.tool "$SITE_OUTPUT/manifests/build-report.json"
ls -lh "$SITE_OUTPUT/deployment/pxeye-bootstrap.yaml" "$SITE_OUTPUT/docs/INSTALL.md"
```

预期`SITE_CONFIGURED ... large_bytes_copied=0 archive_recompressed=false`。输出包括`config/runtime.json`、四份Helm values、Deployment/RBAC、安装辅助工具及新inventory。原材料不修改；大文件通过硬链接复用，禁止编辑这些材料文件。对配置的后续修改，使用新的bundle_id和输出目录重新生成，不能手改部分values导致摘要/证书引用不一致。校验大文件时读取耗时属于正常过程。

初始化同时执行四阶段Helm渲染，但不检查现场网络可达性或实际地址占用，也不部署。失败保留`.configuring-*`目录，不覆盖已有站点。

## 4. 按生成手册部署

主要目标：使用已经带入现场参数的完整命令，依赖顺序为验包/集群→Registry/节点拉取→ConfigMap/Secret→带挂载的PXEye/RBAC→NICo镜像→Helm/UI安装→严格验收。

执行命令（同一终端）：

```bash
cat "$SITE_OUTPUT/docs/INSTALL.md"
```

确认命令（部署后按手册执行）：

```bash
kubectl --context "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["site"]["context"])' "$SITE_CONFIG")" \
  -n nico-system get pods
```

`docs/INSTALL.md`中的每章均提供主要目标、执行命令、确认命令。使用其现场固定context/namespace及目录，不能混用原演练手册。通过初始化/渲染不等于部署成功，Pod Ready也不等于物理装机网络验证通过。
