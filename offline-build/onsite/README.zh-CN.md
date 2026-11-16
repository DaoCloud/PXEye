# 火种机一键安装

[English](README.md) · **简体中文**

## 主要目标

通过一个 Shell 入口，将已有离线包导入现场 Registry，并部署 PXEye / NICo 控制面。
现场不需要 Python、PyYAML、pip 或容器运行时。第一、二步的构建流程、Charts 和大包格式保持不变。

固定安装身份：namespace `nico-system`，NICo 父 Chart release `nico`，PXEye NodePort `31808`。
`--archive` 是唯一必填参数；可选 `--mode kind|k8s`，默认 `kind`，无需填写安装配置文件。

## 前置条件

执行机器为 Linux amd64，具备 Bash 4+、kubectl，以及常见 GNU 工具：tar、gzip、find、sort、stat、
sha256sum、timeout、flock、sync；另需 curl。小工具包已携带锁定版本的 jq、Mike Farah yq 和 Caddy。
现场不会下载依赖，也不会修改系统 Python。

目标集群需要可达的 API Server、具有安装权限的 kubeconfig、可调度的 amd64 节点、可用的默认
StorageClass 和足够容量。节点已经能够从现场 Registry 拉镜像；Registry 支持镜像及 Helm OCI Chart
推送和拉取。默认 StorageClass 必须能够实际创建并挂载卷；默认标记本身不代表存储可用。
`31808` 未被其他 Service 占用。

`nico-system` 应为空，或仅包含 Kubernetes 默认对象和同一次执行创建的资源。健康的共享 cert-manager
会复用；没有时安装包内版本。其他安装留下的部分安装或异常状态会停止；本次执行留下的失败阶段，
只有冻结 intent 与归属核对一致才允许重试。执行器不接管其他安装的 Release、PVC 或数据。

## 执行命令

以下命令在火种机执行，交付文件放在 `/srv/nico`：

```text
/srv/nico/
  bundle.tar.gz           # 已构建的大包，镜像和 Charts
  onsite-tools.tar.gz     # Shell 执行器及固定版本工具
```

解开小工具包，再按目标集群执行。以下为普通 Kubernetes：

```bash
cd /srv/nico
tar -xzf onsite-tools.tar.gz
kubectl config current-context
bash /srv/nico/onsite-tools/install.sh \
  --archive /srv/nico/bundle.tar.gz --mode k8s
```

`k8s` 使用当前 kubeconfig context；执行前通过 `kubectl config use-context` 选择目标。
Kind 使用 `--mode kind` 或省略该参数：优先当前的 `kind-*` context，否则仅接受唯一 Kind 候选。

Registry 自动从已有工作负载镜像及 `local-registry-hosting` 信息发现。无法唯一识别时，在重跑前设置
`NICO_REGISTRY_URL` 为现场的完整 `http://host:port` 或 `https://host:port` 地址。执行器默认跳过 Registry
服务端证书链和名称验证；节点自身的 HTTP/证书信任配置仍由现场准备。

## 阶段与目录

| 阶段 | 作用 |
| --- | --- |
| 01-unpack | 检查归档成员、解压并验证包内文件清单 |
| 02-site | 保存模式、context、Registry 和固定安装身份 |
| 03-preflight | 复核包、集群、工具、cert-manager 与资源归属 |
| 04-import | relok8s 导入镜像，发布并读回 Helm OCI Chart |
| 05-recipe | 冻结安装 values、镜像引用和分阶段计划 |
| 06-pxeye | Helm 安装或核对 PXEye |
| 07-install-* | 依次安装 cert-manager、平台、Vault、Core |
| 08-pxeye-core | 验证 PXEye 通过集群内 mTLS 连接 Core |

目录由归档名派生，无需额外参数：

```text
/srv/nico/bundle/                   # 解压内容，保留原始大包文件不变
/srv/nico/bundle.onsite/
  progress.json                    # 阶段状态和执行身份
  events.jsonl                     # 阶段历史
  run.log                          # 不含口令的控制台日志
  install-config.json              # 自动生成的运行状态，不是用户配置
  environment.sh                   # 查询环境变量
  deployment/                      # OCI 目录、冻结 recipe、私有日志及安装状态
```

Caddy 只在本机 loopback 上为 relok8s 提供传输适配，随本次进程退出，不创建或保留 Registry 服务。
原包里的 Python 文件属于历史包内容，保持原样但不会由 Shell 执行器调用。
生成配方时会修正不符合 DNS 命名规则的 cert-manager 依赖别名，并记录来源 OCI 摘要、派生 Chart 摘要与别名映射；
源码 Chart 和大包保持不变。

## 确认命令

末尾出现 `PXEYE_CORE_CONNECTED` 和 `ONSITE_COMPLETE` 表示 Helm 就绪及 PXEye/Core 连接通过：

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get pods,pvc
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get service "$PXEYE_RELEASE"
cat /srv/nico/bundle.onsite/progress.json
```

## 访问 PXEye

安装完成会打印目标 context 对应的访问命令和取口令命令。火种机执行以下命令并保持终端运行：

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" \
  port-forward --address 0.0.0.0 "service/$PXEYE_RELEASE" 31808:80
```

看到 `Forwarding` 后，通过火种机可达地址的 `31808` 端口访问。取首次生成的口令：

```bash
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" \
  get secret "$PXEYE_RELEASE" -o jsonpath='{.data.bootstrap-password}' | base64 -d; echo
```

执行器只打印取口令命令，不读取口令到控制台日志。Kind 的 NodePort 是否映射到宿主机取决于建集群配置；
port-forward 在两种模式下都适用。

## 失败续跑

修复原因后执行完全相同的命令：

```bash
bash /srv/nico/onsite-tools/install.sh \
  --archive /srv/nico/bundle.tar.gz --mode k8s
```

已完成阶段会复核并复用。模式、context、归档或安装状态格式变化会停止；恢复原目标后再续跑。
更新 Shell 工具会记录源码指纹，并重新核对冻结的配置、配方和 Helm intent，允许修复工具后继续。
不会自动解锁 Helm pending，也不会自动采用旧 Python 执行器的进度。首次改用 Shell 时使用尚未开始安装的
归档名称；不删除或改写旧安装状态来绕过检查。

若确认已没有 Helm 安装进程，可由运维人员检查历史后，使用标准 `helm rollback` 回到本次安装已完成的
最近前序阶段，再执行原命令。执行器核对该阶段的冻结 Chart、values、安装 intent、资源归属、PVC 及健康状态后，
继续未完成阶段；未知部署状态仍会停止。执行器不自动回滚，不修改 Helm Secret。回滚可能暂时移除后续阶段的资源；
Core 重试使用累积父 Chart，会重新调和平台对象并执行 Vault 的升级 hook，已有 PVC 身份和绑定持续受检查。

```bash
tail -n 80 /srv/nico/bundle.onsite/run.log
cat /srv/nico/bundle.onsite/progress.json
```

本步骤只安装控制面。DHCP 初始为零副本；DNS、DHCP、PXE、NTP、材料 HTTP 及物理引导网络由后续站点配置
维护。Helm Ready 不等于真实装机验收通过。
