# 火种机一键安装

[English](README.md) · **简体中文**

## 主要目标

用一条命令将一个 PXEye / NICo 离线包导入火种 Kubernetes 集群，并部署控制面。现场只向执行器提供
`bundle.tar.gz` 的绝对路径；不填写 checksum、解压目录、工作目录、namespace、发布名、证书模式、
DNS/PXE/NTP 地址或 HostInband 网络。

首次安装固定使用：

- namespace：`nico-system`
- NICo 父 Chart release：`nico`
- PXEye Service：`NodePort` `31808`（Kubernetes 同时自动分配 ClusterIP）

执行器优先使用当前的 `kind-*` context（否则只接受唯一候选）、探测 Registry、默认跳过现场 Registry 的 TLS 证书链与名称校验，
并在健康的共享 cert-manager 已存在时复用它；不存在时才安装包内 cert-manager。部分安装或未就绪的
cert-manager 会明确失败，绝不会接管或覆盖。它还会在 Core 阶段完成后，使用同命名空间的客户端
Secret 和集群内 Core 地址验证 mTLS，并将 PXEye 接通到新 Core。

## 前置条件

火种机需要 Python 3.11+、PyYAML、`kubectl`，并且节点已经可以从现场 Registry 拉镜像。交付目录中需要：

```text
bundle.tar.gz          # 大离线交付包
onsite-tools.tar.gz    # 小型执行器；只负责启动大包中的工具
```

`nico-system` 必须为空，或只包含 Kubernetes 自身默认对象及同一次执行已经创建的 `nico` / PXEye release
管理的资源。执行器会拒绝遗留的 PVC、Secret、Service 等 namespaced 资源，不会接管旧的四个独立 NICo
release、已有 PXEye 或数据。

安装过程中，预检也识别本次控制器生成的资源：cert-manager webhook 引用的 CA、Certificate 签发的
Secret、已记录的 Helm hook、Vault 初始化输出，以及通过父资源 UID 关联的对象。这些属于正常安装产物。

## 执行命令

以下命令在火种机执行。第一次先解开小执行器；这不会解开大包。

```bash
cd /srv/nico
tar -xzf onsite-tools.tar.gz
python3 /srv/nico/onsite-tools/tools/onsite/run.py \
  --archive /srv/nico/bundle.tar.gz
```

`--archive` 是唯一必填参数。若 Registry 无法从工作负载镜像或 `local-registry-hosting` 证据唯一识别，
脚本会停在第 2 阶段；仅在这种例外情况下，可在重跑前设置 `NICO_REGISTRY_URL=http(s)://registry-host:port`。
该变量只选择 Registry 端点；执行器仍按默认策略跳过该端点的 TLS 证书链/名称校验，不能将此视为
Registry 身份已验证。

## 确认命令

成功时末尾输出 `PXEYE_CORE_CONNECTED` 和 `ONSITE_COMPLETE`。后者表示 Helm 就绪且 PXEye 已通过
集群内 mTLS 验证连接到 Core。运行目录从归档名自动派生；例如 `/srv/nico/bundle.tar.gz` 会生成：

```text
/srv/nico/bundle/             # 解压后的包；内部清单已验证
/srv/nico/bundle.onsite/      # 进度、日志、冻结的 Helm recipe 和私有状态
```

执行器还会在这个运行目录生成只读的 `environment.sh`，供确认和排障使用；它不是安装输入，避免确认命令误用
当前 shell 的业务集群 context。

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get pods
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get service "$PXEYE_RELEASE"
cat "$(dirname "$WORK")/progress.json"
```

`NodePort` 未被 Kubernetes 占用不等于火种宿主机或外部网络能够访问它。Kind 仍需要在建集群时设置对应的
端口映射，或通过现有的受控访问入口/`kubectl port-forward` 访问 PXEye。

## 访问 PXEye

安装成功后，脚本会打印带实际 context、namespace 的转发命令；通过 SSH 执行时，还会打印火种机 SSH
地址对应的浏览器 URL。在火种机执行打印的命令：

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" \
  port-forward --address 0.0.0.0 "service/$PXEYE_RELEASE" 31808:80
```

保持终端运行。出现 `Forwarding` 后，火种机本机访问 `http://127.0.0.1:31808/`；远程浏览器使用火种机
可达地址和 `31808` 端口。Ctrl+C 结束本次访问会话。

## 失败续跑

修复外部原因后，用完全相同的命令重跑：

```bash
python3 /srv/nico/onsite-tools/tools/onsite/run.py \
  --archive /srv/nico/bundle.tar.gz
```

执行器会复核已完成阶段后继续，不会重新导入已验证的 Chart，也不会自动解锁 Helm pending 操作。查看：

```bash
tail -n 80 /srv/nico/bundle.onsite/run.log
cat /srv/nico/bundle.onsite/progress.json
```

## 首次安装的网络边界

本步骤只部署控制面。它不会把 Kubernetes `ClusterIP` 当成物理网络地址，也不会生成虚假的 HostInband 子网、
DNS/PXE/NTP VIP、DHCP Relay、LoadBalancer、交换机 Relay、路由、ACL 或防火墙规则。初始 Chart 不创建引导服务
的外部发布地址，也没有 HostInband 规划；这不是物理装机验收，更不是替代现场网络隔离策略的安全门控。

包内 `nico-dhcp` Deployment 会刻意以零副本启动。上游 DHCP option 占位符不是真实物理端点，因此在后续站点网络
配置提供真实 DNS/NTP/PXE/VIP 并显式启用 DHCP 前，不会启动 Kea 进程。

物理引导网络地址和 HostInband 规划属于 PXEye 的后续站点配置：DNS 与 NTP 服务器、PXE/DHCP Relay 对外端点、
引导 VLAN 的 prefix/gateway/MTU、外部 Service/VIP，以及交换机 Relay、路由、ACL 与防火墙规则都在该阶段确认。
先完成这些配置并从引导 VLAN 验证 DHCP、DNS、NTP、PXE，再开放真实装机。Helm Ready 不等于物理装机验收通过。
