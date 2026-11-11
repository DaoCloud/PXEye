# 第三步：导入 Helm 离线包并部署 NICo

本工具不构建镜像、不主动拉取公网依赖、不改containerd。它消费 `kind=pxeye-nico-helm` 包：校验解压→relok8s入库→Helm OCI发布→冻结部署配方→按阶段Helm安装。当前先覆盖包内单节点amd64 Core；不自动部署REST，不发起设备发现、Redfish或OS安装。

部署执行和构建产物是不同验收：脚本完成Helm阶段后仍需核对Core严格mTLS、材料HTTP与实际网络。以下是脚本使用说明，其中现场参数为示例，尚未在火种机完成本版本端到端验收。

## 1. 准备工具和工作终端

主要目标：使用Linux x86_64、Python3.11+/PyYAML、kubectl，以及包内Helm/relok8s。所有后续命令在火种机同一个Bash终端执行。旧大包不含本工具时，由开发机导出一个小型工具包，不重建Scout或其他大镜像。

执行命令（仅开发机，仓库根）：

```bash
python3 offline-build/onsite/export.py --output /tmp/nico-onsite-tools
```

确认命令（开发机）：

```bash
ls -lh /tmp/nico-onsite-tools.tar.gz /tmp/nico-onsite-tools.tar.gz.sha256
```

将两份文件复制到火种机`/srv/nico/`。未来新构建的大包直接包含`tools/onsite/`，不必再单独复制。

执行命令（火种机）：

```bash
bash
set -euo pipefail
export CONTEXT=kind-fireseed
cd /srv/nico
sha256sum -c nico-onsite-tools.tar.gz.sha256
test ! -e /srv/nico/nico-onsite-tools
tar -xzf nico-onsite-tools.tar.gz

```

确认命令：

```bash
cd /srv/nico/nico-onsite-tools
sha256sum -c SHA256SUMS
cd /srv/nico
```

Python/PyYAML是火种机前提，不在断网现场自动pip安装。不要使用缺少依赖的解释器继续。

## 2. 校验并解压交付件

主要目标：读取`/srv/nico/bundle.tar.gz`和同目录`SHA256SUMS`，输出独立新目录。命令不依赖当前kubectl context，也不修改集群。

执行命令（火种机）：

```bash
bash /srv/nico/nico-onsite-tools/tools/prepare-bundle.sh
source /srv/nico/onsite/environment.sh
```

确认命令：

```bash
python3 -m json.tool "$BUNDLE/bundle.json"
test -f "$BUNDLE/profiles/install-plan.json"
```

脚本检查Python3.11+/PyYAML、验包解压并生成KIT/BUNDLE/CONFIG/WORK，最后输出`BUNDLE_READY`。第二条命令将变量加载到当前终端。已完整解压且清单匹配时验证后复用；不完整或不同包的目录拒绝覆盖。可加`--directory /srv/nico`、`--output /srv/nico/releases/field-import-02`；从源码目录运行必须提供`--directory`。不要以文件大小推断版本，以bundle.json为准。SHA文件仅匹配本次归档那一行。解压拒绝危险路径、链接和重复成员，按剩余空间限制展开，随后校验内部清单。

## 3. 创建现场配置

主要目标：把目标集群、Registry和现场信息集中到一个JSON文件；不依赖默认context。`prepare-site.sh`读取KIT/BUNDLE/CONFIG/WORK（namespace默认nico-system）；CONTEXT优先使用显式参数/环境变量，未设置时复用已有配置中的context，否则从本机kubeconfig中选择唯一kind-上下文，不使用默认context。多个候选时要求--context指定。source执行会将选中的CONTEXT/NICO_NAMESPACE保留在当前终端。脚本，自动识别原Core发布名、探测Registry、创建恢复配置并执行preflight，不修改集群。已有匹配配置时保留后复用并预检；输入或TLS策略不一致则停止，不覆盖。

执行命令（火种机；本轮保留旧release/PVC的Kind恢复场景）：

```bash
source "$KIT/prepare-site.sh"
```

确认命令：

```bash
python3 -m json.tool "$CONFIG"
```

需要指定参数时，直接传给prepare-site.sh；例如`--skip-tls-verify`明确跳过Registry证书校验，或`--ca-file`指定私有CA。

