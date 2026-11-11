# 第三步：现场导入并部署

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

**目标：把离线交付件安装到明确的 Kubernetes 集群。执行位置：火种机。** 一个现场配置、一个执行脚本；不手工写资源 YAML，不构建镜像，不改 containerd。

## 脚本会经历哪些阶段

| 阶段 | 做什么 | 关注什么 |
| --- | --- | --- |
| 验包与解压 | 验证归档和内部清单，生成独立解压目录 | 已完成目录验证后复用 |
| 现场解析与预检 | 确认 context、Registry、工具和配置 | 不使用默认集群；namespace默认nico-system |
| 镜像和 Chart 入库 | relok8s 推送镜像，Helm OCI 发布并读回 Chart | 入库成功不等于节点能拉取镜像 |
| 冻结安装配方 | 生成现场 values、顺序和摘要 | 不手改派生文件 |
| 可选 PXEye 启动 | 按配置通过独立 Helm Chart 启动 UI | 已有PXEye时设为false，保留原服务 |
| NICo 顺序安装 | cert-manager → 平台依赖 → Vault → 可选材料 → Core | 每阶段通过后才继续，保留原PVC身份 |

## 准备一次

主要目标：让现场拥有完整工具和唯一配置。前提：Python 3.11+/PyYAML、kubectl、可用集群和 Registry；节点已配置好镜像拉取。Helm 和 relok8s 随大包提供。

将第二步 `DELIVERY_FILES` 列出的三个文件复制到火种机 `/srv/nico/`，首次执行：

```bash
cd /srv/nico
sha256sum -c SHA256SUMS &&
test ! -e onsite-tools &&
test ! -e onsite-run.json &&
tar -xzf onsite-tools.tar.gz &&
cp onsite-tools/tools/onsite/run-config.example.json onsite-run.json &&
${EDITOR:-vi} onsite-run.json
```

只维护 `onsite-run.json`，按下表检查：

| 配置 | 最重要的填写规则 |
| --- | --- |
| `archive` / `checksums` | 大包和SHA文件的绝对路径 |
| `extract_directory` / `work_directory` | 每次安装独立，互相分开；脚本自动创建 |
| `site.context` / `namespace` | 推荐明确指定context；null只允许唯一Kind context；namespace默认nico-system |
| `site.mode` / `release_prefix` | 恢复填restore，留空前缀时读取唯一原Core release；全新填new |
| `site.registry` | URL留空自动探测唯一可用端点；CA/跳过TLS校验及认证文件按现场设置 |
| `site.service_ips` / `host_network` | 全新安装必须填写DNS/PXE/NTP IPv4，以及网络name/prefix/gateway/mtu；恢复可复用旧配置 |
| `bootstrap_pxeye` / `site.publish_materials` | 前者在顶层控制PXEye启动；后者在site内控制材料服务，默认均false |
| `site.storage_class` / `phase_values` | 按需指定存储及阶段定制文件；凭据仅引用受限文件 |

模板默认为 **恢复模式、保留已有PXEye**；全新现场必须修改对应选项和网络参数。工具解压、配置创建只做一次；续跑不要重复覆盖。

## 执行一个脚本

执行命令（任意工作目录，首次与失败后相同）：

```bash
python3 /srv/nico/onsite-tools/tools/onsite/run.py --config /srv/nico/onsite-run.json
```

确认：终端显示当前 `STAGE` 和 `DONE` / `FAILED`，最终出现 `ONSITE_COMPLETE`。无需另外执行 import、recipe、install 或 source 环境变量。

## 失败续跑与日志

先查看失败原因，修复后重跑原命令。下面路径使用配置模板默认值：

```bash
tail -n 60 /srv/nico/onsite/field-install-01/run.log
cat /srv/nico/onsite/field-install-01/progress.json
```

| 记录 | 用途 |
| --- | --- |
| `work_directory/progress.json` | 当前阶段、状态、次数、耗时、错误 |
| `events.jsonl` / `run.log` | 追加执行历史，不覆盖失败记录 |
| `deployment/state.json` | 逐Chart和Helm阶段断点、安装意图 |
| `deployment/logs/` / `timings.jsonl` | 具体命令日志及耗时 |
| `deployment/private/` | 受限权限的快照、values及安装输出 |

完成的阶段先核验再跳过。Helm failed或release不存在时可以重试；仍为pending时停止处理，不自动解锁或回滚。Helm已成功但未记账时，核对原意图、版本、values、健康和PVC后补记成功，避免重放初始化。

输入、配置或工具实现改变时使用新工作目录。不要修改断点，不要同时从UI和CLI安装。当前恢复为阶段级，不是字节级续传。

`ONSITE_COMPLETE` 只代表导入和Helm就绪；严格mTLS、材料HTTP、物理DHCP/Scout和OS装机另行验收。脚本不清空数据、不重建Kind，也不发起设备发现、Redfish或主机安装。

依据：[NICo Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation)、[Helm OCI](https://helm.sh/docs/v3/topics/registries/)。