省略`--registry-url`时，脚本从目标namespace的PXEye镜像地址、私有IP/回环镜像地址，以及Kind的`kube-public/local-registry-hosting`声明收集候选，验证`/v2/`后将唯一可用端点写入配置的`registry.url`，来源和探测结果写入`registry.discovery`。不扫描网段。Registry V2返回200或401且有标准API响应头才识别；401只证明端点存在，不证明认证或推送权限。HTTPS优先，证书失败不自动降级HTTP；使用私有CA可加`--ca-file /绝对路径/ca.crt`，明确允许跳过校验时加`--skip-tls-verify`。没有候选、不可达或多个可用端点时停止，可用`--registry-url https://实际入口`明确指定。全新集群没有发现线索时同样需要该覆盖参数。

需要认证时加`--docker-config-directory /绝对路径/docker-auth`，目录须包含有效`config.json`；不在命令行传密码。工具不代替Harbor项目创建或账号授权。自动探测不修改containerd；主机可达不代表Kind节点可拉取。

restore模式自动读取原release的有效values和旧DNS/PXE Service及NTP客户端Service（-nico-ntp-client）地址；Headless NTP Service不作为客户端地址；保留原HostInband和凭据引用。Core镜像采用本次离线包版本，不自动采用来源环境当前运行镜像。配置及values有变化时用新的work_directory；唯有补充data_backup_directory不使已入库内容失效。

prepare-site.sh用于保留数据恢复；全新现场使用onsite.py write-config，省略`--restore`，显式设置context、包路径和工作目录，前缀自行选择；必须在配置中填写`service_ips`和`host_network`，并按现场选择storage_class。例如host_network对象字段为name、prefix、gateway、mtu。生成配置后的更新命令如下，值从交接表设置到同一Bash环境后再执行：

```bash
# 仅全新现场：先按交接表设置DNS_IP、PXE_IP、NTP_IP、HOST_PREFIX、HOST_GATEWAY。
python3 - "$CONFIG" <<'PY'
import json,os,sys
p=sys.argv[1]; c=json.load(open(p))
c['service_ips']={k:os.environ[v] for k,v in [('dns','DNS_IP'),('pxe','PXE_IP'),('ntp','NTP_IP')]}
c['host_network']={'name':'host_boot','prefix':os.environ['HOST_PREFIX'],'gateway':os.environ['HOST_GATEWAY'],'mtu':1500}
with open(p,'w') as f: json.dump(c,f,indent=2)
PY
```

本轮restore不执行上面的全新网络配置命令。`publish_materials`默认false，保留现有x86 boot-artifacts路径。选true只部署材料HTTP，不自动把ARM64/BFB URL注入Core；相应消费者URL/现场可达入口仍需单独配置，不能据此声称支持ARM实机装机。

## 4. 预检并入库

主要目标：校验包和目标集群（同一运行中输入文件元数据未变化时复用已完成的全量校验），然后将镜像与Chart推到现场Registry。不启动NICo工作负载。

执行命令（火种机）：

```bash
python3 "$KIT/onsite.py" preflight --config "$CONFIG"
python3 "$KIT/onsite.py" import --config "$CONFIG"
```

确认命令：

```bash
python3 -m json.tool "$WORK/catalog.json"
test -f "$WORK/state.json"
```

应看到`IMPORT_COMPLETE`。每Chart完成状态可复用；失败后同配置重跑import。relok8s保留内容、不使用force-push。Chart按内容SHA隔离仓库，推送后再pull核对OCI digest和归档SHA。镜像映射以relok8s传输结果记录，不将其描述成节点已验证拉取。

relok8s0.5.4没有TLS跳过参数，因此脚本用127.0.0.1随机端口的临时流式转发，按现场配置连接真实Registry；仅这一进程使用，不修改系统Registry配置。工具把临时地址从所有层级Chart改回现场地址，并恢复被relok8s剥离的子Chart条件，防止禁用组件被意外启动。转发结束关闭端口、删除临时认证配置。

匿名、Docker inline auths，以及同源Bearer认证可用；credential-helper别名与跨主机上传重定向会明确失败，不静默降级。自定义token服务的网络/TLS也必须可达。Kind节点拉取镜像的认证/TLS配置仍须事先正确，导入成功不代表kubelet能拉取。

## 5. 冻结安装配方

主要目标：从OCI重新拉取并核验Chart，将现场values、每阶段顺序和文件摘要冻结下来。沿用官方Chart与受控补丁，不现场手写Deployment。

执行命令（火种机）：

```bash
python3 "$KIT/onsite.py" recipe --config "$CONFIG"
```

确认命令：

```bash
python3 -m json.tool "$WORK/recipe/deployment.json"
ls -lh "$WORK/recipe/charts/" "$WORK/recipe/values/"
```

应看到`RECIPE_READY`。脚本渲染每阶段并检查所有容器镜像属于入库锁，拒绝残留占位符；restore时禁止现有配置开启自动探索/固件更新。额外定制通过config.phase_values引用各阶段YAML，内容摘要纳入运行身份；不是去改生成文件。Core配置将采用已核对的现场地址。

recipe已经存在时不会重生成；它是冻结输入。变更需新工作目录。生成配方不是批准迁移数据，也不代表材料或Core验收通过。

## 6. 选择CLI或UI执行，禁止同时执行

### 6.1 本轮推荐：CLI分阶段恢复

主要目标：沿用旧release与数据，先恢复平台依赖，再进入Core。每个install命令都包含明确context，保留真实退出码和日志。

执行命令（火种机）：

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase cert-manager
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase platform
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase vault
```

确认命令：

```bash
kubectl --context kind-fireseed -n nico-system get pods,pvc
"$BUNDLE/tools/helm" --kube-context kind-fireseed -n nico-system list
```

继续其余阶段：

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase all
```

确认命令：

```bash
kubectl --context kind-fireseed -n nico-system get deploy,sts,pods,jobs,pvc
cat "$WORK/timings.jsonl"
```

all会核对并跳过已完成阶段，继续材料（启用时）和Core；不自动删除资源、不使用atomic回滚掩盖数据库变化。安装前检查Helm资源归属并保存私密快照，安装后核对原PVC UID/PV未变。

首次失败不自动重放。查看Helm、Job与日志、解决原因后，只对明确核对的阶段执行：

```bash
# 将core替换为实际失败阶段。--resume-failed不允许配合--phase all。
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase core --resume-failed
```

若Helm还在pending状态，脚本停止，不强行解锁。CLI对同站点有本机锁，但旧版UI不共享此锁，操作人必须只选一路执行。

### 6.2 已有PXEye：上传小型兼容配方

主要目标：复用现有UI的完整配方上传能力，不升级UI、不改旧对象归属。生成配方后执行：

```bash
python3 "$KIT/onsite.py" ui-package --config "$CONFIG"
ls -lh "$WORK/ui-recipe.tar.gz"
```

确认命令：

```bash
python3 -m json.tool "$WORK/recipe-result.json"
```

将这个小包安全复制到浏览器所在机器，在NICo安装页通过已有离线部署配方上传入口选择它，沿用包内站点/namespace/release默认值。包包含冻结后的Chart和现场values，可能含旧Helm敏感配置，权限600，不提交仓库、不公开分享。

这是兼容路径，不是“旧UI已自动支持catalog.json”。未来UI直接读取OCI目录尚未实现；本次CLI负责OCI拉取与冻结，现有UI只消费完整配方。配方生成后可直接导出UI小包；备份不作为流程前置条件。

### 6.3 全新现场：启动PXEye

主要目标：没有已有PXEye时，使用独立Helm Chart启动UI。已存在且不归此release的Deployment会被拒绝接管，本轮已有火种环境不执行。

执行命令（仅全新现场）：

```bash
python3 "$KIT/onsite.py" bootstrap --config "$CONFIG"
```

确认命令：

```bash
kubectl --context kind-fireseed -n nico-system get deploy,pods,svc
```

Chart创建ConfigMap、登录Secret、PVC、ServiceAccount/RBAC和Service。默认release为namespace加-pxeye；可在配置pxeye_release、pxeye_values设置。Chart生成的bootstrap-password保存在同release的Secret中，操作者按现场凭据交付流程取用，不写到普通日志。已有非Helm PXEye迁移不在本命令中自动处理。

## 7. 完成边界与文件位置

主要目标：能定位错误与继续入口。

执行命令：

```bash
ls -lh "$WORK/catalog.json" "$WORK/state.json" "$WORK/timings.jsonl"
ls "$WORK/logs" "$WORK/private"
```

确认命令：

```bash
python3 -m json.tool "$WORK/state.json"
```

`logs/`保存入库命令与退出结果，`private/`保存旧Helm values、渲染资源、资源快照和安装输出，`timings.jsonl`逐命令记录耗时。script不会删除原包、旧镜像或持久卷。超时/失败保留现场；不把Helm deployed当作严格mTLS、物理DHCP/Relay、Scout启动或OS装机验收。

备份工具仍可按需单独调用，不是生成配方、导出UI包或安装Core的前置条件。

## relok8s 0.5.4 顶层镜像字段兼容

该版本改写顶层镜像字段时可能报`need path or selectors or both`。构建和现场导入共用relocation.py：仅在中间包中将顶层字段临时映射到嵌套字段，迁移完成后恢复原values结构；镜像内容不变。现场对已有包在工作目录生成派生副本，原归档和校验清单保持不变，无需重建大包。修复后使用原配置重新执行import，已完成的Chart回查后复用。
